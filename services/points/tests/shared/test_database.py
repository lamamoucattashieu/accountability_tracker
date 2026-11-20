"""Connections: DATABASE_URL, retry with backoff, and the error checks the services rely on."""

import pymssql
import pytest

from app.shared import database
from app.shared.database import (
    DatabaseUnavailable, connect, is_duplicate_key, is_lock_timeout, parse_url, startup_retry_delays,
)
from tests import sqlserver

URL = "mssql+pymssql://app:p%40ss@db.example:1444/checkins"


def test_database_url_gives_the_connection_arguments():
    assert parse_url(URL) == {"server": "db.example", "port": 1444, "user": "app",
                              "password": "p@ss", "database": "checkins"}


def test_port_defaults_to_1433():
    assert parse_url("mssql+pymssql://app:x@db/checkins")["port"] == 1433


@pytest.mark.parametrize("url", [None, "", "postgres://a:b@h/db", "mssql+pymssql://a:b@h", "mssql+pymssql://a:b@/db"])
def test_a_malformed_database_url_is_refused(url):
    with pytest.raises(ValueError, match="DATABASE_URL"):
        parse_url(url)


class FlakyServer:
    """Fails with the given errors, in order, then connects."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def __call__(self, **arguments):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return FakeRawConnection()


class FakeRawConnection:
    def cursor(self, as_dict=False):
        return self

    def execute(self, sql, params=None):
        pass


def resuming():
    return pymssql.OperationalError(40613, b"Database 'checkins' is not currently available.")


def test_a_paused_database_is_retried_with_growing_waits():
    server, waits = FlakyServer(resuming(), pymssql.OperationalError(20002, b"DB-Lib error 20002"), resuming()), []
    connect(URL, retry_delays=(0.5, 1, 2), connector=server, sleep=waits.append)
    assert server.calls == 4
    assert waits == [0.5, 1, 2]


def test_retrying_stops_after_the_last_wait():
    server = FlakyServer(*(resuming() for _ in range(4)))
    with pytest.raises(DatabaseUnavailable):
        connect(URL, retry_delays=(0.5, 1, 2), connector=server, sleep=lambda s: None)
    assert server.calls == 4


def test_a_wrong_password_is_not_retried():
    server = FlakyServer(pymssql.OperationalError(18456, b"Login failed for user 'app'."))
    with pytest.raises(DatabaseUnavailable):
        connect(URL, retry_delays=(0.5, 1, 2), connector=server, sleep=lambda s: None)
    assert server.calls == 1


def test_a_retryable_code_inside_a_db_lib_message_counts():
    assert database.is_retryable(pymssql.OperationalError(20018, b"... Msg 40613 ... not currently available"))


def test_startup_waits_double_up_to_the_cap_and_fit_the_budget():
    assert startup_retry_delays(budget_s=40, first_s=1, max_s=8) == (1, 2, 4, 8, 8, 8, 8)
    assert sum(startup_retry_delays()) <= database.STARTUP_RETRY_BUDGET_S


# --- against a real SQL Server ---

@pytest.fixture
def real_conn():
    url = sqlserver.create_database("test_database")
    conn = connect(url)
    conn.execute("CREATE TABLE dbo.t (id INT CONSTRAINT PK_t PRIMARY KEY, n INT CONSTRAINT CK_t_n CHECK (n > 0))")
    conn.commit()
    yield conn
    conn.close()
    sqlserver.drop_database(url)


def test_rows_are_dicts_and_writes_are_tracked_until_commit(real_conn):
    assert real_conn.in_transaction is False
    real_conn.execute("INSERT INTO dbo.t (id, n) VALUES (%s, %s)", (1, 5))
    assert real_conn.in_transaction is True
    real_conn.commit()
    assert real_conn.in_transaction is False
    assert real_conn.execute("SELECT id, n FROM dbo.t").fetchall() == [{"id": 1, "n": 5}]
    assert real_conn.in_transaction is False  # reading doesn't count


def test_duplicate_keys_are_told_apart_from_other_violations(real_conn):
    real_conn.execute("INSERT INTO dbo.t (id, n) VALUES (1, 5)")
    with pytest.raises(pymssql.IntegrityError) as duplicate:
        real_conn.execute("INSERT INTO dbo.t (id, n) VALUES (1, 6)")
    real_conn.rollback()
    with pytest.raises(pymssql.IntegrityError) as check:
        real_conn.execute("INSERT INTO dbo.t (id, n) VALUES (2, -1)")
    real_conn.rollback()
    assert is_duplicate_key(duplicate.value) and is_duplicate_key(duplicate.value, "PK_t")
    assert not is_duplicate_key(duplicate.value, "UQ_other")
    assert not is_duplicate_key(check.value)  # a CHECK violation still counts as an error


def test_a_lock_held_too_long_times_out_instead_of_waiting_forever(real_conn, monkeypatch):
    real_conn.execute("INSERT INTO dbo.t (id, n) VALUES (1, 5)")  # holds the row's lock, uncommitted
    other = connect(real_conn_url(real_conn))
    try:
        other.execute("SET LOCK_TIMEOUT 200")
        with pytest.raises(pymssql.OperationalError) as waited:
            other.execute("SELECT n FROM dbo.t WHERE id = 1").fetchall()
        assert is_lock_timeout(waited.value)
    finally:
        other.close()
        real_conn.rollback()


def real_conn_url(conn):
    name = conn.execute("SELECT DB_NAME() AS name").fetchone()["name"]
    return sqlserver.admin_url().rsplit("/", 1)[0] + f"/{name}"
