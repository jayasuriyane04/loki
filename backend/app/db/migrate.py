"""Run Alembic migrations programmatically (start-up and tests)."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

log = logging.getLogger(__name__)
BACKEND = Path(__file__).resolve().parents[2]


def upgrade(database_url: str) -> None:
    """Upgrade to head. A database created before migrations existed (Phase 1 `create_all`) is stamped at the
    baseline first, so existing data is kept."""
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = database_url

    if database_url.startswith("sqlite"):
        engine = create_engine(database_url.replace("+aiosqlite", ""))
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        if "users" in tables and "alembic_version" not in tables:
            log.info("pre-migration database found; stamping baseline 0001")
            command.stamp(cfg, "0001")

    command.upgrade(cfg, "head")
