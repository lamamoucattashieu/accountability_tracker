"""Points & Forfeits domain: the only functions the check-ins domain may call.

Points learns about groups only through the group_directory port (one call per
request, cached in group_snapshots), and about completions only through
record_completion / revoke_completion. Only ids, timestamps and times_per_week
cross the seam.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.config import FORFEIT_MAX_LENGTH
from app.points import repository, rules
from app.points.group_directory import CheckinsUnavailable, get_directory
from app.points.rules import monday_of, week_start_for
from app.shared import uploads
from app.shared.database import is_duplicate_key, is_lock_timeout
from app.shared.timeutils import utc_now_iso

logger = logging.getLogger(__name__)

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


class NotLastWeeksWinner(PointsError):
    pass


class SettlementBusy(PointsError):
    pass


class AssignmentNotFound(PointsError):
    pass


class NotAssignee(PointsError):
    pass


class ProofAlreadySubmitted(PointsError):
    pass


class ProofNotFound(PointsError):
    pass


class GroupInfoUnavailable(PointsError):
    """Checkins can't be reached and Points has never seen this group."""


class GroupInfoStale(PointsError):
    """Checkins can't be reached, so a change can't be checked against current members."""


@dataclass
class Group:
    """What Points knows about a group, from Checkins or from the last snapshot."""
    id: int
    created_at: str
    members: list  # [{"id": int, "joined_at": iso}]
    pending_points_sync: bool
    stale: bool  # True = served from the snapshot because Checkins was unreachable

    @property
    def member_ids(self) -> list[int]:
        return [member["id"] for member in self.members]


def _load_group(conn, group_id: int) -> Group:
    """Ask Checkins about the group, falling back to the last snapshot (cache-aside).

    A fresh answer is saved and committed straight away: it is a cache, not part
    of the request's own work, so it is the second documented exception to
    "commits stay in get_db()". Every caller runs this before its own writes.
    """
    try:
        data = get_directory().fetch_group(group_id)
    except CheckinsUnavailable:
        snapshot = repository.get_group_snapshot(conn, group_id)
        if snapshot is None:
            raise GroupInfoUnavailable("group info is unavailable right now, try again shortly")
        logger.warning("checkins unavailable, serving group %s from its snapshot", group_id)
        return Group(snapshot["id"], snapshot["created_at"], snapshot["members"],
                     snapshot["pending_points_sync"], stale=True)
    if data is None:
        raise GroupNotFound("group not found")
    try:
        repository.save_group_snapshot(conn, data, utc_now_iso())
        conn.commit()
    except Exception as exc:  # e.g. a lock timeout: the cache can wait
        if not is_lock_timeout(exc):
            raise
        conn.rollback()
        logger.warning("could not save the snapshot of group %s", group_id)
    return Group(data["id"], data["created_at"], data["members"],
                 data["pending_points_sync"], stale=False)


def _require_member(conn, user_id: int, group_id: int) -> Group:
    group = _load_group(conn, group_id)
    if user_id not in group.member_ids:
        raise NotGroupMember("not a member of this group")
    return group


def _require_fresh(group: Group) -> None:
    """Changes need current membership: refuse them while only the snapshot is available."""
    if group.stale:
        raise GroupInfoStale("can't confirm the group's members right now, try again shortly")


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


def revoke_completion(conn, checkin_id: int, revoked_at: str = None) -> None:
    """Take back a check-in's points because it was rejected by vote.

    revoked_at is when Checkins rejected it (it may be delivered later); it
    defaults to now. Idempotent: revoking a check-in that was never recorded, or
    was already revoked, is a no-op. Only that check-in's event changes; its
    week is rescored the next time the leaderboard is read.
    """
    repository.revoke_event(conn, checkin_id, revoked_at or utc_now_iso())


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
    Entries carry user ids only: the UI takes names from Checkins, like the feed.
    """
    group = _require_member(conn, user_id, group_id)
    ensure_settled(conn, group_id, now, group)
    week = monday_of(day)
    rows = _weekly_ranking(conn, group_id, week, group.member_ids)
    return {
        "week_start": week.isoformat(),
        "provisional": rules.is_provisional(week, now),
        "membership_stale": group.stale,
        "entries": [
            {
                "user_id": row["user_id"],
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


def _last_weeks_winners(conn, group: Group, now: datetime) -> list[int]:
    """Everyone ranked #1 last week, ties included (RANK gives them all rank 1).

    Uses last week's ranking as it stands now, from the same scoring query as
    the leaderboard. In a week where nobody scored, every member is #1, so a
    new crew can always set its first forfeit.
    """
    last_week = week_start_for(now) - rules.WEEK
    ranking = _weekly_ranking(conn, group.id, last_week, group.member_ids)
    return [row["user_id"] for row in ranking if row["rank"] == 1]


def set_forfeit(conn, user_id: int, group_id: int, text: str, now: datetime) -> dict:
    """Last week's winner adds a new forfeit. It applies from next week: this week's is locked."""
    group = _require_member(conn, user_id, group_id)
    _require_fresh(group)
    ensure_settled(conn, group_id, now, group)
    if user_id not in _last_weeks_winners(conn, group, now):
        raise NotLastWeeksWinner("only last week's winner can set the forfeit")
    text = (text or "").strip()
    if not 1 <= len(text) <= FORFEIT_MAX_LENGTH:
        raise InvalidForfeit(f"forfeit must be 1-{FORFEIT_MAX_LENGTH} characters")
    forfeit_id = repository.insert_forfeit(
        conn, group_id, text, user_id, now.isoformat(timespec="seconds")
    )
    response = _forfeit_response(repository.get_forfeit(conn, forfeit_id))
    response["applies_from"] = (week_start_for(now) + rules.WEEK).isoformat()
    return response


def get_forfeits(conn, user_id: int, group_id: int, now: datetime) -> dict:
    """This week's locked forfeit, the one that will apply from next week, and who may set it."""
    group = _require_member(conn, user_id, group_id)
    ensure_settled(conn, group_id, now, group)
    forfeits = [dict(f) for f in repository.list_forfeits(conn, group_id)]
    this_week = week_start_for(now)
    next_week = this_week + rules.WEEK
    winners = _last_weeks_winners(conn, group, now)
    return {
        "can_set": user_id in winners and not group.stale,
        "membership_stale": group.stale,
        "setters": [{"id": winner} for winner in winners],
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

def ensure_settled(conn, group_id: int, now: datetime, group: Group = None) -> None:
    """Settle every settleable week of the group that isn't settled yet, oldest first.

    Lazy settlement: there is no scheduler, so the first request after a week
    becomes settleable does it. Each week commits on its own, which is the one
    documented exception to "commits stay in get_db()". To make that safe this
    must run before any other write of the request: it refuses to start inside
    an open transaction, so it can never commit a caller's half-done work.

    A settled week is final, so it never settles from incomplete data: not from
    a stale snapshot, and not while Checkins still has points changes for the
    group that haven't reached Points yet.
    """
    if conn.in_transaction:
        raise RuntimeError("ensure_settled must run before any other write in the request")
    if group is None:
        group = _load_group(conn, group_id)
    if group.stale or group.pending_points_sync:
        return
    created_at = datetime.fromisoformat(group.created_at)
    already_settled = repository.settled_week_starts(conn, group_id)
    for week in rules.settleable_weeks(created_at, now):
        if week.isoformat() not in already_settled:
            _settle_week(conn, group, week, now)


def _settle_week(conn, group: Group, week: date, now: datetime) -> None:
    """Settle one week in its own transaction: the settlement and its assignments commit together.

    The group's settlement lock (sp_getapplock) is taken before reading, so a
    concurrent request settling the same week waits here, then sees the week
    settled and does nothing; if it waits longer than the lock timeout it gets
    SettlementBusy. UNIQUE (group_id, week_start) is the backstop if that check
    is ever bypassed: the duplicate rolls back and the existing settlement stays.
    """
    try:
        if not repository.lock_group_for_settlement(conn, group.id):
            raise SettlementBusy("the group is being settled, please try again")
        if repository.get_settlement(conn, group.id, week.isoformat()) is None:
            _write_settlement(conn, group, week, now)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if not is_duplicate_key(exc, "UQ_settlements_group_week"):
            raise  # not the duplicate-settlement backstop: a real error
    except BaseException:
        conn.rollback()
        raise


def _write_settlement(conn, group: Group, week: date, now: datetime) -> None:
    forfeits = [dict(f) for f in repository.list_forfeits(conn, group.id)]
    forfeit = rules.forfeit_for_week(forfeits, week)
    settlement_id = repository.insert_settlement(
        conn, group.id, week.isoformat(),
        None if forfeit is None else forfeit["id"],
        now.isoformat(timespec="seconds"),
    )
    if forfeit is None:
        return  # settled with no assignment, so this week isn't retried on every request
    eligible = rules.eligible_member_ids(group.members, week)
    rows = _weekly_ranking(conn, group.id, week, eligible)
    scores = {row["user_id"]: row["points"] for row in rows}
    for user_id in rules.losers(scores):
        repository.insert_assignment(conn, settlement_id, user_id, scores[user_id])


def list_settlements(conn, user_id: int, group_id: int, now: datetime) -> list[dict]:
    """Settled weeks, newest first, with their losers and each loser's proof status."""
    group = _require_member(conn, user_id, group_id)
    ensure_settled(conn, group_id, now, group)
    assignments = {}
    for row in repository.list_assignments(conn, group_id):
        assignments.setdefault(row["settlement_id"], []).append(_assignment_response(row, now))
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


def _assignment_response(row, now: datetime) -> dict:
    due = rules.due_at(datetime.fromisoformat(row["settled_at"]))
    proof_at = None if row["proof_at"] is None else datetime.fromisoformat(row["proof_at"])
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "score": row["score"],
        "due_at": due.isoformat(),
        "proof_at": row["proof_at"],
        "status": rules.proof_status(due, proof_at, now),
    }


# --- proof ---

def _get_assignment_for_member(conn, user_id: int, assignment_id: int):
    assignment = repository.get_assignment(conn, assignment_id)
    if assignment is None:
        raise AssignmentNotFound("forfeit assignment not found")
    group = _require_member(conn, user_id, assignment["group_id"])
    return assignment, group


def submit_proof(conn, user_id: int, assignment_id: int, photo_file, now: datetime) -> dict:
    """The assigned member uploads photo proof, once. Late proof is accepted and shown as late."""
    assignment, group = _get_assignment_for_member(conn, user_id, assignment_id)
    _require_fresh(group)
    ensure_settled(conn, assignment["group_id"], now, group)
    if assignment["user_id"] != user_id:
        raise NotAssignee("only the member assigned this forfeit can upload proof")
    if assignment["proof_at"] is not None:
        raise ProofAlreadySubmitted("proof was already uploaded")
    photo, photo_type = uploads.validate_image(photo_file)
    # The photo is stored in the assignment's row: stored together with proof_at, or not at all.
    if not repository.set_proof(conn, assignment_id, photo, photo_type, now.isoformat(timespec="seconds")):
        raise ProofAlreadySubmitted("proof was already uploaded")  # a simultaneous upload won
    return _assignment_response(repository.get_assignment(conn, assignment_id), now)


def get_proof_photo(conn, user_id: int, assignment_id: int, now: datetime) -> tuple[bytes, str]:
    """Access-control gate in front of the proof photo: group members only."""
    assignment, group = _get_assignment_for_member(conn, user_id, assignment_id)
    ensure_settled(conn, assignment["group_id"], now, group)
    photo = repository.get_proof_photo(conn, assignment_id)
    if photo is None:
        raise ProofNotFound("no proof uploaded yet")
    return photo["proof_photo"], photo["proof_type"]
