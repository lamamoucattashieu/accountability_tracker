import io
import sqlite3

import pytest

from app.checkins import repository, service
from app.points import service as points_service
from app.shared import uploads
from tests.factories import make_group
from tests.images import image_file


def stored_files(data_dir):
    return list((data_dir / "uploads").iterdir())


@pytest.fixture
def checkin(conn, alice, goal):
    return service.create_checkin(conn, alice, goal["id"], image_file(), "done!")


# --- create ---

def test_create_checkin_is_accepted_and_stores_photo(conn, data_dir, alice, goal):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file("PNG"), None)
    assert checkin["status"] == "accepted"
    assert checkin["goal_id"] == goal["id"]
    assert checkin["user_id"] == alice
    assert checkin["created_at"].endswith("+00:00")
    assert checkin["photo_path"].endswith(".png")
    assert (data_dir / checkin["photo_path"]).is_file()


def test_caption_is_trimmed(conn, alice, goal):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), "  leg day  ")
    assert checkin["caption"] == "leg day"


@pytest.mark.parametrize("caption", ["", "   ", None])
def test_empty_caption_is_stored_as_null(conn, alice, goal, caption):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), caption)
    assert checkin["caption"] is None


def test_caption_limit_applies_after_trimming(conn, data_dir, alice, goal):
    checkin = service.create_checkin(conn, alice, goal["id"], image_file(), " " + "c" * 200 + " ")
    assert len(checkin["caption"]) == 200
    with pytest.raises(service.InvalidCheckin):
        service.create_checkin(conn, alice, goal["id"], image_file(), "c" * 201)
    assert len(stored_files(data_dir)) == 1  # the rejected one was never saved


def test_non_owner_member_cannot_check_in(conn, data_dir, bob, goal):
    with pytest.raises(service.NotGoalOwner):
        service.create_checkin(conn, bob, goal["id"], image_file(), None)
    assert stored_files(data_dir) == []


def test_non_member_cannot_check_in(conn, outsider, goal):
    with pytest.raises(service.NotGroupMember):
        service.create_checkin(conn, outsider, goal["id"], image_file(), None)


def test_check_in_on_missing_goal_is_not_found(conn, alice):
    with pytest.raises(service.GoalNotFound):
        service.create_checkin(conn, alice, 999, image_file(), None)


def test_check_in_on_archived_goal_is_conflict(conn, data_dir, alice, goal):
    service.archive_goal(conn, alice, goal["id"])
    with pytest.raises(service.GoalArchived):
        service.create_checkin(conn, alice, goal["id"], image_file(), None)
    assert stored_files(data_dir) == []


def test_invalid_photo_is_rejected(conn, alice, goal):
    with pytest.raises(uploads.InvalidImage):
        service.create_checkin(conn, alice, goal["id"], io.BytesIO(b"not an image"), None)


def test_photo_is_deleted_when_insert_fails(conn, data_dir, alice, goal, monkeypatch):
    def failing_insert(*args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(repository, "insert_checkin", failing_insert)
    with pytest.raises(sqlite3.OperationalError):
        service.create_checkin(conn, alice, goal["id"], image_file(), None)
    assert stored_files(data_dir) == []


def test_database_rejects_unknown_status(conn, checkin):
    """The CHECK constraint only allows 'accepted' and 'rejected'."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE checkins SET status = 'pending' WHERE id = ?", (checkin["id"],))


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

def test_member_gets_photo_path(conn, data_dir, bob, checkin):
    path = service.get_checkin_photo_path(conn, bob, checkin["id"])
    assert path == (data_dir / checkin["photo_path"]).resolve()


def test_non_member_cannot_get_photo(conn, outsider, checkin):
    with pytest.raises(service.NotGroupMember):
        service.get_checkin_photo_path(conn, outsider, checkin["id"])


def test_photo_of_missing_checkin_is_not_found(conn, alice):
    with pytest.raises(service.CheckinNotFound):
        service.get_checkin_photo_path(conn, alice, 999)


def test_missing_photo_file_is_not_found_and_logged(conn, data_dir, alice, checkin, caplog):
    (data_dir / checkin["photo_path"]).unlink()
    with pytest.raises(service.PhotoMissing):
        service.get_checkin_photo_path(conn, alice, checkin["id"])
    assert "missing photo" in caplog.text


# --- points seam ---

def test_new_checkin_is_recorded_in_points(conn, alice, group_id, goal, checkin):
    event = conn.execute(
        "SELECT * FROM point_events WHERE checkin_id = ?", (checkin["id"],)
    ).fetchone()
    assert event["user_id"] == alice
    assert event["group_id"] == group_id
    assert event["goal_id"] == goal["id"]
    assert event["times_per_week"] == goal["times_per_week"]
    assert event["completed_at"] == checkin["created_at"]


def test_photo_is_deleted_when_recording_points_fails(conn, data_dir, alice, goal, monkeypatch):
    def failing_record(conn, **completion):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(points_service, "record_completion", failing_record)
    with pytest.raises(sqlite3.OperationalError):
        service.create_checkin(conn, alice, goal["id"], image_file(), None)
    assert stored_files(data_dir) == []


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
    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_comment(conn, checkin["id"], bob, "x" * 281, "2026-10-03T10:00:00+00:00")
