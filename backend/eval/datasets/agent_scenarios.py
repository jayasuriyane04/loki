"""Agent evaluation scenarios.

Each scenario sends one message to the real agent and then checks the *resulting state* through the API (did the task
really get created, with the right date?), not just the wording of the reply.

- expect: tools that must be called successfully for the task to count as done properly.
- allowed: tools that are reasonable extras (e.g. listing before deleting). Anything else is an unnecessary call.
- approve: answer to approval requests (True / False); None = the scenario expects none.
- fail_once: a tool whose first call fails with a temporary error (tests recovery).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Kolkata")


@dataclass
class Scenario:
    id: str
    prompt: str
    expect: set[str]
    check: Callable[[Any, str], bool]  # (api client, reply text) -> passed
    allowed: set[str] = field(default_factory=set)
    setup: Callable[[Any], None] | None = None
    approve: bool | None = None
    fail_once: str | None = None
    category: str = "action"


def _local(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ) if iso else None


def _tasks(c) -> list[dict]:
    return c.get("/api/tasks?status=all").json()


def _task(c, word: str) -> dict | None:
    return next((t for t in _tasks(c) if word.lower() in t["title"].lower()), None)


def _next_weekday(wd: int) -> datetime:
    now = datetime.now(TZ)
    days = (wd - now.weekday()) % 7 or 7
    return now + timedelta(days=days)


def _check_passport(c, _):
    t = _task(c, "passport")
    due = _local(t and t["due_at"])
    tomorrow = (datetime.now(TZ) + timedelta(days=1)).date()
    return bool(t and due and due.date() == tomorrow and due.hour == 9 and due.minute == 0)


def _check_stretch(c, _):
    r = next((r for r in c.get("/api/reminders").json() if "stretch" in r["text"].lower()), None)
    at = _local(r and r["remind_at"])
    return bool(at and abs((at - datetime.now(TZ)) - timedelta(hours=2)) < timedelta(minutes=10))


def _check_note(c, _):
    n = next((n for n in c.get("/api/notes").json() if "gift" in n["title"].lower()), None)
    return bool(n and "chess" in n["body"].lower() and "headphones" in n["body"].lower())


def _seed_tasks(*titles):
    def run(c):
        for t in titles:
            c.post("/api/tasks", json={"title": t})
    return run


def _check_dentist(c, _):
    evs = c.get("/api/events?start=" + datetime.now(TZ).date().isoformat() + "T00:00:00Z").json()
    e = next((e for e in evs if "dentist" in e["title"].lower()), None)
    start = _local(e and e["starts_at"])
    friday = _next_weekday(4).date() if datetime.now(TZ).weekday() != 4 else datetime.now(TZ).date()
    return bool(start and start.date() == friday and start.hour == 15)


def _upload_handbook(c):
    from pathlib import Path

    p = Path(__file__).parent / "rag" / "corpus" / "handbook.md"
    c.post("/api/documents", files=[("files", ("handbook.md", p.read_bytes(), "text/markdown"))])


def _count_open(c, reply):
    n = sum(1 for t in _tasks(c) if t["status"] == "open")
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    return bool(_task(c, "milk") and _task(c, "sam") and re.search(rf"\b({n}|{words.get(n, n)})\b", reply.lower()))


SCENARIOS: list[Scenario] = [
    Scenario("task-with-date", "Add a task to renew my passport, due tomorrow at 9am.", {"create_task"}, _check_passport),
    Scenario("reminder-relative", "Remind me in 2 hours to stretch.", {"create_reminder"}, _check_stretch),
    Scenario("note", "Save a note titled 'Gift ideas' with: headphones, a book on chess.", {"create_note"}, _check_note),
    Scenario("list-tasks", "What's on my task list?", {"list_tasks"},
             lambda c, r: "water the plants" in r.lower() and "pay rent" in r.lower(),
             setup=_seed_tasks("Water the plants", "Pay rent"), category="read"),
    Scenario("complete-task", "I called the bank, mark that task as done.", {"complete_task"},
             lambda c, r: (_task(c, "bank") or {}).get("status") == "done",
             allowed={"list_tasks"}, setup=_seed_tasks("Call the bank")),
    Scenario("delete-approved", "Delete my task 'old draft'.", {"delete_task"},
             lambda c, r: _task(c, "old draft") is None,
             allowed={"list_tasks"}, setup=_seed_tasks("Old draft"), approve=True),
    Scenario("delete-denied", "Delete my task 'tax receipts'.", {"delete_task"},
             lambda c, r: _task(c, "tax receipts") is not None and not re.search(r"\b(i've|i have|has been) deleted\b", r.lower()),
             allowed={"list_tasks"}, setup=_seed_tasks("Tax receipts"), approve=False),
    Scenario("calendar", "Put a dentist appointment on my calendar for Friday at 3pm.", {"create_event"}, _check_dentist,
             allowed={"list_events"}),
    Scenario("no-tool-general", "What's the capital of France?", set(), lambda c, r: "paris" in r.lower(), category="no_tool"),
    Scenario("no-tool-date", "What's today's date?", set(),
             lambda c, r: str(datetime.now(TZ).day) in r, allowed={"get_datetime"}, category="no_tool"),
    Scenario("documents", "According to my documents, how long is the Meridian grace period?", set(),
             lambda c, r: bool(re.search(r"\b(5|five)\b", r.lower())), allowed={"search_documents"},
             setup=_upload_handbook, category="read"),
    Scenario("multi-step", "Add tasks to buy milk and to call Sam, then tell me how many open tasks I have.",
             {"create_task"}, _count_open, allowed={"list_tasks"}, setup=_seed_tasks("Book a haircut")),
    Scenario("recover-from-failure", "Add a task to book flights for the conference.", {"create_task"},
             lambda c, r: _task(c, "flight") is not None, fail_once="create_task", category="recovery"),
    Scenario("recover-reminder", "Remind me tomorrow at 8am to take the medicine.", {"create_reminder"},
             lambda c, r: any("medicine" in x["text"].lower() for x in c.get("/api/reminders").json()),
             fail_once="create_reminder", category="recovery"),
]
