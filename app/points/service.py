"""Points & Forfeits domain: the only functions the check-ins domain may call.

This is the seam where a future service split would put an HTTP call or a
published event. Only IDs (and the shared connection, so both domains' writes
commit in one transaction) cross it.
"""

import sqlite3
from datetime import date, datetime, timedelta

from app.auth import service as auth_service
from app.config import FORFEIT_MAX_LENGTH
from app.points import repository, rules
from app.points.rules import monday_of, week_start_for
from app.shared.timeutils import utc_now_iso

POINTS_PER_COMPLETION = 1
# Extra points per goal that hit its weekly target this week and the week before.
STREAK_BONUS = 1


class PointsError(Exception):
    """Base class for every rule violation in the points & forfeits domain."""


class GroupNotFound(PointsError):
    pass


class NotGroupMember(PointsError):
    pass


class InvalidForfeit(PointsError):
    pass


class SettlementBusy(PointsError):
    pass


def _require_member(conn, user_id: int, group_id: int):
    if not auth_service.group_exists(conn, group_id):
        raise GroupNotFound("group not found")
    if not auth_service.is_member(conn, group_id, user_id):
        raise NotGroupMember("not a member of this group")


def record_completion(
    conn, *, checkin_id: int, group_id: int, user_id: int, goal_id: int,
    times_per_week: int, completed_at: str,
) -> None:
    """Record that a check-in counts toward its author's weekly score.

    Called by checkins in the same transaction that creates the check-in.
    times_per_week is the goal's target at this moment, so later goal edits
    don't change how this check-in scores. Idempotent: recording the same
    check-in twice is a no-op (UNIQUE checkin_id).
    """
    week = week_start_for(datetime.fromisoformat(completed_at))
    repository.insert_event(
        conn, checkin_id, group_id, user_id, goal_id, times_per_week,
        week.isoformat(), completed_at,
    )


def revoke_completion(conn, checkin_id: int) -> None:
    """Take back a check-in's points because it was rejected by vote.

    Idempotent: revoking a check-in that was never recorded, or was already
    revoked, is a no-op. Only that check-in's event changes; its week is
    rescored the next time the leaderboard is read.
    """
    repository.revoke_event(conn, checkin_id, utc_now_iso())


def _weekly_ranking(conn, group_id: int, week: date, member_ids: list[int]):
    """Points (with streak bonus) and rank of the given members for one week.

    The one scoring query, shared by the leaderboard and by settlement.
    """
    previous_week = week - timedelta(weeks=1)
    return repository.weekly_ranking(
        conn, group_id, week.isoformat(), previous_week.isoformat(), member_ids,
        POINTS_PER_COMPLETION, STREAK_BONUS,
    )


def get_leaderboard(conn, user_id: int, group_id: int, day: date, now: datetime) -> dict:
    """The ranking for the week containing `day`, for members of the group only.

    points includes streak_bonus: +STREAK_BONUS for each goal that hit its weekly
    target in this week and the previous one. Like the base points, streaks are
    recomputed from the ledger on every read, so a late rejection can end one.
    provisional is true until the week can be settled (votes may still change it).
    """
    _require_member(conn, user_id, group_id)
    ensure_settled(conn, group_id, now)
    week = monday_of(day)
    members = auth_service.list_members(conn, group_id)
    usernames = {member["id"]: member["username"] for member in members}
    rows = _weekly_ranking(conn, group_id, week, list(usernames))
    return {
        "week_start": week.isoformat(),
        "provisional": rules.is_provisional(week, now),
        "entries": [
            {
                "user_id": row["user_id"],
                "username": usernames[row["user_id"]],
                "points": row["points"],
                "streak_bonus": row["streak_bonus"],
                "rank": row["rank"],
            }
            for row in rows
        ],
    }


# --- forfeits ---

def _forfeit_response(forfeit):
    if forfeit is None:
        return None
    return {key: forfeit[key] for key in ("id", "text", "set_by", "created_at")}


def set_forfeit(conn, user_id: int, group_id: int, text: str, now: datetime) -> dict:
    """Add a new forfeit for the group. It applies from next week: this week's is locked."""
    _require_member(conn, user_id, group_id)
    ensure_settled(conn, group_id, now)
    text = (text or "").strip()
    if not 1 <= len(text) <= FORFEIT_MAX_LENGTH:
        raise InvalidForfeit(f"forfeit must be 1-{FORFEIT_MAX_LENGTH} characters")
    forfeit_id = repository.insert_forfeit(
        conn, group_id, text, user_id, now.isoformat(timespec="seconds")
    )
    response = _forfeit_response(repository.get_forfeit(conn, forfeit_id))
    response["applies_from"] = (monday_of(now.date()) + rules.WEEK).isoformat()
    return response


def get_forfeits(conn, user_id: int, group_id: int, now: datetime) -> dict:
    """This week's locked forfeit and the one that will apply from next week."""
    _require_member(conn, user_id, group_id)
    ensure_settled(conn, group_id, now)
    forfeits = [dict(f) for f in repository.list_forfeits(conn, group_id)]
    this_week = week_start_for(now)
    next_week = this_week + rules.WEEK
    return {
        "this_week": {
            "week_start": this_week.isoformat(),
            "forfeit": _forfeit_response(rules.forfeit_for_week(forfeits, this_week)),
        },
        "upcoming": {
            "week_start": next_week.isoformat(),
            "forfeit": _forfeit_response(rules.forfeit_for_week(forfeits, next_week)),
        },
    }


# --- settlement ---

def ensure_settled(conn, group_id: int, now: datetime) -> None:
    """Settle every settleable week of the group that isn't settled yet, oldest first.

    Lazy settlement: there is no scheduler, so the first request after a week
    becomes settleable does it. Each week commits on its own, which is the one
    documented exception to "commits stay in get_db()". To make that safe this
    must run before any other write of the request: it refuses to start inside
    an open transaction, so it can never commit a caller's half-done work.
    """
    if conn.in_transaction:
        raise RuntimeError("ensure_settled must run before any other write in the request")
    created_at = datetime.fromisoformat(auth_service.group_created_at(conn, group_id))
    already_settled = repository.settled_week_starts(conn, group_id)
    for week in rules.settleable_weeks(created_at, now):
        if week.isoformat() not in already_settled:
            _settle_week(conn, group_id, week, now)


def _settle_week(conn, group_id: int, week: date, now: datetime) -> None:
    """Settle one week in its own transaction: the settlement and its assignments commit together.

    BEGIN IMMEDIATE takes SQLite's write lock before reading, so a concurrent
    request settling the same week waits here, then sees the week settled and
    does nothing. UNIQUE (group_id, week_start) is the backstop if that check
    is ever bypassed: the duplicate rolls back and the existing settlement stays.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if exc.sqlite_errorcode == sqlite3.SQLITE_BUSY:  # the busy timeout expired
            raise SettlementBusy("the group is being settled, please try again") from exc
        raise
    try:
        if repository.get_settlement(conn, group_id, week.isoformat()) is None:
            _write_settlement(conn, group_id, week, now)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        if repository.get_settlement(conn, group_id, week.isoformat()) is None:
            raise  # not the duplicate-settlement backstop: a real error
    except BaseException:
        conn.rollback()
        raise


def _write_settlement(conn, group_id: int, week: date, now: datetime) -> None:
    forfeits = [dict(f) for f in repository.list_forfeits(conn, group_id)]
    forfeit = rules.forfeit_for_week(forfeits, week)
    settlement_id = repository.insert_settlement(
        conn, group_id, week.isoformat(),
        None if forfeit is None else forfeit["id"],
        now.isoformat(timespec="seconds"),
    )
    if forfeit is None:
        return  # settled with no assignment, so this week isn't retried on every request
    eligible = rules.eligible_member_ids(auth_service.list_members(conn, group_id), week)
    rows = _weekly_ranking(conn, group_id, week, eligible)
    scores = {row["user_id"]: row["points"] for row in rows}
    for user_id in rules.losers(scores):
        repository.insert_assignment(conn, settlement_id, user_id, scores[user_id])


def list_settlements(conn, user_id: int, group_id: int, now: datetime) -> list[dict]:
    """Settled weeks, newest first, with their losers and each loser's proof status."""
    _require_member(conn, user_id, group_id)
    ensure_settled(conn, group_id, now)
    usernames = {m["id"]: m["username"] for m in auth_service.list_members(conn, group_id)}
    assignments = {}
    for row in repository.list_assignments(conn, group_id):
        assignments.setdefault(row["settlement_id"], []).append(
            _assignment_response(row, usernames, now)
        )
    result = []
    for row in repository.list_settlements(conn, group_id):
        losers = assignments.get(row["id"], [])
        if row["forfeit_id"] is None:
            outcome = "no_forfeit"
        else:
            outcome = "assigned" if losers else "no_loser"
        result.append({
            "week_start": row["week_start"],
            "settled_at": row["settled_at"],
            "forfeit": row["forfeit_text"],
            "outcome": outcome,
            "assignments": losers,
        })
    return result


def _assignment_response(row, usernames: dict, now: datetime) -> dict:
    due = rules.due_at(datetime.fromisoformat(row["settled_at"]))
    proof_at = None if row["proof_at"] is None else datetime.fromisoformat(row["proof_at"])
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": usernames.get(row["user_id"]),
        "score": row["score"],
        "due_at": due.isoformat(),
        "proof_at": row["proof_at"],
        "status": rules.proof_status(due, proof_at, now),
    }
