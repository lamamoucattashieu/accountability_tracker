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


class Settings:
    def __init__(self):
        self.port = int(os.environ.get("PORT", 8000))
        self.data_dir = Path(os.environ.get("DATA_DIR", "./data"))
        self.db_path = self.data_dir / "app.db"
        self.uploads_dir = self.data_dir / "uploads"
        # Send the session cookie over https only. Off by default because local runs
        # use plain http; set COOKIE_SECURE=true when deployed behind https.
        self.cookie_secure = os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


settings = Settings()
