import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import get_settings

# Fixed per database: changing the embedding model to one with another size needs a migration + re-embed.
EMBEDDING_DIM = get_settings().embedding_dim


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Always returns timezone-aware UTC datetimes (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):  # type: ignore[no-untyped-def]
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect):  # type: ignore[no-untyped-def]
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    user: Mapped[User] = relationship(lazy="joined")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    # Working-memory compression: older turns are folded into `summary`; messages created at or
    # before `summary_until` are no longer sent to the model verbatim.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    project: Mapped[str | None] = mapped_column(String(100), nullable=True)  # detected from what was discussed
    digested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # episodic digest written
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="complete")
    input_mode: Mapped[str] = mapped_column(String(8), default="text")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Document passages given to the model for this reply, with which ones it actually cited (Phase 4).
    citations: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # Tool calls made while producing this reply: [{id, tool, args, status, summary, approved}] (Phase 5).
    tool_steps: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")  # IANA name, from the browser
    tool_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {tool: "auto" | "confirm" | "off"}
    preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # see app/personal/preferences.py
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Memory(Base):
    """A durable fact or event about the user. See docs/DATABASE.md (Phase 3)."""

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # profile | episodic | semantic
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    project: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="extracted")  # extracted | user_edited | summary
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # when an episodic event happened
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    project: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority: Mapped[str] = mapped_column(String(8), default="normal")  # low | normal | high
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | done
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(8), default="user")  # user | loki
    alerted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # deadline alert sent
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    remind_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(12), default="scheduled")  # scheduled | delivered | cancelled
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(8), default="user")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    project: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[str] = mapped_column(String(8), default="user")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Event(Base):
    """LOKI's own calendar (external calendar sync is a later integration)."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(8), default="user")
    alerted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # heads-up sent
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # reminder | agent | system
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # e.g. {"project": "Tarka"}
    delivered: Mapped[bool] = mapped_column(Boolean, default=True)  # False = held back (quiet hours)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class ToolExecution(Base):
    """Audit log: every tool call LOKI made or proposed, with its arguments, outcome and approval."""

    __tablename__ = "tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict] = mapped_column(JSON)
    permission: Mapped[str] = mapped_column(String(10))  # read | reversible | confirm
    status: Mapped[str] = mapped_column(String(10))  # ok | error | denied | timeout | invalid | disabled
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = no approval needed
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # truncated
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Project(Base):
    """A project the user works on. Other records refer to it by name (tasks, notes, memories, documents)."""

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_projects_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | paused | done
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM-written, on request
    overview_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Document(Base):
    """An uploaded file in the user's knowledge base. Identity is (user, project, source path)."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("user_id", "project", "source", name="uq_documents_user_project_source"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project: Mapped[str] = mapped_column(String(100), default="")  # "" = no project
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(500))  # file name or relative path inside an uploaded folder
    file_type: Mapped[str] = mapped_column(String(16))  # pdf | markdown | text | html | code
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)  # for code
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | processing | ready | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    # Absolute folder this document is mirrored from (watched folders); None = uploaded.
    watch_root: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Chunk(Base):
    """A searchable passage of a document. On Postgres there is also a generated `tsv` column (full-text search)."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    document: Mapped[Document] = relationship(lazy="joined")
