"""Shared plumbing for the evaluation suites: an isolated database, the real app in-process, report writing.

The evals run LOKI's real code with the real models (Ollama, embeddings, reranker, Whisper, Kokoro) against a
separate database whose name must end in `_eval`; it is wiped at the start of every run. Your own data is never
touched.
"""

import asyncio
import json
import os
import re
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
DEFAULT_DB = "postgresql+asyncpg://loki:loki@127.0.0.1:5432/loki_eval"


def prepare_environment(*, voice: bool) -> str:
    """Point LOKI at a fresh eval database. Must run before `app.main` is imported."""
    url = os.environ.get("EVAL_DATABASE_URL", DEFAULT_DB)
    name = url.rsplit("/", 1)[-1]
    if not name.endswith("_eval"):
        raise SystemExit("EVAL_DATABASE_URL must name a database ending in _eval (it is wiped on every run).")
    if url.startswith("postgresql"):
        asyncio.run(_reset_postgres(url))
    else:
        path = Path(url.split("///", 1)[1])
        path.unlink(missing_ok=True)
    os.environ.update({
        "DATABASE_URL": url,
        "ENVIRONMENT": "test",
        "UPLOAD_DIR": tempfile.mkdtemp(prefix="loki-eval-uploads-"),
        "VOICE_ENABLED": "true" if voice else "false",
        "METRICS_ENABLED": "false",  # eval traffic must not show up as usage
    })
    return url


async def _reset_postgres(url: str) -> None:
    import asyncpg

    raw = url.replace("postgresql+asyncpg://", "postgresql://")
    base, name = raw.rsplit("/", 1)
    admin = await asyncpg.connect(f"{base}/postgres")
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    con = await asyncpg.connect(raw)
    try:
        await con.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await con.close()


def register(client, label: str) -> None:
    """A fresh eval user per scenario (logged in by the session cookie)."""
    from app.core import ratelimit

    ratelimit.register_limiter._events.clear()
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={
        "email": f"eval-{label}-{uuid.uuid4().hex[:6]}@example.com", "password": "eval-password-123456",
        "display_name": "Alex"})
    r.raise_for_status()


def wait_documents(client, n: int, timeout: float = 300) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        docs = client.get("/api/documents").json()
        if len(docs) >= n and all(d["status"] in ("ready", "failed") for d in docs):
            return docs
        time.sleep(0.5)
    raise TimeoutError("documents were not indexed in time")


def turn(ws, text: str, *, approve: bool | None = None, temporary: bool = False) -> dict[str, Any]:
    """Send one message; answer approvals; return the reply, tool results and timings."""
    t0 = time.perf_counter()
    ws.send_json({"type": "user_message", "content": text, "temporary": temporary})
    out: dict[str, Any] = {"tools": [], "approvals": 0, "reply": "", "citations": None, "first_token_s": None,
                           "error": None}
    while True:
        ev = ws.receive_json()
        kind = ev.get("type")
        if kind == "token" and out["first_token_s"] is None:
            out["first_token_s"] = round(time.perf_counter() - t0, 3)
        elif kind == "approval_required":
            out["approvals"] += 1
            ws.send_json({"type": "approval", "approval_id": ev["approval_id"], "approved": bool(approve)})
        elif kind == "tool_result":
            out["tools"].append({"tool": ev["tool"], "status": ev["status"]})
        elif kind == "assistant_end":
            out["reply"] = ev["message"]["content"]
            out["citations"] = ev["message"].get("citations")
        elif kind == "error":
            out["error"] = ev.get("code")
        elif ev == {"type": "state", "state": "idle"}:
            out["total_s"] = round(time.perf_counter() - t0, 3)
            return out


def write_report(suite: str, config: dict[str, Any], headline: dict[str, Any], details: Any) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"{suite}-{stamp}.json"
    path.write_text(json.dumps({"suite": suite, "ran_at": datetime.now(UTC).isoformat(), "config": config,
                                "headline": headline, "details": details}, indent=2, default=str), encoding="utf-8")
    return path


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def pct(values: list[float], q: float) -> float | None:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 3)
