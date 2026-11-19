from datetime import datetime, timedelta, timezone

import pytest

from app.auth import service, tokens
from app.auth.tokens import bearer_token

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)


def test_a_genuine_token_gives_back_its_claims():
    token = tokens.issue(5, "session-abc", LATER)
    assert tokens.verify(token, NOW) == {"uid": 5, "sid": "session-abc", "exp": int(LATER.timestamp())}


def test_an_expired_token_is_rejected():
    assert tokens.verify(tokens.issue(5, "s", NOW), NOW) is None  # expiry is exclusive


def test_a_changed_body_is_rejected():
    """Anyone can read and edit the body, but not re-sign it."""
    token = tokens.issue(5, "s", LATER)
    other_body = tokens.issue(6, "s", LATER).split(".")[0]
    forged = f"{other_body}.{token.split('.')[1]}"
    assert tokens.verify(forged, NOW) is None


def test_a_token_signed_with_another_secret_is_rejected(monkeypatch):
    token = tokens.issue(5, "s", LATER)
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "a-different-secret")
    assert tokens.verify(token, NOW) is None


@pytest.mark.parametrize("token", [None, "", "no-dot", "a.b.c", "x.y"])
def test_malformed_tokens_are_rejected_without_raising(token):
    assert tokens.verify(token, NOW) is None


@pytest.mark.parametrize("header, token", [
    ("Bearer abc.def", "abc.def"),
    ("bearer abc.def", "abc.def"),
    ("Basic abc", None),
    ("Bearer ", None),
    (None, None),
])
def test_bearer_token_is_read_from_the_authorization_header(header, token):
    assert bearer_token(header) == token


def test_token_logs_in_until_logout_deletes_its_session(conn):
    session_id = service.register(conn, "alice", "password1")
    token = service.access_token(conn, session_id)
    assert service.get_user_from_token(conn, token)["username"] == "alice"
    service.logout_token(conn, token)
    assert service.get_user_from_token(conn, token) is None


def test_token_expires_with_its_session(conn):
    session_id = service.register(conn, "alice", "password1")
    claims = tokens.verify(service.access_token(conn, session_id))
    session = service.repository.get_session(conn, session_id)
    assert claims["exp"] == int(datetime.fromisoformat(session["expires_at"]).timestamp())
