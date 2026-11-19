import pytest

from app.config import settings
from app.db import get_connection, init_db
from app.points import group_directory
from tests import factories

TEST_SECRET = "test-only-token-secret"


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    """Every secret a service needs, with test-only values."""
    monkeypatch.setenv("AUTH_TOKEN_SECRET", TEST_SECRET)


@pytest.fixture(autouse=True)
def checkins(monkeypatch):
    """A fresh fake Checkins behind the GroupDirectory port, for every test."""
    fake = factories.reset_directory()
    monkeypatch.setattr(group_directory, "_directory", fake)
    return fake


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temporary folder and create the schema, like startup does."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "points.db")
    monkeypatch.setattr(settings, "uploads_dir", tmp_path / "uploads")
    init_db()
    return tmp_path


@pytest.fixture
def conn(data_dir):
    """A connection to the fresh database under the temporary DATA_DIR."""
    connection = get_connection()
    yield connection
    connection.close()
