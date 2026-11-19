import pytest

from app.checkins import points_client
from app.checkins.points_client import PointsRejected, PointsUnavailable
from app.config import settings
from app.db import get_connection, init_db


TEST_SECRET = "test-only-token-secret"
TEST_INTERNAL_KEY = "test-only-internal-key"


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    """Every secret a service needs, with test-only values."""
    monkeypatch.setenv("AUTH_TOKEN_SECRET", TEST_SECRET)
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


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temporary folder and create the schema, like startup does."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "checkins.db")
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    init_db()
    return tmp_path


@pytest.fixture
def conn(data_dir):
    """A connection to the fresh database under the temporary DATA_DIR."""
    connection = get_connection()
    yield connection
    connection.close()
