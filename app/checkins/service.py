import logging
import sqlite3
from datetime import datetime, timezone

from app.auth import service as auth_service
from app.checkins import repository
from app.config import VOTING_WINDOW
from app.points import service as points_service
from app.shared import uploads
from app.shared.timeutils import utc_now_iso

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 500
MIN_TIMES_PER_WEEK = 1
MAX_TIMES_PER_WEEK = 7
CAPTION_MAX_LENGTH = 200
FEED_LIMIT = 50


class CheckinsError(Exception):
    """Base class for every rule violation in the goals & check-ins domain."""


class GroupNotFound(CheckinsError):
    pass


class GoalNotFound(CheckinsError):
    pass


class NotGroupMember(CheckinsError):
    pass


class NotGoalOwner(CheckinsError):
    pass


class GoalArchived(CheckinsError):
    pass


class InvalidGoal(CheckinsError):
    pass


class CheckinNotFound(CheckinsError):
    pass


class InvalidCheckin(CheckinsError):
    pass


class PhotoMissing(CheckinsError):
    pass


class CannotVoteOwnCheckin(CheckinsError):
    pass


class CheckinAlreadyRejected(CheckinsError):
    pass


class VotingClosed(CheckinsError):
    pass


class AlreadyVoted(CheckinsError):
    pass


# --- rejection rule: pure functions, no database ---

def votes_needed(eligible_voters: int) -> int:
    """A strict majority of the members who may vote (everyone except the author)."""
    return eligible_voters // 2 + 1


def is_rejected(reject_votes: int, eligible_voters: int) -> bool:
    if eligible_voters == 0:
        return False  # solo group: nobody else can vote, so nothing is ever rejected
    return reject_votes >= votes_needed(eligible_voters)


def is_voting_open(posted_at: datetime, now: datetime) -> bool:
    return now < posted_at + VOTING_WINDOW


def _validate_title(title) -> str:
    if not isinstance(title, str):
        raise InvalidGoal("title is required")
    title = title.strip()
    if not title:
        raise InvalidGoal("title cannot be empty")
    if len(title) > TITLE_MAX_LENGTH:
        raise InvalidGoal(f"title must be at most {TITLE_MAX_LENGTH} characters")
    return title


def _validate_description(description):
    if description is None:
        return None
    description = description.strip()
    if not description:
        return None
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise InvalidGoal(
            f"description must be at most {DESCRIPTION_MAX_LENGTH} characters"
        )
    return description


def _validate_times_per_week(times_per_week) -> int:
    if not isinstance(times_per_week, int) or isinstance(times_per_week, bool):
        raise InvalidGoal("times_per_week must be an integer")
    if not MIN_TIMES_PER_WEEK <= times_per_week <= MAX_TIMES_PER_WEEK:
        raise InvalidGoal(
            f"times_per_week must be between {MIN_TIMES_PER_WEEK}"
            f" and {MAX_TIMES_PER_WEEK}"
        )
    return times_per_week


def _validate_caption(caption):
    if caption is None:
        return None
    caption = caption.strip()
    if not caption:
        return None
    if len(caption) > CAPTION_MAX_LENGTH:
        raise InvalidCheckin(f"caption must be at most {CAPTION_MAX_LENGTH} characters")
    return caption


def _require_member(conn, user_id: int, group_id: int):
    if not auth_service.group_exists(conn, group_id):
        raise GroupNotFound("group not found")
    if not auth_service.is_member(conn, group_id, user_id):
        raise NotGroupMember("not a member of this group")


def _get_owned_goal(conn, user_id: int, goal_id: int):
    goal = repository.get_goal_by_id(conn, goal_id)
    if goal is None:
        raise GoalNotFound("goal not found")
    if not auth_service.is_member(conn, goal["group_id"], user_id):
        raise NotGroupMember("not a member of this group")
    if goal["user_id"] != user_id:
        raise NotGoalOwner("only the goal owner can do this")
    if goal["archived_at"] is not None:
        raise GoalArchived("goal is archived")
    return goal


def create_goal(conn, user_id: int, group_id: int, title, description, times_per_week):
    _require_member(conn, user_id, group_id)
    goal_id = repository.insert_goal(
        conn,
        group_id,
        user_id,
        _validate_title(title),
        _validate_description(description),
        _validate_times_per_week(times_per_week),
        utc_now_iso(),
    )
    return repository.get_goal_by_id(conn, goal_id)


def list_group_goals(conn, user_id: int, group_id: int):
    _require_member(conn, user_id, group_id)
    return repository.list_active_goals_for_group(conn, group_id)


def update_goal(conn, user_id: int, goal_id: int, changes: dict):
    """Apply a JSON Merge Patch: absent key = unchanged, description None = clear."""
    goal = _get_owned_goal(conn, user_id, goal_id)
    title = goal["title"]
    description = goal["description"]
    times_per_week = goal["times_per_week"]
    if "title" in changes:
        title = _validate_title(changes["title"])
    if "description" in changes:
        description = _validate_description(changes["description"])
    if "times_per_week" in changes:
        times_per_week = _validate_times_per_week(changes["times_per_week"])
    repository.update_goal(conn, goal_id, title, description, times_per_week)
    return repository.get_goal_by_id(conn, goal_id)


def archive_goal(conn, user_id: int, goal_id: int):
    _get_owned_goal(conn, user_id, goal_id)
    repository.set_archived_at(conn, goal_id, utc_now_iso())
    return repository.get_goal_by_id(conn, goal_id)


def create_checkin(conn, user_id: int, goal_id: int, photo_file, caption):
    goal = _get_owned_goal(conn, user_id, goal_id)
    caption = _validate_caption(caption)
    photo_path = uploads.save_image(photo_file)
    created_at = utc_now_iso()
    try:
        checkin_id = repository.insert_checkin(
            conn, goal["id"], photo_path, caption, created_at
        )
        # In-process call to the Points seam, in this same transaction. After a
        # service split this could become a published event.
        points_service.record_completion(
            conn,
            checkin_id=checkin_id,
            group_id=goal["group_id"],
            user_id=user_id,
            goal_id=goal["id"],
            times_per_week=goal["times_per_week"],
            completed_at=created_at,
        )
    except Exception:
        # Either write failed, so the transaction won't commit: don't leave a
        # file that no row points to. If the commit in get_db() fails later, the
        # file is orphaned anyway: harmless wasted disk, unlike a row pointing
        # to a missing file (handled by PhotoMissing).
        uploads.delete_image(photo_path)
        raise
    return repository.get_checkin(conn, checkin_id)


def list_group_checkins(conn, user_id: int, group_id: int):
    _require_member(conn, user_id, group_id)
    return repository.list_checkins_for_group(conn, group_id, FEED_LIMIT)


def get_checkin_photo_path(conn, user_id: int, checkin_id: int):
    """Access-control gate in front of the file: only group members get the path."""
    checkin = repository.get_checkin(conn, checkin_id)
    if checkin is None:
        raise CheckinNotFound("check-in not found")
    if not auth_service.is_member(conn, checkin["group_id"], user_id):
        raise NotGroupMember("not a member of this group")
    path = uploads.resolve_path(checkin["photo_path"])
    if not path.is_file():
        logger.warning("check-in %s points to missing photo %s", checkin_id, path)
        raise PhotoMissing("photo not found")
    return path


def _check_can_vote(conn, voter_id: int, checkin):
    if not auth_service.is_member(conn, checkin["group_id"], voter_id):
        raise NotGroupMember("not a member of this group")
    if checkin["user_id"] == voter_id:
        raise CannotVoteOwnCheckin("you cannot vote on your own check-in")
    if checkin["status"] == "rejected":
        raise CheckinAlreadyRejected("check-in is already rejected")
    posted_at = datetime.fromisoformat(checkin["created_at"])
    if not is_voting_open(posted_at, datetime.now(timezone.utc)):
        raise VotingClosed("voting on this check-in has closed")
    if repository.has_voted(conn, checkin["id"], voter_id):
        raise AlreadyVoted("you already voted on this check-in")


def cast_rejection_vote(conn, voter_id: int, checkin_id: int) -> dict:
    """Record a vote to reject a check-in, and reject it once the majority is reached.

    Everything below runs on one connection: the vote insert, the status change
    and revoke_completion commit together in get_db(), or not at all. The checks
    in _check_can_vote run before that transaction starts, so two simultaneous
    votes can both pass them; the worst case is one extra vote row on a check-in
    that was just rejected. Status and revoke_completion stay correct because
    mark_rejected only succeeds for one transaction.
    """
    checkin = repository.get_checkin(conn, checkin_id)
    if checkin is None:
        raise CheckinNotFound("check-in not found")
    _check_can_vote(conn, voter_id, checkin)
    try:
        repository.insert_vote(conn, checkin_id, voter_id, utc_now_iso())
    except sqlite3.IntegrityError:
        raise AlreadyVoted("you already voted on this check-in")

    reject_votes = repository.count_votes(conn, checkin_id)
    eligible_voters = auth_service.member_count(conn, checkin["group_id"]) - 1
    status = checkin["status"]
    if is_rejected(reject_votes, eligible_voters) and repository.mark_rejected(conn, checkin_id):
        status = "rejected"
        points_service.revoke_completion(conn, checkin_id)
    return {
        "checkin_id": checkin_id,
        "status": status,
        "reject_votes": reject_votes,
        "votes_needed": votes_needed(eligible_voters),
    }
