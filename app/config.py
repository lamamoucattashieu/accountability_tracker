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


class Settings:
    def __init__(self):
        self.port = int(os.environ.get("PORT", 8000))
        self.data_dir = Path(os.environ.get("DATA_DIR", "./data"))
        self.db_path = self.data_dir / "app.db"
        self.uploads_dir = self.data_dir / "uploads"


settings = Settings()
