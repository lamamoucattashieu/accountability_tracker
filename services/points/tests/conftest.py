import pytest

from app.db import MIGRATIONS_DIR
from app.points import group_directory
from app.shared.database import connect
from app.shared.migrations import apply_migrations
from tests import factories, sqlserver

TEST_SECRET = "test-only-token-secret"
TEST_INTERNAL_KEY = "test-only-internal-key"


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    """Every secret a service needs, with test-only values."""
    monkeypatch.setenv("AUTH_TOKEN_SECRET", TEST_SECRET)
    monkeypatch.setenv("INTERNAL_API_KEY", TEST_INTERNAL_KEY)
    # Tests that touch the database replace this with their own (see the db fixture).
    monkeypatch.setenv("DATABASE_URL", UNUSED_DATABASE_URL)


@pytest.fixture(autouse=True)
def checkins(monkeypatch):
    """A fresh fake Checkins behind the GroupDirectory port, for every test."""
    fake = factories.reset_directory()
    monkeypatch.setattr(group_directory, "_directory", fake)
    return fake


# Child tables first, so foreign keys never block a delete. service_health and
# schema_migrations keep their rows: they come from the migrations.
TABLES = ["forfeit_assignments", "settlements", "forfeits", "point_events", "group_snapshots"]
UNUSED_DATABASE_URL = "mssql+pymssql://unused:unused@localhost:1433/unused"


@pytest.fixture(scope="session")
def database_url():
    """One scratch database for the whole run, built by the real migrations."""
    url = sqlserver.create_database("test_points")
    conn = connect(url)
    try:
        apply_migrations(conn, MIGRATIONS_DIR, "2026-01-01T00:00:00+00:00")
    finally:
        conn.close()
    yield url
    sqlserver.drop_database(url)


@pytest.fixture
def db(database_url, monkeypatch):
    """An empty database for this test: every table wiped, ids starting from 1 again."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    conn = connect(database_url)
    try:
        for table in TABLES:
            conn.execute(f"DELETE FROM dbo.{table}")
        conn.commit()
        for table in TABLES:
            # Reseed only tables that ever had a row: on a never-used table the next id would be 0.
            if conn.execute(
                "SELECT 1 AS used FROM sys.identity_columns WHERE object_id = OBJECT_ID(%s) AND last_value IS NOT NULL",
                (f"dbo.{table}",),
            ).fetchone():
                conn.execute(f"DBCC CHECKIDENT ('dbo.{table}', RESEED, 0) WITH NO_INFOMSGS")
        conn.commit()
    finally:
        conn.close()
    return database_url


@pytest.fixture
def conn(db):
    """A connection to this test's empty database."""
    connection = connect(db)
    yield connection
    connection.close()
