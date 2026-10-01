import sqlite3

import pytest

from app.points import repository, service

# Points stores other domains' ids without foreign keys, so these tests record
# completions with plain ids and need no users, goals or check-ins.
GROUP, ALICE, GYM = 1, 10, 100


def record(conn, checkin_id, completed_at="2026-09-30T12:00:00+00:00", times_per_week=3):
    service.record_completion(
        conn, checkin_id=checkin_id, group_id=GROUP, user_id=ALICE, goal_id=GYM,
        times_per_week=times_per_week, completed_at=completed_at,
    )


def events(conn):
    return conn.execute("SELECT * FROM point_events ORDER BY checkin_id").fetchall()


def test_completion_is_recorded_in_its_week(conn):
    record(conn, 1, completed_at="2026-10-01T09:00:00+00:00")
    [event] = events(conn)
    assert event["checkin_id"] == 1
    assert event["user_id"] == ALICE
    assert event["times_per_week"] == 3
    assert event["week_start"] == "2026-09-28"
    assert event["revoked_at"] is None


def test_completions_either_side_of_the_week_boundary(conn):
    record(conn, 1, completed_at="2026-10-04T23:59:59+00:00")
    record(conn, 2, completed_at="2026-10-05T00:00:00+00:00")
    assert [e["week_start"] for e in events(conn)] == ["2026-09-28", "2026-10-05"]


def test_points_awarded_once_and_duplicate_award_ignored(conn):
    record(conn, 1)
    record(conn, 1)  # e.g. a retried request: no second event, no error
    assert len(events(conn)) == 1


def test_duplicate_is_ignored_by_the_database_not_python(conn):
    args = (1, GROUP, ALICE, GYM, 3, "2026-09-28", "2026-09-30T12:00:00+00:00")
    assert repository.insert_event(conn, *args) is True
    assert repository.insert_event(conn, *args) is False


def test_invalid_event_still_raises_instead_of_being_ignored(conn):
    """ON CONFLICT only ignores a duplicate check-in; other violations are real errors."""
    with pytest.raises(sqlite3.IntegrityError):
        record(conn, 1, times_per_week=9)
    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_event(conn, 2, GROUP, ALICE, GYM, 3, "2026-09-30", "x")  # a Wednesday


def test_revoke_removes_exactly_that_checkins_points(conn):
    record(conn, 1)
    record(conn, 2)
    service.revoke_completion(conn, 1)
    first, second = events(conn)
    assert first["revoked_at"] is not None
    assert second["revoked_at"] is None


def test_revoke_of_unknown_checkin_is_a_no_op(conn):
    service.revoke_completion(conn, 999)
    assert events(conn) == []


def test_revoke_of_already_revoked_checkin_keeps_the_first_timestamp(conn):
    record(conn, 1)
    assert repository.revoke_event(conn, 1, "2026-10-01T10:00:00+00:00") is True
    assert repository.revoke_event(conn, 1, "2026-10-02T10:00:00+00:00") is False
    assert events(conn)[0]["revoked_at"] == "2026-10-01T10:00:00+00:00"


def test_recording_a_revoked_checkin_again_does_not_restore_it(conn):
    record(conn, 1)
    service.revoke_completion(conn, 1)
    record(conn, 1)
    assert events(conn)[0]["revoked_at"] is not None
