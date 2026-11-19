"""The Points half of the demo seed, with a fake Checkins and the completions it would deliver."""

from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

import seed_demo
from app.db import get_connection
from app.points import service
from app.shared.timeutils import week_begins_at, week_start_for
from tests.factories import backdate_group, backdate_join, make_group, make_user

THURSDAY = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)  # after last week has settled
CREW = ["maya", "leo", "zoe", "sam"]


@pytest.fixture
def crew(conn):
    """The crew as the Checkins half creates it, and the check-ins it delivers to Points."""
    ids = {name: make_user(conn, name) for name in CREW}
    group_id = make_group(conn, *ids.values())
    this_week = week_begins_at(week_start_for(THURSDAY))
    created = iso(this_week - 3 * timedelta(weeks=1) - timedelta(hours=12))
    backdate_group(conn, group_id, created)
    for user_id in ids.values():
        backdate_join(conn, group_id, user_id, created)
    checkin_ids = count(1)
    # two weeks ago sam scores nothing; last week leo and sam tie for last
    for weeks_ago, done in ((2, {"maya": 3, "leo": 2, "zoe": 2}), (1, {"maya": 4, "zoe": 3, "leo": 1, "sam": 1})):
        start = this_week - weeks_ago * timedelta(weeks=1)
        for name, times in done.items():
            for n in range(times):
                service.record_completion(
                    conn, checkin_id=next(checkin_ids), group_id=group_id, user_id=ids[name],
                    goal_id=ids[name], times_per_week=7, completed_at=iso(start + timedelta(days=n, hours=9)),
                )
    conn.commit()
    return group_id, ids


def iso(moment):
    return moment.isoformat(timespec="seconds")


def test_demo_seed_settles_past_weeks_with_losers_and_proof(data_dir, crew):
    summary = seed_demo.seed(THURSDAY, *crew)
    assert summary["settled_weeks"] >= 3
    assert summary["forfeit_losers"] >= 3  # sam alone, then leo and sam tied
    assert summary["proofs"] == 1
    conn = get_connection()
    assert conn.execute("SELECT COUNT(*) FROM forfeits").fetchone()[0] == 4  # three past + next week's
    conn.close()


def test_demo_seed_refuses_a_database_that_has_forfeits(data_dir, crew):
    seed_demo.seed(THURSDAY, *crew)
    with pytest.raises(SystemExit):
        seed_demo.seed(THURSDAY, *crew)
