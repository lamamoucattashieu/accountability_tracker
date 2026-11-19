"""The port Checkins uses to tell Points about completions (ports & adapters).

The outbox only knows the two methods below and the two errors, never how the
call is made. Production plugs in an adapter with set_client(); tests plug in
a fake, so they never need the other service running.
"""

from typing import Protocol


class PointsUnavailable(Exception):
    """Points is down, too slow, or answered 5xx: keep the change and retry later."""


class PointsRejected(Exception):
    """Points refused the change itself (4xx): retrying the same payload can't help."""


class PointsClient(Protocol):
    def record(self, completion: dict) -> None: ...

    def revoke(self, checkin_id: int, revoked_at: str) -> None: ...


class LocalPointsClient:
    """Adapter for the monolith: calls the Points service functions in-process.

    Each call uses its own connection and commits on its own, like a request to
    another service would. Replaced by an HTTP adapter after the split.
    """

    def record(self, completion: dict) -> None:
        from app.db import get_db
        from app.points import service as points_service

        with get_db() as conn:
            points_service.record_completion(conn, **completion)

    def revoke(self, checkin_id: int, revoked_at: str) -> None:
        from app.db import get_db
        from app.points import service as points_service

        with get_db() as conn:
            points_service.revoke_completion(conn, checkin_id, revoked_at)


_client: PointsClient = LocalPointsClient()


def set_client(client: PointsClient) -> None:
    global _client
    _client = client


def get_client() -> PointsClient:
    return _client
