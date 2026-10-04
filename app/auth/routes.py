from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from app.auth import service
from app.config import settings
from app.db import get_db

SESSION_COOKIE = "session_id"

router = APIRouter(prefix="/auth", tags=["auth"])
groups_router = APIRouter(prefix="/groups", tags=["groups"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class GroupCreateRequest(BaseModel):
    name: str


class JoinGroupRequest(BaseModel):
    invite_code: str


def get_current_user(session_id: Optional[str] = Cookie(default=None)):
    with get_db() as conn:
        user = service.get_user_from_session(conn, session_id)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,  # JavaScript can't read it, so XSS can't steal it
        samesite="lax",  # not sent on cross-site POSTs, which blocks CSRF
        secure=settings.cookie_secure,  # https only when deployed
        max_age=7 * 24 * 60 * 60,
    )


@router.post("/register", status_code=201)
def register(body: RegisterRequest, response: Response):
    with get_db() as conn:
        try:
            token = service.register(conn, body.username, body.password)
        except service.UsernameTakenError:
            raise HTTPException(status_code=409, detail="username already taken")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    _set_session_cookie(response, token)
    return {"username": body.username}


@router.post("/login")
def login(body: LoginRequest, response: Response):
    with get_db() as conn:
        try:
            token = service.authenticate(conn, body.username, body.password)
        except service.InvalidCredentialsError:
            raise HTTPException(status_code=401, detail="invalid username or password")
    _set_session_cookie(response, token)
    return {"username": body.username}


@router.post("/logout")
def logout(response: Response, session_id: Optional[str] = Cookie(default=None)):
    if session_id:
        with get_db() as conn:
            service.logout(conn, session_id)
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    return {"status": "logged out"}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"id": user["id"], "username": user["username"]}


@groups_router.post("", status_code=201)
def create_group(body: GroupCreateRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            group = service.create_group(conn, user["id"], body.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    return dict(group)


@groups_router.post("/join")
def join_group(body: JoinGroupRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            group = service.join_group(conn, user["id"], body.invite_code)
        except service.InvalidInviteCodeError:
            raise HTTPException(status_code=404, detail="invalid invite code")
    return dict(group)


@groups_router.get("")
def list_groups(user=Depends(get_current_user)):
    with get_db() as conn:
        groups = service.list_my_groups(conn, user["id"])
    return [dict(group) for group in groups]


@groups_router.get("/{group_id}/members")
def list_group_members(group_id: int, user=Depends(get_current_user)):
    """Ids and usernames, so the UI can show names next to other domains' user_ids."""
    with get_db() as conn:
        try:
            return service.get_members(conn, user["id"], group_id)
        except service.GroupNotFoundError:
            raise HTTPException(status_code=404, detail="group not found")
        except service.NotGroupMemberError:
            raise HTTPException(status_code=403, detail="not a member of this group")
