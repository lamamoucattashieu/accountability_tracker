from app.config import COMMENT_MAX_LENGTH

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

CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    photo_path TEXT NOT NULL,
    caption TEXT,
    status TEXT NOT NULL DEFAULT 'accepted' CHECK (status IN ('accepted', 'rejected')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkin_votes (
    checkin_id INTEGER NOT NULL REFERENCES checkins(id),
    voter_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (checkin_id, voter_id)
);

CREATE TABLE IF NOT EXISTS checkin_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_id INTEGER NOT NULL REFERENCES checkins(id),
    author_id INTEGER NOT NULL REFERENCES users(id),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND {COMMENT_MAX_LENGTH}),
    created_at TEXT NOT NULL
);
"""


def create_tables(conn):
    # The comment length limit comes from config.py, so it isn't a duplicated magic number.
    conn.executescript(CREATE_TABLES_SQL.replace("{COMMENT_MAX_LENGTH}", str(COMMENT_MAX_LENGTH)))


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


def insert_checkin(conn, goal_id, photo_path, caption, created_at):
    cur = conn.execute(
        """
        INSERT INTO checkins (goal_id, photo_path, caption, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (goal_id, photo_path, caption, created_at),
    )
    return cur.lastrowid


# Joining goals is fine here: both tables belong to this domain.
CHECKIN_WITH_GOAL_SQL = """
    SELECT checkins.*, goals.group_id, goals.user_id, goals.title AS goal_title,
           (SELECT COUNT(*) FROM checkin_comments
            WHERE checkin_comments.checkin_id = checkins.id) AS comment_count
    FROM checkins
    JOIN goals ON goals.id = checkins.goal_id
"""


def get_checkin(conn, checkin_id):
    return conn.execute(
        CHECKIN_WITH_GOAL_SQL + " WHERE checkins.id = ?", (checkin_id,)
    ).fetchone()


def list_checkins_for_group(conn, group_id, limit):
    return conn.execute(
        CHECKIN_WITH_GOAL_SQL
        + """
        WHERE goals.group_id = ?
        ORDER BY checkins.created_at DESC, checkins.id DESC
        LIMIT ?
        """,
        (group_id, limit),
    ).fetchall()


def insert_vote(conn, checkin_id, voter_id, created_at):
    conn.execute(
        "INSERT INTO checkin_votes (checkin_id, voter_id, created_at) VALUES (?, ?, ?)",
        (checkin_id, voter_id, created_at),
    )


def has_voted(conn, checkin_id, voter_id):
    row = conn.execute(
        "SELECT 1 FROM checkin_votes WHERE checkin_id = ? AND voter_id = ?",
        (checkin_id, voter_id),
    ).fetchone()
    return row is not None


def count_votes(conn, checkin_id):
    return conn.execute(
        "SELECT COUNT(*) FROM checkin_votes WHERE checkin_id = ?", (checkin_id,)
    ).fetchone()[0]


def mark_rejected(conn, checkin_id):
    """Flip accepted -> rejected. Returns True only for the call that actually flipped it."""
    cur = conn.execute(
        "UPDATE checkins SET status = 'rejected' WHERE id = ? AND status = 'accepted'",
        (checkin_id,),
    )
    return cur.rowcount == 1


def insert_comment(conn, checkin_id, author_id, text, created_at):
    cur = conn.execute(
        "INSERT INTO checkin_comments (checkin_id, author_id, text, created_at) VALUES (?, ?, ?, ?)",
        (checkin_id, author_id, text, created_at),
    )
    return cur.lastrowid


def list_comments(conn, checkin_id):
    return conn.execute(
        """
        SELECT id, checkin_id, author_id, text, created_at FROM checkin_comments
        WHERE checkin_id = ?
        ORDER BY created_at, id
        """,
        (checkin_id,),
    ).fetchall()
