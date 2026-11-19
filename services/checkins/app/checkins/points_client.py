"""The port Checkins uses to tell Points about completions (ports & adapters).

The outbox only knows the two methods below and the two errors, never how the
call is made. Production plugs in an adapter with set_client(); tests plug in
a fake, so they never need the other service running.
"""

import logging
from typing import Protocol

import httpx

from app.shared.internal_api import INTERNAL_KEY_HEADER

logger = logging.getLogger(__name__)


class PointsUnavailable(Exception):
    """Points is down, too slow, or answered 5xx: keep the change and retry later."""


class PointsRejected(Exception):
    """Points refused the change itself (4xx): retrying the same payload can't help."""


class PointsClient(Protocol):
    def record(self, completion: dict) -> None: ...

    def revoke(self, checkin_id: int, revoked_at: str) -> None: ...


class UnconfiguredPointsClient:
    """Used until main.py plugs in the real adapter: every change just stays queued."""

    def record(self, completion: dict) -> None:
        raise PointsUnavailable("no Points client configured")

    def revoke(self, checkin_id: int, revoked_at: str) -> None:
        raise PointsUnavailable("no Points client configured")


class HttpPointsClient:
    """Adapter: the Points service's /internal/... endpoints over HTTP, with a timeout.

    Every way a call can go wrong becomes one of the port's two errors, so the
    outbox never sees httpx: a timeout, a refused connection, a 5xx, or a
    rejected key (a configuration problem, fixed by an operator, not by
    dropping the change) -> PointsUnavailable, and the row is retried later;
    any other 4xx -> PointsRejected, and the row is marked failed.
    """

    def __init__(self, base_url: str, timeout_s: float, internal_key: str, transport=None):
        self._http = httpx.Client(
            base_url=base_url, timeout=timeout_s, transport=transport,
            headers={INTERNAL_KEY_HEADER: internal_key},
        )

    def _post(self, path: str, body: dict) -> None:
        try:
            response = self._http.post(path, json=body)
        except httpx.HTTPError as exc:  # timeouts and connection errors
            raise PointsUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code in (401, 403):
            logger.error("points refused our internal key: check INTERNAL_API_KEY on both services")
            raise PointsUnavailable(f"points answered {response.status_code}: internal key refused")
        if response.status_code >= 500:
            raise PointsUnavailable(f"points answered {response.status_code}")
        if response.status_code >= 400:
            raise PointsRejected(f"points answered {response.status_code}: {response.text[:200]}")

    def record(self, completion: dict) -> None:
        self._post("/internal/completions", completion)

    def revoke(self, checkin_id: int, revoked_at: str) -> None:
        self._post(f"/internal/completions/{checkin_id}/revocation", {"revoked_at": revoked_at})


_client: PointsClient = UnconfiguredPointsClient()


def set_client(client: PointsClient) -> None:
    global _client
    _client = client


def get_client() -> PointsClient:
    return _client
