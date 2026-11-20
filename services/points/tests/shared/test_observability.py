"""/health and the request log, through the real app."""

import json

import pytest
from fastapi.testclient import TestClient

from main import app

UNREACHABLE = "mssql+pymssql://sa:x@127.0.0.1:1/nowhere"  # nothing listens on port 1


@pytest.fixture
def api(db):
    return TestClient(app)  # no "with": the startup hook would plug in the real other-service client


def test_health_is_ok_when_the_database_can_be_read_and_written(api, conn, monkeypatch):
    monkeypatch.setattr("main.settings.git_sha", "3f2a9c1")  # GIT_SHA, read at startup
    response = api.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "version": "3f2a9c1"}
    checked = conn.execute("SELECT checked_at FROM dbo.service_health WHERE id = 1").fetchone()["checked_at"]
    assert checked.endswith("+00:00")  # the write really committed


def test_health_is_503_when_the_database_is_unreachable(api, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE)
    response = api.get("/health")
    assert response.status_code == 503
    assert response.json()["db"] == "unavailable"


def test_health_is_503_when_the_database_cant_be_written(api, conn):
    # Reading still works, but this constraint makes health's UPDATE fail.
    conn.execute("UPDATE dbo.service_health SET checked_at = N'never' WHERE id = 1")
    conn.execute("ALTER TABLE dbo.service_health ADD CONSTRAINT CK_test_no_writes CHECK (checked_at = N'never')")
    conn.commit()
    try:
        assert api.get("/health").status_code == 503
    finally:
        conn.execute("ALTER TABLE dbo.service_health DROP CONSTRAINT CK_test_no_writes")
        conn.commit()


def test_every_request_writes_one_json_line(api, capsys):
    api.get("/health?token=secret", headers={"Authorization": "Bearer abc.def", "X-Internal-Key": "k"})
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["method"] == "GET" and entry["path"] == "/health" and entry["status"] == 200
    assert isinstance(entry["duration_ms"], float)
    assert set(entry) == {"service", "method", "path", "status", "duration_ms"}
    for secret in ("secret", "abc.def", "Bearer", "X-Internal-Key"):
        assert secret not in lines[0]  # no query string, no headers


def test_a_failed_request_is_logged_too(api, capsys):
    assert api.get("/no-such-endpoint").status_code == 404
    entry = json.loads([line for line in capsys.readouterr().out.splitlines() if line.startswith("{")][0])
    assert (entry["path"], entry["status"]) == ("/no-such-endpoint", 404)
