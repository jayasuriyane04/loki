"""Notifications (stored + pushed live) with quiet hours, and the proactive scheduler.

Everything proactive is an explicit, user-controlled job on a timer — never continuous LLM inference. Only the
conversation digest uses the model; the other jobs are plain database queries (plus one weather lookup).
"""

import asyncio
import logging
import time as clock
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select

from app.db.models import Event, Notification, Reminder, Task, UserSettings
from app.db.session import SessionLocal
from app.personal.preferences import Preferences

log = logging.getLogger(__name__)
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def in_quiet_hours(prefs: Preferences, local: datetime) -> bool:
    q = prefs.quiet_hours
    if not q.enabled:
        return False
    start, end, now = time.fromisoformat(q.start), time.fromisoformat(q.end), local.time()
    return start <= now < end if start < end else (now >= start or now < end)  # may wrap past midnight


async def user_context(db, user_id: uuid.UUID) -> tuple[Preferences, ZoneInfo]:
    s = await db.get(UserSettings, user_id)
    return Preferences.model_validate((s.preferences if s else None) or {}), _tz(s.timezone if s else None)


class Notifier:
    def __init__(self) -> None:
        self._conns: dict[uuid.UUID, set[Send]] = defaultdict(set)

    def connect(self, user_id: uuid.UUID, send: Send) -> None:
        self._conns[user_id].add(send)

    def disconnect(self, user_id: uuid.UUID, send: Send) -> None:
        self._conns[user_id].discard(send)

    async def _push(self, n: Notification) -> None:
        event = {"type": "notification", "notification": {
            "id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "data": n.data,
            "created_at": n.created_at.isoformat()}}
        for send in list(self._conns.get(n.user_id, ())):
            try:
                await send(event)
            except Exception:  # noqa: BLE001 - a dead socket must not block the others
                self._conns[n.user_id].discard(send)

    async def notify(self, user_id: uuid.UUID, kind: str, title: str, body: str | None = None, *,
                     data: dict | None = None, respect_quiet: bool = False) -> Notification:
        """Store a notification and push it — unless it's proactive and the user is in quiet hours, in which case
        it's held and delivered when quiet hours end. Things the user explicitly asked for (reminders) always go."""
        async with SessionLocal() as db:
            held = False
            if respect_quiet:
                prefs, tz = await user_context(db, user_id)
                held = in_quiet_hours(prefs, datetime.now(tz))
            n = Notification(user_id=user_id, kind=kind, title=title[:300], body=body, data=data, delivered=not held)
            db.add(n)
            await db.commit()
        if not held:
            await self._push(n)
        return n

    async def release_held(self) -> int:
        """Deliver notifications held during quiet hours once those hours are over."""
        released = 0
        async with SessionLocal() as db:
            held = list(await db.scalars(select(Notification).where(Notification.delivered.is_(False))
                                         .order_by(Notification.created_at).limit(200)))
            for n in held:
                prefs, tz = await user_context(db, n.user_id)
                if not in_quiet_hours(prefs, datetime.now(tz)):
                    n.delivered = True
                    released += 1
            await db.commit()
        for n in held:
            if n.delivered:
                await self._push(n)
        return released


class ProactiveScheduler:
    """Runs each job on its own interval. Jobs are cheap DB queries except the (opt-out) conversation digest."""

    def __init__(self, notifier: Notifier, *, reminder_poll_s: float, services: dict[str, Any]) -> None:
        self.notifier = notifier
        self.services = services  # llm, embeddings, knowledge, ingestor, folder_watcher
        self.jobs: list[tuple[str, float, Callable[[], Awaitable[Any]]]] = [
            ("reminders", reminder_poll_s, self.reminders),
            ("deadlines", 60, self.deadlines),
            ("events", 60, self.event_headsups),
            ("briefing", 60, self.daily_briefings),
            ("quiet_release", 60, self.notifier.release_held),
            ("digests", 300, self.digests),
            ("folders", 60, self.folders),
        ]
        self._last: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            now = clock.monotonic()
            for name, every, job in self.jobs:
                if now - self._last.get(name, -1e9) >= every:
                    self._last[name] = now
                    try:
                        await job()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception("proactive job failed", extra={"job": name})
            await asyncio.sleep(5)

    # ---------- jobs ----------
    async def reminders(self) -> int:
        now = datetime.now(UTC)
        async with SessionLocal() as db:
            due = list(await db.scalars(select(Reminder).where(Reminder.status == "scheduled", Reminder.remind_at <= now)
                                        .order_by(Reminder.remind_at).limit(100)))
            for r in due:
                r.status, r.delivered_at = "delivered", now
            await db.commit()
        for r in due:
            late = (now - r.remind_at).total_seconds()
            body = None if late < 120 else f"(Due {int(late // 60)} min ago, while LOKI was not running.)"
            await self.notifier.notify(r.user_id, "reminder", f"Reminder: {r.text}", body)  # always delivered
        if due:
            log.info("reminders delivered", extra={"count": len(due)})
        return len(due)

    # Kept for tests / older callers.
    tick = reminders

    async def deadlines(self) -> int:
        now = datetime.now(UTC)
        sent = 0
        async with SessionLocal() as db:
            tasks = list(await db.scalars(select(Task).where(
                Task.status == "open", Task.due_at.is_not(None), Task.alerted_at.is_(None),
                Task.due_at <= now + timedelta(days=1)).limit(200)))
            for t in tasks:
                prefs, tz = await user_context(db, t.user_id)
                p = prefs.proactive
                if not (prefs.background_processing and p.deadline_alerts):
                    continue
                if t.due_at - timedelta(minutes=p.deadline_lead_min) > now:
                    continue
                local = t.due_at.astimezone(tz)
                if t.due_at <= now:
                    title, body = f"Overdue: {t.title}", f"Was due {local:%a %d %b %H:%M}."
                else:
                    title, body = f"Due soon: {t.title}", f"Due at {local:%H:%M} ({local:%a %d %b})."
                t.alerted_at = now
                await db.commit()
                await self.notifier.notify(t.user_id, "deadline", title, body, data={"task_id": str(t.id), "project": t.project},
                                           respect_quiet=True)
                sent += 1
        return sent

    async def event_headsups(self) -> int:
        now = datetime.now(UTC)
        sent = 0
        async with SessionLocal() as db:
            events = list(await db.scalars(select(Event).where(
                Event.alerted_at.is_(None), Event.starts_at > now, Event.starts_at <= now + timedelta(hours=4)).limit(100)))
            for e in events:
                prefs, tz = await user_context(db, e.user_id)
                p = prefs.proactive
                if not (prefs.background_processing and p.event_headsup):
                    continue
                if e.starts_at - timedelta(minutes=p.event_lead_min) > now:
                    continue
                related = await self._related(db, e)
                local = e.starts_at.astimezone(tz)
                body = f"At {local:%H:%M}" + (f" · {e.location}" if e.location else "")
                if related:
                    body += "\nRelated: " + "; ".join(related)
                e.alerted_at = now
                await db.commit()
                await self.notifier.notify(e.user_id, "event", f"Coming up: {e.title}", body,
                                           data={"event_id": str(e.id)}, respect_quiet=True)
                sent += 1
        return sent

    async def _related(self, db, e: Event) -> list[str]:
        """Surface the user's own material about the event (search, no LLM)."""
        knowledge = self.services.get("knowledge")
        if knowledge is None:
            return []
        try:
            hits = await knowledge.search(db, e.user_id, f"{e.title} {e.notes or ''}".strip(), top_k=3)
        except Exception:  # noqa: BLE001 - a heads-up without related items is still useful
            return []
        out = []
        for h in hits:
            title, heading = h.chunk.document.title, h.chunk.heading_path
            label = title + (f" › {heading}" if heading and heading != title else "")
            if label not in out:
                out.append(label)
        return out[:3]

    async def daily_briefings(self) -> int:
        sent = 0
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(UserSettings)))
        for s in rows:
            prefs = Preferences.model_validate(s.preferences or {})
            p = prefs.proactive
            if not (prefs.background_processing and p.daily_briefing):
                continue
            tz = _tz(s.timezone)
            local = datetime.now(tz)
            if local.time() < time.fromisoformat(p.briefing_time):
                continue
            start_local = datetime.combine(local.date(), time(0), tz)
            async with SessionLocal() as db:
                already = await db.scalar(select(exists().where(
                    Notification.user_id == s.user_id, Notification.kind == "briefing",
                    Notification.created_at >= start_local.astimezone(UTC))))
                if already:
                    continue
                body = await self.compose_briefing(db, s.user_id, tz, p.briefing_location)
            await self.notifier.notify(s.user_id, "briefing", f"Your day — {local:%A %d %B}", body, respect_quiet=True)
            sent += 1
        return sent

    async def compose_briefing(self, db, user_id: uuid.UUID, tz: ZoneInfo, location: str) -> str:
        """Plain template from the user's own data (no LLM)."""
        local = datetime.now(tz)
        start = datetime.combine(local.date(), time(0), tz).astimezone(UTC)
        end = start + timedelta(days=1)
        events = list(await db.scalars(select(Event).where(Event.user_id == user_id, Event.starts_at >= start,
                                                           Event.starts_at < end).order_by(Event.starts_at)))
        due = list(await db.scalars(select(Task).where(Task.user_id == user_id, Task.status == "open",
                                                       Task.due_at.is_not(None), Task.due_at < end).order_by(Task.due_at)))
        reminders = list(await db.scalars(select(Reminder).where(Reminder.user_id == user_id, Reminder.status == "scheduled",
                                                                 Reminder.remind_at < end).order_by(Reminder.remind_at)))
        lines = []
        if location:
            weather = await self._weather(location)
            if weather:
                lines.append(weather)
        lines.append("Calendar: " + ("; ".join(f"{e.starts_at.astimezone(tz):%H:%M} {e.title}" for e in events)
                                     if events else "nothing scheduled"))
        overdue = [t for t in due if t.due_at < start]
        today = [t for t in due if t.due_at >= start]
        if overdue:
            lines.append("Overdue: " + "; ".join(t.title for t in overdue))
        lines.append("Due today: " + ("; ".join(t.title for t in today) if today else "nothing"))
        if reminders:
            lines.append("Reminders: " + "; ".join(f"{r.remind_at.astimezone(tz):%H:%M} {r.text}" for r in reminders))
        return "\n".join(lines)

    async def _weather(self, location: str) -> str | None:
        from app.tools.builtin.info import WeatherIn, get_weather

        try:
            res = await asyncio.wait_for(get_weather(None, WeatherIn(location=location)), 15)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - the briefing still goes out without weather
            return None
        return res.summary

    async def digests(self) -> int:
        from app.personal.digest import digest_pending

        llm, emb = self.services.get("llm"), self.services.get("embeddings")
        return await digest_pending(llm, emb) if llm and emb else 0

    async def folders(self) -> int:
        watcher = self.services.get("folder_watcher")
        return await watcher.scan_due() if watcher else 0
