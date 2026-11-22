"""User preferences: explicit, validated, editable. Stored as JSON on user_settings.preferences."""

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserSettings

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class StylePrefs(_M):
    response_length: Literal["brief", "balanced", "detailed"] = "balanced"
    tone: Literal["casual", "neutral", "formal"] = "neutral"
    language: str = Field("auto", max_length=40, description="'auto' = reply in the language the user writes in")
    markdown: bool = True
    custom_instructions: str = Field("", max_length=1000)


class VoicePrefs(_M):
    voice: str | None = Field(None, max_length=40)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    speak_text_replies: bool = False


class WatchedFolder(_M):
    path: str = Field(min_length=3, max_length=500)
    project: str = Field(min_length=1, max_length=100)
    interval_min: int = Field(30, ge=5, le=1440)


class ProactivePrefs(_M):
    deadline_alerts: bool = True  # tasks with a due time: heads-up before, alert when overdue
    deadline_lead_min: int = Field(60, ge=5, le=1440)
    event_headsup: bool = True  # calendar events: heads-up with related notes/documents
    event_lead_min: int = Field(15, ge=5, le=240)
    daily_briefing: bool = False
    briefing_time: str = "08:00"
    briefing_location: str = Field("", max_length=100)  # for the weather line; blank = no weather
    conversation_digests: bool = True  # summarise finished conversations into episodic memory (uses the LLM)
    watched_folders: list[WatchedFolder] = Field(default_factory=list, max_length=10)

    @field_validator("briefing_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM.match(v):
            raise ValueError("time must be HH:MM (24h)")
        return v


class QuietHours(_M):
    enabled: bool = False
    start: str = "22:00"
    end: str = "07:00"

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM.match(v):
            raise ValueError("time must be HH:MM (24h)")
        return v


class Preferences(_M):
    style: StylePrefs = Field(default_factory=StylePrefs)
    voice: VoicePrefs = Field(default_factory=VoicePrefs)
    proactive: ProactivePrefs = Field(default_factory=ProactivePrefs)
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    background_processing: bool = True  # master switch: no proactive jobs at all when off


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


async def load(db: AsyncSession, user_id: uuid.UUID) -> Preferences:
    s = await db.get(UserSettings, user_id)
    return Preferences.model_validate((s.preferences if s else None) or {})


async def settings_row(db: AsyncSession, user_id: uuid.UUID) -> UserSettings:
    s = await db.get(UserSettings, user_id)
    if s is None:
        s = UserSettings(user_id=user_id, memory_enabled=True, timezone="UTC")
        db.add(s)
        await db.flush()
    return s


LENGTH = {
    "brief": "Keep answers short: one to three sentences unless asked for more. Skip preamble.",
    "balanced": "",
    "detailed": "Give thorough answers: explain reasoning, include examples, and structure longer answers.",
}
TONE = {
    "casual": "Use a relaxed, friendly, informal tone.",
    "neutral": "",
    "formal": "Use a professional, formal tone.",
}


def style_block(p: Preferences, name: str) -> str | None:
    """System-prompt section for the user's explicit style preferences (empty when all defaults)."""
    s = p.style
    lines = [x for x in (LENGTH[s.response_length], TONE[s.tone]) if x]
    if s.language.strip().lower() not in ("", "auto"):
        lines.append(f"Always reply in {s.language.strip()}, even if {name} writes in another language.")
    if not s.markdown:
        lines.append("Don't use Markdown formatting (no headings, bold, tables); plain sentences and simple lists only.")
    block = ""
    if lines:
        block += f"{name}'s preferences for your replies (set by {name} in Settings):\n" + "\n".join(f"- {x}" for x in lines)
    if s.custom_instructions.strip():
        text = s.custom_instructions.strip().replace("</", "‹/")
        block += (f"\n\n{name}'s own instructions for you (follow them unless they conflict with your rules above "
                  f"about honesty, safety and approvals):\n<user_instructions>\n{text}\n</user_instructions>")
    return block.strip() or None
