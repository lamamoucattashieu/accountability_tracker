from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth.current_user import get_current_user
from app.db import get_db
from app.points import service
from app.shared.uploads import ImageTooLarge, InvalidImage, UploadError

router = APIRouter(tags=["points"])

STATUS_CODES = {
    service.GroupNotFound: 404,
    service.NotGroupMember: 403,
    service.InvalidForfeit: 422,
    service.NotLastWeeksWinner: 403,
    service.SettlementBusy: 503,
    service.AssignmentNotFound: 404,
    service.NotAssignee: 403,
    service.ProofAlreadySubmitted: 409,
    service.ProofNotFound: 404,
    service.GroupInfoUnavailable: 503,
    service.GroupInfoStale: 503,
    InvalidImage: 415,
    ImageTooLarge: 413,
}

# Every error this domain's routes translate into an HTTP response.
HANDLED_ERRORS = (service.PointsError, UploadError)


class ForfeitRequest(BaseModel):
    text: str


def _to_http_error(exc: Exception) -> HTTPException:
    status_code = STATUS_CODES[type(exc)]
    headers = {"Retry-After": "1"} if status_code == 503 else None
    return HTTPException(status_code=status_code, detail=str(exc), headers=headers)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _with_proof_url(assignment: dict) -> dict:
    """The photo itself isn't in the response; clients get a URL behind the membership check."""
    url = f"/forfeit-assignments/{assignment['id']}/proof" if assignment["proof_at"] else None
    return {**assignment, "proof_url": url}


@router.get("/groups/{group_id}/leaderboard")
def get_leaderboard(
    group_id: int, week: Optional[date] = None, user=Depends(get_current_user)
):
    """Ranking for the week containing `week` (any day of it), or the current week."""
    now = _now()
    with get_db() as conn:
        try:
            return service.get_leaderboard(conn, user["id"], group_id, week or now.date(), now)
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)


@router.post("/groups/{group_id}/forfeits", status_code=201)
def set_forfeit(group_id: int, body: ForfeitRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            return service.set_forfeit(conn, user["id"], group_id, body.text, _now())
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)


@router.get("/groups/{group_id}/forfeits")
def get_forfeits(group_id: int, user=Depends(get_current_user)):
    """This week's locked forfeit and the upcoming one."""
    with get_db() as conn:
        try:
            return service.get_forfeits(conn, user["id"], group_id, _now())
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)


@router.get("/groups/{group_id}/settlements")
def list_settlements(group_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            settlements = service.list_settlements(conn, user["id"], group_id, _now())
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return [
        {**s, "assignments": [_with_proof_url(a) for a in s["assignments"]]}
        for s in settlements
    ]


@router.post("/forfeit-assignments/{assignment_id}/proof", status_code=201)
def submit_proof(
    assignment_id: int, photo: UploadFile = File(...), user=Depends(get_current_user)
):
    with get_db() as conn:
        try:
            assignment = service.submit_proof(conn, user["id"], assignment_id, photo.file, _now())
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return _with_proof_url(assignment)


@router.get("/forfeit-assignments/{assignment_id}/proof")
def get_proof_photo(assignment_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        try:
            photo, photo_type = service.get_proof_photo(conn, user["id"], assignment_id, _now())
        except HANDLED_ERRORS as exc:
            raise _to_http_error(exc)
    return Response(content=photo, media_type=photo_type)
