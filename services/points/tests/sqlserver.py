"""Scratch SQL Server databases for tests (never Azure SQL, A2 spec 5).

Tests need a SQL Server they may create databases on, given by
TEST_DATABASE_ADMIN_URL (mssql+pymssql://sa:<password>@localhost:1433/master).
Locally that is the SQL Server container (see the README); in CI, a service
container. If it isn't set, it is read from the repository's .env, which is
gitignored. Without it the database tests fail, never silently skip.
"""

import os
import uuid
from pathlib import Path

import pymssql

from app.shared.database import parse_url

ENV_NAME = "TEST_DATABASE_ADMIN_URL"
REPO_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def admin_url() -> str:
    url = os.environ.get(ENV_NAME)
    if not url and REPO_ENV_FILE.exists():
        for line in REPO_ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{ENV_NAME}="):
                url = line.split("=", 1)[1].strip()
    if not url:
        raise RuntimeError(f"{ENV_NAME} is not set: start the local SQL Server (see the README)")
    return url


def _admin_connection():
    # CREATE/DROP DATABASE can't run inside a transaction, so this one autocommits.
    arguments = parse_url(admin_url())
    return pymssql.connect(**arguments, login_timeout=10, autocommit=True)


def create_database(prefix: str) -> str:
    """A new, empty database; returns its DATABASE_URL."""
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    with _admin_connection() as conn:
        conn.cursor().execute(f"CREATE DATABASE [{name}]")
    return admin_url().rsplit("/", 1)[0] + f"/{name}"


def drop_database(url: str) -> None:
    name = parse_url(url)["database"]
    with _admin_connection() as conn:
        conn.cursor().execute(
            f"IF DB_ID(N'{name}') IS NOT NULL BEGIN "
            f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{name}]; END"
        )
