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


class UnconfiguredPointsClient:
    """Used until main.py plugs in the real adapter: every change just stays queued."""

    def record(self, completion: dict) -> None:
        raise PointsUnavailable("no Points client configured")

    def revoke(self, checkin_id: int, revoked_at: str) -> None:
        raise PointsUnavailable("no Points client configured")


_client: PointsClient = UnconfiguredPointsClient()


def set_client(client: PointsClient) -> None:
    global _client
    _client = client


def get_client() -> PointsClient:
    return _client
