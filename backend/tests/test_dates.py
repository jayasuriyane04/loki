from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.tools.base import ToolError
from app.tools.builtin._util import parse_local, parse_natural

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 22, 22, 40, tzinfo=TZ)  # Sunday evening


@pytest.mark.parametrize(
    "text,expected",
    [
        ("tomorrow at 10 AM", "2026-11-23 10:00"),
        ("tomorrow 10am", "2026-11-23 10:00"),
        ("Friday", "2026-11-27 09:00"),  # live bug: the model turned this into Thursday the 26th
        ("friday 6pm", "2026-11-27 18:00"),
        ("on Fri at 18:30", "2026-11-27 18:30"),
        ("Sunday", "2026-11-29 09:00"),  # a weekday name that is today means next week
        ("Monday 8am", "2026-11-23 08:00"),  # weekday index 0 must not be treated as "no weekday"
        ("this Sunday 11pm", "2026-11-22 23:00"),
        ("tonight", "2026-11-22 20:00"),
        ("tomorrow evening", "2026-11-23 18:00"),
        ("day after tomorrow noon", "2026-11-24 12:00"),
        ("in 2 hours", "2026-11-23 00:40"),
        ("in 30 minutes", "2026-11-22 23:10"),
        ("27 Nov 18:00", "2026-11-27 18:00"),
        ("Dec 3", "2026-12-03 09:00"),
        ("3 Jan", "2027-01-03 09:00"),  # already past this year → next year
        ("11pm", "2026-11-22 23:00"),
        ("9am", "2026-11-23 09:00"),  # already past today → tomorrow
    ],
)
def test_natural_dates(text, expected):
    dt, _ = parse_natural(text, NOW)
    assert dt.strftime("%Y-%m-%d %H:%M") == expected


def test_iso_is_local_time_and_returned_as_utc():
    assert parse_local("2026-11-23T10:00", TZ, field="x").isoformat() == "2026-11-23T04:30:00+00:00"
    assert parse_local("2026-11-23T10:00+00:00", TZ, field="x").isoformat() == "2026-11-23T10:00:00+00:00"


def test_gibberish_is_a_clear_tool_error():
    with pytest.raises(ToolError, match="Couldn't understand"):
        parse_local("whenever you like", TZ, field="due")
