CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    description TEXT,
    times_per_week INTEGER NOT NULL CHECK (times_per_week BETWEEN 1 AND 7),
    created_at TEXT NOT NULL,
    archived_at TEXT
);
"""


def create_tables(conn):
    conn.executescript(CREATE_TABLES_SQL)


def insert_goal(conn, group_id, user_id, title, description, times_per_week, created_at):
    cur = conn.execute(
        """
        INSERT INTO goals
            (group_id, user_id, title, description, times_per_week, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (group_id, user_id, title, description, times_per_week, created_at),
    )
    return cur.lastrowid


def get_goal_by_id(conn, goal_id):
    return conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()


def list_active_goals_for_group(conn, group_id):
    return conn.execute(
        """
        SELECT * FROM goals
        WHERE group_id = ? AND archived_at IS NULL
        ORDER BY created_at, id
        """,
        (group_id,),
    ).fetchall()


def update_goal(conn, goal_id, title, description, times_per_week):
    conn.execute(
        """
        UPDATE goals SET title = ?, description = ?, times_per_week = ?
        WHERE id = ?
        """,
        (title, description, times_per_week, goal_id),
    )


def set_archived_at(conn, goal_id, archived_at):
    conn.execute(
        "UPDATE goals SET archived_at = ? WHERE id = ?", (archived_at, goal_id)
    )
