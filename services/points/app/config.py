import os
from datetime import timedelta

# Business rules of Points & Forfeits.
# VOTING_WINDOW must equal Checkins' VOTING_WINDOW (services/checkins/app/config.py):
# a week settles only once every voting window for its check-ins has closed, so
# its ranking can no longer change. A1 got this for free from one shared config;
# after the split the two copies are kept identical (A2 decision: shared code is
# copied per service), and Phase 4 CI checks that they still match.
VOTING_WINDOW = timedelta(hours=48)
SETTLEMENT_DELAY = VOTING_WINDOW
PROOF_DEADLINE = timedelta(days=7)
# Length limit: migrations/001_init.sql holds the same number (a test compares them).
FORFEIT_MAX_LENGTH = 200

# Every call to the other service gives up after this long (A2 spec 3).
DEFAULT_TIMEOUT_S = 2.0
# Where the UI runs locally: python -m http.server 5500 -d ui
DEFAULT_UI_ORIGIN = "http://localhost:5500"

# Secrets have no default (A2 spec 8a): the service refuses to start without them.
# DATABASE_URL holds the database password, so it is a secret too.
REQUIRED_SECRETS = ("DATABASE_URL", "AUTH_TOKEN_SECRET", "INTERNAL_API_KEY")


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
        # The commit the running code was built from, shown by /health. Set at build time.
        self.git_sha = os.environ.get("GIT_SHA", "dev")
        # Where the Checkins service is, and how long to wait for it. Never hardcoded.
        self.checkins_url = os.environ.get("CHECKINS_URL", "http://localhost:8000").rstrip("/")
        self.checkins_timeout_s = float(os.environ.get("CHECKINS_TIMEOUT_S", DEFAULT_TIMEOUT_S))
        # The only browser origins allowed to call this service (the UI's), comma-separated.
        self.cors_origins = [
            origin.strip().rstrip("/")
            for origin in os.environ.get("CORS_ORIGINS", DEFAULT_UI_ORIGIN).split(",")
            if origin.strip()
        ]

    @property
    def database_url(self) -> str:
        """mssql+pymssql://user:password@host:1433/points: this service's own database only."""
        return _required("DATABASE_URL")

    @property
    def auth_token_secret(self) -> str:
        """Verifies access tokens issued by Checkins. Read on use, so rotating needs only a restart."""
        return _required("AUTH_TOKEN_SECRET")

    @property
    def internal_api_key(self) -> str:
        """Shared with the other service: proves an /internal/... call comes from it."""
        return _required("INTERNAL_API_KEY")

    def check_secrets(self) -> None:
        """Called at startup, so a missing secret fails loudly before any request."""
        for name in REQUIRED_SECRETS:
            _required(name)


settings = Settings()
