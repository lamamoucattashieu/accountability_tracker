import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.checkins import repository, service
from app.config import DEFAULT_NUDGE_MESSAGE, NUDGE_MAX_LENGTH
from tests.images import image_file

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)  # a Wednesday
TODAY = "2026-09-30T08:00:00+00:00"
EARLIER_THIS_WEEK = "2026-09-28T09:00:00+00:00"  # Monday
LAST_WEEK = "2026-09-25T09:00:00+00:00"


def post_at(conn, user_id, goal_id, created_at, status="accepted"):
    """A check-in at a chosen time (the service stamps the real clock, so it's moved after)."""
    checkin = service.create_checkin(conn, user_id, goal_id, image_file(), None)
    conn.execute(
        "UPDATE checkins SET created_at = ?, status = ? WHERE id = ?",
        (created_at, status, checkin["id"]),
    )
    return checkin["id"]


def progress_of(conn, viewer, group_id, member, now=NOW):
    rows = service.group_progress(conn, viewer, group_id, now)
    return next(row for row in rows if row["user_id"] == member)


# --- the rule as pure functions ---

@pytest.mark.parametrize(
    "goal_targets, finished",
    [
        ([], False),                 # no goals: not finished, so no way to dodge nudges
        ([(3, 3), (1, 1)], True),
        ([(4, 3)], True),
        ([(2, 3)], False),
        ([(3, 3), (0, 2)], False),   # every goal must hit its target
    ],
)
def test_finished_the_week(goal_targets, finished):
    assert service.finished_the_week(goal_targets) is finished


@pytest.mark.parametrize(
    "finished, posted_today, nudgeable",
    [(False, False, True), (False, True, False), (True, False, False), (True, True, False)],
)
def test_can_be_nudged(finished, posted_today, nudgeable):
    assert service.can_be_nudged(finished, posted_today) is nudgeable


# --- who can be nudged ---

def test_member_with_no_goals_can_be_nudged(conn, alice, bob, group_id):
    assert progress_of(conn, alice, group_id, bob)["can_nudge"] is True


def test_behind_and_silent_today_can_be_nudged(conn, alice, bob, group_id, goal):
    post_at(conn, alice, goal["id"], EARLIER_THIS_WEEK)  # 1 of 3
    row = progress_of(conn, bob, group_id, alice)
    assert (row["finished_week"], row["posted_today"], row["can_nudge"]) == (False, False, True)


def test_posting_today_protects_from_a_nudge(conn, alice, bob, group_id, goal):
    post_at(conn, alice, goal["id"], TODAY)
    row = progress_of(conn, bob, group_id, alice)
    assert (row["posted_today"], row["can_nudge"]) == (True, False)


def test_finishing_the_week_protects_from_a_nudge(conn, alice, bob, group_id):
    small_goal = service.create_goal(conn, alice, group_id, "Read", None, 1)
    post_at(conn, alice, small_goal["id"], EARLIER_THIS_WEEK)
    row = progress_of(conn, bob, group_id, alice)
    assert (row["finished_week"], row["can_nudge"]) == (True, False)


def test_rejected_and_last_weeks_checkins_do_not_count(conn, alice, bob, group_id):
    small_goal = service.create_goal(conn, alice, group_id, "Read", None, 1)
    post_at(conn, alice, small_goal["id"], EARLIER_THIS_WEEK, status="rejected")
    post_at(conn, alice, small_goal["id"], LAST_WEEK)
    assert progress_of(conn, bob, group_id, alice)["finished_week"] is False


def test_you_cannot_nudge_yourself_in_progress(conn, alice, group_id):
    assert progress_of(conn, alice, group_id, alice)["can_nudge"] is False


# --- sending ---

def test_blank_nudge_sends_the_default_message(conn, alice, bob, group_id):
    nudge = service.send_nudge(conn, alice, group_id, bob, "  ", NOW)
    assert nudge["message"] == DEFAULT_NUDGE_MESSAGE


def test_nudger_writes_their_own_message(conn, alice, bob, group_id):
    nudge = service.send_nudge(conn, alice, group_id, bob, "  the gym misses you  ", NOW)
    assert nudge["message"] == "the gym misses you"


def test_nudge_message_over_the_limit_is_rejected(conn, alice, bob, group_id):
    with pytest.raises(service.InvalidNudge):
        service.send_nudge(conn, alice, group_id, bob, "x" * (NUDGE_MAX_LENGTH + 1), NOW)


def test_one_nudge_per_person_per_day(conn, alice, bob, group_id):
    service.send_nudge(conn, alice, group_id, bob, None, NOW)
    with pytest.raises(service.AlreadyNudged):
        service.send_nudge(conn, alice, group_id, bob, "again!", NOW + timedelta(hours=1))
    row = progress_of(conn, alice, group_id, bob)
    assert (row["nudged_today"], row["can_nudge"]) == (True, False)
    service.send_nudge(conn, alice, group_id, bob, None, NOW + timedelta(days=1))  # a new day


def test_cannot_nudge_someone_on_track(conn, alice, bob, group_id, goal):
    post_at(conn, alice, goal["id"], TODAY)
    with pytest.raises(service.NotNudgeable):
        service.send_nudge(conn, bob, group_id, alice, None, NOW)


def test_cannot_nudge_yourself(conn, alice, group_id):
    with pytest.raises(service.CannotNudgeYourself):
        service.send_nudge(conn, alice, group_id, alice, None, NOW)


def test_cannot_nudge_someone_outside_the_group(conn, alice, outsider, group_id):
    with pytest.raises(service.MemberNotFound):
        service.send_nudge(conn, alice, group_id, outsider, None, NOW)


def test_non_member_cannot_nudge_or_see_progress(conn, outsider, bob, group_id):
    with pytest.raises(service.NotGroupMember):
        service.send_nudge(conn, outsider, group_id, bob, None, NOW)
    with pytest.raises(service.NotGroupMember):
        service.group_progress(conn, outsider, group_id, NOW)


def test_database_also_blocks_self_nudges(conn, alice, group_id):
    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_nudge(conn, group_id, alice, alice, "hi", "2026-09-30", "t")


# --- receiving ---

def test_recipient_sees_todays_nudges_only(conn, alice, bob, group_id):
    service.send_nudge(conn, alice, group_id, bob, "yesterday's nudge", NOW - timedelta(days=1))
    service.send_nudge(conn, alice, group_id, bob, "today's nudge", NOW)
    nudges = service.my_nudges_today(conn, bob, group_id, NOW)
    assert [(n["nudger_id"], n["message"]) for n in nudges] == [(alice, "today's nudge")]
    assert service.my_nudges_today(conn, alice, group_id, NOW) == []
