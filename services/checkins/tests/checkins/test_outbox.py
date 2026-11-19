"""The points outbox: queued in the request's transaction, delivered in order afterwards."""

import pytest

from app.checkins import outbox, repository, service
from tests.images import image_file


@pytest.fixture
def two_checkins(conn, alice, goal):
    first = service.create_checkin(conn, alice, goal["id"], image_file(), None)
    second = service.create_checkin(conn, alice, goal["id"], image_file(), None)
    conn.commit()
    return first["id"], second["id"]


def outbox_rows(conn):
    return conn.execute("SELECT * FROM points_outbox ORDER BY id").fetchall()


def test_delivered_rows_are_marked_sent(conn, two_checkins, points):
    outbox.deliver_pending(conn)
    assert points.calls == [("record", two_checkins[0]), ("record", two_checkins[1])]
    assert all(row["sent_at"] is not None for row in outbox_rows(conn))
    assert not service.is_points_pending(conn, two_checkins[0])


def test_points_down_keeps_every_row_pending_and_stops(conn, two_checkins, points):
    points.mode = "down"
    outbox.deliver_pending(conn)
    rows = outbox_rows(conn)
    assert [row["sent_at"] for row in rows] == [None, None]
    assert rows[0]["last_error"] == "points is down"
    assert rows[1]["last_error"] is None  # stopped at the first failure, never tried


def test_pending_rows_are_delivered_in_order_once_points_is_back(conn, two_checkins, points):
    points.mode = "down"
    outbox.deliver_pending(conn)
    points.mode = "up"
    outbox.deliver_pending(conn)
    assert points.calls == [("record", two_checkins[0]), ("record", two_checkins[1])]


def test_a_revoke_is_never_delivered_before_its_record(conn, bob, two_checkins, points):
    points.mode = "down"
    first, _ = two_checkins
    service.cast_rejection_vote(conn, bob, first)  # 2-person group: one vote rejects
    conn.commit()
    outbox.deliver_pending(conn)
    points.mode = "up"
    outbox.deliver_pending(conn)
    assert points.calls[0] == ("record", first)
    assert points.calls.index(("revoke", first)) > points.calls.index(("record", first))


def test_a_row_points_rejects_is_marked_failed_and_skipped(conn, two_checkins, points):
    points.mode = "rejecting"
    outbox.deliver_pending(conn)
    rows = outbox_rows(conn)
    assert all(row["failed_at"] is not None for row in rows)  # both tried: one bad row blocks nothing
    assert rows[0]["last_error"] == "422 invalid completion"
    assert not service.is_points_pending(conn, two_checkins[0])  # failed is not pending


def test_delivery_sends_at_most_one_batch(conn, two_checkins, points):
    outbox.deliver_pending(conn, limit=1)
    assert points.calls == [("record", two_checkins[0])]
    assert service.is_points_pending(conn, two_checkins[1])


def test_group_has_pending_outbox_until_delivered(conn, group_id, two_checkins, points):
    assert repository.group_has_pending_outbox(conn, group_id) is True
    outbox.deliver_pending(conn)
    assert repository.group_has_pending_outbox(conn, group_id) is False


def test_revoke_payload_keeps_the_rejection_time(conn, bob, two_checkins):
    service.cast_rejection_vote(conn, bob, two_checkins[0])
    revoke = conn.execute("SELECT * FROM points_outbox WHERE kind = 'revoke'").fetchone()
    assert revoke["checkin_id"] == two_checkins[0]
    assert '"revoked_at": "' in revoke["payload"]
