"""Retrieval benchmark (Precision/Recall/NDCG/MRR per search mode) and, with --answers, answer quality.

A passage counts as relevant to a query when it contains one of the query's labelled evidence phrases
(datasets/rag/queries.jsonl). Labels are phrases, not chunk ids, so the benchmark survives chunking changes.
"""

import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any

from eval.common import norm, pct, register, turn, wait_documents, write_report

DATA = Path(__file__).resolve().parent / "datasets" / "rag"
K = 5
MODES = ["vector", "keyword", "hybrid", "hybrid+rerank", "production"]
ABSTAIN = re.compile(
    r"(don't|do not|doesn't|does not|didn't|did not|no|can't|cannot|couldn't|could not)\b.{0,40}"
    r"\b(have|cover|mention|contain|include|find|information|details|say|know)"
    r"|not (covered|mentioned|in (your|the) (documents|files))|no (information|mention|details)",
    re.I)

JUDGE_PROMPT = """You check whether an answer is supported by source passages. For each factual claim in the ANSWER,
decide whether the PASSAGES state it. General phrasing, greetings and offers to help are not claims. Reply as JSON:
{"supported": true|false, "unsupported_claims": ["..."]}"""


def load_queries() -> list[dict[str, Any]]:
    return [json.loads(line) for line in (DATA / "queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def corpus_files() -> list[tuple[str, bytes, str]]:
    from eval.pdf import SECURITY_POLICY

    root = DATA / "corpus"
    files = [(p.relative_to(root).as_posix(), p.read_bytes(), "application/octet-stream")
             for p in sorted(root.rglob("*")) if p.is_file()]
    files.append(("security-policy.pdf", SECURITY_POLICY, "application/pdf"))
    return files


def relevant(content: str, phrases: list[str]) -> bool:
    c = norm(content)
    return any(norm(p) in c for p in phrases)


def ranking_metrics(rel: list[bool], total_relevant: int) -> dict[str, float]:
    out = {}
    for k in (1, 3, 5):
        top = rel[:k]
        out[f"p@{k}"] = sum(top) / k
        out[f"recall@{k}"] = 1.0 if any(top) else 0.0
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(rel[:K]) if r)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(total_relevant, K)))
    out[f"ndcg@{K}"] = dcg / idcg if idcg else 0.0
    first = next((i for i, r in enumerate(rel) if r), None)
    out["mrr"] = 1 / (first + 1) if first is not None else 0.0
    return out


async def rank(app, db, user_id: uuid.UUID, query: str, mode: str) -> list[str]:
    """Contents of the top-K passages for one search mode."""
    from app.knowledge.search import RRF_K, hybrid_search, keyword_candidates, vector_candidates
    from app.knowledge.service import _QUERY_INSTRUCTION

    ks = app.state.knowledge
    cand = ks.settings.rag_candidates
    if mode == "production":
        return [h.chunk.content for h in await ks._search_focused(db, user_id, query)][:K]
    qvec = (await app.state.embeddings.embed_documents([_QUERY_INSTRUCTION + query]))[0]
    if mode == "vector":
        return [c.content for c in await vector_candidates(db, user_id, qvec, limit=K, project=None)]
    if mode == "keyword":
        return [c.content for c in await keyword_candidates(db, user_id, query, limit=K, project=None)]
    if mode == "hybrid":  # pure reciprocal-rank fusion ranking, no filtering
        vec = await vector_candidates(db, user_id, qvec, limit=cand, project=None)
        kw = await keyword_candidates(db, user_id, query, limit=cand, project=None)
        score: dict[uuid.UUID, float] = {}
        by_id = {}
        for lst in (vec, kw):
            for r, c in enumerate(lst, start=1):
                score[c.id] = score.get(c.id, 0) + 1 / (RRF_K + r)
                by_id[c.id] = c
        return [by_id[i].content for i in sorted(score, key=lambda i: -score[i])[:K]]
    hits = await hybrid_search(db, user_id, query, qvec, candidates=cand, top_k=K, reranker=ks.reranker,
                               threshold=ks.settings.rerank_threshold)
    return [h.chunk.content for h in hits]


def run(client, app, *, answers: bool, judge: bool) -> Path:
    from sqlalchemy import select

    from app.db.models import Chunk
    from app.db.session import SessionLocal

    register(client, "rag")
    files = corpus_files()
    client.post("/api/documents", files=[("files", f) for f in files], data={"project": "Meridian"})
    docs = wait_documents(client, len(files))
    failed = [d["source"] for d in docs if d["status"] != "ready"]
    user_id = uuid.UUID(client.get("/api/auth/me").json()["id"])
    reranker = app.state.knowledge.reranker
    for _ in range(120):  # the ONNX reranker loads in the background
        if reranker is None or reranker.state != "loading":
            break
        time.sleep(0.5)
    queries = load_queries()

    async def all_chunks():
        async with SessionLocal() as db:
            return [c.content for c in await db.scalars(select(Chunk).where(Chunk.user_id == user_id))]

    chunks = client.portal.call(all_chunks)

    async def search_all():
        results = {}
        async with SessionLocal() as db:
            for q in queries:
                results[q["id"]] = {}
                for mode in MODES:
                    t0 = time.perf_counter()
                    contents = await rank(app, db, user_id, q["query"], mode)
                    results[q["id"]][mode] = (contents, time.perf_counter() - t0)
        return results

    searched = client.portal.call(search_all)
    per_query, by_mode = [], {m: [] for m in MODES}
    false_positive = {m: 0 for m in MODES}
    latency = {m: [] for m in MODES}
    answerable = [q for q in queries if q["relevant"]]
    for q in queries:
        row = {"id": q["id"], "type": q["type"], "query": q["query"], "modes": {}}
        total_rel = sum(1 for c in chunks if relevant(c, q["relevant"])) if q["relevant"] else 0
        for mode in MODES:
            contents, secs = searched[q["id"]][mode]
            latency[mode].append(secs * 1000)
            if not q["relevant"]:
                false_positive[mode] += bool(contents)
                row["modes"][mode] = {"returned": len(contents)}
                continue
            rel = [relevant(c, q["relevant"]) for c in contents]
            m = ranking_metrics(rel, total_rel)
            by_mode[mode].append((q["type"], m))
            row["modes"][mode] = {**m, "returned": len(contents)}
        per_query.append(row)

    def mean(mode: str, key: str, qtype: str | None = None) -> float | None:
        vals = [m[key] for t, m in by_mode[mode] if qtype is None or t == qtype]
        return round(sum(vals) / len(vals), 3) if vals else None

    retrieval = {mode: {key: mean(mode, key) for key in ("p@1", "p@3", "p@5", "recall@1", "recall@3", "recall@5",
                                                          f"ndcg@{K}", "mrr")}
                 | {"p50_ms": pct(latency[mode], 0.5),
                    "unanswerable_with_results": false_positive[mode]}
                 for mode in MODES}
    types = sorted({q["type"] for q in answerable})
    by_type = {t: {"n": sum(1 for q in answerable if q["type"] == t), "recall@5": mean("production", "recall@5", t),
                   "mrr": mean("production", "mrr", t)} for t in types}

    headline: dict[str, Any] = {
        "queries": len(queries), "answerable": len(answerable), "k": K,
        "recall@5": retrieval["production"]["recall@5"], "precision@5": retrieval["production"]["p@5"],
        f"ndcg@{K}": retrieval["production"][f"ndcg@{K}"], "mrr": retrieval["production"]["mrr"],
        "unanswerable_with_results": f"{false_positive['production']}/{len(queries) - len(answerable)}",
    }
    details: dict[str, Any] = {"retrieval_by_mode": retrieval, "production_by_query_type": by_type,
                               "queries": per_query, "documents_failed": failed}
    if answers:
        ans = answer_quality(client, app, queries, judge=judge)
        details["answers"] = ans
        headline.update({k: ans["summary"][k] for k in ("answer_correct", "citation_precision", "citation_validity",
                                                        "context_relevance", "faithfulness", "abstained_when_unanswerable",
                                                        "p50_first_token_s")})
    config = {"embedding_model": app.state.embeddings.model,
              "reranker": reranker.name if reranker else None, "reranker_state": reranker.state if reranker else None,
              "rerank_threshold": app.state.knowledge.settings.rerank_threshold, "chunks": len(chunks),
              "candidates": app.state.knowledge.settings.rag_candidates,
              "llm": app.state.llm.primary.model if answers else None, "judge": judge and answers}
    return write_report("rag", config, headline, details)


def answer_quality(client, app, queries: list[dict], *, judge: bool) -> dict[str, Any]:
    """Ask each question in a temporary chat (documents are searched, memory is not) and score the reply."""
    from sqlalchemy import select

    from app.db.models import Chunk
    from app.db.session import SessionLocal
    from app.llm.base import ChatMessage

    async def chunk_texts():
        async with SessionLocal() as db:
            return {str(c.id): c.content for c in await db.scalars(select(Chunk))}

    full = client.portal.call(chunk_texts)

    def text_of(c: dict) -> str:  # whole passage, not the 600-character snippet
        return full.get(c.get("chunk_id"), c.get("snippet", ""))

    rows = []
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "client_info", "timezone": "UTC"})
        for q in queries:
            r = turn(ws, q["query"], temporary=True)
            reply, cites = r["reply"], r["citations"] or []
            shown = [c for c in cites]
            cited = [c for c in cites if c.get("cited")]
            row: dict[str, Any] = {"id": q["id"], "type": q["type"], "reply": reply, "first_token_s": r["first_token_s"],
                                   "total_s": r["total_s"], "passages_shown": len(shown), "passages_cited": len(cited)}
            markers = {int(n) for n in re.findall(r"\[(\d+)\]", reply)}
            row["invented_markers"] = len(markers - {c["n"] for c in cites})
            if q["relevant"]:
                row["correct"] = all(re.search(f, reply, re.I) for f in q["facts"])
                row["cited_relevant"] = sum(1 for c in cited if relevant(text_of(c), q["relevant"]))
                row["shown_relevant"] = sum(1 for c in shown if relevant(text_of(c), q["relevant"]))
            else:
                row["abstained"] = bool(ABSTAIN.search(reply))
            if judge and q["relevant"] and shown:
                passages = "\n\n".join(f"[{c['n']}] {text_of(c)}" for c in shown)
                try:
                    raw = client.portal.call(lambda: app.state.llm.complete(
                        [ChatMessage("system", JUDGE_PROMPT),
                         ChatMessage("user", f"PASSAGES:\n{passages}\n\nANSWER:\n{reply}")],
                        max_tokens=300,
                        json_schema={"type": "object", "properties": {
                            "supported": {"type": "boolean"},
                            "unsupported_claims": {"type": "array", "items": {"type": "string"}}},
                            "required": ["supported", "unsupported_claims"]}))
                    verdict = json.loads(raw)
                    row["faithful"] = bool(verdict.get("supported"))
                    row["unsupported_claims"] = verdict.get("unsupported_claims", [])[:5]
                except Exception as e:  # noqa: BLE001 - a judge failure is recorded, not fatal
                    row["judge_error"] = str(e)[:200]
            rows.append(row)

    ans = [r for r in rows if "correct" in r]
    un = [r for r in rows if "abstained" in r]
    cited_total = sum(r["passages_cited"] for r in ans)
    shown_total = sum(r["passages_shown"] for r in ans)
    markers_total = cited_total + sum(r["invented_markers"] for r in rows)
    judged = [r for r in ans if "faithful" in r]

    def ratio(a, b):
        return round(a / b, 3) if b else None

    summary = {
        "answer_correct": ratio(sum(r["correct"] for r in ans), len(ans)),
        "citation_precision": ratio(sum(r["cited_relevant"] for r in ans), cited_total),
        "citation_validity": ratio(cited_total, markers_total),
        "context_relevance": ratio(sum(r["shown_relevant"] for r in ans), shown_total),
        "faithfulness": ratio(sum(r["faithful"] for r in judged), len(judged)) if judged else None,
        "abstained_when_unanswerable": ratio(sum(r["abstained"] for r in un), len(un)),
        "answers_with_citation": ratio(sum(1 for r in ans if r["passages_cited"]), len(ans)),
        "p50_first_token_s": pct([r["first_token_s"] for r in rows], 0.5),
        "p50_total_s": pct([r["total_s"] for r in rows], 0.5),
    }
    return {"summary": summary, "rows": rows}
