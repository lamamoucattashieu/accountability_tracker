import pytest

from app.checkins import points_client, service
from app.checkins.points_client import PointsRejected, PointsUnavailable
from tests.factories import make_group, make_user


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


@pytest.fixture
def points(monkeypatch):
    fake = FakePoints()
    monkeypatch.setattr(points_client, "_client", fake)
    return fake


def queued_revokes(conn):
    """checkin_ids of every revoke queued in the points outbox, oldest first."""
    rows = conn.execute(
        "SELECT checkin_id FROM points_outbox WHERE kind = 'revoke' ORDER BY id"
    ).fetchall()
    return [row["checkin_id"] for row in rows]


@pytest.fixture
def alice(conn):
    return make_user(conn, "alice")


@pytest.fixture
def bob(conn):
    return make_user(conn, "bob")


@pytest.fixture
def outsider(conn):
    return make_user(conn, "outsider")


@pytest.fixture
def group_id(conn, alice, bob):
    return make_group(conn, alice, bob)


@pytest.fixture
def goal(conn, alice, group_id):
    return service.create_goal(conn, alice, group_id, "Gym", "at least 45 min", 3)
