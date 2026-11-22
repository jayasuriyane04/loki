import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ----
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be blank")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime


# ---- conversations ----
class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    is_temporary: bool = False


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationSummary(ORM):
    id: uuid.UUID
    title: str
    is_temporary: bool
    created_at: datetime
    updated_at: datetime


class MessageOut(ORM):
    id: uuid.UUID
    role: str
    content: str
    status: str
    input_mode: str
    provider: str | None
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    first_token_ms: int | None
    citations: list[dict] | None = None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


# ---- memory ----
MemoryKind = Literal["profile", "episodic", "semantic"]


class MemoryOut(ORM):
    id: uuid.UUID
    kind: str
    content: str
    importance: float
    project: str | None
    source: str
    source_conversation_id: uuid.UUID | None
    event_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
    use_count: int
    similarity: float | None = None


class MemoryCreate(BaseModel):
    content: str = Field(min_length=3, max_length=400)
    kind: MemoryKind = "profile"
    importance: float = Field(default=0.8, ge=0, le=1)
    project: str | None = Field(default=None, max_length=100)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=3, max_length=400)
    kind: MemoryKind | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    project: str | None = Field(default=None, max_length=100)


class SettingsOut(BaseModel):
    memory_enabled: bool


class SettingsUpdate(BaseModel):
    memory_enabled: bool | None = None


# ---- knowledge base ----
class DocumentOut(ORM):
    id: uuid.UUID
    project: str
    title: str
    source: str
    file_type: str
    language: str | None
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int
    page_count: int | None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


class ChunkOut(ORM):
    id: uuid.UUID
    ordinal: int
    content: str
    heading_path: str | None
    page: int | None
    line_start: int | None
    line_end: int | None


class DocumentDetail(DocumentOut):
    chunks: list[ChunkOut]


class UploadResult(BaseModel):
    source: str
    status: Literal["queued", "unchanged", "rejected"]
    document_id: uuid.UUID | None = None
    reason: str | None = None


class SearchHitOut(BaseModel):
    document_id: uuid.UUID
    title: str
    source: str
    project: str
    heading_path: str | None
    page: int | None
    line_start: int | None
    line_end: int | None
    content: str
    score: float
    rerank: float | None
    vector_rank: int | None
    keyword_rank: int | None


# ---- system ----
class ProviderStatus(BaseModel):
    provider: str
    model: str
    ok: bool
    latency_ms: int | None
    error: str | None


class ModelsOut(BaseModel):
    primary: ProviderStatus
    fallback: ProviderStatus | None


# ---- websocket (client → server) ----
class WSUserMessage(BaseModel):
    type: Literal["user_message"]
    conversation_id: uuid.UUID | None = None
    content: str = Field(min_length=1)
    temporary: bool = False
    input_mode: Literal["text", "voice"] = "text"


class WSControl(BaseModel):
    type: Literal["cancel", "ping"]


class WSAudioUtterance(BaseModel):
    """Announces that the next binary frame is one spoken utterance (mono int16 PCM)."""

    type: Literal["audio_utterance"]
    conversation_id: uuid.UUID | None = None
    temporary: bool = False
    sample_rate: Literal[16000] = 16000


class WSVoiceConfig(BaseModel):
    type: Literal["voice_config"]
    speak_replies: bool = True  # speak replies to voice input
    speak_text_replies: bool = False  # also speak replies to typed messages
    voice: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
