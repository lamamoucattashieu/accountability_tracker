import io
import json

import pymssql

import pytest

from app.checkins import repository, service
from app.db import get_db
from app.shared import uploads
from tests.factories import make_group
from tests.images import image_bytes, image_file


def checkin_count(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM checkins").fetchone()["n"]


@pytest.fixture
def checkin(conn, alice, goal):
    return service.create_checkin(conn, alice, goal["id"], image_file(), "done!")


# --- create ---

def test_create_checkin_is_accepted_and_stores_photo(conn, alice, goal):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file("PNG"), None)
    assert checkin["status"] == "accepted"
    assert checkin["goal_id"] == goal["id"]
    assert checkin["user_id"] == alice
    assert checkin["created_at"].endswith("+00:00")
    assert "photo" not in checkin  # the bytes are never part of a check-in row read
    photo, photo_type = service.get_checkin_photo(conn, alice, checkin["id"])
    assert (photo, photo_type) == (image_bytes("PNG"), "image/png")


def test_caption_is_trimmed(conn, alice, goal):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), "  leg day  ")
    assert checkin["caption"] == "leg day"


@pytest.mark.parametrize("caption", ["", "   ", None])
def test_empty_caption_is_stored_as_null(conn, alice, goal, caption):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), caption)
    assert checkin["caption"] is None


def test_caption_limit_applies_after_trimming(conn, alice, goal):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), " " + "c" * 200 + " ")
    assert len(checkin["caption"]) == 200
    with pytest.raises(service.InvalidCheckin):
        service.create_checkin(conn, alice, goal["id"], image_file(), "c" * 201)
    assert checkin_count(conn) == 1  # the rejected one was never saved


def test_non_owner_member_cannot_check_in(conn, bob, goal):
    with pytest.raises(service.NotGoalOwner):
        service.create_checkin(conn, bob, goal["id"], image_file(), None)
    assert checkin_count(conn) == 0


def test_non_member_cannot_check_in(conn, outsider, goal):
    with pytest.raises(service.NotGroupMember):
        service.create_checkin(conn, outsider, goal["id"], image_file(), None)


def test_check_in_on_missing_goal_is_not_found(conn, alice):
    with pytest.raises(service.GoalNotFound):
        service.create_checkin(conn, alice, 999, image_file(), None)


def test_check_in_on_archived_goal_is_conflict(conn, alice, goal):
    service.archive_goal(conn, alice, goal["id"])
    with pytest.raises(service.GoalArchived):
        service.create_checkin(conn, alice, goal["id"], image_file(), None)
    assert checkin_count(conn) == 0


def test_invalid_photo_is_rejected(conn, alice, goal):
    with pytest.raises(uploads.InvalidImage):
        service.create_checkin(conn, alice, goal["id"], io.BytesIO(b"not an image"), None)


def test_nothing_is_kept_when_the_insert_fails(conn, alice, goal, monkeypatch):
    def failing_insert(*args):
        raise pymssql.OperationalError(1222, b"Lock request time out period exceeded.")

    monkeypatch.setattr(repository, "insert_checkin", failing_insert)
    with pytest.raises(pymssql.OperationalError):
        service.create_checkin(conn, alice, goal["id"], image_file(), None)
    assert checkin_count(conn) == 0


def test_database_rejects_unknown_status(conn, checkin):
    """The CHECK constraint only allows 'accepted' and 'rejected'."""
    with pytest.raises(pymssql.IntegrityError):
        conn.execute("UPDATE checkins SET status = 'pending' WHERE id = %s", (checkin["id"],))


# --- feed ---

def test_feed_is_newest_first(conn, alice, bob, group_id, goal):
    bob_goal = service.create_goal(conn, bob, group_id, "Read", None, 5)
    first = service.create_checkin(conn, alice, goal["id"], image_file(), "first")
    second = service.create_checkin(conn, bob, bob_goal["id"], image_file(), "second")
    third = service.create_checkin(conn, alice, goal["id"], image_file(), "third")
    feed = service.list_group_checkins(conn, bob, group_id)
    assert [c["id"] for c in feed] == [third["id"], second["id"], first["id"]]


def test_feed_is_capped(conn, alice, group_id, goal, monkeypatch):
    monkeypatch.setattr(service, "FEED_LIMIT", 2)
    for _ in range(3):
        service.create_checkin(conn, alice, goal["id"], image_file(), None)
    assert len(service.list_group_checkins(conn, alice, group_id)) == 2


def test_feed_keeps_checkins_of_archived_goals(conn, alice, group_id, goal, checkin):
    service.archive_goal(conn, alice, goal["id"])
    feed = service.list_group_checkins(conn, alice, group_id)
    assert [c["id"] for c in feed] == [checkin["id"]]


def test_feed_excludes_other_groups(conn, alice, bob, group_id, checkin):
    other_group = make_group(conn, bob)
    other_goal = service.create_goal(conn, bob, other_group, "Swim", None, 2)
    service.create_checkin(conn, bob, other_goal["id"], image_file(), None)
    feed = service.list_group_checkins(conn, alice, group_id)
    assert [c["id"] for c in feed] == [checkin["id"]]


def test_non_member_cannot_see_feed(conn, outsider, group_id):
    with pytest.raises(service.NotGroupMember):
        service.list_group_checkins(conn, outsider, group_id)


def test_feed_of_missing_group_is_not_found(conn, alice):
    with pytest.raises(service.GroupNotFound):
        service.list_group_checkins(conn, alice, 999)


# --- photo access ---

def test_member_gets_the_photo(conn, bob, checkin):
    assert service.get_checkin_photo(conn, bob, checkin["id"]) == (image_bytes("JPEG"), "image/jpeg")


def test_non_member_cannot_get_photo(conn, outsider, checkin):
    with pytest.raises(service.NotGroupMember):
        service.get_checkin_photo(conn, outsider, checkin["id"])


def test_photo_of_missing_checkin_is_not_found(conn, alice):
    with pytest.raises(service.CheckinNotFound):
        service.get_checkin_photo(conn, alice, 999)


# --- points seam (the outbox) ---

def test_new_checkin_queues_its_completion_for_points(conn, alice, group_id, goal, checkin):
    row = conn.execute("SELECT * FROM points_outbox WHERE checkin_id = %s", (checkin["id"],)).fetchone()
    assert row["kind"] == "record"
    assert json.loads(row["payload"]) == {
        "checkin_id": checkin["id"],
        "group_id": group_id,
        "user_id": alice,
        "goal_id": goal["id"],
        "times_per_week": goal["times_per_week"],
        "completed_at": checkin["created_at"],
    }
    assert checkin["points_pending"] == 1  # not delivered yet


def test_checkin_is_saved_when_points_is_down(conn, alice, goal, points):
    """Replaces A1's "photo deleted when recording points fails": recording can't fail any more."""
    points.mode = "down"
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), None)
    conn.commit()
    service.deliver_points_changes(conn)
    assert service.get_checkin(conn, checkin["id"])["status"] == "accepted"
    assert service.is_points_pending(conn, checkin["id"]) is True


def test_nothing_is_kept_when_queueing_the_completion_fails(conn, alice, goal, monkeypatch):
    """The check-in, its photo and its outbox row are one transaction: replaces A1's photo-file cleanup."""
    conn.commit()  # keep the setup; the check-in gets its own request transaction

    def failing_insert(*args):
        raise pymssql.OperationalError(1222, b"Lock request time out period exceeded.")

    monkeypatch.setattr(repository, "insert_outbox", failing_insert)
    with pytest.raises(pymssql.OperationalError):
        with get_db() as request_conn:  # the same get_db() a real request uses
            service.create_checkin(request_conn, alice, goal["id"], image_file(), None)
    assert checkin_count(conn) == 0


# --- comments on proof ---

def test_member_comments_on_a_checkin(conn, bob, checkin):
    comment = service.add_comment(conn, bob, checkin["id"], "  okay that's actually impressive  ")
    assert comment["text"] == "okay that's actually impressive"
    assert comment["author_id"] == bob
    assert comment["created_at"].endswith("+00:00")


def test_author_can_reply_on_their_own_checkin(conn, alice, bob, checkin):
    service.add_comment(conn, bob, checkin["id"], "is that even you?")
    service.add_comment(conn, alice, checkin["id"], "yes, receipts attached")
    comments = service.list_comments(conn, alice, checkin["id"])
    assert [c["author_id"] for c in comments] == [bob, alice]  # oldest first


def test_feed_shows_the_comment_count(conn, alice, bob, group_id, checkin):
    service.add_comment(conn, bob, checkin["id"], "nice")
    [item] = service.list_group_checkins(conn, alice, group_id)
    assert item["comment_count"] == 1


@pytest.mark.parametrize("text", ["", "   ", None, "x" * 281])
def test_invalid_comment_is_rejected(conn, bob, checkin, text):
    with pytest.raises(service.InvalidComment):
        service.add_comment(conn, bob, checkin["id"], text)


def test_comment_at_the_length_limit_is_accepted(conn, bob, checkin):
    assert len(service.add_comment(conn, bob, checkin["id"], "x" * 280)["text"]) == 280


def test_non_member_cannot_comment_or_read_comments(conn, outsider, checkin):
    with pytest.raises(service.NotGroupMember):
        service.add_comment(conn, outsider, checkin["id"], "hi")
    with pytest.raises(service.NotGroupMember):
        service.list_comments(conn, outsider, checkin["id"])


def test_comment_on_missing_checkin_is_not_found(conn, bob):
    with pytest.raises(service.CheckinNotFound):
        service.add_comment(conn, bob, 999, "hi")


def test_database_also_enforces_the_comment_length(conn, bob, checkin):
    # NVARCHAR(280) refuses it before the CHECK runs ("would be truncated"): either way, not stored.
    with pytest.raises(pymssql.DatabaseError):
        repository.insert_comment(conn, checkin["id"], bob, "x" * 281, "2026-10-03T10:00:00+00:00")
