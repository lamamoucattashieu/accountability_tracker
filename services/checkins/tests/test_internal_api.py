"""The endpoint Points calls, and who may call this service at all (internal key, CORS)."""

import pytest
from fastapi.testclient import TestClient

from app.checkins import service
from main import app
from tests.conftest import TEST_INTERNAL_KEY
from tests.factories import make_group, make_user
from tests.images import image_file

INTERNAL = {"X-Internal-Key": TEST_INTERNAL_KEY}


@pytest.fixture
def api(data_dir):
    # No "with": the startup hook would plug in the real Points client.
    return TestClient(app)


@pytest.fixture
def group(conn):
    alice, bob = make_user(conn, "alice"), make_user(conn, "bob")
    group_id = make_group(conn, alice, bob)
    conn.commit()
    return group_id, alice, bob


def test_group_for_points_has_ids_and_join_times_only(api, group):
    group_id, alice, bob = group
    body = api.get(f"/internal/groups/{group_id}", headers=INTERNAL).json()
    assert set(body) == {"id", "created_at", "members", "pending_points_sync"}
    assert [member["id"] for member in body["members"]] == [alice, bob]
    assert set(body["members"][0]) == {"id", "joined_at"}  # no usernames cross the seam
    assert body["pending_points_sync"] is False


def test_group_for_points_reports_undelivered_points(api, conn, group, points):
    group_id, alice, _ = group
    goal = service.create_goal(conn, alice, group_id, "Gym", None, 3)
    points.mode = "down"
    service.create_checkin(conn, alice, goal["id"], image_file(), None)
    conn.commit()
    assert api.get(f"/internal/groups/{group_id}", headers=INTERNAL).json()["pending_points_sync"] is True


def test_unknown_group_is_not_found(api):
    assert api.get("/internal/groups/999", headers=INTERNAL).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}])
def test_internal_endpoint_needs_the_internal_key(api, group, headers):
    assert api.get(f"/internal/groups/{group[0]}", headers=headers).status_code == 401


def test_the_ui_origin_may_call_from_a_browser(api):
    preflight = api.options("/auth/login", headers={
        "Origin": "http://localhost:5500",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,authorization",
    })
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5500"


def test_any_other_origin_gets_no_cors_permission(api):
    response = api.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
