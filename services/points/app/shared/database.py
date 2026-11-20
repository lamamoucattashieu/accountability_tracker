"""SQL Server connections: one per request, retried while the database wakes up.

Identical in both services (A2 decision: small shared code is copied).

- DATABASE_URL looks like mssql+pymssql://user:password@host:1433/database
  (special characters in the password URL-encoded).
- Only opening a connection is retried, never a query, so a write can't run
  twice. Azure SQL serverless pauses when idle; while it resumes (up to about a
  minute) connecting fails with 40613, or with pymssql's DB-Lib 20002/20003.
- Connection wraps pymssql's connection so repositories keep writing
  conn.execute(sql, params) and reading row["column"], and so the service
  can tell whether the request has unsaved writes (in_transaction).
"""

import logging
import time
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

import pymssql

logger = logging.getLogger(__name__)

URL_SCHEME = "mssql+pymssql"
DEFAULT_PORT = 1433

# How long one connection attempt may take.
CONNECT_TIMEOUT_S = 5
# /health makes one short attempt: it reports the database's state right now.
HEALTH_CONNECT_TIMEOUT_S = 3
# Waits between attempts for a request: 0.5 + 1 + 2 + 4 + 8 s of backoff. Even with
# every attempt timing out, a request gives up well inside Container Apps' 240 s.
REQUEST_RETRY_DELAYS_S = (0.5, 1, 2, 4, 8)
# At startup (migrations) the database may be resuming from pause: keep trying
# this long, doubling the wait up to STARTUP_MAX_DELAY_S, then exit and let the
# platform restart the container.
STARTUP_RETRY_BUDGET_S = 120
STARTUP_FIRST_DELAY_S = 1
STARTUP_MAX_DELAY_S = 8
# SQL Server waits for a lock forever by default; SQLite gave up after 5 s.
LOCK_TIMEOUT_MS = 5000

# Errors that mean "not available yet, try again": 40613 database unavailable
# (resuming), 40197/40501 service busy, 4060 cannot open the database yet,
# 20002/20003/20009 pymssql (DB-Lib) connection failures and timeouts.
SERVER_RETRYABLE_ERRORS = {40613, 40197, 40501, 4060}
RETRYABLE_ERRORS = SERVER_RETRYABLE_ERRORS | {20002, 20003, 20009}
# DB-Lib's generic "General SQL Server error": the server's own message is in the text.
DB_LIB_GENERAL_ERROR = 20018
# 2627 = UNIQUE or PRIMARY KEY constraint violated, 2601 = unique index violated.
DUPLICATE_KEY_ERRORS = {2627, 2601}
LOCK_TIMEOUT_ERROR = 1222

# Statements that change data or schema: after one, the connection has unsaved work.
WRITE_KEYWORDS = ("INSERT", "UPDATE", "DELETE", "MERGE", "EXEC", "CREATE", "ALTER", "DROP")


class DatabaseUnavailable(Exception):
    """The database couldn't be reached, even after retrying."""


def parse_url(url: str) -> dict:
    """pymssql.connect() arguments from a DATABASE_URL."""
    parts = urlparse(url or "")
    if parts.scheme != URL_SCHEME or not parts.hostname or not parts.path.strip("/"):
        raise ValueError(f"DATABASE_URL must look like {URL_SCHEME}://user:password@host:1433/database")
    return {
        "server": parts.hostname,
        "port": parts.port or DEFAULT_PORT,
        "user": unquote(parts.username or ""),
        "password": unquote(parts.password or ""),
        "database": parts.path.strip("/"),
    }


def error_number(exc: Exception):
    """SQL Server's error number of a pymssql error, or None."""
    if exc.args and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def is_retryable(exc: Exception) -> bool:
    """Decided by the error number. A wrong password (18456) is never retried, even
    though pymssql's text for it also mentions DB-Lib 20002."""
    number = error_number(exc)
    if number == DB_LIB_GENERAL_ERROR:
        # Only the generic wrapper is read further: is the server's own error a "resuming" one?
        return any(str(code) in str(exc) for code in SERVER_RETRYABLE_ERRORS)
    return number in RETRYABLE_ERRORS


def is_duplicate_key(exc: Exception, constraint: str = None) -> bool:
    """True for a UNIQUE/PRIMARY KEY violation (of that constraint, when one is named)."""
    if not isinstance(exc, pymssql.IntegrityError) or error_number(exc) not in DUPLICATE_KEY_ERRORS:
        return False
    return constraint is None or constraint in str(exc)


def is_lock_timeout(exc: Exception) -> bool:
    return error_number(exc) == LOCK_TIMEOUT_ERROR


class Connection:
    """A pymssql connection with dict rows and a record of unsaved writes."""

    def __init__(self, raw):
        self._raw = raw
        self.in_transaction = False  # True after a write, until commit or rollback

    def execute(self, sql: str, params=None):
        cursor = self._raw.cursor(as_dict=True)
        cursor.execute(sql, params)
        if sql.lstrip().upper().startswith(WRITE_KEYWORDS):
            self.in_transaction = True
        return cursor

    def commit(self) -> None:
        self._raw.commit()
        self.in_transaction = False

    def rollback(self) -> None:
        self._raw.rollback()
        self.in_transaction = False

    def close(self) -> None:
        self._raw.close()  # anything not committed is rolled back


def connect(url: str, retry_delays=REQUEST_RETRY_DELAYS_S, connect_timeout=CONNECT_TIMEOUT_S,
            connector=pymssql.connect, sleep=time.sleep) -> Connection:
    """Open a connection, waiting retry_delays[i] seconds after each retryable failure."""
    arguments = parse_url(url)
    attempts = len(retry_delays) + 1
    for attempt in range(attempts):
        try:
            raw = connector(**arguments, login_timeout=connect_timeout, autocommit=False)
        except (pymssql.OperationalError, pymssql.InterfaceError) as exc:
            if attempt + 1 == attempts or not is_retryable(exc):
                raise DatabaseUnavailable(f"can't connect to the database: {exc}") from exc
            delay = retry_delays[attempt]
            logger.warning("database not available yet (attempt %d of %d), retrying in %ss",
                           attempt + 1, attempts, delay)
            sleep(delay)
            continue
        conn = Connection(raw)
        conn.execute(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}")
        return conn


def startup_retry_delays(budget_s=STARTUP_RETRY_BUDGET_S, first_s=STARTUP_FIRST_DELAY_S,
                         max_s=STARTUP_MAX_DELAY_S) -> tuple:
    """Doubling waits (1, 2, 4, 8, 8, ...) that add up to the startup budget."""
    delays, total, delay = [], 0, first_s
    while total + delay <= budget_s:
        delays.append(delay)
        total += delay
        delay = min(delay * 2, max_s)
    return tuple(delays)


@contextmanager
def transaction(url: str, retry_delays=REQUEST_RETRY_DELAYS_S):
    """One connection for one unit of work: committed at the end, rolled back on error."""
    conn = connect(url, retry_delays)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
