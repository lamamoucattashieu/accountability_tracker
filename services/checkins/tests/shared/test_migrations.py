"""The migration runner, against a real scratch SQL Server database."""

import logging

import pytest

from app.shared import migrations
from app.shared.database import connect
from app.shared.migrations import MigrationError, apply_migrations, batches, checksum, discover
from tests import sqlserver

NOW = "2026-11-20T10:00:00+00:00"


@pytest.fixture
def db_url():
    url = sqlserver.create_database("test_migrations")
    yield url
    sqlserver.drop_database(url)


@pytest.fixture
def conn(db_url):
    connection = connect(db_url)
    yield connection
    connection.close()


def write(folder, name, sql):
    (folder / name).write_text(sql, encoding="utf-8")


def recorded(conn):
    rows = conn.execute("SELECT version FROM dbo.schema_migrations ORDER BY version").fetchall()
    return [row["version"] for row in rows]


def test_pending_migrations_are_applied_in_order_and_recorded(conn, tmp_path):
    write(tmp_path, "002_add_row.sql", "INSERT INTO dbo.notes (text) VALUES (N'second')")
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.notes (id INT IDENTITY PRIMARY KEY, text NVARCHAR(50))")
    assert apply_migrations(conn, tmp_path, NOW) == ["001_init", "002_add_row"]
    assert recorded(conn) == ["001_init", "002_add_row"]


def test_a_second_boot_applies_nothing(conn, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.notes (id INT PRIMARY KEY)")
    apply_migrations(conn, tmp_path, NOW)
    assert apply_migrations(conn, tmp_path, NOW) == []
    assert "nothing to apply" in caplog.text


def test_a_migration_can_change_a_table_that_already_holds_data(conn, tmp_path):
    """Test-only stand-in for the real 002 (A2 spec 4.3): rows survive, the new column is backfilled."""
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.goals (id INT PRIMARY KEY, title NVARCHAR(80) NOT NULL)")
    apply_migrations(conn, tmp_path, NOW)
    conn.execute("INSERT INTO dbo.goals (id, title) VALUES (1, N'Gym'), (2, N'Read')")
    conn.commit()
    write(tmp_path, "002_add_emoji.sql", "\n".join([
        "ALTER TABLE dbo.goals ADD emoji NVARCHAR(8) NULL",
        "GO",
        "UPDATE dbo.goals SET emoji = N'*' WHERE emoji IS NULL",
        "GO",
        "ALTER TABLE dbo.goals ALTER COLUMN emoji NVARCHAR(8) NOT NULL",
    ]))
    assert apply_migrations(conn, tmp_path, NOW) == ["002_add_emoji"]
    rows = conn.execute("SELECT id, title, emoji FROM dbo.goals ORDER BY id").fetchall()
    assert rows == [{"id": 1, "title": "Gym", "emoji": "*"}, {"id": 2, "title": "Read", "emoji": "*"}]


def test_a_failing_migration_is_rolled_back_and_not_recorded(conn, tmp_path):
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.notes (id INT PRIMARY KEY)")
    write(tmp_path, "002_broken.sql", "CREATE TABLE dbo.half (id INT)\nGO\nINSERT INTO dbo.no_such_table VALUES (1)")
    with pytest.raises(MigrationError, match="002_broken failed and was rolled back"):
        apply_migrations(conn, tmp_path, NOW)
    assert recorded(conn) == ["001_init"]  # the earlier one stays applied
    assert conn.execute("SELECT OBJECT_ID(N'dbo.half') AS id").fetchone()["id"] is None  # nothing of 002 is left


def test_an_edited_applied_migration_stops_startup(conn, tmp_path):
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.notes (id INT PRIMARY KEY)")
    apply_migrations(conn, tmp_path, NOW)
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.notes (id INT PRIMARY KEY, extra INT)")
    with pytest.raises(MigrationError, match="was edited after it was applied"):
        apply_migrations(conn, tmp_path, NOW)


def test_an_applied_migration_missing_from_the_folder_stops_startup(conn, tmp_path):
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.notes (id INT PRIMARY KEY)")
    apply_migrations(conn, tmp_path, NOW)
    (tmp_path / "001_init.sql").unlink()
    with pytest.raises(MigrationError, match="missing"):
        apply_migrations(conn, tmp_path, NOW)


def test_a_second_copy_waits_for_the_first_and_gives_up_after_the_timeout(db_url, conn, tmp_path):
    write(tmp_path, "001_init.sql", "CREATE TABLE dbo.notes (id INT PRIMARY KEY)")
    first = connect(db_url)
    try:
        migrations._lock(first, 1000)  # another copy is migrating right now
        with pytest.raises(MigrationError, match="another copy"):
            apply_migrations(conn, tmp_path, NOW, lock_timeout_ms=500)
    finally:
        migrations._unlock(first)
        first.close()
    assert apply_migrations(conn, tmp_path, NOW) == ["001_init"]  # once it's free, it goes ahead


# --- no database needed ---

def test_line_endings_dont_change_the_checksum():
    assert checksum("CREATE TABLE t (id INT)\r\nGO\r\n") == checksum("CREATE TABLE t (id INT)\nGO\n")


def test_go_lines_split_batches():
    assert batches("CREATE TABLE a (id INT)\ngo\n  GO  \nCREATE TABLE b (id INT)\nGO") == [
        "CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"]


@pytest.mark.parametrize("names, problem", [
    (["1_init.sql"], "NNN_name.sql"),
    (["001_Init.sql"], "NNN_name.sql"),
    (["001_init.sql", "001_again.sql"], "share the number"),
])
def test_badly_named_migrations_stop_startup(tmp_path, names, problem):
    for name in names:
        write(tmp_path, name, "SELECT 1")
    with pytest.raises(MigrationError, match=problem):
        discover(tmp_path)
