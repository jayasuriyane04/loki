import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import current_user
from app.core.config import get_settings
from app.db.models import Chunk, Document, Memory, User
from app.db.session import get_db
from app.knowledge.extract import UploadRejected, classify, clean_source
from app.knowledge.ingest import Ingestor
from app.knowledge.service import KnowledgeService
from app.llm.base import LLMError
from app.schemas import ChunkOut, DocumentDetail, DocumentOut, SearchHitOut, UploadResult

router = APIRouter(prefix="/api", tags=["knowledge"])
log = logging.getLogger(__name__)


def _storage_dir(user_id: uuid.UUID) -> Path:
    d = Path(get_settings().upload_dir).resolve() / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean_project(project: str) -> str:
    p = " ".join(project.split())
    if len(p) > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Project name is too long (max 100 characters).")
    return p


async def _owned(db: AsyncSession, user: User, doc_id: uuid.UUID) -> Document:
    doc = await db.scalar(select(Document).where(Document.id == doc_id, Document.user_id == user.id))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def _quick_check(source: str, data: bytes, max_bytes: int) -> None:
    """Cheap validation at upload time; full extraction happens in the background worker."""
    file_type, _ = classify(source)
    if not data:
        raise UploadRejected("File is empty.")
    if len(data) > max_bytes:
        raise UploadRejected(f"File is larger than {max_bytes // (1024 * 1024)} MB.")
    if file_type == "pdf" and not data.startswith(b"%PDF"):
        raise UploadRejected("Not a valid PDF file.")
    if file_type != "pdf" and b"\x00" in data[:8192]:
        raise UploadRejected("This looks like a binary file, not text.")


@router.post("/documents", response_model=list[UploadResult])
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    paths: list[str] | None = Form(None, description="Relative path per file (folder uploads); defaults to file name"),
    project: str = Form(""),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    s = get_settings()
    if len(files) > s.max_files_per_upload:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"At most {s.max_files_per_upload} files per upload.")
    if paths is not None and len(paths) != len(files):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "`paths` must have one entry per file.")
    project = _clean_project(project)
    ingestor: Ingestor = request.app.state.ingestor
    max_bytes = s.max_upload_mb * 1024 * 1024
    results: list[UploadResult] = []
    to_queue: list[uuid.UUID] = []

    for i, f in enumerate(files):
        raw_name = (paths[i] if paths else None) or f.filename or "upload"
        try:
            source = clean_source(raw_name)
            data = await f.read(max_bytes + 1)
            _quick_check(source, data, max_bytes)
        except UploadRejected as e:
            results.append(UploadResult(source=raw_name[:500], status="rejected", reason=str(e)))
            continue
        digest = hashlib.sha256(data).hexdigest()
        doc = await db.scalar(
            select(Document).where(Document.user_id == user.id, Document.project == project, Document.source == source)
        )
        if doc is not None and doc.sha256 == digest and doc.status in ("ready", "pending", "processing"):
            results.append(UploadResult(source=source, status="unchanged", document_id=doc.id))
            continue
        if doc is None:
            doc = Document(
                user_id=user.id, project=project, title=Path(source).name[:300], source=source,
                file_type=classify(source)[0], sha256=digest, size_bytes=len(data), status="pending",
                storage_path="", chunk_count=0,
            )
            db.add(doc)
            await db.flush()
        path = _storage_dir(user.id) / f"{doc.id}.bin"
        await asyncio.to_thread(path.write_bytes, data)
        doc.storage_path, doc.sha256, doc.size_bytes = str(path), digest, len(data)
        doc.status, doc.error = "pending", None
        to_queue.append(doc.id)
        results.append(UploadResult(source=source, status="queued", document_id=doc.id))

    await db.commit()
    for doc_id in to_queue:
        ingestor.enqueue(doc_id)
    log.info(
        "documents uploaded",
        extra={"queued": len(to_queue), "rejected": sum(r.status == "rejected" for r in results), "project": project},
    )
    return results


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    project: str | None = None, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(Document.user_id == user.id)
    if project is not None:
        stmt = stmt.where(Document.project == project)
    return list(await db.scalars(stmt.order_by(Document.project, Document.source)))


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
async def get_document(doc_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    doc = await _owned(db, user, doc_id)
    chunks = await db.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.ordinal))
    return DocumentDetail(
        **DocumentOut.model_validate(doc).model_dump(), chunks=[ChunkOut.model_validate(c) for c in chunks]
    )


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    doc = await _owned(db, user, doc_id)
    path = Path(doc.storage_path)
    await db.delete(doc)  # chunks cascade
    await db.commit()
    await asyncio.to_thread(path.unlink, missing_ok=True)


@router.post("/documents/{doc_id}/reindex", response_model=DocumentOut)
async def reindex_document(
    doc_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    doc = await _owned(db, user, doc_id)
    doc.status, doc.error = "pending", None
    await db.commit()
    request.app.state.ingestor.enqueue(doc.id)
    return doc


@router.get("/knowledge/search", response_model=list[SearchHitOut])
async def search_knowledge(
    request: Request,
    q: str = Query(min_length=1, max_length=500),
    project: str | None = None,
    limit: int = Query(8, ge=1, le=20),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """The exact retrieval LOKI uses in chat, for inspecting what it would see."""
    svc: KnowledgeService = request.app.state.knowledge
    try:
        hits = await svc.search(db, user.id, q, project=project, top_k=limit)
    except LLMError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Embedding model unavailable: {e}") from e
    return [
        SearchHitOut(
            document_id=h.chunk.document_id, title=h.chunk.document.title, source=h.chunk.document.source,
            project=h.chunk.document.project, heading_path=h.chunk.heading_path, page=h.chunk.page,
            line_start=h.chunk.line_start, line_end=h.chunk.line_end, content=h.chunk.content,
            score=round(h.score, 4), rerank=None if h.rerank is None else round(h.rerank, 4),
            vector_rank=h.vector_rank, keyword_rank=h.keyword_rank,
        )
        for h in hits
    ]


@router.get("/knowledge/status")
async def knowledge_status(request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(Document.status, func.count(), func.coalesce(func.sum(Document.chunk_count), 0))
        .where(Document.user_id == user.id)
        .group_by(Document.status)
    )
    by_status = {st: n for st, n, _ in rows.all()}
    chunks = await db.scalar(select(func.count()).select_from(Chunk).where(Chunk.user_id == user.id))
    rr = request.app.state.knowledge.reranker
    return {
        "documents": sum(by_status.values()),
        "by_status": by_status,
        "chunks": chunks,
        "embedding_model": request.app.state.embeddings.model,
        "reranker": {"model": rr.name if rr else None, "state": rr.state if rr else "disabled", "error": rr.error if rr else None},
    }


@router.get("/projects")
async def list_projects(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Project names used by documents or memories, for pickers."""
    docs = await db.scalars(select(Document.project).where(Document.user_id == user.id, Document.project != "").distinct())
    mems = await db.scalars(select(Memory.project).where(Memory.user_id == user.id, Memory.project.is_not(None)).distinct())
    return sorted({*docs, *mems}, key=str.lower)
