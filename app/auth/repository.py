CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL REFERENCES groups(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
"""


def create_tables(conn):
    conn.executescript(CREATE_TABLES_SQL)


def insert_user(conn, username, password_hash, created_at):
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, created_at),
    )
    return cur.lastrowid


def get_user_by_username(conn, username):
    return conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()


def get_user_by_id(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def insert_session(conn, session_id, user_id, created_at, expires_at):
    conn.execute(
        "INSERT INTO sessions (id, user_id, created_at, expires_at)"
        " VALUES (?, ?, ?, ?)",
        (session_id, user_id, created_at, expires_at),
    )


def get_session(conn, session_id):
    return conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()


def delete_session(conn, session_id):
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def insert_group(conn, name, invite_code, created_by, created_at):
    cur = conn.execute(
        "INSERT INTO groups (name, invite_code, created_by, created_at)"
        " VALUES (?, ?, ?, ?)",
        (name, invite_code, created_by, created_at),
    )
    return cur.lastrowid


def get_group_by_invite_code(conn, invite_code):
    return conn.execute(
        "SELECT * FROM groups WHERE invite_code = ?", (invite_code,)
    ).fetchone()


def get_group_by_id(conn, group_id):
    return conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()


def add_group_member(conn, group_id, user_id, joined_at):
    conn.execute(
        "INSERT OR IGNORE INTO group_members (group_id, user_id, joined_at)"
        " VALUES (?, ?, ?)",
        (group_id, user_id, joined_at),
    )


def list_groups_for_user(conn, user_id):
    return conn.execute(
        """
        SELECT groups.* FROM groups
        JOIN group_members ON group_members.group_id = groups.id
        WHERE group_members.user_id = ?
        ORDER BY groups.created_at
        """,
        (user_id,),
    ).fetchall()


def is_group_member(conn, group_id, user_id):
    row = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    ).fetchone()
    return row is not None


def group_exists(conn, group_id):
    row = conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone()
    return row is not None


def count_group_members(conn, group_id):
    return conn.execute(
        "SELECT COUNT(*) FROM group_members WHERE group_id = ?", (group_id,)
    ).fetchone()[0]
