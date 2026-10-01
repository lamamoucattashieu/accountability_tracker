import json

from app.config import FORFEIT_MAX_LENGTH

# Points stores other domains' ids (checkin, group, user, goal) without foreign
# keys: they arrive only through record_completion, and keeping the tables free
# of cross-domain references means a future split doesn't have to drop any (ADR-2).
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS point_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_id INTEGER NOT NULL UNIQUE,
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    goal_id INTEGER NOT NULL,
    times_per_week INTEGER NOT NULL CHECK (times_per_week BETWEEN 1 AND 7),
    week_start TEXT NOT NULL CHECK (strftime('%w', week_start) = '1'),
    completed_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_point_events_group_week
    ON point_events (group_id, week_start);

-- Append-only: a forfeit is never updated or deleted, so past weeks keep theirs.
CREATE TABLE IF NOT EXISTS forfeits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND {FORFEIT_MAX_LENGTH}),
    set_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

-- One row per group and week: UNIQUE makes settling a week twice impossible.
CREATE TABLE IF NOT EXISTS settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    week_start TEXT NOT NULL CHECK (strftime('%w', week_start) = '1'),
    forfeit_id INTEGER REFERENCES forfeits(id),
    settled_at TEXT NOT NULL,
    UNIQUE (group_id, week_start)
);

-- One row per loser of a settled week; score is frozen at settlement.
CREATE TABLE IF NOT EXISTS forfeit_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settlement_id INTEGER NOT NULL REFERENCES settlements(id),
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    proof_path TEXT,
    proof_at TEXT,
    UNIQUE (settlement_id, user_id),
    CHECK ((proof_path IS NULL) = (proof_at IS NULL))
);
"""


def create_tables(conn):
    # The forfeit length limit comes from config.py, so it isn't duplicated as a magic number.
    conn.executescript(CREATE_TABLES_SQL.replace("{FORFEIT_MAX_LENGTH}", str(FORFEIT_MAX_LENGTH)))


def insert_event(
    conn, checkin_id, group_id, user_id, goal_id, times_per_week, week_start, completed_at
):
    """Returns False if this check-in was already recorded.

    ON CONFLICT (checkin_id) ignores only the duplicate; unlike INSERT OR IGNORE,
    a CHECK or NOT NULL violation still raises.
    """
    cur = conn.execute(
        """
        INSERT INTO point_events
            (checkin_id, group_id, user_id, goal_id, times_per_week, week_start, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (checkin_id) DO NOTHING
        """,
        (checkin_id, group_id, user_id, goal_id, times_per_week, week_start, completed_at),
    )
    return cur.rowcount == 1


def revoke_event(conn, checkin_id, revoked_at):
    """Returns True only for the call that actually revoked the event."""
    cur = conn.execute(
        """
        UPDATE point_events SET revoked_at = ?
        WHERE checkin_id = ? AND revoked_at IS NULL
        """,
        (revoked_at, checkin_id),
    )
    return cur.rowcount == 1



# Members come in as a JSON list of ids (from the auth service), so members with
# no points are ranked too, without joining another domain's tables.
WEEKLY_RANKING_SQL = """
WITH members(user_id) AS (
    SELECT value FROM json_each(:member_ids)
),
numbered AS (
    -- Valid completions of this week and the previous one, numbered per goal and
    -- week. nth decides which ones score; done and latest_target decide whether
    -- the goal hit its weekly target (judged by the week's latest check-in).
    SELECT user_id, goal_id, week_start, times_per_week,
           ROW_NUMBER() OVER goal_week AS nth,
           COUNT(*) OVER (PARTITION BY goal_id, week_start) AS done,
           FIRST_VALUE(times_per_week) OVER (
               PARTITION BY goal_id, week_start
               ORDER BY completed_at DESC, checkin_id DESC
           ) AS latest_target
    FROM point_events
    WHERE group_id = :group_id
      AND week_start IN (:week_start, :previous_week_start)
      AND revoked_at IS NULL
    WINDOW goal_week AS (PARTITION BY goal_id, week_start ORDER BY completed_at, checkin_id)
),
base AS (
    -- Only the first times_per_week completions per goal score (a revoked one frees its slot).
    SELECT user_id, SUM(nth <= times_per_week) * :points_per_completion AS points
    FROM numbered
    WHERE week_start = :week_start
    GROUP BY user_id
),
hits AS (
    SELECT DISTINCT user_id, goal_id, week_start
    FROM numbered
    WHERE done >= latest_target
),
streaks AS (
    -- A goal hit both this week and last week is on a streak of 2+ weeks.
    SELECT this_week.user_id, COUNT(*) * :streak_bonus AS bonus
    FROM hits AS this_week
    JOIN hits AS last_week
      ON last_week.goal_id = this_week.goal_id
     AND last_week.week_start = :previous_week_start
    WHERE this_week.week_start = :week_start
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
    cur = conn.execute(
        "INSERT INTO forfeits (group_id, text, set_by, created_at) VALUES (?, ?, ?, ?)",
        (group_id, text, set_by, created_at),
    )
    return cur.lastrowid


def get_forfeit(conn, forfeit_id):
    return conn.execute("SELECT * FROM forfeits WHERE id = ?", (forfeit_id,)).fetchone()


def list_forfeits(conn, group_id):
    return conn.execute(
        "SELECT * FROM forfeits WHERE group_id = ? ORDER BY created_at, id", (group_id,)
    ).fetchall()


# --- settlements ---

def settled_week_starts(conn, group_id):
    rows = conn.execute(
        "SELECT week_start FROM settlements WHERE group_id = ?", (group_id,)
    ).fetchall()
    return {row["week_start"] for row in rows}


def get_settlement(conn, group_id, week_start):
    return conn.execute(
        "SELECT * FROM settlements WHERE group_id = ? AND week_start = ?", (group_id, week_start)
    ).fetchone()


def insert_settlement(conn, group_id, week_start, forfeit_id, settled_at):
    cur = conn.execute(
        """
        INSERT INTO settlements (group_id, week_start, forfeit_id, settled_at)
        VALUES (?, ?, ?, ?)
        """,
        (group_id, week_start, forfeit_id, settled_at),
    )
    return cur.lastrowid


def insert_assignment(conn, settlement_id, user_id, score):
    conn.execute(
        "INSERT INTO forfeit_assignments (settlement_id, user_id, score) VALUES (?, ?, ?)",
        (settlement_id, user_id, score),
    )


def list_settlements(conn, group_id):
    return conn.execute(
        """
        SELECT settlements.*, forfeits.text AS forfeit_text
        FROM settlements
        LEFT JOIN forfeits ON forfeits.id = settlements.forfeit_id
        WHERE settlements.group_id = ?
        ORDER BY settlements.week_start DESC
        """,
        (group_id,),
    ).fetchall()


def list_assignments(conn, group_id):
    return conn.execute(
        """
        SELECT forfeit_assignments.*, settlements.settled_at
        FROM forfeit_assignments
        JOIN settlements ON settlements.id = forfeit_assignments.settlement_id
        WHERE settlements.group_id = ?
        ORDER BY forfeit_assignments.settlement_id, forfeit_assignments.user_id
        """,
        (group_id,),
    ).fetchall()



# --- proof ---

def get_assignment(conn, assignment_id):
    return conn.execute(
        """
        SELECT forfeit_assignments.*, settlements.group_id, settlements.settled_at
        FROM forfeit_assignments
        JOIN settlements ON settlements.id = forfeit_assignments.settlement_id
        WHERE forfeit_assignments.id = ?
        """,
        (assignment_id,),
    ).fetchone()


def set_proof(conn, assignment_id, proof_path, proof_at):
    """Returns True only for the upload that actually stored the proof (once per assignment)."""
    cur = conn.execute(
        """
        UPDATE forfeit_assignments SET proof_path = ?, proof_at = ?
        WHERE id = ? AND proof_path IS NULL
        """,
        (proof_path, proof_at, assignment_id),
    )
    return cur.rowcount == 1
