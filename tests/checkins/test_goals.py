import pytest

from app.auth import repository as auth_repository
from app.auth.security import new_invite_code
from app.checkins import service
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


@pytest.fixture
def alice(conn):
    return make_user(conn, "alice")


@pytest.fixture
def bob(conn):
    return make_user(conn, "bob")


@pytest.fixture
def outsider(conn):
    return make_user(conn, "outsider")


@pytest.fixture
def group_id(conn, alice, bob):
    return make_group(conn, alice, bob)


@pytest.fixture
def goal(conn, alice, group_id):
    return service.create_goal(conn, alice, group_id, "Gym", "at least 45 min", 3)


# --- create ---

def test_create_goal_stores_fields(conn, alice, group_id):
    goal = service.create_goal(conn, alice, group_id, "Gym", "at least 45 min", 3)
    assert goal["title"] == "Gym"
    assert goal["description"] == "at least 45 min"
    assert goal["times_per_week"] == 3
    assert goal["user_id"] == alice
    assert goal["group_id"] == group_id
    assert goal["archived_at"] is None
    assert goal["created_at"].endswith("+00:00")


@pytest.mark.parametrize("times_per_week", [0, 8, -1])
def test_create_goal_rejects_times_per_week_out_of_range(conn, alice, group_id, times_per_week):
    with pytest.raises(service.InvalidGoal):
        service.create_goal(conn, alice, group_id, "Gym", None, times_per_week)


@pytest.mark.parametrize("times_per_week", [1, 7])
def test_create_goal_accepts_times_per_week_bounds(conn, alice, group_id, times_per_week):
    goal = service.create_goal(conn, alice, group_id, "Gym", None, times_per_week)
    assert goal["times_per_week"] == times_per_week


def test_create_goal_rejects_non_integer_times_per_week(conn, alice, group_id):
    with pytest.raises(service.InvalidGoal):
        service.create_goal(conn, alice, group_id, "Gym", None, True)


def test_create_goal_trims_title(conn, alice, group_id):
    goal = service.create_goal(conn, alice, group_id, "  Gym  ", None, 3)
    assert goal["title"] == "Gym"


def test_create_goal_rejects_whitespace_only_title(conn, alice, group_id):
    with pytest.raises(service.InvalidGoal):
        service.create_goal(conn, alice, group_id, "   ", None, 3)


def test_title_limit_applies_after_trimming(conn, alice, group_id):
    goal = service.create_goal(conn, alice, group_id, " " + "a" * 80 + " ", None, 3)
    assert len(goal["title"]) == 80
    with pytest.raises(service.InvalidGoal):
        service.create_goal(conn, alice, group_id, "a" * 81, None, 3)


def test_description_limit_applies_after_trimming(conn, alice, group_id):
    goal = service.create_goal(conn, alice, group_id, "Gym", " " + "d" * 500 + " ", 3)
    assert len(goal["description"]) == 500
    with pytest.raises(service.InvalidGoal):
        service.create_goal(conn, alice, group_id, "Gym", "d" * 501, 3)


@pytest.mark.parametrize("description", ["", "   ", None])
def test_empty_description_is_stored_as_null(conn, alice, group_id, description):
    goal = service.create_goal(conn, alice, group_id, "Gym", description, 3)
    assert goal["description"] is None


def test_non_member_cannot_create_goal(conn, outsider, group_id):
    with pytest.raises(service.NotGroupMember):
        service.create_goal(conn, outsider, group_id, "Gym", None, 3)


def test_create_goal_in_missing_group_is_not_found(conn, alice):
    with pytest.raises(service.GroupNotFound):
        service.create_goal(conn, alice, 999, "Gym", None, 3)


# --- list ---

def test_list_returns_active_goals_of_all_members(conn, alice, bob, group_id):
    service.create_goal(conn, alice, group_id, "Gym", None, 3)
    service.create_goal(conn, bob, group_id, "Read", None, 5)
    goals = service.list_group_goals(conn, alice, group_id)
    assert [g["title"] for g in goals] == ["Gym", "Read"]


def test_list_excludes_archived_goals(conn, alice, group_id, goal):
    service.create_goal(conn, alice, group_id, "Read", None, 5)
    service.archive_goal(conn, alice, goal["id"])
    goals = service.list_group_goals(conn, alice, group_id)
    assert [g["title"] for g in goals] == ["Read"]


def test_list_excludes_other_groups(conn, alice, bob, group_id, goal):
    other_group = make_group(conn, bob)
    service.create_goal(conn, bob, other_group, "Swim", None, 2)
    goals = service.list_group_goals(conn, alice, group_id)
    assert [g["title"] for g in goals] == ["Gym"]


def test_non_member_cannot_list_goals(conn, outsider, group_id):
    with pytest.raises(service.NotGroupMember):
        service.list_group_goals(conn, outsider, group_id)


def test_list_goals_of_missing_group_is_not_found(conn, alice):
    with pytest.raises(service.GroupNotFound):
        service.list_group_goals(conn, alice, 999)


# --- update (JSON Merge Patch) ---

def test_owner_can_update_all_fields(conn, alice, goal):
    updated = service.update_goal(
        conn, alice, goal["id"],
        {"title": "Gym!", "description": "60 min", "times_per_week": 4},
    )
    assert updated["title"] == "Gym!"
    assert updated["description"] == "60 min"
    assert updated["times_per_week"] == 4


def test_absent_fields_are_unchanged(conn, alice, goal):
    updated = service.update_goal(conn, alice, goal["id"], {"times_per_week": 5})
    assert updated["title"] == "Gym"
    assert updated["description"] == "at least 45 min"
    assert updated["times_per_week"] == 5


def test_null_description_clears_it(conn, alice, goal):
    updated = service.update_goal(conn, alice, goal["id"], {"description": None})
    assert updated["description"] is None


def test_whitespace_description_update_is_stored_as_null(conn, alice, goal):
    updated = service.update_goal(conn, alice, goal["id"], {"description": "   "})
    assert updated["description"] is None


@pytest.mark.parametrize("field", ["title", "times_per_week"])
def test_null_title_or_times_per_week_is_rejected(conn, alice, goal, field):
    with pytest.raises(service.InvalidGoal):
        service.update_goal(conn, alice, goal["id"], {field: None})


def test_update_rejects_whitespace_only_title(conn, alice, goal):
    with pytest.raises(service.InvalidGoal):
        service.update_goal(conn, alice, goal["id"], {"title": "  "})


def test_update_rejects_times_per_week_out_of_range(conn, alice, goal):
    with pytest.raises(service.InvalidGoal):
        service.update_goal(conn, alice, goal["id"], {"times_per_week": 8})


def test_non_owner_member_cannot_update(conn, bob, goal):
    with pytest.raises(service.NotGoalOwner):
        service.update_goal(conn, bob, goal["id"], {"title": "Mine now"})


def test_non_member_cannot_update(conn, outsider, goal):
    with pytest.raises(service.NotGroupMember):
        service.update_goal(conn, outsider, goal["id"], {"title": "Mine now"})


def test_update_missing_goal_is_not_found(conn, alice, group_id):
    with pytest.raises(service.GoalNotFound):
        service.update_goal(conn, alice, 999, {"title": "x"})


def test_archived_goal_cannot_be_updated(conn, alice, goal):
    service.archive_goal(conn, alice, goal["id"])
    with pytest.raises(service.GoalArchived):
        service.update_goal(conn, alice, goal["id"], {"title": "Back"})


# --- archive ---

def test_owner_can_archive(conn, alice, goal):
    archived = service.archive_goal(conn, alice, goal["id"])
    assert archived["archived_at"] is not None
    assert archived["archived_at"].endswith("+00:00")


def test_archiving_twice_is_conflict_and_keeps_timestamp(conn, alice, goal):
    first = service.archive_goal(conn, alice, goal["id"])
    with pytest.raises(service.GoalArchived):
        service.archive_goal(conn, alice, goal["id"])
    row = conn.execute(
        "SELECT archived_at FROM goals WHERE id = ?", (goal["id"],)
    ).fetchone()
    assert row["archived_at"] == first["archived_at"]


def test_non_owner_member_cannot_archive(conn, bob, goal):
    with pytest.raises(service.NotGoalOwner):
        service.archive_goal(conn, bob, goal["id"])


def test_non_member_cannot_archive(conn, outsider, goal):
    with pytest.raises(service.NotGroupMember):
        service.archive_goal(conn, outsider, goal["id"])


def test_archive_missing_goal_is_not_found(conn, alice):
    with pytest.raises(service.GoalNotFound):
        service.archive_goal(conn, alice, 999)


# --- schema ---

def test_database_rejects_times_per_week_out_of_range(conn, alice, group_id):
    """The CHECK constraint is a second line of defence behind the service."""
    import sqlite3

    from app.checkins import repository

    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_goal(conn, group_id, alice, "Gym", None, 9, utc_now_iso())
