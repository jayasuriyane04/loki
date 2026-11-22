"""Phase 5: tasks, reminders, notes, events, notifications, tool execution log, user timezone/tool prefs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.db.models import EMBEDDING_DIM, UTCDateTime

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _owned(name: str, *cols: sa.Column) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        *cols,
    )
    op.create_index(f"ix_{name}_user_id", name, ["user_id"])


def upgrade() -> None:
    with op.batch_alter_table("messages") as b:
        b.add_column(sa.Column("tool_steps", sa.JSON(), nullable=True))
    with op.batch_alter_table("user_settings") as b:
        b.add_column(sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"))
        b.add_column(sa.Column("tool_prefs", sa.JSON(), nullable=True))

    _owned(
        "tasks",
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("project", sa.String(100), nullable=True),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("due_at", UTCDateTime(), nullable=True),
        sa.Column("completed_at", UTCDateTime(), nullable=True),
        sa.Column("created_by", sa.String(8), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    _owned(
        "reminders",
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("remind_at", UTCDateTime(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("delivered_at", UTCDateTime(), nullable=True),
        sa.Column("created_by", sa.String(8), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_reminders_remind_at", "reminders", ["remind_at"])
    _owned(
        "notes",
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("project", sa.String(100), nullable=True),
        sa.Column("created_by", sa.String(8), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    _owned(
        "events",
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("starts_at", UTCDateTime(), nullable=False),
        sa.Column("ends_at", UTCDateTime(), nullable=True),
        sa.Column("location", sa.String(300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(8), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_events_starts_at", "events", ["starts_at"])
    _owned(
        "notifications",
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("read_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    _owned(
        "tool_executions",
        sa.Column(
            "conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("permission", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("summary", sa.String(500), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_tool_executions_conversation_id", "tool_executions", ["conversation_id"])
    op.create_index("ix_tool_executions_created_at", "tool_executions", ["created_at"])


def downgrade() -> None:
    for t in ("tool_executions", "notifications", "events", "notes", "reminders", "tasks"):
        op.drop_table(t)
    with op.batch_alter_table("user_settings") as b:
        b.drop_column("tool_prefs")
        b.drop_column("timezone")
    with op.batch_alter_table("messages") as b:
        b.drop_column("tool_steps")
