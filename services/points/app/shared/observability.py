"""Health check and request log: how anyone can tell, from outside, whether a service is well.

Identical in both services (A2 decision: small shared code is copied).

- health(): 200 only when the service can read AND write its own database, 503
  otherwise. One quick attempt, no retry: it reports the database as it is
  right now. It never calls the other service (A2 spec 3).
- add_request_log(): one JSON line per request on stdout with method, path,
  status and duration. Never the query string, headers (tokens, the internal
  key) or bodies (passwords, photos).
"""

import json
import logging
import time

from fastapi import FastAPI, Request

from app.shared.database import HEALTH_CONNECT_TIMEOUT_S, connect
from app.shared.timeutils import utc_now_iso

logger = logging.getLogger(__name__)


def health(database_url: str, version: str) -> tuple[int, dict]:
    """(status code, body) for GET /health."""
    try:
        conn = connect(database_url, retry_delays=(), connect_timeout=HEALTH_CONNECT_TIMEOUT_S)
        try:
            conn.execute("SELECT COUNT(*) AS n FROM dbo.schema_migrations").fetchone()  # read
            conn.execute("UPDATE dbo.service_health SET checked_at = %s WHERE id = 1", (utc_now_iso(),))  # write
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # any failure to read or write means "not healthy"
        logger.warning("health check failed: %s", exc)
        return 503, {"status": "error", "db": "unavailable", "version": version}
    return 200, {"status": "ok", "db": "ok", "version": version}


def request_log_line(service: str, method: str, path: str, status: int, duration_ms: float) -> str:
    return json.dumps({"service": service, "method": method, "path": path,
                       "status": status, "duration_ms": round(duration_ms, 1)})


def add_request_log(app: FastAPI, service: str) -> None:
    @app.middleware("http")
    async def log_request(request: Request, call_next):
        started = time.perf_counter()
        status = 500  # if the handler raises, the client gets a 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            # request.url.path: the path only, never the query string.
            print(request_log_line(service, request.method, request.url.path, status, duration_ms), flush=True)
