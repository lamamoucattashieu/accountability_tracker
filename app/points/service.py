"""Points & Forfeits domain: the only functions the check-ins domain may call.

This is the seam where a future service split would put an HTTP call or a
published event. Only IDs (and the shared connection, so both domains' writes
commit in one transaction) cross it.
"""

from datetime import date, datetime, timedelta, timezone

POINTS_PER_COMPLETION = 1


# --- week rule: pure functions, no database ---

def monday_of(day: date) -> date:
    """The Monday of the week a calendar day falls in. Weeks run Monday to Sunday."""
    return day - timedelta(days=day.weekday())


def week_start_for(moment: datetime) -> date:
    """The week a moment belongs to, with weeks starting Monday 00:00 UTC."""
    return monday_of(moment.astimezone(timezone.utc).date())


def revoke_completion(conn, checkin_id: int) -> None:
    """Take back the points a check-in earned, because it was rejected by vote.

    Must be idempotent: revoking a check-in that was never recorded, or was
    already revoked, is a no-op. Phase 4 implements this; until then there are
    no points to revoke.
    """
