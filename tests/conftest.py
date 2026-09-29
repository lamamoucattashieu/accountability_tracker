import pytest

from app.config import settings
from app.db import get_connection, init_db


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temporary folder and create the schema, like startup does."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.db")
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    init_db()
    return tmp_path


@pytest.fixture
def conn(data_dir):
    """A connection to the fresh database under the temporary DATA_DIR."""
    connection = get_connection()
    yield connection
    connection.close()
