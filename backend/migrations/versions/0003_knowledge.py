"""Phase 4: knowledge base (documents, chunks) and message citations.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.db.models import EMBEDDING_DIM, UTCDateTime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"

    with op.batch_alter_table("messages") as b:
        b.add_column(sa.Column("citations", sa.JSON(), nullable=True))

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project", sa.String(100), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("indexed_at", UTCDateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "project", "source", name="uq_documents_user_project_source"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.String(500), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_user_id", "chunks", ["user_id"])
    if is_pg:
        # Full-text side of hybrid search: generated tsvector (headings weighted above body) + GIN index.
        op.execute(
            "ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS ("
            "setweight(to_tsvector('english', coalesce(heading_path, '')), 'A') || "
            "setweight(to_tsvector('english', content), 'B')) STORED"
        )
        op.execute("CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)")
        op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    with op.batch_alter_table("messages") as b:
        b.drop_column("citations")
