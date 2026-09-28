import hashlib
import secrets

_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, _, expected_hex = password_hash.partition("$")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return secrets.compare_digest(digest.hex(), expected_hex)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_invite_code() -> str:
    return secrets.token_hex(4).upper()
