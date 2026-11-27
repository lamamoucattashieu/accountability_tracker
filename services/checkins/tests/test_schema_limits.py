"""The limits written into the migrations match the ones the code enforces.

A migration is a fixed file (it can't read config.py, and an applied one must
never change), so the same numbers live in two places: these tests stop them
from drifting apart. The last test runs the real 001 and 002 files against a
database that already holds groups, as on Azure.
"""

import shutil
from pathlib import Path

import pytest

from app.checkins import service
from app.config import COMMENT_MAX_LENGTH, GROUP_NAME_MAX_LENGTH, NUDGE_MAX_LENGTH, USERNAME_MAX_LENGTH
from app.shared.database import connect
from app.shared.migrations import apply_migrations
from tests import sqlserver

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


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
    ("groups", "name", GROUP_NAME_MAX_LENGTH),
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
    ("CK_groups_name_length", [GROUP_NAME_MAX_LENGTH]),
    ("CK_goals_times_per_week", [service.MIN_TIMES_PER_WEEK, service.MAX_TIMES_PER_WEEK]),
])
def test_check_constraints_use_the_same_limits(conn, constraint, numbers):
    definition = check_definition(conn, constraint)
    for number in numbers:
        assert f"({number})" in definition, definition


def test_migration_002_keeps_existing_groups_and_shortens_long_names(tmp_path):
    """The real 001, some data, then the real 002 (A2 spec 4.3): every row survives."""
    url = sqlserver.create_database("test_migration_002")
    conn = connect(url)
    try:
        shutil.copy(MIGRATIONS / "001_init.sql", tmp_path)
        assert apply_migrations(conn, tmp_path, "2026-11-27T10:00:00+00:00") == ["001_init"]
        conn.execute(
            "INSERT INTO dbo.users (username, password_hash, created_at) VALUES (N'alice', N'x', N'2026-11-01T00:00:00+00:00')"
        )
        long_name = "the very long name of a group that kept going " + "and going " * 5
        for name in ["gym gremlins", "g" * GROUP_NAME_MAX_LENGTH, long_name]:
            conn.execute(
                "INSERT INTO dbo.groups (name, invite_code, created_by, created_at) "
                "VALUES (%s, %s, 1, N'2026-11-01T00:00:00+00:00')",
                (name, f"CODE{len(name):04d}"),
            )
        conn.commit()

        shutil.copy(MIGRATIONS / "002_limit_group_names.sql", tmp_path)
        assert apply_migrations(conn, tmp_path, "2026-11-27T10:00:00+00:00") == ["002_limit_group_names"]

        names = [row["name"] for row in conn.execute("SELECT name FROM dbo.groups ORDER BY id").fetchall()]
        assert names == ["gym gremlins", "g" * GROUP_NAME_MAX_LENGTH, long_name[:GROUP_NAME_MAX_LENGTH].rstrip()]
        assert column_chars(conn, "groups", "name") == GROUP_NAME_MAX_LENGTH
    finally:
        conn.close()
        sqlserver.drop_database(url)
