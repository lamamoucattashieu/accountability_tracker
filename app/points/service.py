"""Points & Forfeits domain: the only functions the check-ins domain may call.

This is the seam where a future service split would put an HTTP call or a
published event. Only IDs (and the shared connection, so both domains' writes
commit in one transaction) cross it.
"""

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


def get_leaderboard(conn, user_id: int, group_id: int, day: date) -> dict:
    """The ranking for the week containing `day`, for members of the group only.

    points includes streak_bonus: +STREAK_BONUS for each goal that hit its weekly
    target in this week and the previous one. Like the base points, streaks are
    recomputed from the ledger on every read, so a late rejection can end one.
    """
    _require_member(conn, user_id, group_id)
    week = monday_of(day)
    members = auth_service.list_members(conn, group_id)
    usernames = {member["id"]: member["username"] for member in members}
    rows = _weekly_ranking(conn, group_id, week, list(usernames))
    return {
        "week_start": week.isoformat(),
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
