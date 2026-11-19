"""Endpoints only the Checkins service calls (its points outbox). Every one needs the internal key.

Both are idempotent receivers: Checkins delivers at least once, so the same
call may arrive twice, and the second is a no-op answered with the same 204.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from pydantic import AwareDatetime, BaseModel, Field

from app.db import get_db
from app.points import service
from app.shared.internal_api import require_internal_key

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_key)])


def _utc_iso(moment: datetime) -> str:
    """Stored timestamps are always ISO 8601 UTC, whatever offset the caller used."""
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


class Completion(BaseModel):
    checkin_id: int
    group_id: int
    user_id: int
    goal_id: int
    times_per_week: int = Field(ge=1, le=7)
    completed_at: AwareDatetime  # must carry a timezone, so its week can't be misread


class Revocation(BaseModel):
    revoked_at: AwareDatetime


@router.post("/completions", status_code=204)
def record_completion(body: Completion):
    with get_db() as conn:
        service.record_completion(
            conn, checkin_id=body.checkin_id, group_id=body.group_id, user_id=body.user_id,
            goal_id=body.goal_id, times_per_week=body.times_per_week,
            completed_at=_utc_iso(body.completed_at),
        )
    return Response(status_code=204)


@router.post("/completions/{checkin_id}/revocation", status_code=204)
def revoke_completion(checkin_id: int, body: Revocation):
    with get_db() as conn:
        service.revoke_completion(conn, checkin_id, _utc_iso(body.revoked_at))
    return Response(status_code=204)
