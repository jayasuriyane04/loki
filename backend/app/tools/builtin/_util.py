import re
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.base import ToolError

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
PARTS_OF_DAY = {"morning": time(9), "noon": time(12), "midday": time(12), "afternoon": time(14),
                "evening": time(18), "tonight": time(20), "night": time(20), "midnight": time(0)}


def _time_of(text: str) -> time | None:
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b", text) or re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        ampm = (m.group(3) or "").replace(".", "") if m.lastindex and m.lastindex >= 3 else ""
        if ampm == "pm" and h < 12:
            h += 12
        if ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return time(h, mi)
    for word, t in PARTS_OF_DAY.items():
        if re.search(rf"\b{word}\b", text):
            return t
    return None


def parse_natural(value: str, now: datetime) -> tuple[datetime, bool] | None:
    """'tomorrow 10am', 'Friday', 'next friday 6pm', 'in 2 hours', '27 Nov 18:30' → (local datetime, has_time).

    Small models get weekday arithmetic wrong; letting them pass the user's own words and resolving them here is exact.
    """
    s = " ".join(value.lower().replace(",", " ").split())
    if m := re.search(r"\bin\s+(\d+|an?|one|two|three)\s+(minute|min|hour|day|week)s?\b", s):
        n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}.get(m.group(1)) or int(m.group(1))
        unit = {"minute": "minutes", "min": "minutes", "hour": "hours", "day": "days", "week": "weeks"}[m.group(2)]
        return now + timedelta(**{unit: n}), unit in ("minutes", "hours")
    t = _time_of(s)
    day = None
    if re.search(r"\bday after tomorrow\b", s):
        day = now.date() + timedelta(days=2)
    elif re.search(r"\btomorrow\b", s):
        day = now.date() + timedelta(days=1)
    elif re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", s):
        day = now.date()
    elif re.search(r"\bnext week\b", s):
        day = now.date() + timedelta(days=7)
    elif (wd := next((i for i, w in enumerate(WEEKDAYS) if re.search(rf"\b{w[:3]}(?:{w[3:]})?\b", s)), None)) is not None:
        ahead = (wd - now.weekday()) % 7
        if ahead == 0 and not re.search(r"\b(today|this)\b", s):
            ahead = 7
        if re.search(rf"\bnext\s+{WEEKDAYS[wd][:3]}", s) and ahead < 7:
            ahead += 7 if ahead == 0 else 0
        day = now.date() + timedelta(days=ahead)
    elif m := (re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")[a-z]*\b", s)
               or re.search(r"\b(" + "|".join(MONTHS) + r")[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b", s)):
        a, b = m.group(1), m.group(2)
        d, mon = (int(a), b) if a.isdigit() else (int(b), a)
        month = MONTHS.index(mon[:3]) + 1
        year = now.year + (1 if (month, d) < (now.month, now.day) else 0)
        try:
            day = datetime(year, month, d).date()
        except ValueError:
            return None
    elif t is not None:  # just a time: today if still ahead, else tomorrow
        candidate = datetime.combine(now.date(), t, now.tzinfo)
        return (candidate if candidate > now else candidate + timedelta(days=1)), True
    if day is None:
        return None
    return datetime.combine(day, t or time(9), now.tzinfo), t is not None


def parse_local(value: str, tz: ZoneInfo, *, field: str) -> datetime:
    """A date/time from the model → aware UTC. Accepts ISO 8601 (local time if no offset) or the user's own words
    ('tomorrow 10am', 'Friday', 'in 2 hours'). Dates without a time mean 09:00 local."""
    v = value.strip()
    iso = v.replace(" ", "T", 1) if re.match(r"^\d{4}-\d{2}-\d{2} \d", v) else v
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(UTC)
    except ValueError:
        pass
    parsed = parse_natural(v, datetime.now(tz))
    if parsed is None:
        raise ToolError(f"Couldn't understand {field}={value!r}. Use the user's words like 'Friday 10am' or ISO 2026-11-27T10:00.")
    return parsed[0].astimezone(UTC)


def fmt_local(dt: datetime | None, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%a %d %b %Y %H:%M") if dt else "-"


def short(id_: uuid.UUID) -> str:
    return str(id_)[:8]


async def resolve(db: AsyncSession, model, user_id: uuid.UUID, ref: str, *, label: str, title_col=None, where=None):
    """Find a user's row by full UUID, by the 8-character short id shown in listings, or by its title.

    Accepting the title matters: small models invent ids ("task-7c2a…") when they only know the name, and then
    loop trying to fix it. With titles they can just say "buy groceries".
    """
    raw = ref.strip().strip("“”\"'")
    key = raw.lower()
    base = select(model).where(model.user_id == user_id)
    if where is not None:
        base = base.where(where)
    try:
        row = await db.get(model, uuid.UUID(key))
        if row is not None and row.user_id == user_id:
            return row
    except ValueError:
        pass
    if len(key) >= 4 and re.fullmatch(r"[0-9a-f-]+", key):
        rows = list(await db.scalars(base.where(cast(model.id, String).like(f"{key}%")).limit(2)))
        if len(rows) == 1:
            return rows[0]
    if title_col is not None and len(key) >= 2:
        exact = list(await db.scalars(base.where(func.lower(title_col) == key).limit(2)))
        rows = exact or list(await db.scalars(base.where(func.lower(title_col).contains(key)).limit(3)))
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            names = ", ".join(f"{short(r.id)} “{getattr(r, title_col.key)}”" for r in rows)
            raise ToolError(f"Several {label}s match {raw!r}: {names}. Use the id.")
    raise ToolError(f"No {label} matches {raw!r}. List them to see what exists.")
