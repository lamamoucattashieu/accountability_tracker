from datetime import datetime, timedelta, timezone

import pytest

from app.auth import repository, service
from app.auth.security import hash_password, verify_password
from app.shared.timeutils import utc_now_iso


# --- passwords ---

def test_password_is_stored_hashed_and_verifies():
    stored = hash_password("correct horse")
    assert "correct horse" not in stored
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)


def test_same_password_gets_a_different_salt_each_time():
    assert hash_password("same password") != hash_password("same password")


# --- registration and login ---

def test_register_creates_a_user_and_a_session(conn):
    token = service.register(conn, "alice", "password1")
    user = service.get_user_from_session(conn, token)
    assert user["username"] == "alice"
    assert user["password_hash"] != "password1"


@pytest.mark.parametrize(
    "username, password",
    [("al", "password1"), ("alice", "short")],
    ids=["username too short", "password too short"],
)
def test_register_rejects_short_credentials(conn, username, password):
    with pytest.raises(ValueError):  # the route maps this to 422
        service.register(conn, username, password)


def test_register_rejects_a_taken_username(conn):
    service.register(conn, "alice", "password1")
    with pytest.raises(service.UsernameTakenError):  # 409
        service.register(conn, "alice", "password2")


def test_login_with_the_right_password_starts_a_session(conn):
    service.register(conn, "alice", "password1")
    token = service.authenticate(conn, "alice", "password1")
    assert service.get_user_from_session(conn, token)["username"] == "alice"


@pytest.mark.parametrize("username, password", [("alice", "wrong-pass"), ("nobody", "password1")])
def test_login_failures_look_the_same(conn, username, password):
    service.register(conn, "alice", "password1")
    with pytest.raises(service.InvalidCredentialsError):  # 401, same for both cases
        service.authenticate(conn, username, password)


# --- sessions ---

@pytest.mark.parametrize("token", [None, "", "not-a-real-token"])
def test_missing_or_unknown_session_is_logged_out(conn, token):
    assert service.get_user_from_session(conn, token) is None


def test_expired_session_is_logged_out_and_deleted(conn):
    user_id = repository.insert_user(conn, "alice", hash_password("password1"), utc_now_iso())
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
    repository.insert_session(conn, "old-token", user_id, utc_now_iso(), expired)
    assert service.get_user_from_session(conn, "old-token") is None
    assert repository.get_session(conn, "old-token") is None


def test_logout_ends_the_session(conn):
    token = service.register(conn, "alice", "password1")
    service.logout(conn, token)
    assert service.get_user_from_session(conn, token) is None


# --- groups ---

def make_user(conn, name):
    return repository.insert_user(conn, name, "not-a-real-hash", utc_now_iso())


def test_creating_a_group_makes_you_its_first_member(conn):
    alice = make_user(conn, "alice")
    group = service.create_group(conn, alice, "  gym bros  ")
    assert group["name"] == "gym bros"
    assert len(group["invite_code"]) == 8
    assert service.is_member(conn, group["id"], alice)


@pytest.mark.parametrize("name", ["", "   "])
def test_group_name_cannot_be_empty(conn, name):
    alice = make_user(conn, "alice")
    with pytest.raises(ValueError):  # 422
        service.create_group(conn, alice, name)


def test_joining_with_an_invite_code_ignores_case_and_spaces(conn):
    alice, bob = make_user(conn, "alice"), make_user(conn, "bob")
    group = service.create_group(conn, alice, "gym bros")
    joined = service.join_group(conn, bob, f"  {group['invite_code'].lower()}  ")
    assert joined["id"] == group["id"]
    assert [g["id"] for g in service.list_my_groups(conn, bob)] == [group["id"]]


def test_joining_twice_keeps_one_membership(conn):
    alice, bob = make_user(conn, "alice"), make_user(conn, "bob")
    group = service.create_group(conn, alice, "gym bros")
    service.join_group(conn, bob, group["invite_code"])
    service.join_group(conn, bob, group["invite_code"])
    assert service.member_count(conn, group["id"]) == 2


def test_wrong_invite_code_is_rejected(conn):
    bob = make_user(conn, "bob")
    with pytest.raises(service.InvalidInviteCodeError):  # 404
        service.join_group(conn, bob, "NOPE1234")


def test_you_only_see_your_own_groups(conn):
    alice, bob = make_user(conn, "alice"), make_user(conn, "bob")
    service.create_group(conn, alice, "alice's crew")
    assert service.list_my_groups(conn, bob) == []
