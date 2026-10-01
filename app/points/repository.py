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

