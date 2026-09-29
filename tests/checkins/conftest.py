import pytest

from app.checkins import service
from tests.factories import make_group, make_user


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
