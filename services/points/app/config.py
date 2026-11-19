import os
from datetime import timedelta
from pathlib import Path

# Business rules of Points & Forfeits.
# VOTING_WINDOW must equal Checkins' VOTING_WINDOW (services/checkins/app/config.py):
# a week settles only once every voting window for its check-ins has closed, so
# its ranking can no longer change. A1 got this for free from one shared config;
# after the split the two copies are kept identical (A2 decision: shared code is
# copied per service), and Phase 4 CI checks that they still match.
VOTING_WINDOW = timedelta(hours=48)
SETTLEMENT_DELAY = VOTING_WINDOW
PROOF_DEADLINE = timedelta(days=7)
FORFEIT_MAX_LENGTH = 200

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
        self.port = int(os.environ.get("PORT", 8001))
        self.data_dir = Path(os.environ.get("DATA_DIR", "./data"))
        self.db_path = self.data_dir / "points.db"
        self.uploads_dir = self.data_dir / "uploads"

    @property
    def auth_token_secret(self) -> str:
        """Verifies access tokens issued by Checkins. Read on use, so rotating needs only a restart."""
        return _required("AUTH_TOKEN_SECRET")

    def check_secrets(self) -> None:
        """Called at startup, so a missing secret fails loudly before any request."""
        for name in REQUIRED_SECRETS:
            _required(name)


settings = Settings()
