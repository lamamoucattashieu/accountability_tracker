from app.auth import repository, service
from app.shared.timeutils import utc_now_iso


def test_is_member_and_group_exists(conn):
    now = utc_now_iso()
    alice = repository.insert_user(conn, "alice", "not-a-real-hash", now)
    bob = repository.insert_user(conn, "bob", "not-a-real-hash", now)
    group_id = repository.insert_group(conn, "friends", "ABCD1234", alice, now)
    repository.add_group_member(conn, group_id, alice, now)

    assert service.group_exists(conn, group_id) is True
    assert service.group_exists(conn, 999) is False
    assert service.is_member(conn, group_id, alice) is True
    assert service.is_member(conn, group_id, bob) is False
    assert service.is_member(conn, 999, alice) is False
