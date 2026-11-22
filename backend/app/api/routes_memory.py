import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.db.models import Memory, User, UserSettings
from app.db.session import get_db
from app.llm.base import LLMError
from app.memory import store
from app.memory.secrets import find_secrets
from app.memory.service import MemoryService
from app.schemas import MemoryCreate, MemoryKind, MemoryOut, MemoryUpdate, SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api", tags=["memory"])


def _memory(request: Request) -> MemoryService:
    return request.app.state.memory


def _reject_secrets(text: str) -> None:
    if kinds := find_secrets(text):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"This looks like it contains a secret ({', '.join(kinds)}). LOKI never stores secrets in memory.",
        )


async def _embed(svc: MemoryService, text: str) -> list[float]:
    try:
        return await svc.embed_for_storage(text)
    except LLMError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Embedding model unavailable: {e}") from e


async def _owned(db: AsyncSession, user: User, memory_id: uuid.UUID) -> Memory:
    m = await db.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user.id))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found")
    return m


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(
    request: Request,
    kind: MemoryKind | None = None,
    q: str | None = Query(default=None, max_length=500),
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """All memories (newest first), or a semantic search when `q` is given."""
    kinds = (kind,) if kind else store.KINDS
    if q:
        svc = _memory(request)
        try:
            vec = await svc.embeddings.embed_query(q)
        except LLMError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Embedding model unavailable: {e}") from e
        hits = await store.search(db, user.id, vec, k=min(limit, 50), min_similarity=0.2, kinds=kinds)
        return [MemoryOut.model_validate(h.memory).model_copy(update={"similarity": round(h.similarity, 3)}) for h in hits]
    rows = await db.scalars(
        select(Memory)
        .where(Memory.user_id == user.id, Memory.kind.in_(kinds))
        .order_by(Memory.updated_at.desc())
        .limit(limit)
    )
    return list(rows)


@router.get("/memories/stats")
async def memory_stats(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(Memory.kind, func.count()).where(Memory.user_id == user.id).group_by(Memory.kind))
    counts = {k: 0 for k in store.KINDS} | {k: n for k, n in rows.all()}
    return {"total": sum(counts.values()), "by_kind": counts}


@router.post("/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def add_memory(
    body: MemoryCreate, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    content = " ".join(body.content.split())
    _reject_secrets(content)
    svc = _memory(request)
    m = Memory(
        user_id=user.id,
        kind=body.kind,
        content=content,
        importance=body.importance,
        project=body.project or None,
        source="user_edited",
        embedding=await _embed(svc, content),
        embedding_model=svc.embeddings.model,
        use_count=0,
    )
    db.add(m)
    await db.commit()
    return m


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def edit_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    m = await _owned(db, user, memory_id)
    if body.content is not None:
        content = " ".join(body.content.split())
        _reject_secrets(content)
        if content != m.content:
            svc = _memory(request)
            m.embedding = await _embed(svc, content)
            m.embedding_model = svc.embeddings.model
            m.content = content
    if body.kind is not None:
        m.kind = body.kind
    if body.importance is not None:
        m.importance = body.importance
    if "project" in body.model_fields_set:
        m.project = body.project or None
    m.source = "user_edited"
    await db.commit()
    await db.refresh(m)
    return m


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, user, memory_id))
    await db.commit()


@router.delete("/memories")
async def delete_all_memories(
    confirm: bool = Query(False, description="Must be true: deletes every memory, permanently."),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if not confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass confirm=true to delete all memories.")
    deleted = await store.delete_all(db, user.id)
    await db.commit()
    return {"deleted": deleted}


@router.get("/settings", response_model=SettingsOut)
async def get_settings_(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return SettingsOut(memory_enabled=await store.memory_enabled(db, user.id))


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = await db.get(UserSettings, user.id)
    if s is None:
        s = UserSettings(user_id=user.id, memory_enabled=True)
        db.add(s)
    if body.memory_enabled is not None:
        s.memory_enabled = body.memory_enabled
    await db.commit()
    return SettingsOut(memory_enabled=s.memory_enabled)
