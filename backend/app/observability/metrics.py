"""Aggregations behind the Analytics page. Computed in Python from the traces/events of the selected window:
volumes on a personal assistant are small, and this keeps SQLite and Postgres behaving the same."""

import json
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, MetricEvent, TraceRow
from app.observability.trace import sink

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval" / "results"
FAILED = {"error", "timeout", "invalid"}


def pct(values: list[float | int | None], q: float) -> float | None:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def dist(values: list[float | int | None]) -> dict[str, Any]:
    v = [x for x in values if x is not None]
    return {"n": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95), "max": max(v) if v else None}


def rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _span_ms(t: TraceRow, name: str) -> int | None:
    for s in t.spans or ():
        if s["name"] == name:
            return s["duration_ms"]
    return None


def _span_attr(t: TraceRow, name: str, key: str) -> Any:
    for s in t.spans or ():
        if s["name"] == name:
            return (s.get("attrs") or {}).get(key)
    return None


async def summary(db: AsyncSession, user_id: uuid.UUID, days: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    traces = list(await db.scalars(select(TraceRow).where(TraceRow.user_id == user_id, TraceRow.created_at >= since)
                                   .order_by(TraceRow.created_at)))
    events = list(await db.scalars(select(MetricEvent).where(MetricEvent.created_at >= since)))
    turns = [t for t in traces if t.kind in ("chat_turn", "voice_turn")]
    voice = [t for t in turns if t.kind == "voice_turn"]
    answered = [t for t in turns if t.model]

    # ---- voice ----
    voice_out = {
        "turns": len(voice),
        "stt_ms": dist([t.stt_ms for t in voice]),
        "first_audio_ms": dist([t.first_audio_ms for t in voice]),
        "total_ms": dist([t.duration_ms for t in voice]),
        "stt_errors": sum(1 for t in voice if (t.attrs or {}).get("stt_error")),
        "no_speech": sum(1 for t in voice if (t.attrs or {}).get("stt_empty")),
        "stop_commands": sum(1 for t in voice if (t.attrs or {}).get("stop_command")),
        "interrupted": sum(1 for t in turns if t.status == "interrupted"),
        "tts_failures": sum(1 for t in turns if (t.attrs or {}).get("tts_failed")),
    }
    voice_out["stt_error_rate"] = rate(voice_out["stt_errors"], len(voice))

    # ---- model / responses ----
    by_model: dict[str, dict[str, Any]] = {}
    for t in answered:
        m = by_model.setdefault(f"{t.provider}/{t.model}", {"turns": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                                            "cost_usd": None})
        m["turns"] += 1
        m["prompt_tokens"] += t.prompt_tokens or 0
        m["completion_tokens"] += t.completion_tokens or 0
        c = sink.cost(t.model, t.prompt_tokens, t.completion_tokens)
        if c is not None:
            m["cost_usd"] = round((m["cost_usd"] or 0) + c, 6)
    responses = {
        "turns": len(turns),
        "first_token_ms": dist([t.first_token_ms for t in answered]),
        "total_ms": dist([t.duration_ms for t in answered]),
        "errors": sum(1 for t in turns if t.status == "error"),
        "error_rate": rate(sum(1 for t in turns if t.status == "error"), len(turns)),
        "fallbacks": sum(1 for t in turns if (t.attrs or {}).get("fell_back")),
        "prompt_tokens": sum(t.prompt_tokens or 0 for t in answered),
        "completion_tokens": sum(t.completion_tokens or 0 for t in answered),
        "cost_usd": round(sum(m["cost_usd"] or 0 for m in by_model.values()), 6)
        if any(m["cost_usd"] is not None for m in by_model.values()) else None,
        "by_model": by_model,
    }

    # ---- retrieval / RAG (live) ----
    with_docs = [t for t in turns if (_span_attr(t, "retrieval", "hits") or 0) > 0]
    cited = [t for t in turns if (t.attrs or {}).get("citations")]
    shown = sum(t.attrs["citations"]["shown"] for t in cited)
    used = sum(t.attrs["citations"]["cited"] for t in cited)
    invented = sum((t.attrs or {}).get("invented_citations") or 0 for t in turns)
    rag = {
        "retrieval_ms": dist([_span_ms(t, "retrieval") for t in turns]),
        "turns_with_documents": len(with_docs),
        "avg_passages": round(sum(_span_attr(t, "retrieval", "hits") for t in with_docs) / len(with_docs), 2)
        if with_docs else None,
        "turns_citing": sum(1 for t in cited if t.attrs["citations"]["cited"]),
        "passages_shown": shown,
        "passages_cited": used,
        "invented_citations": invented,
        # Share of [n] markers in answers that point at a real passage.
        "citation_validity": rate(used, used + invented),
    }

    # ---- memory ----
    extracts = [t for t in traces if t.kind == "memory_extract"]
    memory = {
        "recall_ms": dist([_span_ms(t, "memory_recall") for t in turns]),
        "recalls_with_hits": sum(1 for t in turns if (_span_attr(t, "memory_recall", "hits") or 0) > 0),
        "extraction_ms": dist([t.duration_ms for t in extracts]),
        "extraction_errors": sum(1 for t in extracts if t.status == "error"),
    }

    # ---- agent ----
    tool_turns = [t for t in turns if (t.attrs or {}).get("tools")]
    calls = [c for t in tool_turns for c in t.attrs["tools"]]
    per_tool: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "ok": 0, "ms": []})
    for c in calls:
        p = per_tool[c["tool"]]
        p["calls"] += 1
        p["ok"] += c["status"] == "ok"
        p["ms"].append(c["ms"])
    failed_turns = [t for t in tool_turns if any(c["status"] in FAILED for c in t.attrs["tools"])]
    recovered = 0
    for t in failed_turns:
        seq = t.attrs["tools"]
        first_fail = next(i for i, c in enumerate(seq) if c["status"] in FAILED)
        if any(c["status"] == "ok" for c in seq[first_fail + 1:]) and t.status == "ok":
            recovered += 1
    guards = Counter()
    for t in turns:
        for k, v in (t.attrs or {}).items():
            if k.startswith("events.guard."):
                guards[k.removeprefix("events.guard.")] += v
    agent = {
        "turns_with_tools": len(tool_turns),
        "tool_calls": len(calls),
        "success_rate": rate(sum(1 for c in calls if c["status"] == "ok"), len(calls)),
        "denied": sum(1 for c in calls if c["status"] == "denied"),
        "failed": sum(1 for c in calls if c["status"] in FAILED),
        "failure_recovery_rate": rate(recovered, len(failed_turns)),
        "turns_with_failures": len(failed_turns),
        "model_steps": dist([(t.attrs or {}).get("model_steps") for t in tool_turns]),
        "guards": dict(guards),
        "per_tool": sorted(
            [{"tool": k, "calls": v["calls"], "success_rate": rate(v["ok"], v["calls"]), "p50_ms": pct(v["ms"], 0.5)}
             for k, v in per_tool.items()], key=lambda x: -x["calls"]),
    }

    # ---- system ----
    http = [e for e in events if e.kind == "http"]
    routes: dict[str, list[int]] = defaultdict(list)
    for e in http:
        routes[e.name].append(e.duration_ms or 0)
    errors = [e for e in events if e.kind == "error"]
    gauges = [e for e in events if e.kind == "gauge" and e.name == "ws_connections"]
    fb = list(await db.scalars(select(Message.feedback).join(Conversation, Conversation.id == Message.conversation_id)
                               .where(Conversation.user_id == user_id, Message.feedback.is_not(None),
                                      Message.created_at >= since)))
    system = {
        "requests": len(http),
        "api_ms": dist([e.duration_ms for e in http]),
        "server_errors": sum(1 for e in http if not e.ok),
        "slowest_routes": sorted(
            [{"route": k, "n": len(v), "p50_ms": pct(v, 0.5), "p95_ms": pct(v, 0.95)} for k, v in routes.items()],
            key=lambda x: -(x["p95_ms"] or 0))[:8],
        "errors": len(errors),
        "errors_by_source": Counter(e.name for e in errors).most_common(8),
        "recent_errors": [{"at": e.created_at, "source": e.name, "message": (e.attrs or {}).get("message")}
                          for e in sorted(errors, key=lambda e: e.created_at, reverse=True)[:8]],
        "connections_now": sink.ws_connections,
        "connections_peak": max([int((e.attrs or {}).get("peak") or e.value or 0) for e in gauges] + [sink.ws_peak]),
        "feedback": {"up": sum(1 for f in fb if f > 0), "down": sum(1 for f in fb if f < 0)},
        "dropped_metrics": sink.dropped,
    }

    # ---- daily series ----
    daily: dict[str, dict[str, Any]] = {}
    for d in range(days - 1, -1, -1):
        key = (datetime.now(UTC) - timedelta(days=d)).date().isoformat()
        daily[key] = {"date": key, "turns": 0, "errors": 0, "tokens": 0, "latencies": []}
    for t in turns:
        row = daily.get(t.created_at.astimezone(UTC).date().isoformat())
        if row:
            row["turns"] += 1
            row["errors"] += t.status == "error"
            row["tokens"] += (t.prompt_tokens or 0) + (t.completion_tokens or 0)
            row["latencies"].append(t.first_token_ms)
    series = [{**{k: v for k, v in r.items() if k != "latencies"}, "p50_first_token_ms": pct(r["latencies"], 0.5)}
              for r in daily.values()]

    return {"days": days, "voice": voice_out, "responses": responses, "rag": rag, "memory": memory, "agent": agent,
            "system": system, "daily": series, "evals": latest_evals()}


def latest_evals() -> dict[str, Any]:
    """Headline numbers from the newest offline evaluation report of each suite (backend/eval/results)."""
    out: dict[str, Any] = {}
    if not EVAL_DIR.is_dir():
        return out
    for f in sorted(EVAL_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        suite = data.get("suite")
        if suite:
            out[suite] = {"file": f.name, "ran_at": data.get("ran_at"), "headline": data.get("headline"),
                          "config": data.get("config")}
    return out


def eval_report(name: str) -> dict[str, Any] | None:
    f = (EVAL_DIR / name).resolve()
    if f.parent != EVAL_DIR.resolve() or f.suffix != ".json" or not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


async def recent_traces(db: AsyncSession, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
    rows = await db.scalars(select(TraceRow).where(TraceRow.user_id == user_id)
                            .order_by(TraceRow.created_at.desc()).limit(limit))
    return [{
        "id": str(t.id), "kind": t.kind, "status": t.status, "input_mode": t.input_mode, "created_at": t.created_at,
        "conversation_id": str(t.conversation_id) if t.conversation_id else None, "model": t.model,
        "duration_ms": t.duration_ms, "first_token_ms": t.first_token_ms, "first_audio_ms": t.first_audio_ms,
        "stt_ms": t.stt_ms, "prompt_tokens": t.prompt_tokens, "completion_tokens": t.completion_tokens,
        "spans": t.spans or [], "attrs": t.attrs or {},
    } for t in rows]
