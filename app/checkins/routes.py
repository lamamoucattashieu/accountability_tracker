from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.routes import get_current_user
from app.checkins import service
from app.db import get_db

router = APIRouter(tags=["goals"])

STATUS_CODES = {
    service.GroupNotFound: 404,
    service.GoalNotFound: 404,
    service.NotGroupMember: 403,
    service.NotGoalOwner: 403,
    service.GoalArchived: 409,
    service.InvalidGoal: 422,
}


class GoalCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    times_per_week: int


class GoalUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    times_per_week: Optional[int] = None


def _to_http_error(exc: service.CheckinsError) -> HTTPException:
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
        except service.CheckinsError as exc:
            raise _to_http_error(exc)
    return dict(goal)


@router.get("/groups/{group_id}/goals")
def list_goals(group_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            goals = service.list_group_goals(conn, user["id"], group_id)
        except service.CheckinsError as exc:
            raise _to_http_error(exc)
    return [dict(goal) for goal in goals]


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalUpdateRequest, user=Depends(get_current_user)):
    changes = body.model_dump(exclude_unset=True)
    with get_db() as conn:
        try:
            goal = service.update_goal(conn, user["id"], goal_id, changes)
        except service.CheckinsError as exc:
            raise _to_http_error(exc)
    return dict(goal)


@router.post("/goals/{goal_id}/archive")
def archive_goal(goal_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            goal = service.archive_goal(conn, user["id"], goal_id)
        except service.CheckinsError as exc:
            raise _to_http_error(exc)
    return dict(goal)
