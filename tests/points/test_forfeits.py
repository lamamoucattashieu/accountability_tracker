import sqlite3
from itertools import count

import pytest

from app.config import FORFEIT_MAX_LENGTH
from app.points import repository, service
from tests.factories import make_user
from tests.points.conftest import complete, utc

WEDNESDAY = utc(2026, 9, 30, 12)  # in the week starting 2026-09-28
_ids = count(1)


def test_member_sets_a_trimmed_forfeit_that_applies_from_next_week(call, people, group):
    forfeit = call(service.set_forfeit, people["ana"], group, "  20 push-ups  ", WEDNESDAY)
    assert forfeit["text"] == "20 push-ups"
    assert forfeit["set_by"] == people["ana"]
    assert forfeit["applies_from"] == "2026-10-05"


@pytest.mark.parametrize("text", ["", "   ", None, "x" * (FORFEIT_MAX_LENGTH + 1)])
def test_invalid_forfeit_text_is_rejected(call, people, group, text):
    with pytest.raises(service.InvalidForfeit):
        call(service.set_forfeit, people["ana"], group, text, WEDNESDAY)


def test_forfeit_at_the_length_limit_is_accepted(call, people, group):
    forfeit = call(service.set_forfeit, people["ana"], group, "x" * FORFEIT_MAX_LENGTH, WEDNESDAY)
    assert len(forfeit["text"]) == FORFEIT_MAX_LENGTH


def test_database_also_enforces_the_length_limit(conn, people, group):
    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_forfeit(conn, group, "x" * (FORFEIT_MAX_LENGTH + 1), people["ana"], "t")


def test_forfeits_are_append_only(call, conn, people, group):
    call(service.set_forfeit, people["ana"], group, "push-ups", WEDNESDAY)
    call(service.set_forfeit, people["ben"], group, "cold shower", WEDNESDAY)
    assert [f["text"] for f in repository.list_forfeits(conn, group)] == ["push-ups", "cold shower"]


def test_non_member_cannot_set_a_forfeit(call, conn, group):
    outsider = make_user(conn, "outsider")
    conn.commit()
    with pytest.raises(service.NotGroupMember):
        call(service.set_forfeit, outsider, group, "push-ups", WEDNESDAY)


def test_forfeit_for_missing_group_is_not_found(call, people):
    with pytest.raises(service.GroupNotFound):
        call(service.set_forfeit, people["ana"], 999, "push-ups", WEDNESDAY)


def test_forfeit_changed_mid_week_shows_as_upcoming(call, people, group):
    call(service.set_forfeit, people["ana"], group, "push-ups", utc(2026, 9, 25, 10))  # last week
    call(service.set_forfeit, people["ben"], group, "cold shower", WEDNESDAY)        # this week
    forfeits = call(service.get_forfeits, people["cy"], group, WEDNESDAY)
    assert forfeits["this_week"]["week_start"] == "2026-09-28"
    assert forfeits["this_week"]["forfeit"]["text"] == "push-ups"
    assert forfeits["upcoming"]["week_start"] == "2026-10-05"
    assert forfeits["upcoming"]["forfeit"]["text"] == "cold shower"


def test_no_forfeit_set_yet(call, people, group):
    forfeits = call(service.get_forfeits, people["ana"], group, WEDNESDAY)
    assert forfeits["this_week"]["forfeit"] is None
    assert forfeits["upcoming"]["forfeit"] is None


def test_non_member_cannot_see_forfeits(call, conn, group):
    outsider = make_user(conn, "outsider")
    conn.commit()
    with pytest.raises(service.NotGroupMember):
        call(service.get_forfeits, outsider, group, WEDNESDAY)


# --- only last week's winner sets the forfeit ---

LAST_WEEK = "2026-09-23T12:00:00+00:00"  # in the week before WEDNESDAY's week


def score_last_week(conn, user_id, group, completions):
    for _ in range(completions):
        complete(conn, next(_ids), user_id, group, LAST_WEEK)
    conn.commit()


def test_last_weeks_winner_can_set_the_forfeit(call, conn, people, group):
    score_last_week(conn, people["ana"], group, 2)
    score_last_week(conn, people["ben"], group, 1)
    forfeit = call(service.set_forfeit, people["ana"], group, "push-ups", WEDNESDAY)
    assert forfeit["text"] == "push-ups"


def test_anyone_else_cannot_set_the_forfeit(call, conn, people, group):
    score_last_week(conn, people["ana"], group, 2)
    with pytest.raises(service.NotLastWeeksWinner):
        call(service.set_forfeit, people["ben"], group, "push-ups", WEDNESDAY)
    assert repository.list_forfeits(conn, group) == []


def test_everyone_tied_at_first_can_set_it(call, conn, people, group):
    score_last_week(conn, people["ana"], group, 1)
    score_last_week(conn, people["ben"], group, 1)
    call(service.set_forfeit, people["ana"], group, "push-ups", WEDNESDAY)
    call(service.set_forfeit, people["ben"], group, "cold shower", WEDNESDAY)
    with pytest.raises(service.NotLastWeeksWinner):
        call(service.set_forfeit, people["cy"], group, "dance video", WEDNESDAY)


def test_after_an_empty_week_anyone_can_set_it(call, people, group):
    # Nobody scored last week, so every member is #1: a new crew can always start.
    assert call(service.set_forfeit, people["cy"], group, "push-ups", WEDNESDAY)["text"] == "push-ups"


def test_forfeits_view_says_who_may_set_the_next_one(call, conn, people, group):
    score_last_week(conn, people["ben"], group, 1)
    as_ben = call(service.get_forfeits, people["ben"], group, WEDNESDAY)
    as_ana = call(service.get_forfeits, people["ana"], group, WEDNESDAY)
    assert as_ben["can_set"] is True
    assert as_ana["can_set"] is False
    assert as_ana["setters"] == [{"id": people["ben"], "username": "ben"}]
