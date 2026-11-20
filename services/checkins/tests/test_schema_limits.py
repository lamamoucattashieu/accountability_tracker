"""The limits written into migrations/001_init.sql match the ones the code enforces.

A migration is a fixed file (it can't read config.py, and an applied one must
never change), so the same numbers live in two places: these tests stop them
from drifting apart.
"""

import pytest

from app.checkins import service
from app.config import COMMENT_MAX_LENGTH, NUDGE_MAX_LENGTH, USERNAME_MAX_LENGTH


def column_chars(conn, table, column):
    row = conn.execute(
        "SELECT max_length FROM sys.columns WHERE object_id = OBJECT_ID(%s) AND name = %s",
        (f"dbo.{table}", column),
    ).fetchone()
    return row["max_length"] // 2  # NVARCHAR stores 2 bytes per character


def check_definition(conn, name):
    return conn.execute(
        "SELECT definition FROM sys.check_constraints WHERE name = %s", (name,)
    ).fetchone()["definition"]


@pytest.mark.parametrize("table, column, limit", [
    ("users", "username", USERNAME_MAX_LENGTH),
    ("goals", "title", service.TITLE_MAX_LENGTH),
    ("goals", "description", service.DESCRIPTION_MAX_LENGTH),
    ("checkins", "caption", service.CAPTION_MAX_LENGTH),
    ("checkin_comments", "text", COMMENT_MAX_LENGTH),
    ("nudges", "message", NUDGE_MAX_LENGTH),
])
def test_column_sizes_match_the_code(conn, table, column, limit):
    assert column_chars(conn, table, column) == limit


@pytest.mark.parametrize("constraint, numbers", [
    ("CK_checkin_comments_length", [COMMENT_MAX_LENGTH]),
    ("CK_nudges_length", [NUDGE_MAX_LENGTH]),
    ("CK_goals_times_per_week", [service.MIN_TIMES_PER_WEEK, service.MAX_TIMES_PER_WEEK]),
])
def test_check_constraints_use_the_same_limits(conn, constraint, numbers):
    definition = check_definition(conn, constraint)
    for number in numbers:
        assert f"({number})" in definition, definition
