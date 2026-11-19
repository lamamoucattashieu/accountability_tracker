"""Endpoints only the Points service calls. Every one needs the internal key."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.checkins import service
from app.db import get_db
from app.shared.internal_api import require_internal_key

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_key)])


class Member(BaseModel):
    id: int
    joined_at: str


class GroupForPoints(BaseModel):
    id: int
    created_at: str
    members: list[Member]
    pending_points_sync: bool


@router.get("/groups/{group_id}", response_model=GroupForPoints)
def get_group(group_id: int):
    with get_db() as conn:
        group = service.group_for_points(conn, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="group not found")
    return group
