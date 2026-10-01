from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth.routes import get_current_user
from app.db import get_db
from app.points import service

router = APIRouter(tags=["points"])

STATUS_CODES = {
    service.GroupNotFound: 404,
    service.NotGroupMember: 403,
}


@router.get("/groups/{group_id}/leaderboard")
def get_leaderboard(
    group_id: int, week: Optional[date] = None, user=Depends(get_current_user)
):
    """Ranking for the week containing `week` (any day of it), or the current week."""
    day = week or datetime.now(timezone.utc).date()
    with get_db() as conn:
        try:
            return service.get_leaderboard(conn, user["id"], group_id, day)
        except service.PointsError as exc:
            raise HTTPException(status_code=STATUS_CODES[type(exc)], detail=str(exc))
