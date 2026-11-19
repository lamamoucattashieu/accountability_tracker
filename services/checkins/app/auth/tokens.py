"""Signed access tokens: the user's login, readable by any service that has the secret.

A token is "<body>.<signature>". The body is base64url JSON {"uid", "sid", "exp"};
the signature is HMAC-SHA256 of the body with AUTH_TOKEN_SECRET. Anyone can read
a body, but only a holder of the secret can make a signature that verifies, so
a changed user id or expiry is rejected. Points verifies tokens itself, without
asking Checkins, so it keeps working while Checkins is down.

Only the Python standard library is used: no JWT package needed.
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

from app.config import settings


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(body: str) -> str:
    digest = hmac.new(settings.auth_token_secret.encode(), body.encode(), hashlib.sha256).digest()
    return _encode(digest)


def issue(user_id: int, session_id: str, expires_at: datetime) -> str:
    claims = {"uid": user_id, "sid": session_id, "exp": int(expires_at.timestamp())}
    body = _encode(json.dumps(claims, separators=(",", ":")).encode())
    return f"{body}.{_signature(body)}"


def verify(token, now: datetime = None):
    """The token's claims if it is genuine and not expired, else None. Never raises."""
    if not token or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    # compare_digest takes the same time however many characters match, so the
    # response time can't be used to guess a valid signature character by character.
    if not hmac.compare_digest(signature, _signature(body)):
        return None
    try:
        claims = json.loads(_decode(body))
    except ValueError:
        return None
    now = now or datetime.now(timezone.utc)
    if claims.get("exp", 0) <= now.timestamp():
        return None
    return claims


def bearer_token(authorization_header):
    """The token from an "Authorization: Bearer <token>" header, or None."""
    if not authorization_header:
        return None
    scheme, _, token = authorization_header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
