"""One-off: copy LOKI's data from the development SQLite file into PostgreSQL.

Usage (from backend/):
    .venv\\Scripts\\python.exe scripts\\sqlite_to_postgres.py sqlite+aiosqlite:///./loki.db \\
        postgresql+asyncpg://loki:loki@127.0.0.1:5432/loki

The target is migrated to head first. Refuses to run if the target already has users. The SQLite file is only
read, never modified.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.db import migrate  # noqa: E402
from app.db.models import Base  # noqa: E402

ORDER = ["users", "sessions", "conversations", "messages", "user_settings", "memories"]


async def copy(src_url: str, dst_url: str) -> None:
    # Alembic's env runs its own event loop, so migrations go to a worker thread.
    await asyncio.to_thread(migrate.upgrade, src_url)  # bring the SQLite file to the same schema version first
    await asyncio.to_thread(migrate.upgrade, dst_url)
    src, dst = create_async_engine(src_url), create_async_engine(dst_url)
    try:
        async with dst.connect() as d:
            existing = await d.scalar(select(func.count()).select_from(Base.metadata.tables["users"]))
        if existing:
            raise SystemExit(f"Target already has {existing} users; refusing to copy over existing data.")
        async with src.connect() as s, dst.begin() as d:
            for name in ORDER:
                table = Base.metadata.tables[name]
                rows = [dict(r._mapping) for r in await s.execute(select(table))]
                if rows:
                    await d.execute(table.insert(), rows)
                print(f"{name:15} {len(rows):5} rows")
    finally:
        await src.dispose()
        await dst.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    asyncio.run(copy(sys.argv[1], sys.argv[2]))
