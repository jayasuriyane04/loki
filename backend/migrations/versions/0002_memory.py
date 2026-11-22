"""Phase 3: memories, user settings, conversation summaries.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.db.models import EMBEDDING_DIM, UTCDateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    with op.batch_alter_table("conversations") as b:
        b.add_column(sa.Column("summary", sa.Text(), nullable=True))
        b.add_column(sa.Column("summary_until", UTCDateTime(), nullable=True))

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )

    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("project", sa.String(100), nullable=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column(
            "source_conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
    )
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_index("ix_memories_source_conversation_id", "memories", ["source_conversation_id"])
    if is_pg:
        op.execute(
            "CREATE INDEX ix_memories_embedding_hnsw ON memories USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    op.drop_table("memories")
    op.drop_table("user_settings")
    with op.batch_alter_table("conversations") as b:
        b.drop_column("summary_until")
        b.drop_column("summary")
