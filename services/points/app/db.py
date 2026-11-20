"""This service's database: one connection per request, schema from migrations."""

from pathlib import Path

from app.config import settings
from app.shared.database import connect, startup_retry_delays, transaction
from app.shared.migrations import apply_migrations
from app.shared.timeutils import utc_now_iso

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_connection():
    return connect(settings.database_url)


def get_db():
    """One request's unit of work: committed at the end, rolled back on error."""
    return transaction(settings.database_url)


def init_db():
    """Apply pending migrations at startup, waiting for a database that is still resuming."""
    conn = connect(settings.database_url, startup_retry_delays())
    try:
        apply_migrations(conn, MIGRATIONS_DIR, utc_now_iso())
    finally:
        conn.close()
