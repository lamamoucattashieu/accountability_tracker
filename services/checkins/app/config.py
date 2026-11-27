import os
from datetime import timedelta

# Business rules of Goals & Check-ins.
# VOTING_WINDOW must equal Points' VOTING_WINDOW (services/points/app/config.py),
# which settles a week only once every voting window for its check-ins has closed.
# The two copies are kept identical, and Phase 4 CI checks that they still match.
VOTING_WINDOW = timedelta(hours=48)
# Length limits: the migrations hold the same numbers (tests compare them).
USERNAME_MAX_LENGTH = 50
GROUP_NAME_MAX_LENGTH = 60  # migrations/002_limit_group_names.sql
COMMENT_MAX_LENGTH = 280
NUDGE_MAX_LENGTH = 140
DEFAULT_NUDGE_MESSAGE = "don't be a loser, get to work and get it done."
# Most points-outbox rows delivered per request, so a long backlog can't make one request slow.
OUTBOX_BATCH = 20


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
        self.port = int(os.environ.get("PORT", 8000))
        # The commit the running code was built from, shown by /health. Set at build time.
        self.git_sha = os.environ.get("GIT_SHA", "dev")
        # Where the Points service is, and how long to wait for it. Never hardcoded.
        self.points_url = os.environ.get("POINTS_URL", "http://localhost:8001").rstrip("/")
        self.points_timeout_s = float(os.environ.get("POINTS_TIMEOUT_S", DEFAULT_TIMEOUT_S))
        # The only browser origins allowed to call this service (the UI's), comma-separated.
        self.cors_origins = [
            origin.strip().rstrip("/")
            for origin in os.environ.get("CORS_ORIGINS", DEFAULT_UI_ORIGIN).split(",")
            if origin.strip()
        ]

    @property
    def database_url(self) -> str:
        """mssql+pymssql://user:password@host:1433/checkins: this service's own database only."""
        return _required("DATABASE_URL")

    @property
    def auth_token_secret(self) -> str:
        """Signs access tokens. Read on use, so a rotated secret needs only a restart."""
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
