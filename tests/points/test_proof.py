import io
import sqlite3
from datetime import timedelta

import pytest

from app.points import repository, service
from app.shared import uploads
from tests.factories import make_user
from tests.images import image_file
from tests.points.test_settlement import FORFEIT_SET, SETTLES, score, week_of

DUE = SETTLES + timedelta(days=7)


def stored_files(data_dir):
    return list((data_dir / "uploads").iterdir())


@pytest.fixture
def assignment(call, conn, people, group):
    """ben lost the week of 2026-09-28; returns his forfeit assignment."""
    call(service.set_forfeit, people["ana"], group, "20 push-ups", FORFEIT_SET)
    score(conn, people["ana"], group, 2)
    score(conn, people["cy"], group, 2)
    [ben] = week_of(call, people["ana"], group, SETTLES)["assignments"]
    return ben


def test_assignee_uploads_proof_before_the_deadline(call, data_dir, people, assignment):
    result = call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    assert result["status"] == "submitted"
    assert result["proof_at"] == SETTLES.isoformat()
    assert len(stored_files(data_dir)) == 1


def test_late_proof_is_accepted_and_shown_as_late(call, people, group, assignment):
    late = DUE + timedelta(hours=1)
    result = call(service.submit_proof, people["ben"], assignment["id"], image_file(), late)
    assert result["status"] == "late"
    [listed] = week_of(call, people["ana"], group, late)["assignments"]
    assert listed["status"] == "late"


def test_non_assignee_cannot_upload_proof(call, data_dir, people, assignment):
    with pytest.raises(service.NotAssignee):
        call(service.submit_proof, people["ana"], assignment["id"], image_file(), SETTLES)
    assert stored_files(data_dir) == []


def test_second_proof_is_a_conflict(call, data_dir, people, assignment):
    call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    with pytest.raises(service.ProofAlreadySubmitted):
        call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    assert len(stored_files(data_dir)) == 1


def test_simultaneous_second_upload_loses_and_its_file_is_deleted(
    call, data_dir, people, assignment, monkeypatch
):
    # The other upload stored its proof between our check and our UPDATE.
    monkeypatch.setattr(repository, "set_proof", lambda *args: False)
    with pytest.raises(service.ProofAlreadySubmitted):
        call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    assert stored_files(data_dir) == []


def test_proof_file_is_deleted_when_the_database_write_fails(
    call, data_dir, people, assignment, monkeypatch
):
    def failing_set_proof(*args):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(repository, "set_proof", failing_set_proof)
    with pytest.raises(sqlite3.OperationalError):
        call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    assert stored_files(data_dir) == []


def test_invalid_proof_image_is_rejected(call, data_dir, people, assignment):
    with pytest.raises(uploads.InvalidImage):
        call(service.submit_proof, people["ben"], assignment["id"], io.BytesIO(b"text"), SETTLES)
    assert stored_files(data_dir) == []


def test_non_member_cannot_upload_or_see_proof(call, conn, assignment):
    outsider = make_user(conn, "outsider")
    conn.commit()
    with pytest.raises(service.NotGroupMember):
        call(service.submit_proof, outsider, assignment["id"], image_file(), SETTLES)
    with pytest.raises(service.NotGroupMember):
        call(service.get_proof_photo_path, outsider, assignment["id"], SETTLES)


def test_missing_assignment_is_not_found(call, people, group):
    with pytest.raises(service.AssignmentNotFound):
        call(service.submit_proof, people["ben"], 999, image_file(), SETTLES)


def test_any_member_can_see_the_proof_photo(call, data_dir, people, assignment):
    call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    path = call(service.get_proof_photo_path, people["cy"], assignment["id"], SETTLES)
    assert path.is_file()
    assert path.parent == (data_dir / "uploads").resolve()


def test_proof_photo_before_upload_is_not_found(call, people, assignment):
    with pytest.raises(service.ProofNotFound):
        call(service.get_proof_photo_path, people["cy"], assignment["id"], SETTLES)


def test_missing_proof_file_is_not_found_and_logged(call, data_dir, people, assignment, caplog):
    call(service.submit_proof, people["ben"], assignment["id"], image_file(), SETTLES)
    for path in stored_files(data_dir):
        path.unlink()
    with pytest.raises(service.ProofNotFound):
        call(service.get_proof_photo_path, people["cy"], assignment["id"], SETTLES)
    assert "missing proof" in caplog.text
