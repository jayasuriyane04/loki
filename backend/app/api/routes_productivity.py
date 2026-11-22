"""REST API for the things LOKI manages for the user: tasks, reminders, notes, calendar, notifications, tools."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.db.models import Event, Note, Notification, Reminder, Task, ToolExecution, User, UserSettings
from app.db.session import get_db
from app.tools.registry import REGISTRY

router = APIRouter(prefix="/api", tags=["productivity"])


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Datetimes must include a timezone offset.")
    return dt.astimezone(UTC) if dt else None


async def _owned(db: AsyncSession, model, user: User, item_id: uuid.UUID):
    row = await db.scalar(select(model).where(model.id == item_id, model.user_id == user.id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return row


# ---------- tasks ----------
class TaskOut(Out):
    id: uuid.UUID
    title: str
    notes: str | None
    project: str | None
    priority: str
    status: str
    due_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str | None = Field(None, max_length=5000)
    project: str | None = Field(None, max_length=100)
    priority: Literal["low", "normal", "high"] = "normal"
    due_at: datetime | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    notes: str | None = Field(None, max_length=5000)
    project: str | None = Field(None, max_length=100)
    priority: Literal["low", "normal", "high"] | None = None
    due_at: datetime | None = None
    status: Literal["open", "done"] | None = None


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(status_: Literal["open", "done", "all"] = Query("open", alias="status"),
                     user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    q = select(Task).where(Task.user_id == user.id)
    if status_ != "all":
        q = q.where(Task.status == status_)
    return list(await db.scalars(q.order_by(Task.status, Task.due_at.is_(None), Task.due_at, Task.created_at.desc())))


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(body: TaskIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    t = Task(user_id=user.id, **body.model_dump(exclude={"due_at"}), due_at=_aware(body.due_at))
    db.add(t)
    await db.commit()
    return t


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(task_id: uuid.UUID, body: TaskPatch, user: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    t = await _owned(db, Task, user, task_id)
    data = body.model_dump(exclude_unset=True)
    if "due_at" in data:
        data["due_at"] = _aware(data["due_at"])
    if "status" in data:
        t.completed_at = datetime.now(UTC) if data["status"] == "done" else None
    for k, v in data.items():
        setattr(t, k, v)
    await db.commit()
    return t


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Task, user, task_id))
    await db.commit()


# ---------- reminders ----------
class ReminderOut(Out):
    id: uuid.UUID
    text: str
    remind_at: datetime
    status: str
    delivered_at: datetime | None
    created_by: str
    created_at: datetime


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    remind_at: datetime


@router.get("/reminders", response_model=list[ReminderOut])
async def list_reminders(include_past: bool = False, user: User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    q = select(Reminder).where(Reminder.user_id == user.id)
    if not include_past:
        q = q.where(Reminder.status == "scheduled")
    return list(await db.scalars(q.order_by(Reminder.remind_at.desc() if include_past else Reminder.remind_at).limit(200)))


@router.post("/reminders", response_model=ReminderOut, status_code=201)
async def create_reminder(body: ReminderIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    when = _aware(body.remind_at)
    if when <= datetime.now(UTC):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That time is in the past.")
    r = Reminder(user_id=user.id, text=body.text.strip(), remind_at=when)
    db.add(r)
    await db.commit()
    return r


@router.post("/reminders/{reminder_id}/cancel", response_model=ReminderOut)
async def cancel_reminder(reminder_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    r = await _owned(db, Reminder, user, reminder_id)
    if r.status == "scheduled":
        r.status = "cancelled"
        await db.commit()
    return r


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Reminder, user, reminder_id))
    await db.commit()


# ---------- notes ----------
class NoteOut(Out):
    id: uuid.UUID
    title: str
    body: str
    project: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50_000)
    project: str | None = Field(None, max_length=100)


@router.get("/notes", response_model=list[NoteOut])
async def list_notes(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return list(await db.scalars(select(Note).where(Note.user_id == user.id).order_by(Note.updated_at.desc()).limit(500)))


async def _embed_note(request: Request, title: str, body: str) -> list[float] | None:
    try:
        return (await request.app.state.embeddings.embed_documents([f"{title}\n\n{body[:4000]}"]))[0]
    except Exception:  # noqa: BLE001 - a note is still saved; it just won't be found by meaning until edited
        return None


@router.post("/notes", response_model=NoteOut, status_code=201)
async def create_note(body: NoteIn, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    n = Note(user_id=user.id, **body.model_dump(), embedding=await _embed_note(request, body.title, body.body))
    db.add(n)
    await db.commit()
    return n


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def patch_note(note_id: uuid.UUID, body: NoteIn, request: Request, user: User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    n = await _owned(db, Note, user, note_id)
    n.title, n.body, n.project = body.title, body.body, body.project
    n.embedding = await _embed_note(request, body.title, body.body)
    await db.commit()
    return n


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Note, user, note_id))
    await db.commit()


# ---------- calendar ----------
class EventOut(Out):
    id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime | None
    location: str | None
    notes: str | None
    created_by: str


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=2000)


@router.get("/events", response_model=list[EventOut])
async def list_events(start: datetime | None = None, end: datetime | None = None, user: User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    q = select(Event).where(Event.user_id == user.id)
    if start:
        q = q.where(Event.starts_at >= _aware(start))
    if end:
        q = q.where(Event.starts_at < _aware(end))
    return list(await db.scalars(q.order_by(Event.starts_at).limit(500)))


@router.post("/events", response_model=EventOut, status_code=201)
async def create_event(body: EventIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if body.ends_at and body.ends_at <= body.starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The event must end after it starts.")
    e = Event(user_id=user.id, **body.model_dump(exclude={"starts_at", "ends_at"}),
              starts_at=_aware(body.starts_at), ends_at=_aware(body.ends_at))
    db.add(e)
    await db.commit()
    return e


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(event_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Event, user, event_id))
    await db.commit()


# ---------- notifications ----------
class NotificationOut(Out):
    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    read_at: datetime | None
    created_at: datetime


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(unread: bool = False, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    return list(await db.scalars(q.order_by(Notification.created_at.desc()).limit(100)))


@router.post("/notifications/read", status_code=204)
async def mark_notifications_read(ids: list[uuid.UUID] | None = Body(None, embed=True), user: User = Depends(current_user),
                                  db: AsyncSession = Depends(get_db)):
    """Mark the given notifications (or all) as read."""
    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if ids:
        q = q.where(Notification.id.in_(ids))
    await db.execute(q.values(read_at=datetime.now(UTC)))
    await db.commit()


# ---------- tools ----------
class ToolInfo(BaseModel):
    name: str
    description: str
    category: str
    permission: str
    always_confirm: bool
    setting: Literal["auto", "confirm", "off"]  # effective
    parameters: dict


class ToolPrefIn(BaseModel):
    setting: Literal["auto", "confirm", "off"]


async def _prefs(db: AsyncSession, user: User) -> UserSettings:
    s = await db.get(UserSettings, user.id)
    if s is None:
        s = UserSettings(user_id=user.id, memory_enabled=True, timezone="UTC")
        db.add(s)
        await db.flush()
    return s


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    prefs = (await db.get(UserSettings, user.id))
    prefs_map = prefs.tool_prefs if prefs else None
    return [
        ToolInfo(name=t.name, description=t.description, category=t.category, permission=t.permission,
                 always_confirm=t.always_confirm, setting=t.effective(prefs_map),
                 parameters=t.schema()["function"]["parameters"])
        for t in sorted(REGISTRY.values(), key=lambda t: (t.category, t.name))
    ]


@router.patch("/tools/{name}", response_model=ToolInfo)
async def set_tool_pref(name: str, body: ToolPrefIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    t = REGISTRY.get(name)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown tool")
    if body.setting == "auto" and (t.always_confirm or t.permission == "confirm"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{name} always asks for approval (it deletes data, runs commands or acts on your computer).")
    s = await _prefs(db, user)
    prefs = dict(s.tool_prefs or {})
    if body.setting == "auto" or (body.setting == "confirm" and t.permission == "confirm"):
        prefs.pop(name, None)  # back to default
    else:
        prefs[name] = body.setting
    s.tool_prefs = prefs
    await db.commit()
    return ToolInfo(name=t.name, description=t.description, category=t.category, permission=t.permission,
                    always_confirm=t.always_confirm, setting=t.effective(prefs), parameters=t.schema()["function"]["parameters"])


class ExecutionOut(Out):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    tool: str
    arguments: dict
    permission: str
    status: str
    approved: bool | None
    summary: str | None
    error: str | None
    duration_ms: int
    created_at: datetime


@router.get("/tool-executions", response_model=list[ExecutionOut])
async def list_executions(limit: int = Query(100, ge=1, le=500), tool: str | None = None,
                          user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    q = select(ToolExecution).where(ToolExecution.user_id == user.id)
    if tool:
        q = q.where(ToolExecution.tool == tool)
    return list(await db.scalars(q.order_by(ToolExecution.created_at.desc()).limit(limit)))
