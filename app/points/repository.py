import json

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
"""


def create_tables(conn):
    conn.executescript(CREATE_TABLES_SQL)


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
    SELECT value FROM json_each(?)
),
numbered AS (
    -- Number each goal's valid check-ins in order; only the first
    -- times_per_week of them score (a revoked one frees its slot).
    SELECT user_id, times_per_week,
           ROW_NUMBER() OVER (PARTITION BY goal_id ORDER BY completed_at, checkin_id) AS nth
    FROM point_events
    WHERE group_id = ? AND week_start = ? AND revoked_at IS NULL
),
totals AS (
    SELECT user_id, SUM(nth <= times_per_week) * ? AS points
    FROM numbered
    GROUP BY user_id
)
SELECT members.user_id,
       COALESCE(totals.points, 0) AS points,
       RANK() OVER (ORDER BY COALESCE(totals.points, 0) DESC) AS rank
FROM members
LEFT JOIN totals ON totals.user_id = members.user_id
ORDER BY rank, members.user_id
"""


def weekly_ranking(conn, group_id, week_start, member_ids, points_per_completion):
    return conn.execute(
        WEEKLY_RANKING_SQL,
        (json.dumps(member_ids), group_id, week_start, points_per_completion),
    ).fetchall()
