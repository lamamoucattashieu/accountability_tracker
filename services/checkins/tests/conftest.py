import pytest

from app.checkins import points_client
from app.checkins.points_client import PointsRejected, PointsUnavailable
from app.db import MIGRATIONS_DIR
from app.shared.database import connect
from app.shared.migrations import apply_migrations
from tests import sqlserver


TEST_SECRET = "test-only-token-secret"
TEST_INTERNAL_KEY = "test-only-internal-key"


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    """Every secret a service needs, with test-only values."""
    monkeypatch.setenv("AUTH_TOKEN_SECRET", TEST_SECRET)
    # Tests that touch the database replace this with their own (see the db fixture).
    monkeypatch.setenv("DATABASE_URL", UNUSED_DATABASE_URL)
    monkeypatch.setenv("INTERNAL_API_KEY", TEST_INTERNAL_KEY)


class FakePoints:
    """Stands in for the Points service behind the PointsClient port.

    mode "up" records every call, "down" raises PointsUnavailable (like a timeout
    or a refused connection), "rejecting" raises PointsRejected (like a 4xx).
    """

    def __init__(self):
        self.mode = "up"
        self.calls = []

    def _answer(self, call):
        if self.mode == "down":
            raise PointsUnavailable("points is down")
        if self.mode == "rejecting":
            raise PointsRejected("422 invalid completion")
        self.calls.append(call)

    def record(self, completion):
        self._answer(("record", completion["checkin_id"]))

    def revoke(self, checkin_id, revoked_at):
        self._answer(("revoke", checkin_id))


@pytest.fixture(autouse=True)
def points(monkeypatch):
    """Every check-ins test talks to a fake Points, never a real one."""
    fake = FakePoints()
    monkeypatch.setattr(points_client, "_client", fake)
    return fake


# Child tables first, so foreign keys never block a delete. service_health and
# schema_migrations keep their rows: they come from the migrations.
TABLES = ["points_outbox", "checkin_votes", "checkin_comments", "nudges", "checkins",
          "goals", "group_members", "sessions", "groups", "users"]
UNUSED_DATABASE_URL = "mssql+pymssql://unused:unused@localhost:1433/unused"


@pytest.fixture(scope="session")
def database_url():
    """One scratch database for the whole run, built by the real migrations."""
    url = sqlserver.create_database("test_checkins")
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
