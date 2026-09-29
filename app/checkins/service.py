from app.auth import service as auth_service
from app.checkins import repository
from app.shared.timeutils import utc_now_iso

TITLE_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 500
MIN_TIMES_PER_WEEK = 1
MAX_TIMES_PER_WEEK = 7


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
