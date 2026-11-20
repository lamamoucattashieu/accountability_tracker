"""SQL for the points ledger, forfeits, settlements and group snapshots.

The schema lives in migrations/001_init.sql. Every value is passed as a
parameter (%s / %(name)s), never formatted into the SQL: no SQL injection.
Points stores the other service's ids (check-in, group, user, goal) without
foreign keys: that data lives in Checkins' database (ADR-3, ADR-6).
"""

import json

from app.shared.database import LOCK_TIMEOUT_MS, is_duplicate_key


def insert_event(
    conn, checkin_id, group_id, user_id, goal_id, times_per_week, week_start, completed_at
):
    """Returns False if this check-in was already recorded.

    Only a duplicate of UQ_point_events_checkin counts as "already recorded";
    a CHECK or NOT NULL violation still raises, as in A1. A duplicate key fails
    only this statement, so the caller's transaction carries on.
    """
    try:
        conn.execute(
            """
            INSERT INTO point_events
                (checkin_id, group_id, user_id, goal_id, times_per_week, week_start, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (checkin_id, group_id, user_id, goal_id, times_per_week, week_start, completed_at),
        )
    except Exception as exc:
        if is_duplicate_key(exc, "UQ_point_events_checkin"):
            return False
        raise
    return True


def revoke_event(conn, checkin_id, revoked_at):
    """Returns True only for the call that actually revoked the event."""
    cur = conn.execute(
        """
        UPDATE point_events SET revoked_at = %s
        WHERE checkin_id = %s AND revoked_at IS NULL
        """,
        (revoked_at, checkin_id),
    )
    return cur.rowcount == 1


# Members come in as a JSON list of ids (from Checkins), so members with no
# points are ranked too, without reading another service's tables.
WEEKLY_RANKING_SQL = """
WITH members(user_id) AS (
    SELECT user_id FROM OPENJSON(%(member_ids)s) WITH (user_id INT '$')
),
numbered AS (
    -- Valid completions of this week and the previous one, numbered per goal and
    -- week. nth decides which ones score; done and latest_target decide whether
    -- the goal hit its weekly target (judged by the week's latest check-in).
    SELECT user_id, goal_id, week_start, times_per_week,
           ROW_NUMBER() OVER (PARTITION BY goal_id, week_start ORDER BY completed_at, checkin_id) AS nth,
           COUNT(*) OVER (PARTITION BY goal_id, week_start) AS done,
           FIRST_VALUE(times_per_week) OVER (
               PARTITION BY goal_id, week_start
               ORDER BY completed_at DESC, checkin_id DESC
           ) AS latest_target
    FROM point_events
    WHERE group_id = %(group_id)s
      AND week_start IN (%(week_start)s, %(previous_week_start)s)
      AND revoked_at IS NULL
),
base AS (
    -- Only the first times_per_week completions per goal score (a revoked one frees its slot).
    SELECT user_id,
           SUM(CASE WHEN nth <= times_per_week THEN 1 ELSE 0 END) * %(points_per_completion)s AS points
    FROM numbered
    WHERE week_start = %(week_start)s
    GROUP BY user_id
),
hits AS (
    SELECT DISTINCT user_id, goal_id, week_start
    FROM numbered
    WHERE done >= latest_target
),
streaks AS (
    -- A goal hit both this week and last week is on a streak of 2+ weeks.
    SELECT this_week.user_id, COUNT(*) * %(streak_bonus)s AS bonus
    FROM hits AS this_week
    JOIN hits AS last_week
      ON last_week.goal_id = this_week.goal_id
     AND last_week.week_start = %(previous_week_start)s
    WHERE this_week.week_start = %(week_start)s
    GROUP BY this_week.user_id
),
totals AS (
    SELECT members.user_id,
           COALESCE(base.points, 0) + COALESCE(streaks.bonus, 0) AS points,
           COALESCE(streaks.bonus, 0) AS streak_bonus
    FROM members
    LEFT JOIN base ON base.user_id = members.user_id
    LEFT JOIN streaks ON streaks.user_id = members.user_id
)
SELECT user_id, points, streak_bonus,
       RANK() OVER (ORDER BY points DESC) AS rank
FROM totals
ORDER BY rank, user_id
"""


def weekly_ranking(conn, group_id, week_start, previous_week_start, member_ids,
                   points_per_completion, streak_bonus):
    return conn.execute(
        WEEKLY_RANKING_SQL,
        {
            "member_ids": json.dumps(member_ids),
            "group_id": group_id,
            "week_start": week_start,
            "previous_week_start": previous_week_start,
            "points_per_completion": points_per_completion,
            "streak_bonus": streak_bonus,
        },
    ).fetchall()


# --- forfeits ---

def insert_forfeit(conn, group_id, text, set_by, created_at):
    return conn.execute(
        "INSERT INTO forfeits (group_id, text, set_by, created_at) OUTPUT INSERTED.id VALUES (%s, %s, %s, %s)",
        (group_id, text, set_by, created_at),
    ).fetchone()["id"]


def get_forfeit(conn, forfeit_id):
    return conn.execute("SELECT * FROM forfeits WHERE id = %s", (forfeit_id,)).fetchone()


def list_forfeits(conn, group_id):
    return conn.execute(
        "SELECT * FROM forfeits WHERE group_id = %s ORDER BY created_at, id", (group_id,)
    ).fetchall()


# --- settlements ---

def lock_group_for_settlement(conn, group_id) -> bool:
    """Take this group's settlement lock for the rest of the transaction.

    A named lock in the database (sp_getapplock): a second request settling the
    same group waits here, then sees the week settled. Returns False if it
    waited LOCK_TIMEOUT_MS without getting it.
    """
    row = conn.execute(
        """
        DECLARE @result INT;
        EXEC @result = sp_getapplock @Resource = %s, @LockMode = 'Exclusive',
                                     @LockOwner = 'Transaction', @LockTimeout = %s;
        SELECT @result AS result;
        """,
        (f"settle-group-{group_id}", LOCK_TIMEOUT_MS),
    ).fetchone()
    return row["result"] >= 0


def settled_week_starts(conn, group_id):
    rows = conn.execute(
        "SELECT week_start FROM settlements WHERE group_id = %s", (group_id,)
    ).fetchall()
    return {row["week_start"] for row in rows}


def get_settlement(conn, group_id, week_start):
    return conn.execute(
        "SELECT * FROM settlements WHERE group_id = %s AND week_start = %s", (group_id, week_start)
    ).fetchone()


def insert_settlement(conn, group_id, week_start, forfeit_id, settled_at):
    return conn.execute(
        """
        INSERT INTO settlements (group_id, week_start, forfeit_id, settled_at)
        OUTPUT INSERTED.id
        VALUES (%s, %s, %s, %s)
        """,
        (group_id, week_start, forfeit_id, settled_at),
    ).fetchone()["id"]


def insert_assignment(conn, settlement_id, user_id, score):
    conn.execute(
        "INSERT INTO forfeit_assignments (settlement_id, user_id, score) VALUES (%s, %s, %s)",
        (settlement_id, user_id, score),
    )


def list_settlements(conn, group_id):
    return conn.execute(
        """
        SELECT settlements.*, forfeits.text AS forfeit_text
        FROM settlements
        LEFT JOIN forfeits ON forfeits.id = settlements.forfeit_id
        WHERE settlements.group_id = %s
        ORDER BY settlements.week_start DESC
        """,
        (group_id,),
    ).fetchall()


# The proof photo's bytes are never selected here: only get_proof_photo reads them.
ASSIGNMENT_COLUMNS = """
    forfeit_assignments.id, forfeit_assignments.settlement_id, forfeit_assignments.user_id,
    forfeit_assignments.score, forfeit_assignments.proof_at
"""


def list_assignments(conn, group_id):
    return conn.execute(
        f"""
        SELECT {ASSIGNMENT_COLUMNS}, settlements.settled_at
        FROM forfeit_assignments
        JOIN settlements ON settlements.id = forfeit_assignments.settlement_id
        WHERE settlements.group_id = %s
        ORDER BY forfeit_assignments.settlement_id, forfeit_assignments.user_id
        """,
        (group_id,),
    ).fetchall()


# --- proof ---

def get_assignment(conn, assignment_id):
    return conn.execute(
        f"""
        SELECT {ASSIGNMENT_COLUMNS}, settlements.group_id, settlements.settled_at
        FROM forfeit_assignments
        JOIN settlements ON settlements.id = forfeit_assignments.settlement_id
        WHERE forfeit_assignments.id = %s
        """,
        (assignment_id,),
    ).fetchone()


def set_proof(conn, assignment_id, proof_photo, proof_type, proof_at):
    """Returns True only for the upload that actually stored the proof (once per assignment)."""
    cur = conn.execute(
        """
        UPDATE forfeit_assignments SET proof_photo = %s, proof_type = %s, proof_at = %s
        WHERE id = %s AND proof_at IS NULL
        """,
        (proof_photo, proof_type, proof_at, assignment_id),
    )
    return cur.rowcount == 1


def get_proof_photo(conn, assignment_id):
    return conn.execute(
        "SELECT proof_photo, proof_type FROM forfeit_assignments WHERE id = %s AND proof_at IS NOT NULL",
        (assignment_id,),
    ).fetchone()


# --- group snapshots ---

def save_group_snapshot(conn, group: dict, fetched_at):
    """Update the group's snapshot, or add it if Points has never seen the group."""
    values = (group["created_at"], json.dumps(group["members"]), int(group["pending_points_sync"]),
              fetched_at, group["id"])
    cur = conn.execute(
        """
        UPDATE group_snapshots
        SET created_at = %s, members = %s, pending_points_sync = %s, fetched_at = %s
        WHERE group_id = %s
        """,
        values,
    )
    if cur.rowcount == 0:
        try:
            conn.execute(
                """
                INSERT INTO group_snapshots (created_at, members, pending_points_sync, fetched_at, group_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                values,
            )
        except Exception as exc:
            if not is_duplicate_key(exc, "PK_group_snapshots"):
                raise  # a request that inserted the same group first is fine: it's a cache


def get_group_snapshot(conn, group_id):
    row = conn.execute("SELECT * FROM group_snapshots WHERE group_id = %s", (group_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["group_id"],
        "created_at": row["created_at"],
        "members": json.loads(row["members"]),
        "pending_points_sync": bool(row["pending_points_sync"]),
        "fetched_at": row["fetched_at"],
    }
