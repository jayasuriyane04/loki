"""Productivity tools: tasks, reminders, notes, calendar events, notifications."""

from datetime import UTC, datetime, timedelta
from typing import Literal

import numpy as np
from pydantic import Field
from sqlalchemy import select

from app.db.models import Event, Note, Reminder, Task
from app.tools.base import NoInput, ToolContext, ToolError, ToolInput, ToolResult
from app.tools.builtin._util import fmt_local, parse_local, resolve, short
from app.tools.registry import precheck, tool

WHEN = ("When, in the user's own words ('Friday 10am', 'tomorrow evening', 'in 2 hours', '27 Nov 18:00') "
        "or ISO local time like 2026-11-27T10:00. LOKI converts it exactly; prefer the user's words.")


# ---------- tasks ----------
class CreateTaskIn(ToolInput):
    title: str = Field(min_length=2, max_length=300)
    due: str | None = Field(None, description=WHEN)
    priority: Literal["low", "normal", "high"] = "normal"
    project: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=2000)


@tool("create_task", "Add a task to the user's task list.", CreateTaskIn, permission="reversible", category="productivity")
async def create_task(ctx: ToolContext, a: CreateTaskIn) -> ToolResult:
    due = parse_local(a.due, ctx.tz, field="due") if a.due else None
    async with ctx.sessions() as db:
        t = Task(user_id=ctx.user_id, title=a.title.strip(), due_at=due, priority=a.priority, project=a.project,
                 notes=a.notes, created_by="loki")
        db.add(t)
        await db.commit()
    when = f", due {fmt_local(due, ctx.tz)}" if due else ""
    return ToolResult(f"Task created (id {short(t.id)}): {t.title}{when}.", f"Added task “{t.title}”{when}",
                      {"id": str(t.id), "type": "task"})


class ListTasksIn(ToolInput):
    status: Literal["open", "done", "all"] = "open"
    project: str | None = None


@tool("list_tasks", "List the user's tasks (open by default) with their ids.", ListTasksIn, permission="read",
      category="productivity")
async def list_tasks(ctx: ToolContext, a: ListTasksIn) -> ToolResult:
    async with ctx.sessions() as db:
        q = select(Task).where(Task.user_id == ctx.user_id)
        if a.status != "all":
            q = q.where(Task.status == a.status)
        if a.project:
            q = q.where(Task.project == a.project)
        rows = list(await db.scalars(q.order_by(Task.due_at.is_(None), Task.due_at, Task.created_at).limit(50)))
    if not rows:
        return ToolResult("No matching tasks.", "Checked tasks: none")
    lines = [
        f"- {short(t.id)} [{t.status}] {t.title}" + (f" (due {fmt_local(t.due_at, ctx.tz)})" if t.due_at else "")
        + (f" [{t.priority}]" if t.priority != "normal" else "") + (f" #{t.project}" if t.project else "")
        for t in rows
    ]
    return ToolResult("\n".join(lines), f"Checked tasks: {len(rows)} {a.status}")


class TaskRefIn(ToolInput):
    task: str = Field(description="The task's title (e.g. 'buy groceries') or its id from list_tasks")


@tool("complete_task", "Mark a task as done.", TaskRefIn, permission="reversible", category="productivity")
async def complete_task(ctx: ToolContext, a: TaskRefIn) -> ToolResult:
    async with ctx.sessions() as db:
        t = await resolve(db, Task, ctx.user_id, a.task, label="task", title_col=Task.title)
        t.status, t.completed_at = "done", datetime.now(UTC)
        await db.commit()
    return ToolResult(f"Marked done: {t.title}", f"Completed task “{t.title}”", {"id": str(t.id), "type": "task"})


@tool("delete_task", "Permanently delete a task.", TaskRefIn, permission="confirm", category="productivity",
      always_confirm=True)
async def delete_task(ctx: ToolContext, a: TaskRefIn) -> ToolResult:
    async with ctx.sessions() as db:
        t = await resolve(db, Task, ctx.user_id, a.task, label="task", title_col=Task.title)
        title = t.title
        await db.delete(t)
        await db.commit()
    return ToolResult(f"Deleted task: {title}", f"Deleted task “{title}”")


# ---------- reminders ----------
class CreateReminderIn(ToolInput):
    text: str = Field(min_length=2, max_length=500, description="What to remind the user about")
    remind_at: str = Field(description=WHEN)


@tool("create_reminder", "Schedule a reminder; LOKI notifies the user at that time.", CreateReminderIn,
      permission="reversible", category="productivity")
async def create_reminder(ctx: ToolContext, a: CreateReminderIn) -> ToolResult:
    when = parse_local(a.remind_at, ctx.tz, field="remind_at")
    if when <= datetime.now(UTC) - timedelta(minutes=1):
        raise ToolError(f"{fmt_local(when, ctx.tz)} is in the past (now it is {fmt_local(datetime.now(UTC), ctx.tz)}).")
    async with ctx.sessions() as db:
        r = Reminder(user_id=ctx.user_id, text=a.text.strip(), remind_at=when, created_by="loki")
        db.add(r)
        await db.commit()
    local = fmt_local(when, ctx.tz)
    return ToolResult(f"Reminder set (id {short(r.id)}) for {local} ({ctx.timezone}): {r.text}",
                      f"Reminder for {local}: “{r.text}”", {"id": str(r.id), "type": "reminder", "at": when.isoformat()})


@tool("list_reminders", "List upcoming reminders with their ids.", NoInput, permission="read", category="productivity")
async def list_reminders(ctx: ToolContext, a: NoInput) -> ToolResult:
    async with ctx.sessions() as db:
        rows = list(await db.scalars(select(Reminder).where(Reminder.user_id == ctx.user_id, Reminder.status == "scheduled")
                                     .order_by(Reminder.remind_at).limit(50)))
    if not rows:
        return ToolResult("No upcoming reminders.", "Checked reminders: none")
    return ToolResult("\n".join(f"- {short(r.id)} {fmt_local(r.remind_at, ctx.tz)}: {r.text}" for r in rows),
                      f"Checked reminders: {len(rows)} upcoming")


class ReminderRefIn(ToolInput):
    reminder: str = Field(description="The reminder's text or its id from list_reminders")


@tool("cancel_reminder", "Cancel a scheduled reminder.", ReminderRefIn, permission="reversible", category="productivity")
async def cancel_reminder(ctx: ToolContext, a: ReminderRefIn) -> ToolResult:
    async with ctx.sessions() as db:
        r = await resolve(db, Reminder, ctx.user_id, a.reminder, label="reminder", title_col=Reminder.text,
                          where=Reminder.status == "scheduled")
        r.status = "cancelled"
        await db.commit()
    return ToolResult(f"Cancelled reminder: {r.text}", f"Cancelled reminder “{r.text}”")


# ---------- notes ----------
class CreateNoteIn(ToolInput):
    title: str = Field(min_length=2, max_length=300)
    body: str = Field(min_length=2, max_length=50_000, description="Markdown")
    project: str | None = Field(None, max_length=100)


@tool("create_note", "Save a note (Markdown), e.g. a summary or report, to the user's notes.", CreateNoteIn,
      permission="reversible", category="productivity")
async def create_note(ctx: ToolContext, a: CreateNoteIn) -> ToolResult:
    emb = ctx.services.get("embeddings")
    vec = (await emb.embed_documents([f"{a.title}\n\n{a.body[:4000]}"]))[0] if emb else None
    async with ctx.sessions() as db:
        n = Note(user_id=ctx.user_id, title=a.title.strip(), body=a.body, project=a.project, created_by="loki", embedding=vec)
        db.add(n)
        await db.commit()
    return ToolResult(f"Note saved (id {short(n.id)}): {n.title}", f"Saved note “{n.title}”",
                      {"id": str(n.id), "type": "note"})


class SearchNotesIn(ToolInput):
    query: str = Field(min_length=2, max_length=300)


@tool("search_notes", "Search the user's notes by meaning; returns titles, ids and excerpts.", SearchNotesIn,
      permission="read", category="productivity")
async def search_notes(ctx: ToolContext, a: SearchNotesIn) -> ToolResult:
    emb = ctx.services["embeddings"]
    q = np.asarray((await emb.embed_documents([a.query]))[0], dtype=np.float32)
    async with ctx.sessions() as db:
        notes = list(await db.scalars(select(Note).where(Note.user_id == ctx.user_id, Note.embedding.is_not(None))))
    scored = sorted(((float(np.dot(q, np.asarray(n.embedding, dtype=np.float32))), n) for n in notes),
                    key=lambda t: -t[0])[:5]
    scored = [(s, n) for s, n in scored if s >= 0.3]
    if not scored:
        return ToolResult("No matching notes.", f"Searched notes for “{a.query}”: none")
    return ToolResult("\n".join(f"- {short(n.id)} {n.title}: {n.body[:300]}" for _, n in scored),
                      f"Searched notes for “{a.query}” ({len(scored)} found)")


class NoteRefIn(ToolInput):
    note: str = Field(description="The note's title or its id")


@tool("read_note", "Read a note in full.", NoteRefIn, permission="read", category="productivity")
async def read_note(ctx: ToolContext, a: NoteRefIn) -> ToolResult:
    async with ctx.sessions() as db:
        n = await resolve(db, Note, ctx.user_id, a.note, label="note", title_col=Note.title)
    return ToolResult(f"# {n.title}\n\n{n.body[:12000]}", f"Read note “{n.title}”")


@tool("delete_note", "Permanently delete a note.", NoteRefIn, permission="confirm", category="productivity",
      always_confirm=True)
async def delete_note(ctx: ToolContext, a: NoteRefIn) -> ToolResult:
    async with ctx.sessions() as db:
        n = await resolve(db, Note, ctx.user_id, a.note, label="note", title_col=Note.title)
        title = n.title
        await db.delete(n)
        await db.commit()
    return ToolResult(f"Deleted note: {title}", f"Deleted note “{title}”")


# ---------- calendar ----------
class CreateEventIn(ToolInput):
    title: str = Field(min_length=2, max_length=300)
    starts_at: str = Field(description=WHEN)
    ends_at: str | None = Field(None, description=WHEN)
    location: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=2000)


@tool("create_event", "Add an event to LOKI's calendar.", CreateEventIn, permission="reversible", category="productivity")
async def create_event(ctx: ToolContext, a: CreateEventIn) -> ToolResult:
    start = parse_local(a.starts_at, ctx.tz, field="starts_at")
    end = parse_local(a.ends_at, ctx.tz, field="ends_at") if a.ends_at else None
    if end and end <= start:
        raise ToolError("ends_at must be after starts_at.")
    async with ctx.sessions() as db:
        e = Event(user_id=ctx.user_id, title=a.title.strip(), starts_at=start, ends_at=end, location=a.location,
                  notes=a.notes, created_by="loki")
        db.add(e)
        await db.commit()
    return ToolResult(f"Event created (id {short(e.id)}): {e.title} at {fmt_local(start, ctx.tz)}",
                      f"Added “{e.title}” on {fmt_local(start, ctx.tz)}", {"id": str(e.id), "type": "event"})


class ListEventsIn(ToolInput):
    start: str | None = Field(None, description=WHEN + ". Default: now")
    days: int = Field(7, ge=1, le=90)


@tool("list_events", "List calendar events in a time window (default: the next 7 days).", ListEventsIn,
      permission="read", category="productivity")
async def list_events(ctx: ToolContext, a: ListEventsIn) -> ToolResult:
    start = parse_local(a.start, ctx.tz, field="start") if a.start else datetime.now(UTC)
    end = start + timedelta(days=a.days)
    async with ctx.sessions() as db:
        rows = list(await db.scalars(select(Event).where(Event.user_id == ctx.user_id, Event.starts_at >= start,
                                                         Event.starts_at < end).order_by(Event.starts_at)))
    if not rows:
        return ToolResult(f"No events between {fmt_local(start, ctx.tz)} and {fmt_local(end, ctx.tz)}.", "Checked calendar: no events")
    return ToolResult("\n".join(f"- {short(e.id)} {fmt_local(e.starts_at, ctx.tz)}: {e.title}"
                                + (f" @ {e.location}" if e.location else "") for e in rows),
                      f"Checked calendar: {len(rows)} events")


class EventRefIn(ToolInput):
    event: str = Field(description="The event's title or its id")


@tool("delete_event", "Permanently delete a calendar event.", EventRefIn, permission="confirm",
      category="productivity", always_confirm=True)
async def delete_event(ctx: ToolContext, a: EventRefIn) -> ToolResult:
    async with ctx.sessions() as db:
        e = await resolve(db, Event, ctx.user_id, a.event, label="event", title_col=Event.title)
        title = e.title
        await db.delete(e)
        await db.commit()
    return ToolResult(f"Deleted event: {title}", f"Deleted event “{title}”")


# ---------- pre-approval checks: the user approves a named target, never a made-up id ----------
@precheck("delete_task")
async def _pre_delete_task(ctx: ToolContext, a: TaskRefIn) -> str:
    async with ctx.sessions() as db:
        t = await resolve(db, Task, ctx.user_id, a.task, label="task", title_col=Task.title)
    return f"Permanently delete task “{t.title}”" + (f" (due {fmt_local(t.due_at, ctx.tz)})" if t.due_at else "")


@precheck("delete_note")
async def _pre_delete_note(ctx: ToolContext, a: NoteRefIn) -> str:
    async with ctx.sessions() as db:
        n = await resolve(db, Note, ctx.user_id, a.note, label="note", title_col=Note.title)
    return f"Permanently delete note “{n.title}”"


@precheck("delete_event")
async def _pre_delete_event(ctx: ToolContext, a: EventRefIn) -> str:
    async with ctx.sessions() as db:
        e = await resolve(db, Event, ctx.user_id, a.event, label="event", title_col=Event.title)
    return f"Permanently delete event “{e.title}” on {fmt_local(e.starts_at, ctx.tz)}"


# ---------- notifications ----------
class NotifyIn(ToolInput):
    title: str = Field(min_length=2, max_length=200)
    body: str | None = Field(None, max_length=2000)


@tool("notify_user", "Send the user a notification (e.g. when a long multi-step job is finished).", NotifyIn,
      permission="reversible", category="productivity")
async def notify_user(ctx: ToolContext, a: NotifyIn) -> ToolResult:
    await ctx.services["notifier"].notify(ctx.user_id, "agent", a.title, a.body)
    return ToolResult("Notification sent.", f"Notified you: “{a.title}”")
