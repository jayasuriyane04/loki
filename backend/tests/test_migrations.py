import sqlite3

from app.db import migrate


def test_fresh_database_upgrades_to_head(tmp_path):
    db = tmp_path / "fresh.db"
    migrate.upgrade(f"sqlite+aiosqlite:///{db.as_posix()}")
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"users", "sessions", "conversations", "messages", "memories", "user_settings"} <= tables
    assert con.execute("select version_num from alembic_version").fetchone() == ("0003",)


def test_pre_migration_database_is_stamped_and_upgraded_without_data_loss(tmp_path):
    """Phase 1 created tables with create_all and had no alembic_version table."""
    db = tmp_path / "phase1.db"
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    migrate.upgrade(url)
    con = sqlite3.connect(db)
    con.execute("drop table chunks")
    con.execute("drop table documents")
    con.execute("alter table messages drop column citations")
    con.execute("drop table memories")
    con.execute("drop table user_settings")
    con.execute("drop table alembic_version")
    con.execute("alter table conversations drop column summary")
    con.execute("alter table conversations drop column summary_until")
    con.execute(
        "insert into users (id, email, display_name, password_hash, is_active, created_at, updated_at) "
        "values ('u1', 'a@example.com', 'A', 'x', 1, '2026-11-22', '2026-11-22')"
    )
    con.commit()
    con.close()

    migrate.upgrade(url)

    con = sqlite3.connect(db)
    assert con.execute("select version_num from alembic_version").fetchone() == ("0003",)
    assert con.execute("select email from users").fetchall() == [("a@example.com",)]
    assert "summary" in [r[1] for r in con.execute("pragma table_info(conversations)")]
