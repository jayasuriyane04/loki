"""Phase 6: preferences, projects, proactive alert tracking, conversation digests.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op

from app.db.models import UTCDateTime

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_settings") as b:
        b.add_column(sa.Column("preferences", sa.JSON(), nullable=True))
    with op.batch_alter_table("conversations") as b:
        b.add_column(sa.Column("project", sa.String(100), nullable=True))
        b.add_column(sa.Column("digested_at", UTCDateTime(), nullable=True))
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("alerted_at", UTCDateTime(), nullable=True))
    with op.batch_alter_table("events") as b:
        b.add_column(sa.Column("alerted_at", UTCDateTime(), nullable=True))
    with op.batch_alter_table("notifications") as b:
        b.add_column(sa.Column("data", sa.JSON(), nullable=True))
        b.add_column(sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("overview_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])


def downgrade() -> None:
    op.drop_table("projects")
    with op.batch_alter_table("notifications") as b:
        b.drop_column("delivered")
        b.drop_column("data")
    with op.batch_alter_table("events") as b:
        b.drop_column("alerted_at")
    with op.batch_alter_table("tasks") as b:
        b.drop_column("alerted_at")
    with op.batch_alter_table("conversations") as b:
        b.drop_column("digested_at")
        b.drop_column("project")
    with op.batch_alter_table("user_settings") as b:
        b.drop_column("preferences")
