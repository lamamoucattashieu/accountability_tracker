from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.routes import get_current_user
from app.checkins import service
from app.db import get_db
from app.shared.uploads import ImageTooLarge, InvalidImage, UploadError

router = APIRouter(tags=["goals"])

STATUS_CODES = {
    service.GroupNotFound: 404,
    service.GoalNotFound: 404,
    service.NotGroupMember: 403,
    service.NotGoalOwner: 403,
    service.GoalArchived: 409,
    service.InvalidGoal: 422,
    service.CheckinNotFound: 404,
    service.PhotoMissing: 404,
    service.InvalidCheckin: 422,
    InvalidImage: 415,
    ImageTooLarge: 413,
}

# Every error this domain's routes translate into an HTTP response.
HANDLED_ERRORS = (service.CheckinsError, UploadError)


class GoalCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    times_per_week: int


class GoalUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    times_per_week: Optional[int] = None


def _to_http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=STATUS_CODES[type(exc)], detail=str(exc))


@router.post("/groups/{group_id}/goals", status_code=201)
def create_goal(group_id: int, body: GoalCreateRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            goal = service.create_goal(
                conn,
                user["id"],
                group_id,
                body.title,
                body.description,
                body.times_per_week,
            )
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return dict(goal)


@router.get("/groups/{group_id}/goals")
def list_goals(group_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            goals = service.list_group_goals(conn, user["id"], group_id)
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return [dict(goal) for goal in goals]


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalUpdateRequest, user=Depends(get_current_user)):
    changes = body.model_dump(exclude_unset=True)
    with get_db() as conn:
        try:
            goal = service.update_goal(conn, user["id"], goal_id, changes)
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return dict(goal)


@router.post("/goals/{goal_id}/archive")
def archive_goal(goal_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            goal = service.archive_goal(conn, user["id"], goal_id)
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return dict(goal)


def _checkin_response(checkin) -> dict:
    """The stored photo path is internal; clients get a URL behind the access check."""
    response = dict(checkin)
    del response["photo_path"]
    response["photo_url"] = f"/checkins/{checkin['id']}/photo"
    return response


@router.post("/goals/{goal_id}/checkins", status_code=201, tags=["checkins"])
def create_checkin(
    goal_id: int,
    photo: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    user=Depends(get_current_user),
):
    with get_db() as conn:
        try:
            checkin = service.create_checkin(conn, user["id"], goal_id, photo.file, caption)
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return _checkin_response(checkin)


@router.get("/groups/{group_id}/checkins", tags=["checkins"])
def list_checkins(group_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            checkins = service.list_group_checkins(conn, user["id"], group_id)
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return [_checkin_response(checkin) for checkin in checkins]


@router.get("/checkins/{checkin_id}/photo", tags=["checkins"])
def get_checkin_photo(checkin_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            path = service.get_checkin_photo_path(conn, user["id"], checkin_id)
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return FileResponse(path)
