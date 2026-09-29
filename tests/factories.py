from app.auth import repository as auth_repository
from app.auth.security import new_invite_code
from app.shared.timeutils import utc_now_iso


def make_user(conn, username):
    # Insert directly: register() hashes the password, which is slow and irrelevant here.
    return auth_repository.insert_user(conn, username, "not-a-real-hash", utc_now_iso())


def make_group(conn, *member_ids):
    now = utc_now_iso()
    group_id = auth_repository.insert_group(
        conn, "friends", new_invite_code(), member_ids[0], now
    )
    for user_id in member_ids:
        auth_repository.add_group_member(conn, group_id, user_id, now)
    return group_id
