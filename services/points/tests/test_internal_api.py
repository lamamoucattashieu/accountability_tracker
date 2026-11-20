"""The endpoints Checkins' outbox calls, Points' own token check, and CORS."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import tokens
from main import app
from tests.conftest import TEST_INTERNAL_KEY
from tests.factories import make_group, make_user

INTERNAL = {"X-Internal-Key": TEST_INTERNAL_KEY}
COMPLETION = {"checkin_id": 7, "group_id": 1, "user_id": 2, "goal_id": 3,
              "times_per_week": 3, "completed_at": "2026-11-19T10:00:00+00:00"}


@pytest.fixture
def api(db):
    # No "with": the startup hook would plug in the real Checkins directory.
    return TestClient(app)


def events(conn):
    return conn.execute("SELECT checkin_id, completed_at, revoked_at FROM point_events").fetchall()


def test_a_completion_is_recorded_once_however_often_it_arrives(api, conn):
    """Idempotent receiver: the outbox delivers at least once."""
    assert api.post("/internal/completions", json=COMPLETION, headers=INTERNAL).status_code == 204
    assert api.post("/internal/completions", json=COMPLETION, headers=INTERNAL).status_code == 204
    assert [tuple(row.values()) for row in events(conn)] == [(7, "2026-11-19T10:00:00+00:00", None)]


def test_times_are_stored_in_utc_whatever_offset_was_sent(api, conn):
    api.post("/internal/completions", headers=INTERNAL,
             json={**COMPLETION, "completed_at": "2026-11-19T11:00:00+01:00"})
    assert events(conn)[0]["completed_at"] == "2026-11-19T10:00:00+00:00"


@pytest.mark.parametrize("change", [
    {"times_per_week": 0},
    {"times_per_week": 8},
    {"completed_at": "2026-11-19T10:00:00"},  # no timezone
    {"checkin_id": "seven"},
])
def test_an_invalid_completion_is_rejected_with_422(api, change):
    response = api.post("/internal/completions", json={**COMPLETION, **change}, headers=INTERNAL)
    assert response.status_code == 422


def test_a_revocation_is_a_no_op_when_repeated_or_unknown(api, conn):
    api.post("/internal/completions", json=COMPLETION, headers=INTERNAL)
    body = {"revoked_at": "2026-11-19T12:00:00+00:00"}
    for checkin_id in (7, 7, 999):
        assert api.post(f"/internal/completions/{checkin_id}/revocation", json=body, headers=INTERNAL).status_code == 204
    assert events(conn)[0]["revoked_at"] == "2026-11-19T12:00:00+00:00"


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}])
def test_internal_endpoints_need_the_internal_key(api, headers):
    assert api.post("/internal/completions", json=COMPLETION, headers=headers).status_code == 401


def test_public_endpoints_need_a_token_signed_by_checkins(api, conn):
    alice = make_user(conn, "alice")
    group_id = make_group(conn, alice)
    token = tokens.issue(alice, "session-1", datetime.now(timezone.utc) + timedelta(days=1))
    assert api.get(f"/groups/{group_id}/leaderboard").status_code == 401
    assert api.get(f"/groups/{group_id}/leaderboard", headers={"Authorization": "Bearer forged.token"}).status_code == 401
    ok = api.get(f"/groups/{group_id}/leaderboard", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


def test_checkins_down_and_no_snapshot_is_a_clear_503(api, conn, checkins):
    alice = make_user(conn, "alice")
    group_id = make_group(conn, alice)
    checkins.down = True
    token = tokens.issue(alice, "session-1", datetime.now(timezone.utc) + timedelta(days=1))
    response = api.get(f"/groups/{group_id}/leaderboard", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503
    assert "try again" in response.json()["detail"]


def test_the_ui_origin_may_call_from_a_browser(api):
    preflight = api.options("/groups/1/forfeits", headers={
        "Origin": "http://localhost:5500",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,authorization",
    })
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5500"


def test_any_other_origin_gets_no_cors_permission(api):
    assert "access-control-allow-origin" not in api.get("/health", headers={"Origin": "https://evil.example"}).headers
