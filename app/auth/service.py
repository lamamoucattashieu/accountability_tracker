from datetime import datetime, timedelta, timezone

from app.auth import repository
from app.auth.security import (
    hash_password,
    new_invite_code,
    new_session_token,
    verify_password,
)

SESSION_TTL = timedelta(days=7)


class UsernameTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidInviteCodeError(Exception):
    pass


def _create_session(conn, user_id: int) -> str:
    token = new_session_token()
    expires_at = (datetime.now(timezone.utc) + SESSION_TTL).isoformat()
    repository.insert_session(conn, token, user_id, expires_at)
    return token


def register(conn, username: str, password: str) -> str:
    if len(username) < 3:
        raise ValueError("username must be at least 3 characters")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if repository.get_user_by_username(conn, username):
        raise UsernameTakenError(username)
    user_id = repository.insert_user(conn, username, hash_password(password))
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
    group_id = repository.insert_group(conn, name, invite_code, user_id)
    repository.add_group_member(conn, group_id, user_id)
    return repository.get_group_by_id(conn, group_id)


def join_group(conn, user_id: int, invite_code: str):
    group = repository.get_group_by_invite_code(conn, invite_code.strip().upper())
    if group is None:
        raise InvalidInviteCodeError(invite_code)
    repository.add_group_member(conn, group["id"], user_id)
    return group


def list_my_groups(conn, user_id: int):
    return repository.list_groups_for_user(conn, user_id)
