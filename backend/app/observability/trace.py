"""Traces and events.

A `Trace` follows one unit of work (a chat or voice turn, a memory extraction). Code deep in the stack adds spans
with `async with span("retrieval"): ...` without any plumbing: the active trace lives in a context variable, and
when there is none (tests, scripts) spans cost nothing.

Writes never block the request path: traces and events go into an in-memory buffer that a background task flushes
to the database every few seconds.
"""

import asyncio
import contextvars
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any

log = logging.getLogger(__name__)

_current: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("loki_trace", default=None)


def _ms(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)


@dataclass
class Trace:
    kind: str  # chat_turn | voice_turn | memory_extract
    user_id: uuid.UUID | None = None
    input_mode: str = "text"
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    started: float = field(default_factory=time.perf_counter)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    spans: list[dict[str, Any]] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | error | interrupted | empty
    # Well-known measurements (columns, so the dashboard can aggregate them cheaply).
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    provider: str | None = None
    model: str | None = None
    first_token_ms: int | None = None
    first_audio_ms: int | None = None
    stt_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    duration_ms: int | None = None
    _token: contextvars.Token | None = None

    # --- lifecycle ---
    def __enter__(self) -> "Trace":
        self._token = _current.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is asyncio.CancelledError and self.status == "ok":
            self.status = "interrupted"
        elif exc is not None and self.status == "ok":
            self.status = "error"
            self.attrs.setdefault("error", type(exc).__name__)
        if self._token is not None:
            _current.reset(self._token)
            self._token = None
        self.finish()

    def finish(self) -> None:
        if self.duration_ms is None:
            self.duration_ms = _ms(self.started)
            sink.add_trace(self)

    # --- recording ---
    def add_span(self, name: str, start: float, duration_ms: int, **attrs: Any) -> None:
        s = {"name": name, "start_ms": int((start - self.started) * 1000), "duration_ms": duration_ms}
        if attrs:
            s["attrs"] = attrs
        self.spans.append(s)

    def incr(self, key: str, by: int = 1) -> None:
        self.attrs[key] = self.attrs.get(key, 0) + by

    def append(self, key: str, item: Any) -> None:
        self.attrs.setdefault(key, []).append(item)


def current_trace() -> Trace | None:
    return _current.get()


@asynccontextmanager
async def span(name: str, **attrs: Any) -> AsyncIterator[dict[str, Any]]:
    """Time a block. Yields a dict the block can add attributes to (e.g. hit counts)."""
    t = _current.get()
    extra: dict[str, Any] = dict(attrs)
    start = time.perf_counter()
    try:
        yield extra
    except BaseException as e:
        extra["error"] = type(e).__name__
        raise
    finally:
        if t is not None:
            t.add_span(name, start, _ms(start), **extra)


def event(name: str, **attrs: Any) -> None:
    """A point-in-time marker on the current trace (e.g. a guard firing)."""
    t = _current.get()
    if t is not None:
        t.add_span(name, time.perf_counter(), 0, **attrs)
        t.incr(f"events.{name}")


def traced(kind: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator: run a coroutine inside its own trace (for background work such as memory extraction)."""

    def deco(fn):
        @wraps(fn)
        async def wrapper(*a, **kw):
            with Trace(kind):
                return await fn(*a, **kw)

        return wrapper

    return deco


def record_event(kind: str, name: str, *, duration_ms: int | None = None, ok: bool = True, value: float | None = None,
                 user_id: uuid.UUID | None = None, **attrs: Any) -> None:
    """A system-level metric event (HTTP request, error, gauge sample, job run)."""
    sink.add_event({"id": uuid.uuid4(), "kind": kind, "name": name[:200], "duration_ms": duration_ms, "ok": ok,
                    "value": value, "user_id": user_id, "attrs": attrs or None, "created_at": datetime.now(UTC)})


class _Sink:
    """Buffers traces and events in memory; `run()` flushes them to the database every few seconds."""

    MAX_BUFFER = 5000

    def __init__(self) -> None:
        self.traces: list[Trace] = []
        self.events: list[dict[str, Any]] = []
        self.enabled = True
        self.dropped = 0
        self.prices: dict[str, tuple[float, float]] = {}  # model -> USD per 1M (input, output) tokens
        self.ws_connections = 0
        self.ws_peak = 0

    def add_trace(self, t: Trace) -> None:
        if not self.enabled:
            return
        if len(self.traces) >= self.MAX_BUFFER:
            self.dropped += 1
            return
        self.traces.append(t)

    def add_event(self, e: dict[str, Any]) -> None:
        if not self.enabled:
            return
        if len(self.events) >= self.MAX_BUFFER:
            self.dropped += 1
            return
        self.events.append(e)

    def ws_opened(self) -> None:
        self.ws_connections += 1
        self.ws_peak = max(self.ws_peak, self.ws_connections)

    def ws_closed(self) -> None:
        self.ws_connections = max(0, self.ws_connections - 1)

    def cost(self, model: str | None, prompt: int | None, completion: int | None) -> float | None:
        p = self.prices.get(model or "")
        if p is None:
            return None
        return round(((prompt or 0) * p[0] + (completion or 0) * p[1]) / 1_000_000, 6)

    async def flush(self) -> int:
        from app.db.models import MetricEvent, TraceRow
        from app.db.session import SessionLocal

        traces, self.traces = self.traces, []
        events, self.events = self.events, []
        if not traces and not events:
            return 0
        try:
            async with SessionLocal() as db:
                for t in traces:
                    db.add(TraceRow(
                        id=t.id, user_id=t.user_id, kind=t.kind, status=t.status, input_mode=t.input_mode,
                        conversation_id=t.conversation_id, message_id=t.message_id, provider=t.provider, model=t.model,
                        duration_ms=t.duration_ms, first_token_ms=t.first_token_ms, first_audio_ms=t.first_audio_ms,
                        stt_ms=t.stt_ms, prompt_tokens=t.prompt_tokens, completion_tokens=t.completion_tokens,
                        cost_usd=self.cost(t.model, t.prompt_tokens, t.completion_tokens),
                        spans=t.spans or None, attrs=t.attrs or None, created_at=t.created_at,
                    ))
                for e in events:
                    db.add(MetricEvent(**e))
                await db.commit()
        except Exception:  # noqa: BLE001 - metrics must never take the app down
            log.warning("metrics flush failed", exc_info=True)
            return 0
        return len(traces) + len(events)

    async def prune(self, days: int) -> None:
        from sqlalchemy import delete

        from app.db.models import MetricEvent, TraceRow
        from app.db.session import SessionLocal

        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with SessionLocal() as db:
            await db.execute(delete(TraceRow).where(TraceRow.created_at < cutoff))
            await db.execute(delete(MetricEvent).where(MetricEvent.created_at < cutoff))
            await db.commit()

    async def run(self, *, interval_s: float = 5, retention_days: int = 30) -> None:
        last_sample = last_prune = 0.0
        try:
            while True:
                await asyncio.sleep(interval_s)
                now = time.monotonic()
                if now - last_sample >= 60:
                    last_sample = now
                    record_event("gauge", "ws_connections", value=self.ws_connections, peak=self.ws_peak)
                    self.ws_peak = self.ws_connections
                await self.flush()
                if now - last_prune >= 3600:
                    last_prune = now
                    try:
                        await self.prune(retention_days)
                    except Exception:  # noqa: BLE001
                        log.warning("metrics prune failed", exc_info=True)
        finally:
            await asyncio.shield(self.flush())


sink = _Sink()


class ErrorCapture(logging.Handler):
    """Counts ERROR-level log records as `error` events (logger + message, no stack traces)."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("app.observability"):
            return
        try:
            record_event("error", record.name, ok=False, message=record.getMessage()[:300],
                         exc=record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None)
        except Exception:  # noqa: BLE001
            pass
