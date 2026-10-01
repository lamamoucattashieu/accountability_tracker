from datetime import datetime, timezone

import pytest

from app.points import service
from tests.factories import make_group, make_user

# Sunday of the week starting 2026-09-14: everyone is eligible from the week of 2026-09-21.
GROUP_CREATED = "2026-09-20T09:00:00+00:00"


@pytest.fixture
def call(conn):
    """Run a service function and commit, like get_db() does at the end of a request.

    Settlement refuses to start inside an open transaction, so each call has to
    begin from a committed state, exactly as a real request does.
    """
    def _call(function, *args, **kwargs):
        result = function(conn, *args, **kwargs)
        conn.commit()
        return result
    return _call


@pytest.fixture
def people(conn):
    return {name: make_user(conn, name) for name in ("ana", "ben", "cy")}


@pytest.fixture
def group(conn, people):
    """A group created, and joined by everyone, on GROUP_CREATED."""
    group_id = make_group(conn, *people.values())
    backdate_group(conn, group_id, GROUP_CREATED)
    for user_id in people.values():
        backdate_join(conn, group_id, user_id, GROUP_CREATED)
    conn.commit()
    return group_id


def backdate_group(conn, group_id, created_at):
    conn.execute("UPDATE groups SET created_at = ? WHERE id = ?", (created_at, group_id))


def backdate_join(conn, group_id, user_id, joined_at):
    conn.execute(
        "UPDATE group_members SET joined_at = ? WHERE group_id = ? AND user_id = ?",
        (joined_at, group_id, user_id),
    )


def at(text):
    return datetime.fromisoformat(text)


def utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def complete(conn, checkin_id, user_id, group_id, completed_at, goal_id=None, times_per_week=3):
    """Record one completion for user_id (one goal per user unless goal_id is given).

    Returns the checkin_id, so tests can revoke it later.
    """
    service.record_completion(
        conn, checkin_id=checkin_id, group_id=group_id, user_id=user_id,
        goal_id=goal_id if goal_id is not None else user_id,
        times_per_week=times_per_week, completed_at=completed_at,
    )
    return checkin_id
