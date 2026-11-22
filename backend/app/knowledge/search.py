"""Hybrid retrieval: vector + keyword candidates, merged with reciprocal-rank fusion, then cross-encoder reranked."""

import logging
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document
from app.knowledge.chunking import passage_label
from app.knowledge.rerank import Reranker

log = logging.getLogger(__name__)
RRF_K = 60


@dataclass
class Hit:
    chunk: Chunk
    vector_rank: int | None
    keyword_rank: int | None
    fused: float
    rerank: float | None = None

    @property
    def score(self) -> float:
        """Final relevance used for thresholding/ordering (reranker probability when available)."""
        return self.rerank if self.rerank is not None else self.fused


def _scope(stmt, user_id: uuid.UUID, project: str | None):
    stmt = stmt.join(Document, Chunk.document_id == Document.id).where(
        Chunk.user_id == user_id, Document.status == "ready"
    )
    return stmt.where(Document.project == project) if project is not None else stmt


async def vector_candidates(
    db: AsyncSession, user_id: uuid.UUID, qvec: list[float], *, limit: int, project: str | None
) -> list[Chunk]:
    if db.bind.dialect.name == "postgresql":
        stmt = _scope(select(Chunk), user_id, project).where(Chunk.embedding.is_not(None))
        return list(await db.scalars(stmt.order_by(Chunk.embedding.cosine_distance(qvec)).limit(limit)))
    rows = list(await db.scalars(_scope(select(Chunk), user_id, project).where(Chunk.embedding.is_not(None))))
    q = np.asarray(qvec, dtype=np.float32)
    rows.sort(key=lambda c: -float(np.dot(q, np.asarray(c.embedding, dtype=np.float32))))
    return rows[:limit]


_WORD = re.compile(r"[a-z0-9_]{2,}")
_STOP = set("the a an and or of to in on for is are was were be how what which who does do did can with my me i it this that".split())


def _tokens(s: str) -> list[str]:
    return [w for w in _WORD.findall(s.lower()) if w not in _STOP]


async def keyword_candidates(
    db: AsyncSession, user_id: uuid.UUID, query: str, *, limit: int, project: str | None
) -> list[Chunk]:
    if db.bind.dialect.name == "postgresql":
        # websearch_to_tsquery ANDs the terms; fall back to OR so partial matches still surface.
        terms = " | ".join(re.sub(r"[^\w]", "", t) for t in _tokens(query) if re.sub(r"[^\w]", "", t))
        if not terms:
            return []
        tsq = func.to_tsquery("english", terms)
        rank = func.ts_rank_cd(text("chunks.tsv"), tsq)
        stmt = _scope(select(Chunk), user_id, project).where(text("chunks.tsv @@ to_tsquery('english', :terms)"))
        stmt = stmt.params(terms=terms).order_by(rank.desc()).limit(limit)
        return list(await db.scalars(stmt))
    # SQLite (dev/tests): small BM25 over the user's chunks.
    rows = list(await db.scalars(_scope(select(Chunk), user_id, project)))
    q = set(_tokens(query))
    if not q or not rows:
        return []
    docs = [Counter(_tokens(f"{c.heading_path or ''} {c.content}")) for c in rows]
    avg = sum(sum(d.values()) for d in docs) / len(docs)
    df = {t: sum(1 for d in docs if t in d) for t in q}
    scored = []
    for c, d in zip(rows, docs, strict=True):
        length = sum(d.values()) or 1
        s = sum(
            math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5)) * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * length / avg))
            for t in q
            if d[t]
        )
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda t: -t[0])
    return [c for _, c in scored[:limit]]


async def hybrid_search(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    qvec: list[float],
    *,
    candidates: int,
    top_k: int,
    reranker: Reranker | None,
    threshold: float,
    project: str | None = None,
) -> list[Hit]:
    vec = await vector_candidates(db, user_id, qvec, limit=candidates, project=project)
    kw = await keyword_candidates(db, user_id, query, limit=candidates, project=project)
    hits: dict[uuid.UUID, Hit] = {}
    for rank, c in enumerate(vec, start=1):
        hits[c.id] = Hit(c, rank, None, 1 / (RRF_K + rank))
    for rank, c in enumerate(kw, start=1):
        h = hits.setdefault(c.id, Hit(c, None, None, 0.0))
        h.keyword_rank = rank
        h.fused += 1 / (RRF_K + rank)
    pool = sorted(hits.values(), key=lambda h: -h.fused)[:candidates]
    if not pool:
        return []
    if reranker is not None and reranker.state == "ready":
        texts = []
        for h in pool:
            d = h.chunk.document
            label = passage_label(d.title, d.source, d.file_type, d.language, h.chunk.heading_path)
            texts.append(f"{label}\n{h.chunk.content}")
        for h, s in zip(pool, await reranker.score(query, texts), strict=True):
            h.rerank = s

        def keep(h: Hit) -> bool:
            # The reranker is trained mostly on prose and under-scores code. A passage that BOTH the semantic and
            # the keyword search put in their top 2 is strong evidence by itself, unless the reranker clearly objects.
            agreed = (h.vector_rank or 99) <= 2 and (h.keyword_rank or 99) <= 2
            return h.rerank >= threshold or (agreed and h.rerank >= threshold * 0.6)

        pool = [h for h in sorted(pool, key=lambda h: -h.rerank) if keep(h)]
    else:
        # Without a reranker there is no calibrated score: keep only passages both searches agree on, or the top few.
        agreed = [h for h in pool if h.vector_rank and h.keyword_rank]
        pool = agreed or pool[: max(2, top_k // 2)]
    return pool[:top_k]
