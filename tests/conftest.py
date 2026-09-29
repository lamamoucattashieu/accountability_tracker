import pytest

from app.config import settings
from app.db import get_connection, init_db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """A fresh database under a temporary DATA_DIR, created by init_db()."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.db")
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    init_db()
    connection = get_connection()
    yield connection
    connection.close()
