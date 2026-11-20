"""SQL for goals, check-ins, votes, comments, nudges and the points outbox.

The schema lives in migrations/001_init.sql. Every value is passed as a
parameter (%s), never formatted into the SQL: no SQL injection.
"""


def insert_goal(conn, group_id, user_id, title, description, times_per_week, created_at):
    cur = conn.execute(
        """
        INSERT INTO goals
            (group_id, user_id, title, description, times_per_week, created_at)
        OUTPUT INSERTED.id
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (group_id, user_id, title, description, times_per_week, created_at),
    )
    return cur.fetchone()["id"]


def get_goal_by_id(conn, goal_id):
    return conn.execute("SELECT * FROM goals WHERE id = %s", (goal_id,)).fetchone()


def list_active_goals_for_group(conn, group_id):
    return conn.execute(
        """
        SELECT * FROM goals
        WHERE group_id = %s AND archived_at IS NULL
        ORDER BY created_at, id
        """,
        (group_id,),
    ).fetchall()


def update_goal(conn, goal_id, title, description, times_per_week):
    conn.execute(
        """
        UPDATE goals SET title = %s, description = %s, times_per_week = %s
        WHERE id = %s
        """,
        (title, description, times_per_week, goal_id),
    )


def set_archived_at(conn, goal_id, archived_at):
    conn.execute(
        "UPDATE goals SET archived_at = %s WHERE id = %s", (archived_at, goal_id)
    )


def insert_checkin(conn, goal_id, photo, photo_type, caption, created_at):
    cur = conn.execute(
        """
        INSERT INTO checkins (goal_id, photo, photo_type, caption, created_at)
        OUTPUT INSERTED.id
        VALUES (%s, %s, %s, %s, %s)
        """,
        (goal_id, photo, photo_type, caption, created_at),
    )
    return cur.fetchone()["id"]


# Joining goals is fine here: both tables belong to this domain. The photo
# column is never selected here: only get_checkin_photo reads the bytes.
CHECKIN_WITH_GOAL_SQL = """
    SELECT checkins.id, checkins.goal_id, checkins.caption, checkins.status, checkins.created_at,
           goals.group_id, goals.user_id, goals.title AS goal_title,
           (SELECT COUNT(*) FROM checkin_comments
            WHERE checkin_comments.checkin_id = checkins.id) AS comment_count,
           CASE WHEN EXISTS (SELECT 1 FROM points_outbox
                             WHERE points_outbox.checkin_id = checkins.id
                               AND points_outbox.sent_at IS NULL
                               AND points_outbox.failed_at IS NULL)
                THEN 1 ELSE 0 END AS points_pending
    FROM checkins
    JOIN goals ON goals.id = checkins.goal_id
"""


def get_checkin_photo(conn, checkin_id):
    return conn.execute(
        "SELECT photo, photo_type FROM checkins WHERE id = %s", (checkin_id,)
    ).fetchone()


def get_checkin(conn, checkin_id):
    return conn.execute(
        CHECKIN_WITH_GOAL_SQL + " WHERE checkins.id = %s", (checkin_id,)
    ).fetchone()


def list_checkins_for_group(conn, group_id, limit):
    return conn.execute(
        CHECKIN_WITH_GOAL_SQL.replace("SELECT", "SELECT TOP (%s)", 1)
        + """
        WHERE goals.group_id = %s
        ORDER BY checkins.created_at DESC, checkins.id DESC
        """,
        (limit, group_id),
    ).fetchall()


def insert_vote(conn, checkin_id, voter_id, created_at):
    conn.execute(
        "INSERT INTO checkin_votes (checkin_id, voter_id, created_at) VALUES (%s, %s, %s)",
        (checkin_id, voter_id, created_at),
    )


def has_voted(conn, checkin_id, voter_id):
    row = conn.execute(
        "SELECT 1 AS found FROM checkin_votes WHERE checkin_id = %s AND voter_id = %s",
        (checkin_id, voter_id),
    ).fetchone()
    return row is not None


def count_votes(conn, checkin_id):
    return conn.execute(
        "SELECT COUNT(*) AS n FROM checkin_votes WHERE checkin_id = %s", (checkin_id,)
    ).fetchone()["n"]


def mark_rejected(conn, checkin_id):
    """Flip accepted -> rejected. Returns True only for the call that actually flipped it."""
    cur = conn.execute(
        "UPDATE checkins SET status = 'rejected' WHERE id = %s AND status = 'accepted'",
        (checkin_id,),
    )
    return cur.rowcount == 1


def insert_comment(conn, checkin_id, author_id, text, created_at):
    cur = conn.execute(
        "INSERT INTO checkin_comments (checkin_id, author_id, text, created_at)"
        " OUTPUT INSERTED.id VALUES (%s, %s, %s, %s)",
        (checkin_id, author_id, text, created_at),
    )
    return cur.fetchone()["id"]


def list_comments(conn, checkin_id):
    return conn.execute(
        """
        SELECT id, checkin_id, author_id, text, created_at FROM checkin_comments
        WHERE checkin_id = %s
        ORDER BY created_at, id
        """,
        (checkin_id,),
    ).fetchall()


# --- nudges ---

def goal_progress(conn, group_id, since):
    """Each active goal with its accepted check-ins since `since` (the week's start)."""
    return conn.execute(
        """
        SELECT goals.id AS goal_id, goals.user_id, goals.times_per_week,
               (SELECT COUNT(*) FROM checkins
                WHERE checkins.goal_id = goals.id
                  AND checkins.status = 'accepted'
                  AND checkins.created_at >= %s) AS done
        FROM goals
        WHERE goals.group_id = %s AND goals.archived_at IS NULL
        """,
        (since, group_id),
    ).fetchall()


def users_who_posted_since(conn, group_id, since):
    rows = conn.execute(
        """
        SELECT DISTINCT goals.user_id FROM checkins
        JOIN goals ON goals.id = checkins.goal_id
        WHERE goals.group_id = %s AND checkins.created_at >= %s
        """,
        (group_id, since),
    ).fetchall()
    return {row["user_id"] for row in rows}


def insert_nudge(conn, group_id, nudger_id, nudged_id, message, day, created_at):
    cur = conn.execute(
        """
        INSERT INTO nudges (group_id, nudger_id, nudged_id, message, day, created_at)
        OUTPUT INSERTED.id
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (group_id, nudger_id, nudged_id, message, day, created_at),
    )
    return cur.fetchone()["id"]


def nudges_sent_on(conn, group_id, nudger_id, day):
    rows = conn.execute(
        "SELECT nudged_id FROM nudges WHERE group_id = %s AND nudger_id = %s AND day = %s",
        (group_id, nudger_id, day),
    ).fetchall()
    return {row["nudged_id"] for row in rows}


def nudges_received_on(conn, group_id, nudged_id, day):
    return conn.execute(
        """
        SELECT id, nudger_id, message, created_at FROM nudges
        WHERE group_id = %s AND nudged_id = %s AND day = %s
        ORDER BY created_at, id
        """,
        (group_id, nudged_id, day),
    ).fetchall()


# --- points outbox ---

def insert_outbox(conn, kind, checkin_id, group_id, payload, created_at):
    conn.execute(
        """
        INSERT INTO points_outbox (kind, checkin_id, group_id, payload, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (kind, checkin_id, group_id, payload, created_at),
    )


def pending_outbox(conn, limit):
    """Oldest first, so a check-in's revoke is never sent before its record."""
    return conn.execute(
        """
        SELECT TOP (%s) * FROM points_outbox
        WHERE sent_at IS NULL AND failed_at IS NULL
        ORDER BY id
        """,
        (limit,),
    ).fetchall()


def mark_outbox_sent(conn, outbox_id, sent_at):
    conn.execute("UPDATE points_outbox SET sent_at = %s WHERE id = %s", (sent_at, outbox_id))


def mark_outbox_failed(conn, outbox_id, failed_at, error):
    conn.execute(
        "UPDATE points_outbox SET failed_at = %s, last_error = %s WHERE id = %s",
        (failed_at, error, outbox_id),
    )


def note_outbox_error(conn, outbox_id, error):
    conn.execute("UPDATE points_outbox SET last_error = %s WHERE id = %s", (error, outbox_id))


def group_has_pending_outbox(conn, group_id):
    row = conn.execute(
        """
        SELECT TOP 1 1 AS pending FROM points_outbox
        WHERE group_id = %s AND sent_at IS NULL AND failed_at IS NULL
        """,
        (group_id,),
    ).fetchone()
    return row is not None
