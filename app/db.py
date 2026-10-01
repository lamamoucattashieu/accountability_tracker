import sqlite3
from contextlib import contextmanager

from app.auth import repository as auth_repository
from app.checkins import repository as checkins_repository
from app.config import settings
from app.points import repository as points_repository


def get_connection():
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        auth_repository.create_tables(conn)
        checkins_repository.create_tables(conn)
        points_repository.create_tables(conn)
