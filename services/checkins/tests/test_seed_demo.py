from datetime import datetime, timezone

import pytest

import seed_demo
from app.db import get_connection

THURSDAY = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def test_demo_seed_creates_the_checkins_half_and_delivers_its_points(db, points):
    summary = seed_demo.seed(THURSDAY)
    assert summary["users"] == 4
    assert summary["rejected"] == 1          # a check-in voted down by the crew
    assert summary["comments"] >= 4
    assert summary["nudges"] == 2
    assert summary["points_delivered"] == summary["checkins"] + summary["rejected"]  # records + revoke
    conn = get_connection()
    oldest = conn.execute("SELECT MIN(created_at) AS oldest FROM checkins").fetchone()["oldest"]
    conn.close()
    assert oldest < "2026-09-28"  # backdated weeks exist, so Points has past weeks to settle


def test_demo_seed_stops_when_points_is_not_running(db, points):
    points.mode = "down"
    with pytest.raises(SystemExit, match="Points service running"):
        seed_demo.seed(THURSDAY)


def test_demo_seed_refuses_a_database_that_has_users(db, points):
    seed_demo.seed(THURSDAY)
    with pytest.raises(SystemExit):
        seed_demo.seed(THURSDAY)
