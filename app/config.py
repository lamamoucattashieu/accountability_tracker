import os
from pathlib import Path


class Settings:
    def __init__(self):
        self.port = int(os.environ.get("PORT", 8000))
        self.data_dir = Path(os.environ.get("DATA_DIR", "./data"))
        self.db_path = self.data_dir / "app.db"
        self.uploads_dir = self.data_dir / "uploads"


settings = Settings()
