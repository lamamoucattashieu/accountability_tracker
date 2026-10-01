"""Points & Forfeits domain: the only functions the check-ins domain may call.

This is the seam where a future service split would put an HTTP call or a
published event. Only IDs (and the shared connection, so both domains' writes
commit in one transaction) cross it.
"""

from datetime import date, datetime, timedelta

from app.auth import service as auth_service
from app.points import repository
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


def get_leaderboard(conn, user_id: int, group_id: int, day: date) -> dict:
    """The ranking for the week containing `day`, for members of the group only.

    points includes streak_bonus: +STREAK_BONUS for each goal that hit its weekly
    target in this week and the previous one. Like the base points, streaks are
    recomputed from the ledger on every read, so a late rejection can end one.
    """
    if not auth_service.group_exists(conn, group_id):
        raise GroupNotFound("group not found")
    if not auth_service.is_member(conn, group_id, user_id):
        raise NotGroupMember("not a member of this group")
    week = monday_of(day)
    previous_week = week - timedelta(weeks=1)
    members = auth_service.list_members(conn, group_id)
    usernames = {member["id"]: member["username"] for member in members}
    rows = repository.weekly_ranking(
        conn, group_id, week.isoformat(), previous_week.isoformat(), list(usernames),
        POINTS_PER_COMPLETION, STREAK_BONUS,
    )
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
