"""Background ingestion: extract → clean → chunk → embed → swap chunks atomically. One document at a time."""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.models import Chunk, Document
from app.db.session import SessionLocal
from app.knowledge.chunking import chunk, passage_label
from app.knowledge.extract import UploadRejected, extract
from app.llm.base import LLMError
from app.llm.embeddings import EmbeddingProvider

log = logging.getLogger(__name__)
EMBED_BATCH = 32


class Ingestor:
    """In-process queue + single worker. Survives restarts: unfinished documents are re-queued at start-up.

    Kept in-process on purpose: Celery has no Windows support, and one GPU-bound worker is all this machine needs.
    """

    def __init__(self, embeddings: EmbeddingProvider, settings: Settings) -> None:
        self.embeddings = embeddings
        self.settings = settings
        self.queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._queued: set[uuid.UUID] = set()

    async def start(self) -> None:
        async with SessionLocal() as db:
            stuck = await db.scalars(select(Document.id).where(Document.status.in_(("pending", "processing"))))
            for doc_id in stuck:
                self.enqueue(doc_id)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def enqueue(self, doc_id: uuid.UUID) -> None:
        if doc_id not in self._queued:
            self._queued.add(doc_id)
            self.queue.put_nowait(doc_id)

    async def wait_idle(self) -> None:
        """Test helper: block until everything queued so far has been processed."""
        await self.queue.join()

    async def _run(self) -> None:
        while True:
            doc_id = await self.queue.get()
            self._queued.discard(doc_id)
            try:
                await self.process(doc_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ingestion crashed", extra={"document_id": str(doc_id)})
            finally:
                self.queue.task_done()

    async def process(self, doc_id: uuid.UUID) -> None:
        start = time.perf_counter()
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            if doc is None:
                return
            doc.status, doc.error = "processing", None
            await db.commit()
            try:
                data = await asyncio.to_thread(Path(doc.storage_path).read_bytes)
                extracted = await asyncio.to_thread(
                    extract, doc.source, data, max_bytes=self.settings.max_upload_mb * 1024 * 1024
                )
                drafts = chunk(extracted, max_chars=self.settings.chunk_chars, overlap=self.settings.chunk_overlap_chars)
                if not drafts:
                    raise UploadRejected("No text to index.")
                vectors: list[list[float]] = []
                for i in range(0, len(drafts), EMBED_BATCH):
                    batch = drafts[i : i + EMBED_BATCH]
                    vectors += await self.embeddings.embed_documents(
                        [
                            f"{passage_label(extracted.title, doc.source, extracted.file_type, extracted.language, d.heading_path)}"
                            f"\n\n{d.content}"
                            for d in batch
                        ]
                    )
            except (UploadRejected, LLMError, OSError) as e:
                doc.status, doc.error = "failed", str(e)[:500]
                await db.commit()
                log.warning("ingestion failed", extra={"document_id": str(doc_id), "error": doc.error})
                return

            # Swap in one transaction: searches see either the old chunks or the new ones, never a mix or nothing.
            await db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            db.add_all(
                Chunk(
                    document_id=doc.id,
                    user_id=doc.user_id,
                    ordinal=i,
                    content=d.content,
                    heading_path=d.heading_path,
                    page=d.page,
                    line_start=d.line_start,
                    line_end=d.line_end,
                    embedding=v,
                )
                for i, (d, v) in enumerate(zip(drafts, vectors, strict=True))
            )
            doc.title = extracted.title
            doc.file_type, doc.language = extracted.file_type, extracted.language
            doc.page_count = extracted.page_count
            doc.chunk_count = len(drafts)
            doc.status, doc.indexed_at = "ready", datetime.now(UTC)
            await db.commit()
            log.info(
                "document indexed",
                extra={"document_id": str(doc_id), "chunks": len(drafts), "s": round(time.perf_counter() - start, 2)},
            )
