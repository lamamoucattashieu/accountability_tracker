"""End-to-end smoke test: the running compose stack, reached the way a user reaches it.

The small top of the testing pyramid: one path through the whole system (nginx, both
services, both databases, the call across the seam), not every rule (the services' own
tests do that). Run it after "docker compose up -d --build", from the repository root:

    pytest e2e

It creates a uniquely named user and group, so it can run on a stack that already has data.
"""

import io
import time
import uuid

import httpx
import pytest
from PIL import Image

UI = "http://localhost:5500"
CHECKINS = "http://localhost:8000"
POINTS = "http://localhost:8001"
# The first start on an empty volume can be slow (SQL Server, then the migrations).
STARTUP_TIMEOUT_S = 120


def wait_until_healthy(url: str) -> dict:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while True:
        try:
            response = httpx.get(f"{url}/health", timeout=5)
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            pytest.fail(f"{url}/health was not 200 within {STARTUP_TIMEOUT_S}s: is the stack up?")
        time.sleep(2)


@pytest.fixture(scope="module")
def stack():
    return {name: wait_until_healthy(url) for name, url in (("checkins", CHECKINS), ("points", POINTS))}


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (138, 123, 255)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_both_services_are_healthy_with_their_database(stack):
    for name, body in stack.items():
        assert body["status"] == "ok" and body["db"] == "ok", name
        assert body["version"], name


def test_nginx_serves_the_ui_and_its_service_urls():
    page = httpx.get(f"{UI}/")
    assert page.status_code == 200 and "lockin." in page.text
    config = httpx.get(f"{UI}/config.js")
    assert config.status_code == 200
    assert CHECKINS in config.text and POINTS in config.text


def test_a_checkin_crosses_the_seam_and_scores(stack):
    name = f"smoke{uuid.uuid4().hex[:8]}"
    registered = httpx.post(f"{CHECKINS}/auth/register", json={"username": name, "password": "smoke-password"})
    assert registered.status_code == 201
    me = {"Authorization": f"Bearer {registered.json()['token']}"}

    group = httpx.post(f"{CHECKINS}/groups", json={"name": "smoke crew"}, headers=me).json()
    goal = httpx.post(f"{CHECKINS}/groups/{group['id']}/goals",
                      json={"title": "Gym", "times_per_week": 3}, headers=me).json()
    checkin = httpx.post(f"{CHECKINS}/goals/{goal['id']}/checkins", headers=me, timeout=30,
                         files={"photo": ("proof.jpg", jpeg(), "image/jpeg")})
    assert checkin.status_code == 201
    assert checkin.json()["points_pending"] is False  # Points took it right after the commit

    photo = httpx.get(f"{CHECKINS}{checkin.json()['photo_url']}", headers=me)
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"

    board = httpx.get(f"{POINTS}/groups/{group['id']}/leaderboard", headers=me, timeout=30)
    assert board.status_code == 200
    assert [entry["points"] for entry in board.json()["entries"]] == [1]  # the token works in Points too


def test_the_browser_origin_is_allowed_by_both_services():
    for url in (CHECKINS, POINTS):
        preflight = httpx.options(f"{url}/groups", headers={
            "Origin": UI, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization"})
        assert preflight.headers.get("access-control-allow-origin") == UI, url
