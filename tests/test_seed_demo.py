from datetime import datetime, timezone

import pytest

import seed_demo
from app.db import get_connection

THURSDAY = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)  # after last week has settled


def test_demo_seed_shows_every_feature(data_dir):
    summary = seed_demo.seed(THURSDAY)
    assert summary["users"] == 4
    assert summary["rejected"] == 1          # a check-in voted down by the crew
    assert summary["comments"] >= 4
    assert summary["forfeit_losers"] >= 2    # including a tie that shares the forfeit
    assert summary["nudges"] == 2
    conn = get_connection()
    upcoming = conn.execute("SELECT COUNT(*) FROM forfeits").fetchone()[0]
    proofs = conn.execute("SELECT COUNT(*) FROM forfeit_assignments WHERE proof_path IS NOT NULL").fetchone()[0]
    conn.close()
    assert upcoming == 4 and proofs == 1


def test_demo_seed_refuses_a_database_that_has_users(data_dir):
    seed_demo.seed(THURSDAY)
    with pytest.raises(SystemExit):
        seed_demo.seed(THURSDAY)
