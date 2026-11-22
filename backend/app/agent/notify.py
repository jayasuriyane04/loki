"""Notifications (stored + pushed live to every open LOKI tab of the user) and the reminder scheduler."""

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.models import Notification, Reminder
from app.db.session import SessionLocal

log = logging.getLogger(__name__)
Send = Callable[[dict[str, Any]], Awaitable[None]]


class Notifier:
    def __init__(self) -> None:
        self._conns: dict[uuid.UUID, set[Send]] = defaultdict(set)

    def connect(self, user_id: uuid.UUID, send: Send) -> None:
        self._conns[user_id].add(send)

    def disconnect(self, user_id: uuid.UUID, send: Send) -> None:
        self._conns[user_id].discard(send)

    async def notify(self, user_id: uuid.UUID, kind: str, title: str, body: str | None = None) -> Notification:
        async with SessionLocal() as db:
            n = Notification(user_id=user_id, kind=kind, title=title[:300], body=body)
            db.add(n)
            await db.commit()
        event = {"type": "notification", "notification": {
            "id": str(n.id), "kind": kind, "title": n.title, "body": body, "created_at": n.created_at.isoformat()}}
        for send in list(self._conns.get(user_id, ())):
            try:
                await send(event)
            except Exception:  # noqa: BLE001 - a dead socket must not block the others
                self._conns[user_id].discard(send)
        return n


class ReminderScheduler:
    """Polls for due reminders. Delivery is stored, so reminders that fall due while LOKI is closed are shown
    as soon as the user opens it (and are delivered when the backend starts again)."""

    def __init__(self, notifier: Notifier, poll_s: float) -> None:
        self.notifier = notifier
        self.poll_s = poll_s
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def tick(self) -> int:
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
            await self.notifier.notify(r.user_id, "reminder", f"Reminder: {r.text}", body)
        if due:
            log.info("reminders delivered", extra={"count": len(due)})
        return len(due)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reminder scheduler tick failed")
            await asyncio.sleep(self.poll_s)
