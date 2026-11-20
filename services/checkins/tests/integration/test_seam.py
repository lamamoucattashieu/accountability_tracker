"""Integration tests across the seam: both real services, over real HTTP.

Each test starts Checkins and Points as separate processes (uvicorn) on free
ports, each with its own scratch database, the way they run in production. They
show the flows that cross the seam, and what happens when one service is
stopped: the other keeps serving its own domain, and the cross-seam flow fails
in the designed way (A2 spec 3).
"""

import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image

from tests import sqlserver

SERVICES = Path(__file__).resolve().parents[3]  # .../services
STARTUP_TIMEOUT_S = 20
SECRETS = {"AUTH_TOKEN_SECRET": "integration-secret", "INTERNAL_API_KEY": "integration-key"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Service:
    """One service as a real process. stop() and start() keep its database."""

    def __init__(self, name, port, env):
        self.name, self.port, self.env = name, port, env
        self.url = f"http://127.0.0.1:{port}"
        self.process = None

    def start(self):
        env = {**os.environ, **SECRETS, **self.env, "PORT": str(self.port)}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=SERVICES / self.name, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.url}/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        self.stop()
        raise RuntimeError(f"{self.name} did not start")

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process = None


@pytest.fixture
def system():
    checkins_port, points_port = free_port(), free_port()
    checkins_db = sqlserver.create_database("test_seam_checkins")
    points_db = sqlserver.create_database("test_seam_points")
    checkins = Service("checkins", checkins_port, {
        "DATABASE_URL": checkins_db,
        "POINTS_URL": f"http://127.0.0.1:{points_port}", "POINTS_TIMEOUT_S": "1"})
    points = Service("points", points_port, {
        "DATABASE_URL": points_db,
        "CHECKINS_URL": f"http://127.0.0.1:{checkins_port}", "CHECKINS_TIMEOUT_S": "1"})
    checkins.start()
    points.start()
    yield checkins, points
    checkins.stop()
    points.stop()
    sqlserver.drop_database(checkins_db)
    sqlserver.drop_database(points_db)


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 100, 50)).save(buffer, format="JPEG")
    return buffer.getvalue()


class Crew:
    """Two members of one group, talking to both services like the UI does."""

    def __init__(self, checkins, points):
        self.checkins, self.points = checkins, points
        self.alice = self._register("alice")
        self.bob = self._register("bob")
        group = httpx.post(f"{checkins.url}/groups", json={"name": "crew"}, headers=self.alice).json()
        httpx.post(f"{checkins.url}/groups/join", json={"invite_code": group["invite_code"]}, headers=self.bob)
        self.group_id = group["id"]
        self.goal_id = httpx.post(f"{checkins.url}/groups/{self.group_id}/goals", headers=self.alice,
                                  json={"title": "Gym", "times_per_week": 3}).json()["id"]

    def _register(self, name):
        body = httpx.post(f"{self.checkins.url}/auth/register", json={"username": name, "password": "password1"}).json()
        return {"Authorization": f"Bearer {body['token']}"}

    def check_in(self):
        return httpx.post(f"{self.checkins.url}/goals/{self.goal_id}/checkins", headers=self.alice,
                          files={"photo": ("proof.jpg", jpeg(), "image/jpeg")}, timeout=10)

    def leaderboard(self):
        return httpx.get(f"{self.points.url}/groups/{self.group_id}/leaderboard", headers=self.alice, timeout=10)

    def alice_points(self):
        alice_id = httpx.get(f"{self.checkins.url}/auth/me", headers=self.alice).json()["id"]
        entries = self.leaderboard().json()["entries"]
        return next(entry["points"] for entry in entries if entry["user_id"] == alice_id)

    def feed(self):
        return httpx.get(f"{self.checkins.url}/groups/{self.group_id}/checkins", headers=self.alice, timeout=10)


def test_a_checkin_scores_in_points_and_a_rejection_takes_it_back(system):
    crew = Crew(*system)
    checkin = crew.check_in()
    assert checkin.status_code == 201
    assert checkin.json()["points_pending"] is False  # delivered right after the commit
    assert crew.alice_points() == 1
    vote = httpx.post(f"{crew.checkins.url}/checkins/{checkin.json()['id']}/votes", headers=crew.bob)
    assert vote.json()["status"] == "rejected"  # two members: bob's vote alone rejects it
    assert crew.alice_points() == 0


def test_with_points_stopped_checkins_still_works_and_catches_up_later(system):
    checkins, points = system
    crew = Crew(checkins, points)
    points.stop()

    checkin = crew.check_in()
    assert checkin.status_code == 201  # Checkins keeps serving its own domain
    assert checkin.json()["points_pending"] is True
    assert [item["points_pending"] for item in crew.feed().json()] == [True]

    points.start()
    assert [item["points_pending"] for item in crew.feed().json()] == [False]  # the feed load delivered it
    assert crew.alice_points() == 1


def test_with_checkins_stopped_points_serves_its_last_snapshot(system):
    checkins, points = system
    crew = Crew(checkins, points)
    crew.check_in()
    assert crew.leaderboard().json()["membership_stale"] is False  # leaves a snapshot
    checkins.stop()

    board = crew.leaderboard()
    assert board.status_code == 200  # Points keeps serving its own domain
    assert board.json()["membership_stale"] is True
    forfeit = httpx.post(f"{points.url}/groups/{crew.group_id}/forfeits", headers=crew.alice, json={"text": "push-ups"})
    assert forfeit.status_code == 503  # a change needs current membership
    assert "try again" in forfeit.json()["detail"]
