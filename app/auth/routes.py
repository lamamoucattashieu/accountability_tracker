from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.auth import service
from app.auth.tokens import bearer_token
from app.db import get_db

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


def get_current_user(authorization: Optional[str] = Header(default=None)):
    """The user behind the "Authorization: Bearer <token>" header, or 401.

    A header, not a cookie: the UI is on another site than the services, where
    browsers block cookies. The browser never adds the header on its own, so a
    forged cross-site request carries no login (no CSRF).
    """
    with get_db() as conn:
        user = service.get_user_from_token(conn, bearer_token(authorization))
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


@router.post("/register", status_code=201)
def register(body: RegisterRequest):
    with get_db() as conn:
        try:
            session_id = service.register(conn, body.username, body.password)
        except service.UsernameTakenError:
            raise HTTPException(status_code=409, detail="username already taken")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        token = service.access_token(conn, session_id)
    return {"username": body.username, "token": token}


@router.post("/login")
def login(body: LoginRequest):
    with get_db() as conn:
        try:
            session_id = service.authenticate(conn, body.username, body.password)
        except service.InvalidCredentialsError:
            raise HTTPException(status_code=401, detail="invalid username or password")
        token = service.access_token(conn, session_id)
    return {"username": body.username, "token": token}


@router.post("/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    with get_db() as conn:
        service.logout_token(conn, bearer_token(authorization))
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
