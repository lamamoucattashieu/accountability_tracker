"""A fake Checkins for Points tests, behind the GroupDirectory port.

Points owns no users or groups: it asks Checkins. These helpers keep the A1
test vocabulary (make_user, make_group, backdating a join) but write to the fake
directory instead of auth tables. `conn` is accepted and unused, so the tests
read exactly as before the split.
"""

from itertools import count

from app.points.group_directory import CheckinsUnavailable
from app.shared.timeutils import utc_now_iso


class FakeGroupDirectory:
    def __init__(self):
        self.groups = {}        # group_id -> {"created_at": iso, "members": {user_id: joined_at}}
        self.usernames = {}     # user_id -> username, for readable assertions
        self.down = False       # True: behave like Checkins timing out or refusing connections
        self.pending = set()    # group ids with points changes not yet delivered
        self._user_ids = count(1)
        self._group_ids = count(1)

    def fetch_group(self, group_id):
        if self.down:
            raise CheckinsUnavailable("checkins is down")
        group = self.groups.get(group_id)
        if group is None:
            return None
        return {
            "id": group_id,
            "created_at": group["created_at"],
            "members": [{"id": user_id, "joined_at": joined_at}
                        for user_id, joined_at in group["members"].items()],
            "pending_points_sync": group_id in self.pending,
        }


# Replaced by a fresh one before every test (see tests/conftest.py).
directory = FakeGroupDirectory()


def reset_directory():
    global directory
    directory = FakeGroupDirectory()
    return directory


def make_user(conn, username):
    user_id = next(directory._user_ids)
    directory.usernames[user_id] = username
    return user_id


def username_of(user_id):
    return directory.usernames[user_id]


def make_group(conn, *member_ids):
    now = utc_now_iso()
    group_id = next(directory._group_ids)
    directory.groups[group_id] = {"created_at": now, "members": {user_id: now for user_id in member_ids}}
    return group_id


def add_member(conn, group_id, user_id, joined_at):
    directory.groups[group_id]["members"][user_id] = joined_at


def backdate_group(conn, group_id, created_at):
    directory.groups[group_id]["created_at"] = created_at


def backdate_join(conn, group_id, user_id, joined_at):
    directory.groups[group_id]["members"][user_id] = joined_at
