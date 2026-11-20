"""SQL for users, sessions and groups. The schema lives in migrations/001_init.sql."""

from app.shared.database import is_duplicate_key


def insert_user(conn, username, password_hash, created_at):
    return conn.execute(
        "INSERT INTO users (username, password_hash, created_at) OUTPUT INSERTED.id VALUES (%s, %s, %s)",
        (username, password_hash, created_at),
    ).fetchone()["id"]


def get_user_by_username(conn, username):
    return conn.execute(
        "SELECT * FROM users WHERE username = %s", (username,)
    ).fetchone()


def get_user_by_id(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def insert_session(conn, session_id, user_id, created_at, expires_at):
    conn.execute(
        "INSERT INTO sessions (id, user_id, created_at, expires_at)"
        " VALUES (%s, %s, %s, %s)",
        (session_id, user_id, created_at, expires_at),
    )


def get_session(conn, session_id):
    return conn.execute(
        "SELECT * FROM sessions WHERE id = %s", (session_id,)
    ).fetchone()


def delete_session(conn, session_id):
    conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))


def insert_group(conn, name, invite_code, created_by, created_at):
    return conn.execute(
        "INSERT INTO groups (name, invite_code, created_by, created_at)"
        " OUTPUT INSERTED.id VALUES (%s, %s, %s, %s)",
        (name, invite_code, created_by, created_at),
    ).fetchone()["id"]


def get_group_by_invite_code(conn, invite_code):
    return conn.execute(
        "SELECT * FROM groups WHERE invite_code = %s", (invite_code,)
    ).fetchone()


def get_group_by_id(conn, group_id):
    return conn.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()


def add_group_member(conn, group_id, user_id, joined_at):
    """Joining a group you're already in changes nothing (the primary key says so).

    A duplicate key fails only this statement; the rest of the request's
    transaction carries on.
    """
    try:
        conn.execute(
            "INSERT INTO group_members (group_id, user_id, joined_at) VALUES (%s, %s, %s)",
            (group_id, user_id, joined_at),
        )
    except Exception as exc:
        if not is_duplicate_key(exc, "PK_group_members"):
            raise


def list_groups_for_user(conn, user_id):
    return conn.execute(
        """
        SELECT groups.* FROM groups
        JOIN group_members ON group_members.group_id = groups.id
        WHERE group_members.user_id = %s
        ORDER BY groups.created_at
        """,
        (user_id,),
    ).fetchall()


def is_group_member(conn, group_id, user_id):
    row = conn.execute(
        "SELECT 1 AS found FROM group_members WHERE group_id = %s AND user_id = %s",
        (group_id, user_id),
    ).fetchone()
    return row is not None


def group_exists(conn, group_id):
    row = conn.execute("SELECT 1 AS found FROM groups WHERE id = %s", (group_id,)).fetchone()
    return row is not None


def count_group_members(conn, group_id):
    return conn.execute(
        "SELECT COUNT(*) AS n FROM group_members WHERE group_id = %s", (group_id,)
    ).fetchone()["n"]


def list_group_members(conn, group_id):
    return conn.execute(
        """
        SELECT users.id, users.username, group_members.joined_at FROM group_members
        JOIN users ON users.id = group_members.user_id
        WHERE group_members.group_id = %s
        ORDER BY users.id
        """,
        (group_id,),
    ).fetchall()
