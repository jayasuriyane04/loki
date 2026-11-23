"""Phase 7: traces, metric events, message feedback.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

from app.db.models import UTCDateTime

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_mode", sa.String(8), nullable=False, server_default="text"),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("first_audio_ms", sa.Integer(), nullable=True),
        sa.Column("stt_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("spans", sa.JSON(), nullable=True),
        sa.Column("attrs", sa.JSON(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_traces_user_id", "traces", ["user_id"])
    op.create_index("ix_traces_kind", "traces", ["kind"])
    op.create_index("ix_traces_created_at", "traces", ["created_at"])
    op.create_table(
        "metric_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("attrs", sa.JSON(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_metric_events_kind", "metric_events", ["kind"])
    op.create_index("ix_metric_events_created_at", "metric_events", ["created_at"])
    with op.batch_alter_table("messages") as b:
        b.add_column(sa.Column("feedback", sa.Integer(), nullable=True))
        b.add_column(sa.Column("feedback_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as b:
        b.drop_column("feedback_note")
        b.drop_column("feedback")
    op.drop_table("metric_events")
    op.drop_table("traces")
