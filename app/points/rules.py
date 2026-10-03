"""Points & Forfeits rules as pure functions: plain values in, decisions out.

No database and no clock: callers pass `now`, so every rule is tested with
fixed times. The service orchestrates these with the database.
"""

from datetime import date, datetime, timedelta

from app.config import PROOF_DEADLINE, SETTLEMENT_DELAY
from app.shared.timeutils import monday_of, week_begins_at, week_start_for  # noqa: F401 (re-exported)

WEEK = timedelta(weeks=1)


# --- weeks (the week definition itself lives in app/shared/timeutils.py) ---

def settles_at(week_start: date) -> datetime:
    """Week end + SETTLEMENT_DELAY: from then on no vote can change the week's ranking."""
    return week_begins_at(week_start) + WEEK + SETTLEMENT_DELAY


def is_provisional(week_start: date, now: datetime) -> bool:
    return now < settles_at(week_start)


def settleable_weeks(group_created_at: datetime, now: datetime) -> list[date]:
    """Every week from the group's creation week that can be settled at `now`, oldest first."""
    weeks = []
    week = week_start_for(group_created_at)
    while settles_at(week) <= now:
        weeks.append(week)
        week += WEEK
    return weeks


# --- losers ---

def eligible_member_ids(members: list[dict], week_start: date) -> list[int]:
    """Members who joined before the week started; mid-week joiners can't lose it."""
    starts = week_begins_at(week_start)
    return [m["id"] for m in members if datetime.fromisoformat(m["joined_at"]) < starts]


def losers(scores: dict[int, int]) -> list[int]:
    """Everyone tied at the lowest score, or nobody if all scores are equal (or none exist)."""
    if len(set(scores.values())) < 2:
        return []
    lowest = min(scores.values())
    return sorted(user_id for user_id, score in scores.items() if score == lowest)


# --- forfeits and proof ---

def forfeit_for_week(forfeits: list[dict], week_start: date):
    """The latest forfeit set before the week's Monday 00:00 UTC (it locks when the week starts)."""
    starts = week_begins_at(week_start)
    candidates = [f for f in forfeits if datetime.fromisoformat(f["created_at"]) < starts]
    if not candidates:
        return None
    return max(candidates, key=lambda f: (datetime.fromisoformat(f["created_at"]), f["id"]))


def due_at(settled_at: datetime) -> datetime:
    return settled_at + PROOF_DEADLINE


def proof_status(due: datetime, proof_at, now: datetime) -> str:
    """pending / overdue before proof exists; submitted / late once it does. Never stored."""
    if proof_at is None:
        return "overdue" if now > due else "pending"
    return "late" if proof_at > due else "submitted"
