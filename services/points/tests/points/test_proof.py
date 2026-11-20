import io
from datetime import timedelta

import pymssql
import pytest

from app.points import repository, service
from app.shared import uploads
from tests.factories import make_user
from tests.images import image_bytes, image_file
from tests.points.test_settlement import FORFEIT_SET, SETTLES, score, week_of

DUE = SETTLES + timedelta(days=7)


def stored_proofs(conn):
    return conn.execute(
        "SELECT COUNT(*) AS n FROM forfeit_assignments WHERE proof_photo IS NOT NULL"
    ).fetchone()["n"]


@pytest.fixture
def assignment(call, conn, people, group):
    """ben lost the week of 2026-09-28; returns his forfeit assignment."""
    call(service.set_forfeit, people["ana"], group, "20 push-ups", FORFEIT_SET)
    score(conn, people["ana"], group, 2)
    score(conn, people["cy"], group, 2)
    [ben] = week_of(call, people["ana"], group, SETTLES)["assignments"]
    return ben


def test_assignee_uploads_proof_before_the_deadline(call, conn, people, assignment):
    result = call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    assert result["status"] == "submitted"
    assert result["proof_at"] == SETTLES.isoformat()
    assert stored_proofs(conn) == 1


def test_late_proof_is_accepted_and_shown_as_late(call, people, group, assignment):
    late = DUE + timedelta(hours=1)
    result = call(service.submit_proof, people["ben"], assignment["id"], image_file(), late)
    assert result["status"] == "late"
    [listed] = week_of(call, people["ana"], group, late)["assignments"]
    assert listed["status"] == "late"


def test_non_assignee_cannot_upload_proof(call, conn, people, assignment):
    with pytest.raises(service.NotAssignee):
        call(service.submit_proof, people["ana"], assignment["id"], image_file(), SETTLES)
    assert stored_proofs(conn) == 0


def test_second_proof_is_a_conflict(call, conn, people, assignment):
    call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    with pytest.raises(service.ProofAlreadySubmitted):
        call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    assert stored_proofs(conn) == 1


def test_simultaneous_second_upload_loses(call, people, assignment, monkeypatch):
    # The other upload stored its proof between our check and our UPDATE.
    monkeypatch.setattr(repository, "set_proof", lambda *args: False)
    with pytest.raises(service.ProofAlreadySubmitted):
        call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)


def test_a_failed_database_write_leaves_no_proof(call, conn, people, assignment, monkeypatch):
    """Replaces A1's "proof file deleted when the write fails": the photo is in the row now."""
    def failing_set_proof(*args):
        raise pymssql.OperationalError(1222, b"Lock request time out period exceeded.")

    monkeypatch.setattr(repository, "set_proof", failing_set_proof)
    with pytest.raises(pymssql.OperationalError):
        call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    assert stored_proofs(conn) == 0


def test_invalid_proof_image_is_rejected(call, conn, people, assignment):
    with pytest.raises(uploads.InvalidImage):
        call(service.submit_proof, people["ben"], assignment["id"], io.BytesIO(b"text"), SETTLES)
    assert stored_proofs(conn) == 0


def test_non_member_cannot_upload_or_see_proof(call, conn, assignment):
    outsider = make_user(conn, "outsider")
    conn.commit()
    with pytest.raises(service.NotGroupMember):
        call(service.submit_proof, outsider, assignment["id"], image_file(), SETTLES)
    with pytest.raises(service.NotGroupMember):
        call(service.get_proof_photo, outsider, assignment["id"], SETTLES)


def test_missing_assignment_is_not_found(call, people, group):
    with pytest.raises(service.AssignmentNotFound):
        call(service.submit_proof, people["ben"], 999, image_file(), SETTLES)


def test_any_member_can_see_the_proof_photo(call, people, assignment):
    call(service.submit_proof, people["ben"], assignment["id"], image_file("PNG"), SETTLES)
    photo = call(service.get_proof_photo, people["cy"], assignment["id"], SETTLES)
    assert photo == (image_bytes("PNG"), "image/png")


def test_proof_photo_before_upload_is_not_found(call, people, assignment):
    with pytest.raises(service.ProofNotFound):
        call(service.get_proof_photo, people["cy"], assignment["id"], SETTLES)


def test_settlement_lists_never_carry_the_photo_bytes(call, people, group, assignment):
    call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    [listed] = week_of(call, people["ana"], group, SETTLES)["assignments"]
    assert "proof_photo" not in listed and listed["proof_at"] == SETTLES.isoformat()
