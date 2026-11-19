from app.auth import repository as auth_repository
from app.auth.security import new_invite_code
from app.shared.timeutils import utc_now_iso


# user id -> username of the users made in the current test. Points responses
# carry user ids only (the UI takes names from Checkins), so tests use this to
# keep their assertions readable.
_usernames = {}


def make_user(conn, username):
    # Insert directly: register() hashes the password, which is slow and irrelevant here.
    user_id = auth_repository.insert_user(conn, username, "not-a-real-hash", utc_now_iso())
    _usernames[user_id] = username
    return user_id


def username_of(user_id):
    return _usernames[user_id]


def make_group(conn, *member_ids):
    now = utc_now_iso()
    group_id = auth_repository.insert_group(
        conn, "friends", new_invite_code(), member_ids[0], now
    )
    for user_id in member_ids:
        auth_repository.add_group_member(conn, group_id, user_id, now)
    return group_id
