import os
from datetime import timedelta
from pathlib import Path

# Business rules shared across domains. They are named here, not inside one
# domain, so a domain never imports another just to read a number.
VOTING_WINDOW = timedelta(hours=48)
# A week settles only once every voting window for its check-ins has closed,
# so this is defined as the voting window: the two can never drift apart.
SETTLEMENT_DELAY = VOTING_WINDOW
PROOF_DEADLINE = timedelta(days=7)
FORFEIT_MAX_LENGTH = 200
COMMENT_MAX_LENGTH = 280
NUDGE_MAX_LENGTH = 140
DEFAULT_NUDGE_MESSAGE = "don't be a loser, get to work and get it done."
# Most points-outbox rows delivered per request, so a long backlog can't make one request slow.
OUTBOX_BATCH = 20


# Secrets have no default (A2 spec 8a): the service refuses to start without them.
REQUIRED_SECRETS = ("AUTH_TOKEN_SECRET",)


class MissingSecret(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingSecret(f"environment variable {name} must be set (it is a secret, so it has no default)")
    return value


class Settings:
    def __init__(self):
        self.port = int(os.environ.get("PORT", 8000))
        self.data_dir = Path(os.environ.get("DATA_DIR", "./data"))
        self.db_path = self.data_dir / "app.db"
        self.uploads_dir = self.data_dir / "uploads"

    @property
    def auth_token_secret(self) -> str:
        """Signs access tokens. Read on use, so a rotated secret needs only a restart."""
        return _required("AUTH_TOKEN_SECRET")

    def check_secrets(self) -> None:
        """Called at startup, so a missing secret fails loudly before any request."""
        for name in REQUIRED_SECRETS:
            _required(name)


settings = Settings()
