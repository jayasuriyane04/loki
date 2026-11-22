"""Memory persistence + vector search. Postgres uses pgvector in SQL; SQLite (dev/tests) scores in Python."""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory, UserSettings

KINDS = ("profile", "episodic", "semantic")


@dataclass
class ScoredMemory:
    memory: Memory
    similarity: float
    score: float


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))


def rank(similarity: float, m: Memory, now: datetime) -> float:
    """Relevance first; importance and recency only break near-ties."""
    age_days = max(0.0, (now - (m.event_at or m.updated_at)).total_seconds() / 86400)
    return similarity + 0.10 * m.importance + 0.05 * math.exp(-age_days / 90)


async def nearest(
    db: AsyncSession, user_id: uuid.UUID, vector: list[float], *, limit: int, kinds: tuple[str, ...] = KINDS
) -> list[tuple[Memory, float]]:
    """(memory, cosine similarity) for the closest memories of one user, best first."""
    base: Select = select(Memory).where(
        Memory.user_id == user_id, Memory.embedding.is_not(None), Memory.kind.in_(kinds)
    )
    if db.bind.dialect.name == "postgresql":
        dist = Memory.embedding.cosine_distance(vector).label("dist")
        rows = (await db.execute(base.add_columns(dist).order_by(dist).limit(limit))).all()
        return [(m, 1.0 - float(d)) for m, d in rows]
    q = np.asarray(vector, dtype=np.float32)
    scored = [(m, _cosine(q, np.asarray(m.embedding, dtype=np.float32))) for m in (await db.scalars(base))]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:limit]


async def search(
    db: AsyncSession,
    user_id: uuid.UUID,
    vector: list[float],
    *,
    k: int,
    min_similarity: float,
    kinds: tuple[str, ...] = KINDS,
) -> list[ScoredMemory]:
    now = datetime.now(UTC)
    hits = await nearest(db, user_id, vector, limit=k * 3, kinds=kinds)
    ranked = [ScoredMemory(m, s, rank(s, m, now)) for m, s in hits if s >= min_similarity]
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:k]


async def core_profile(db: AsyncSession, user_id: uuid.UUID, *, limit: int = 6) -> list[Memory]:
    """The most important profile facts — always in context so LOKI knows who it is talking to."""
    rows = await db.scalars(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.kind == "profile", Memory.importance >= 0.7)
        .order_by(Memory.importance.desc(), Memory.updated_at.desc())
        .limit(limit)
    )
    return list(rows)


async def episodes_between(
    db: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime, *, limit: int = 6
) -> list[Memory]:
    rows = await db.scalars(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.kind == "episodic",
            Memory.event_at.is_not(None),
            Memory.event_at >= start,
            Memory.event_at < end,
        )
        .order_by(Memory.event_at.desc())
        .limit(limit)
    )
    return list(rows)


async def mark_used(db: AsyncSession, memories: list[Memory]) -> None:
    now = datetime.now(UTC)
    for m in memories:
        m.last_used_at = now
        m.use_count = (m.use_count or 0) + 1


async def memory_enabled(db: AsyncSession, user_id: uuid.UUID) -> bool:
    s = await db.get(UserSettings, user_id)
    return True if s is None else s.memory_enabled


async def delete_all(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(delete(Memory).where(Memory.user_id == user_id))
    return result.rowcount or 0
