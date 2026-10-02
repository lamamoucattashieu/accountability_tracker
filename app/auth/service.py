from datetime import datetime, timedelta, timezone

from app.auth import repository
from app.auth.security import (
    hash_password,
    new_invite_code,
    new_session_token,
    verify_password,
)
from app.shared.timeutils import utc_now_iso

SESSION_TTL = timedelta(days=7)


class UsernameTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidInviteCodeError(Exception):
    pass


class GroupNotFoundError(Exception):
    pass


class NotGroupMemberError(Exception):
    pass


def _create_session(conn, user_id: int) -> str:
    token = new_session_token()
    now = datetime.now(timezone.utc)
    created_at = now.isoformat(timespec="seconds")
    expires_at = (now + SESSION_TTL).isoformat(timespec="seconds")
    repository.insert_session(conn, token, user_id, created_at, expires_at)
    return token


def register(conn, username: str, password: str) -> str:
    if len(username) < 3:
        raise ValueError("username must be at least 3 characters")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if repository.get_user_by_username(conn, username):
        raise UsernameTakenError(username)
    user_id = repository.insert_user(
        conn, username, hash_password(password), utc_now_iso()
    )
    return _create_session(conn, user_id)


def authenticate(conn, username: str, password: str) -> str:
    user = repository.get_user_by_username(conn, username)
    if user is None or not verify_password(password, user["password_hash"]):
        raise InvalidCredentialsError()
    return _create_session(conn, user["id"])


def logout(conn, session_token: str):
    repository.delete_session(conn, session_token)


def get_user_from_session(conn, session_token):
    if not session_token:
        return None
    session = repository.get_session(conn, session_token)
    if session is None:
        return None
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        repository.delete_session(conn, session_token)
        return None
    return repository.get_user_by_id(conn, session["user_id"])


def create_group(conn, user_id: int, name: str):
    name = name.strip()
    if not name:
        raise ValueError("group name cannot be empty")
    invite_code = new_invite_code()
    while repository.get_group_by_invite_code(conn, invite_code):
        invite_code = new_invite_code()
    now = utc_now_iso()
    group_id = repository.insert_group(conn, name, invite_code, user_id, now)
    repository.add_group_member(conn, group_id, user_id, now)
    return repository.get_group_by_id(conn, group_id)


def join_group(conn, user_id: int, invite_code: str):
    group = repository.get_group_by_invite_code(conn, invite_code.strip().upper())
    if group is None:
        raise InvalidInviteCodeError(invite_code)
    repository.add_group_member(conn, group["id"], user_id, utc_now_iso())
    return group


def list_my_groups(conn, user_id: int):
    return repository.list_groups_for_user(conn, user_id)


def is_member(conn, group_id: int, user_id: int) -> bool:
    return repository.is_group_member(conn, group_id, user_id)


def group_exists(conn, group_id: int) -> bool:
    return repository.group_exists(conn, group_id)


def member_count(conn, group_id: int) -> int:
    return repository.count_group_members(conn, group_id)


def list_members(conn, group_id: int) -> list[dict]:
    """Plain dicts, not database rows, so callers in other domains don't depend on our tables."""
    return [dict(row) for row in repository.list_group_members(conn, group_id)]


def group_created_at(conn, group_id: int):
    """ISO 8601 UTC creation time of a group, or None if it doesn't exist."""
    group = repository.get_group_by_id(conn, group_id)
    return None if group is None else group["created_at"]


def get_members(conn, user_id: int, group_id: int) -> list[dict]:
    """Display names for a group's members: members only (404, then 403, as elsewhere)."""
    if not group_exists(conn, group_id):
        raise GroupNotFoundError(group_id)
    if not is_member(conn, group_id, user_id):
        raise NotGroupMemberError(group_id)
    return [
        {"id": member["id"], "username": member["username"]}
        for member in list_members(conn, group_id)
    ]
