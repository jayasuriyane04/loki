"""Phase 6: documents mirrored from watched folders.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as b:
        b.add_column(sa.Column("watch_root", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as b:
        b.drop_column("watch_root")
