"""Points & Forfeits domain: the only functions the check-ins domain may call.

This is the seam where a future service split would put an HTTP call or a
published event. Only IDs (and the shared connection, so both domains' writes
commit in one transaction) cross it.
"""

from datetime import date, datetime, timedelta, timezone

from app.points import repository
from app.shared.timeutils import utc_now_iso

POINTS_PER_COMPLETION = 1


# --- week rule: pure functions, no database ---

def monday_of(day: date) -> date:
    """The Monday of the week a calendar day falls in. Weeks run Monday to Sunday."""
    return day - timedelta(days=day.weekday())


def week_start_for(moment: datetime) -> date:
    """The week a moment belongs to, with weeks starting Monday 00:00 UTC."""
    return monday_of(moment.astimezone(timezone.utc).date())


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
