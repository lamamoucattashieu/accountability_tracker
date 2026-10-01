import sqlite3
import threading
from datetime import date, timedelta
from itertools import count

import pytest

from app.config import settings
from app.db import get_connection
from app.points import repository, service
from tests.factories import make_group, make_user
from tests.points.conftest import backdate_group, backdate_join, complete, utc

WEEK = date(2026, 9, 28)
SETTLES = utc(2026, 10, 7)                    # week end + 48h: Wednesday 00:00 UTC
SECOND = timedelta(seconds=1)
FORFEIT_SET = utc(2026, 9, 25, 10)            # the Friday before WEEK, so it applies to WEEK
_ids = count(1)


def score(conn, user_id, group, points, day="2026-09-30T12:00:00+00:00"):
    """Give user_id `points` completions in the week of `day`; returns their checkin ids.

    Commits like the check-in request that records them would.
    """
    checkin_ids = [complete(conn, next(_ids), user_id, group, day) for _ in range(points)]
    conn.commit()
    return checkin_ids


def week_of(call, viewer, group, now, week=WEEK):
    settlements = call(service.list_settlements, viewer, group, now)
    return next((s for s in settlements if s["week_start"] == week.isoformat()), None)


def losers(settlement):
    return [a["username"] for a in settlement["assignments"]]


@pytest.fixture
def forfeit(call, people, group):
    return call(service.set_forfeit, people["ana"], group, "20 push-ups", FORFEIT_SET)


# --- who loses ---

def test_lowest_scorer_is_assigned_the_forfeit(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 2)
    score(conn, people["ben"], group, 1)
    score(conn, people["cy"], group, 3)
    settled = week_of(call, people["ana"], group, SETTLES)
    assert settled["forfeit"] == "20 push-ups"
    assert settled["outcome"] == "assigned"
    assert losers(settled) == ["ben"]
    assert settled["assignments"][0]["score"] == 1


def test_everyone_tied_at_the_lowest_score_shares_the_forfeit(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 2)
    settled = week_of(call, people["ana"], group, SETTLES)
    assert losers(settled) == ["ben", "cy"]
    first, second = settled["assignments"]
    assert first["id"] != second["id"]  # each uploads their own proof


def test_nobody_loses_when_everyone_is_tied(call, conn, people, group, forfeit):
    for user_id in people.values():
        score(conn, user_id, group, 1)
    settled = week_of(call, people["ana"], group, SETTLES)
    assert (settled["outcome"], settled["assignments"]) == ("no_loser", [])


def test_empty_week_has_no_loser(call, people, group, forfeit):
    settled = week_of(call, people["ana"], group, SETTLES)
    assert (settled["outcome"], settled["assignments"]) == ("no_loser", [])


def test_member_with_zero_checkins_can_lose(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 1)
    score(conn, people["ben"], group, 1)
    settled = week_of(call, people["ana"], group, SETTLES)
    assert losers(settled) == ["cy"]
    assert settled["assignments"][0]["score"] == 0


def test_member_who_joined_mid_week_cannot_lose_it(call, conn, people, group, forfeit):
    dave = make_user(conn, "dave")
    conn.execute(
        "INSERT INTO group_members (group_id, user_id, joined_at) VALUES (?, ?, ?)",
        (group, dave, "2026-09-30T08:00:00+00:00"),
    )
    score(conn, people["ana"], group, 2)
    score(conn, people["ben"], group, 1)
    score(conn, people["cy"], group, 1)
    settled = week_of(call, people["ana"], group, SETTLES)
    assert losers(settled) == ["ben", "cy"]  # dave scored 0 but wasn't eligible


def test_single_member_group_has_no_loser(call, conn, people):
    solo = make_group(conn, people["ana"])
    backdate_group(conn, solo, "2026-09-20T09:00:00+00:00")
    backdate_join(conn, solo, people["ana"], "2026-09-20T09:00:00+00:00")
    conn.commit()
    call(service.set_forfeit, people["ana"], solo, "push-ups", FORFEIT_SET)
    settled = week_of(call, people["ana"], solo, SETTLES)
    assert settled["outcome"] == "no_loser"


def test_creation_week_settles_with_no_losers(call, conn, people, group):
    # A forfeit already locked for the creation week (2026-09-14), but nobody joined before it.
    conn.execute(
        "INSERT INTO forfeits (group_id, text, set_by, created_at) VALUES (?, ?, ?, ?)",
        (group, "push-ups", people["ana"], "2026-09-13T10:00:00+00:00"),
    )
    score(conn, people["ana"], group, 1, day="2026-09-20T12:00:00+00:00")
    settled = week_of(call, people["ana"], group, SETTLES, week=date(2026, 9, 14))
    assert (settled["forfeit"], settled["outcome"]) == ("push-ups", "no_loser")


# --- which forfeit ---

def test_no_forfeit_set_still_settles_the_week(call, conn, people, group):
    score(conn, people["ana"], group, 2)
    settled = week_of(call, people["ana"], group, SETTLES)
    assert settled["forfeit"] is None
    assert settled["outcome"] == "no_forfeit"
    assert settled["assignments"] == []
    assert WEEK.isoformat() in repository.settled_week_starts(conn, group)  # not retried


def test_forfeit_changed_mid_week_does_not_change_that_week(call, conn, people, group, forfeit):
    call(service.set_forfeit, people["ben"], group, "cold shower", utc(2026, 9, 30, 10))
    score(conn, people["ana"], group, 1)
    settled = week_of(call, people["ana"], group, SETTLES)
    assert settled["forfeit"] == "20 push-ups"


# --- when ---

def test_week_is_not_settled_just_before_week_end_plus_48h(call, people, group, forfeit):
    assert week_of(call, people["ana"], group, SETTLES - SECOND) is None


def test_week_is_settled_exactly_at_week_end_plus_48h(call, people, group, forfeit):
    assert week_of(call, people["ana"], group, SETTLES) is not None


def test_settlement_is_final_after_week_end_plus_48h(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 1)
    first = week_of(call, people["ana"], group, SETTLES + SECOND)
    score(conn, people["ben"], group, 5)  # can't happen in practice; shows nothing is recomputed
    later = week_of(call, people["ana"], group, SETTLES + timedelta(days=1))
    assert later["settled_at"] == first["settled_at"]
    assert losers(later) == losers(first)


def test_leaderboard_is_provisional_until_the_week_can_settle(call, people, group):
    before = call(service.get_leaderboard, people["ana"], group, WEEK, SETTLES - SECOND)
    after = call(service.get_leaderboard, people["ana"], group, WEEK, SETTLES)
    assert before["provisional"] is True
    assert after["provisional"] is False


def test_backlog_settles_every_week_since_creation_oldest_first(call, conn, people):
    group = make_group(conn, *people.values())
    backdate_group(conn, group, "2026-09-02T10:00:00+00:00")
    for user_id in people.values():
        backdate_join(conn, group, user_id, "2026-09-02T10:00:00+00:00")
    conn.commit()
    call(service.set_forfeit, people["ana"], group, "push-ups", utc(2026, 9, 2, 11))
    score(conn, people["ana"], group, 1, day="2026-09-16T12:00:00+00:00")
    settlements = call(service.list_settlements, people["ana"], group, SETTLES)
    assert [s["week_start"] for s in settlements] == [
        "2026-09-28", "2026-09-21", "2026-09-14", "2026-09-07", "2026-08-31",
    ]
    by_id = conn.execute("SELECT week_start FROM settlements ORDER BY id").fetchall()
    assert [row["week_start"] for row in by_id][0] == "2026-08-31"  # oldest settled first
    week_14 = next(s for s in settlements if s["week_start"] == "2026-09-14")
    assert losers(week_14) == ["ben", "cy"]


def test_late_rejection_before_settlement_changes_the_loser(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 1)
    bens = score(conn, people["ben"], group, 2)
    score(conn, people["cy"], group, 3)
    # Tuesday after the week: still inside the voting window, both of ben's are rejected.
    for checkin_id in bens:
        service.revoke_completion(conn, checkin_id)
    conn.commit()
    settled = week_of(call, people["ana"], group, SETTLES)
    assert losers(settled) == ["ben"]
    assert settled["assignments"][0]["score"] == 0


# --- idempotency and concurrency ---

def counts(conn, group):
    settlements = conn.execute(
        "SELECT COUNT(*) FROM settlements WHERE group_id = ?", (group,)
    ).fetchone()[0]
    assignments = conn.execute(
        """SELECT COUNT(*) FROM forfeit_assignments
           JOIN settlements ON settlements.id = forfeit_assignments.settlement_id
           WHERE settlements.group_id = ?""",
        (group,),
    ).fetchone()[0]
    return settlements, assignments


def test_settling_twice_changes_nothing(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 2)
    conn.commit()
    call(service.ensure_settled, group, SETTLES)
    first = counts(conn, group)
    call(service.ensure_settled, group, SETTLES + timedelta(hours=1))
    assert counts(conn, group) == first == (3, 2)  # weeks 09-14, 09-21, 09-28; ben and cy lose


def test_unique_constraint_is_the_backstop(call, conn, people, group, forfeit, monkeypatch):
    """Even if the 'already settled?' checks are bypassed, a second settlement is rejected."""
    score(conn, people["ana"], group, 2)
    conn.commit()
    call(service.ensure_settled, group, SETTLES)
    real_get_settlement = repository.get_settlement

    def blind_inside_transaction(conn, group_id, week):
        # The pre-insert check (inside BEGIN IMMEDIATE) misses the existing row, as in a
        # race; the check after the rollback sees the real table.
        return None if conn.in_transaction else real_get_settlement(conn, group_id, week)

    monkeypatch.setattr(repository, "settled_week_starts", lambda conn, group_id: set())
    monkeypatch.setattr(repository, "get_settlement", blind_inside_transaction)
    call(service.ensure_settled, group, SETTLES)  # hits UNIQUE, rolls back, no error
    monkeypatch.undo()
    assert counts(conn, group) == (3, 2)


def test_two_connections_racing_on_the_first_settlement(conn, people, group, forfeit):
    """Two requests settle at the same moment: one wins, the other waits and changes nothing."""
    score(conn, people["ana"], group, 2)
    conn.commit()
    start = threading.Barrier(2)
    errors = []

    def request():
        connection = get_connection()  # its own connection, like a separate request
        try:
            start.wait()
            service.ensure_settled(connection, group, SETTLES)
        except Exception as exc:  # collected so the main thread can assert on it
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=request) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert counts(conn, group) == (3, 2)


def test_busy_timeout_becomes_settlement_busy_not_a_crash(people, group, forfeit):
    holder = get_connection()
    holder.execute("BEGIN IMMEDIATE")  # another request is mid-write and holds the lock
    impatient = sqlite3.connect(settings.db_path, timeout=0.1)
    impatient.row_factory = sqlite3.Row
    try:
        with pytest.raises(service.SettlementBusy):
            service.ensure_settled(impatient, group, SETTLES)
    finally:
        impatient.close()
        holder.rollback()
        holder.close()


def test_settlement_refuses_to_start_inside_an_open_transaction(conn, people, group):
    conn.execute("UPDATE groups SET name = 'renamed' WHERE id = ?", (group,))  # uncommitted work
    with pytest.raises(RuntimeError):
        service.ensure_settled(conn, group, SETTLES)


# --- visibility and proof status ---

def test_assignment_is_due_seven_days_after_settlement(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 1)
    score(conn, people["ben"], group, 1)
    settled = week_of(call, people["ana"], group, SETTLES)
    [assignment] = settled["assignments"]
    assert assignment["due_at"] == (SETTLES + timedelta(days=7)).isoformat()
    assert assignment["status"] == "pending"


def test_missing_proof_becomes_overdue_on_read(call, conn, people, group, forfeit):
    score(conn, people["ana"], group, 1)
    score(conn, people["ben"], group, 1)
    week_of(call, people["ana"], group, SETTLES)
    later = week_of(call, people["ana"], group, SETTLES + timedelta(days=7, seconds=1))
    assert later["assignments"][0]["status"] == "overdue"


def test_non_member_cannot_see_settlements(call, conn, group):
    outsider = make_user(conn, "outsider")
    conn.commit()
    with pytest.raises(service.NotGroupMember):
        call(service.list_settlements, outsider, group, SETTLES)


def test_settlements_of_missing_group_are_not_found(call, people):
    with pytest.raises(service.GroupNotFound):
        call(service.list_settlements, people["ana"], 999, SETTLES)
