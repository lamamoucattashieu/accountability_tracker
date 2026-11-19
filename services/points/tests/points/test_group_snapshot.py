"""When Checkins can't answer: serve reads from the snapshot, refuse changes, never settle."""

import pytest

from app.points import repository, service
from tests.points.conftest import at, complete

SETTLES = at("2026-10-01T00:00:00+00:00")  # week of 2026-09-21 settles from here (Wed + 48h)


@pytest.fixture
def directory(checkins):
    """The fake Checkins from tests/conftest.py, which can be switched off."""
    return checkins


@pytest.fixture
def forfeit(conn, people, group):
    repository.insert_forfeit(conn, group, "push-ups", people["ana"], "2026-09-20T10:00:00+00:00")
    complete(conn, 1, people["ana"], group, "2026-09-23T12:00:00+00:00")
    conn.commit()


def test_leaderboard_is_served_from_the_snapshot_when_checkins_is_down(call, people, group, directory):
    fresh = call(service.get_leaderboard, people["ana"], group, SETTLES.date(), SETTLES)
    directory.down = True
    stale = call(service.get_leaderboard, people["ana"], group, SETTLES.date(), SETTLES)
    assert fresh["membership_stale"] is False
    assert stale["membership_stale"] is True
    assert stale["entries"] == fresh["entries"]


def test_never_seen_group_is_unavailable_when_checkins_is_down(call, people, group, directory):
    directory.down = True
    with pytest.raises(service.GroupInfoUnavailable):
        call(service.get_leaderboard, people["ana"], group, SETTLES.date(), SETTLES)


def test_changes_are_refused_while_membership_is_stale(call, people, group, directory):
    call(service.get_forfeits, people["ana"], group, SETTLES)  # leaves a snapshot
    directory.down = True
    with pytest.raises(service.GroupInfoStale):
        call(service.set_forfeit, people["ana"], group, "push-ups", SETTLES)
    assert call(service.get_forfeits, people["ana"], group, SETTLES)["can_set"] is False


def test_no_settlement_from_a_stale_snapshot(call, conn, people, group, forfeit, directory):
    call(service.get_leaderboard, people["ana"], group, SETTLES.date(), at("2026-09-24T12:00:00+00:00"))
    directory.down = True
    call(service.list_settlements, people["ana"], group, SETTLES)
    # The creation week was settled by the fresh call above; the next one must wait.
    assert "2026-09-21" not in repository.settled_week_starts(conn, group)


def test_no_settlement_while_checkins_has_undelivered_points(call, conn, people, group, forfeit, directory):
    directory.pending.add(group)
    call(service.list_settlements, people["ana"], group, SETTLES)
    assert repository.settled_week_starts(conn, group) == set()
    directory.pending.discard(group)
    call(service.list_settlements, people["ana"], group, SETTLES)
    assert "2026-09-21" in repository.settled_week_starts(conn, group)


def test_revoke_keeps_the_time_checkins_rejected_it(conn, people, group):
    complete(conn, 7, people["ana"], group, "2026-09-23T12:00:00+00:00")
    service.revoke_completion(conn, 7, "2026-09-23T13:00:00+00:00")
    row = conn.execute("SELECT revoked_at FROM point_events WHERE checkin_id = 7").fetchone()
    assert row["revoked_at"] == "2026-09-23T13:00:00+00:00"
