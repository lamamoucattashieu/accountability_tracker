from datetime import date
from itertools import count

import pytest

from app.points import service
from tests.factories import make_group, make_user

THIS_WEEK = date(2026, 9, 28)
NEXT_WEEK = date(2026, 10, 5)
_checkin_ids = count(1)


@pytest.fixture
def users(conn):
    return {name: make_user(conn, name) for name in ("alice", "bob", "carol")}


@pytest.fixture
def group_id(conn, users):
    return make_group(conn, *users.values())


@pytest.fixture
def complete(conn, group_id):
    """Record a completion and return its checkin_id."""
    def _complete(user_id, goal_id, at="2026-09-30T12:00:00+00:00", times_per_week=3):
        checkin_id = next(_checkin_ids)
        service.record_completion(
            conn, checkin_id=checkin_id, group_id=group_id, user_id=user_id,
            goal_id=goal_id, times_per_week=times_per_week, completed_at=at,
        )
        return checkin_id
    return _complete


def board(conn, viewer, group_id, day=THIS_WEEK):
    """The leaderboard as (username, points, rank) tuples, for short assertions."""
    result = service.get_leaderboard(conn, viewer, group_id, day)
    return [(e["username"], e["points"], e["rank"]) for e in result["entries"]]


# --- scoring rule ---

def test_each_completion_scores_one_point(conn, users, group_id, complete):
    complete(users["alice"], goal_id=1)
    complete(users["alice"], goal_id=1)
    assert board(conn, users["alice"], group_id)[0] == ("alice", 2, 1)


def test_only_the_first_times_per_week_completions_score(conn, users, group_id, complete):
    for _ in range(5):
        complete(users["alice"], goal_id=1, times_per_week=3)
    assert board(conn, users["alice"], group_id)[0] == ("alice", 3, 1)


def test_the_cap_is_per_goal(conn, users, group_id, complete):
    complete(users["alice"], goal_id=1, times_per_week=1)
    complete(users["alice"], goal_id=1, times_per_week=1)
    complete(users["alice"], goal_id=2, times_per_week=1)
    assert board(conn, users["alice"], group_id)[0] == ("alice", 2, 1)


def test_rejected_completion_frees_its_slot_for_a_later_one(conn, users, group_id, complete):
    first = complete(users["alice"], goal_id=1, at="2026-09-29T10:00:00+00:00", times_per_week=1)
    complete(users["alice"], goal_id=1, at="2026-09-30T10:00:00+00:00", times_per_week=1)
    assert board(conn, users["alice"], group_id)[0] == ("alice", 1, 1)
    service.revoke_completion(conn, first)
    assert board(conn, users["alice"], group_id)[0] == ("alice", 1, 1)  # the second one now scores


def test_revoked_completion_without_a_replacement_loses_its_point(conn, users, group_id, complete):
    checkin_id = complete(users["alice"], goal_id=1)
    complete(users["alice"], goal_id=1)
    service.revoke_completion(conn, checkin_id)
    assert board(conn, users["alice"], group_id)[0] == ("alice", 1, 1)


def test_each_completion_keeps_the_target_it_was_made_under(conn, users, group_id, complete):
    # Target 3 for the first three, then the goal is edited down to 1.
    for _ in range(3):
        complete(users["alice"], goal_id=1, times_per_week=3)
    complete(users["alice"], goal_id=1, times_per_week=1)  # 4th completion > target 1
    assert board(conn, users["alice"], group_id)[0] == ("alice", 3, 1)


# --- weeks ---

def test_completion_just_before_and_after_the_boundary(conn, users, group_id, complete):
    complete(users["alice"], goal_id=1, at="2026-10-04T23:59:59+00:00")
    complete(users["bob"], goal_id=2, at="2026-10-05T00:00:00+00:00")
    assert board(conn, users["alice"], group_id, THIS_WEEK)[0] == ("alice", 1, 1)
    assert board(conn, users["alice"], group_id, NEXT_WEEK)[0] == ("bob", 1, 1)


def test_any_day_selects_its_whole_week(conn, users, group_id, complete):
    complete(users["alice"], goal_id=1, at="2026-09-28T08:00:00+00:00")
    result = service.get_leaderboard(conn, users["alice"], group_id, date(2026, 10, 4))
    assert result["week_start"] == "2026-09-28"
    assert result["entries"][0]["points"] == 1


def test_revocation_after_the_week_ended_changes_that_week_only(conn, users, group_id, complete):
    old = complete(users["alice"], goal_id=1, at="2026-10-04T22:00:00+00:00")
    complete(users["alice"], goal_id=1, at="2026-10-05T09:00:00+00:00")
    service.revoke_completion(conn, old)  # the vote lands in the next week
    assert board(conn, users["alice"], group_id, THIS_WEEK)[0] == ("alice", 0, 1)
    assert board(conn, users["alice"], group_id, NEXT_WEEK)[0] == ("alice", 1, 1)


# --- ranking ---

def test_ties_share_a_rank_and_leave_a_gap(conn, users, group_id, complete):
    complete(users["alice"], goal_id=1)
    complete(users["bob"], goal_id=2)
    assert board(conn, users["alice"], group_id) == [
        ("alice", 1, 1),
        ("bob", 1, 1),
        ("carol", 0, 3),
    ]


def test_empty_week_shows_every_member_tied_at_zero(conn, users, group_id):
    assert board(conn, users["alice"], group_id) == [
        ("alice", 0, 1),
        ("bob", 0, 1),
        ("carol", 0, 1),
    ]


def test_zero_point_member_is_shown_last(conn, users, group_id, complete):
    complete(users["bob"], goal_id=2)
    complete(users["carol"], goal_id=3)
    complete(users["carol"], goal_id=3)
    assert board(conn, users["alice"], group_id) == [
        ("carol", 2, 1),
        ("bob", 1, 2),
        ("alice", 0, 3),
    ]


def test_ranking_with_several_members_and_weeks(conn, users, group_id, complete):
    complete(users["alice"], goal_id=1, at="2026-09-29T10:00:00+00:00")
    complete(users["alice"], goal_id=1, at="2026-09-30T10:00:00+00:00")
    complete(users["bob"], goal_id=2, at="2026-10-01T10:00:00+00:00")
    complete(users["bob"], goal_id=2, at="2026-10-06T10:00:00+00:00")  # next week
    complete(users["bob"], goal_id=2, at="2026-10-07T10:00:00+00:00")  # next week
    complete(users["carol"], goal_id=3, at="2026-10-08T10:00:00+00:00")  # next week
    assert board(conn, users["alice"], group_id, THIS_WEEK) == [
        ("alice", 2, 1),
        ("bob", 1, 2),
        ("carol", 0, 3),
    ]
    assert board(conn, users["alice"], group_id, NEXT_WEEK) == [
        ("bob", 2, 1),
        ("carol", 1, 2),
        ("alice", 0, 3),
    ]


def test_other_groups_points_are_not_counted(conn, users, group_id, complete):
    other_group = make_group(conn, users["alice"])
    service.record_completion(
        conn, checkin_id=next(_checkin_ids), group_id=other_group, user_id=users["alice"],
        goal_id=9, times_per_week=3, completed_at="2026-09-30T12:00:00+00:00",
    )
    assert board(conn, users["alice"], group_id)[0] == ("alice", 0, 1)


# --- access ---

def test_non_member_cannot_see_the_leaderboard(conn, group_id):
    outsider = make_user(conn, "outsider")
    with pytest.raises(service.NotGroupMember):
        service.get_leaderboard(conn, outsider, group_id, THIS_WEEK)


def test_leaderboard_of_missing_group_is_not_found(conn, users):
    with pytest.raises(service.GroupNotFound):
        service.get_leaderboard(conn, users["alice"], 999, THIS_WEEK)


# --- streak bonus ---

LAST_WEEK_DAY = "2026-09-22T12:00:00+00:00"   # in the week of 2026-09-21
THIS_WEEK_DAY = "2026-09-30T12:00:00+00:00"   # in the week of 2026-09-28


def hit(complete, user_id, goal_id, at, times_per_week=2):
    """Complete a goal's full weekly target within the week of `at`."""
    return [complete(user_id, goal_id, at=at, times_per_week=times_per_week)
            for _ in range(times_per_week)]


def entry(conn, viewer, group_id, username, day=THIS_WEEK):
    result = service.get_leaderboard(conn, viewer, group_id, day)
    return next(e for e in result["entries"] if e["username"] == username)


def test_target_hit_two_weeks_in_a_row_earns_the_bonus(conn, users, group_id, complete):
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    alice = entry(conn, users["alice"], group_id, "alice")
    assert alice["streak_bonus"] == 1
    assert alice["points"] == 3  # 2 completions + 1 bonus


def test_first_week_of_a_streak_earns_no_bonus(conn, users, group_id, complete):
    hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    assert entry(conn, users["alice"], group_id, "alice")["streak_bonus"] == 0


def test_streak_needs_this_week_hit_too(conn, users, group_id, complete):
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    complete(users["alice"], 1, at=THIS_WEEK_DAY, times_per_week=2)  # 1 of 2: not hit
    alice = entry(conn, users["alice"], group_id, "alice")
    assert (alice["points"], alice["streak_bonus"]) == (1, 0)


def test_partial_last_week_breaks_the_streak(conn, users, group_id, complete):
    complete(users["alice"], 1, at=LAST_WEEK_DAY, times_per_week=2)  # 1 of 2
    hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    assert entry(conn, users["alice"], group_id, "alice")["streak_bonus"] == 0


def test_bonus_stays_flat_on_long_streaks(conn, users, group_id, complete):
    hit(complete, users["alice"], 1, "2026-09-15T12:00:00+00:00")
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    assert entry(conn, users["alice"], group_id, "alice")["streak_bonus"] == 1


def test_each_streaking_goal_earns_its_own_bonus(conn, users, group_id, complete):
    for goal_id in (1, 2):
        hit(complete, users["alice"], goal_id, LAST_WEEK_DAY)
        hit(complete, users["alice"], goal_id, THIS_WEEK_DAY)
    alice = entry(conn, users["alice"], group_id, "alice")
    assert (alice["points"], alice["streak_bonus"]) == (6, 2)


def test_streak_is_per_goal_not_per_member(conn, users, group_id, complete):
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    hit(complete, users["alice"], 2, THIS_WEEK_DAY)  # a different goal this week
    assert entry(conn, users["alice"], group_id, "alice")["streak_bonus"] == 0


def test_late_rejection_in_last_week_removes_this_weeks_bonus(conn, users, group_id, complete):
    last_week = hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    service.revoke_completion(conn, last_week[0])  # last week drops to 1 of 2
    alice = entry(conn, users["alice"], group_id, "alice")
    assert (alice["points"], alice["streak_bonus"]) == (2, 0)


def test_rejection_this_week_removes_points_and_bonus(conn, users, group_id, complete):
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    this_week = hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    service.revoke_completion(conn, this_week[1])
    alice = entry(conn, users["alice"], group_id, "alice")
    assert (alice["points"], alice["streak_bonus"]) == (1, 0)


def test_extra_completion_replaces_a_rejected_one_and_keeps_the_streak(
    conn, users, group_id, complete
):
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    this_week = hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    complete(users["alice"], 1, at=THIS_WEEK_DAY, times_per_week=2)  # a 3rd, beyond the target
    service.revoke_completion(conn, this_week[0])
    alice = entry(conn, users["alice"], group_id, "alice")
    assert (alice["points"], alice["streak_bonus"]) == (3, 1)


def test_the_latest_checkins_target_decides_whether_the_week_was_hit(
    conn, users, group_id, complete
):
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    # This week: one completion under target 3, then the goal is edited down to 1.
    complete(users["alice"], 1, at="2026-09-29T09:00:00+00:00", times_per_week=3)
    complete(users["alice"], 1, at="2026-09-30T09:00:00+00:00", times_per_week=1)
    assert entry(conn, users["alice"], group_id, "alice")["streak_bonus"] == 1


def test_streak_bonus_can_break_a_tie(conn, users, group_id, complete):
    hit(complete, users["alice"], 1, LAST_WEEK_DAY)
    hit(complete, users["alice"], 1, THIS_WEEK_DAY)
    for _ in range(2):
        complete(users["bob"], 2, at=THIS_WEEK_DAY, times_per_week=2)
    assert board(conn, users["alice"], group_id) == [
        ("alice", 3, 1),
        ("bob", 2, 2),
        ("carol", 0, 3),
    ]
