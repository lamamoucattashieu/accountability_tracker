"""Versioned migrations: the only way the schema is created or changed.

Identical in both services (A2 decision: small shared code is copied).

Files are migrations/NNN_name.sql (NNN = 001, 002, ...), applied in order on
startup. Each one runs in its own transaction together with its row in
schema_migrations, so it is applied completely and recorded, or not at all.
A file that is already applied is never run again, and must never be edited:
its SHA-256 is recorded, and a changed file stops the service from starting.
Corrections always go in a new file (forward-only, A2 spec 4).

A file may hold several batches separated by lines containing only GO.
Statements that can't run inside a transaction (CREATE DATABASE, ...) don't
belong in migrations.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FILE_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
BATCH_SEPARATOR = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)
# Only one copy of a service may migrate at a time; a second one waits this long.
LOCK_RESOURCE = "schema_migrations"
LOCK_TIMEOUT_MS = 60_000

CREATE_TABLE_SQL = """
IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NULL
CREATE TABLE dbo.schema_migrations (
    version NVARCHAR(255) NOT NULL CONSTRAINT PK_schema_migrations PRIMARY KEY,
    checksum CHAR(64) NOT NULL,
    applied_at NVARCHAR(32) NOT NULL
)
"""


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    version: str     # the file name without .sql, e.g. "001_init"
    sql: str
    checksum: str


def checksum(sql: str) -> str:
    """SHA-256 of the file, with Windows line endings counted as Unix ones.

    Git may check the same file out with CRLF on Windows and LF in a Linux
    container; that must not look like an edit.
    """
    return hashlib.sha256(sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def discover(folder: Path) -> list[Migration]:
    """Every migration file in the folder, in order. Badly named or duplicate numbers stop startup."""
    migrations, numbers = [], set()
    for path in sorted(Path(folder).glob("*.sql")):
        match = FILE_NAME.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name}: migration files are named NNN_name.sql (lowercase)")
        if match.group(1) in numbers:
            raise MigrationError(f"{path.name}: two migrations share the number {match.group(1)}")
        numbers.add(match.group(1))
        sql = path.read_text(encoding="utf-8")
        migrations.append(Migration(path.stem, sql, checksum(sql)))
    return migrations


def batches(sql: str) -> list[str]:
    return [batch.strip() for batch in BATCH_SEPARATOR.split(sql) if batch.strip()]


def _lock(conn, lock_timeout_ms: int) -> None:
    row = conn.execute(
        """
        DECLARE @result INT;
        EXEC @result = sp_getapplock @Resource = %s, @LockMode = 'Exclusive',
                                     @LockOwner = 'Session', @LockTimeout = %s;
        SELECT @result AS result;
        """,
        (LOCK_RESOURCE, lock_timeout_ms),
    ).fetchone()
    conn.commit()
    if row["result"] < 0:
        raise MigrationError("another copy of this service is applying migrations; gave up waiting")


def _unlock(conn) -> None:
    conn.execute("EXEC sp_releaseapplock @Resource = %s, @LockOwner = 'Session'", (LOCK_RESOURCE,))
    conn.commit()


def _applied(conn) -> dict:
    rows = conn.execute("SELECT version, checksum FROM dbo.schema_migrations").fetchall()
    return {row["version"]: row["checksum"].strip() for row in rows}


def apply_migrations(conn, folder: Path, now: str, lock_timeout_ms: int = LOCK_TIMEOUT_MS) -> list[str]:
    """Apply every migration not yet applied, in order. Returns the versions applied now."""
    _lock(conn, lock_timeout_ms)
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        applied = _applied(conn)
        files = discover(folder)
        missing = sorted(set(applied) - {m.version for m in files})
        if missing:
            raise MigrationError(f"applied migrations are missing from {folder}: {', '.join(missing)}")
        done_now = []
        for migration in files:
            if migration.version in applied:
                if applied[migration.version] != migration.checksum:
                    raise MigrationError(
                        f"{migration.version}.sql was edited after it was applied; "
                        "never edit an applied migration, add a new one instead")
                continue
            _apply_one(conn, migration, now)
            done_now.append(migration.version)
        if done_now:
            for version in done_now:
                logger.info("migration %s applied", version)
        else:
            logger.info("migrations: nothing to apply")
        return done_now
    finally:
        _unlock(conn)


def _apply_one(conn, migration: Migration, now: str) -> None:
    """One migration and its schema_migrations row, in one transaction."""
    try:
        for batch in batches(migration.sql):
            conn.execute(batch)
        conn.execute(
            "INSERT INTO dbo.schema_migrations (version, checksum, applied_at) VALUES (%s, %s, %s)",
            (migration.version, migration.checksum, now),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise MigrationError(f"migration {migration.version} failed and was rolled back: {exc}") from exc
