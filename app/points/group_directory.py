"""The port Points uses to learn a group's members from Checkins (ports & adapters).

fetch_group returns a plain dict, or None if the group doesn't exist:
    {"id": int, "created_at": iso, "members": [{"id": int, "joined_at": iso}],
     "pending_points_sync": bool}
and raises CheckinsUnavailable when the answer can't be had right now.
Production plugs in an adapter with set_directory(); tests plug in a fake.
"""

from typing import Optional, Protocol


class CheckinsUnavailable(Exception):
    """Checkins is down, too slow, or answered with an error."""


class GroupDirectory(Protocol):
    def fetch_group(self, group_id: int) -> Optional[dict]: ...


class LocalGroupDirectory:
    """Adapter for the monolith: reads auth and the outbox in-process, on its own connection.

    Replaced by an HTTP adapter after the split.
    """

    def fetch_group(self, group_id: int) -> Optional[dict]:
        from app.auth import service as auth_service
        from app.checkins import repository as checkins_repository
        from app.db import get_db

        with get_db() as conn:
            created_at = auth_service.group_created_at(conn, group_id)
            if created_at is None:
                return None
            return {
                "id": group_id,
                "created_at": created_at,
                "members": [
                    {"id": m["id"], "joined_at": m["joined_at"]}
                    for m in auth_service.list_members(conn, group_id)
                ],
                "pending_points_sync": checkins_repository.group_has_pending_outbox(conn, group_id),
            }


_directory: GroupDirectory = LocalGroupDirectory()


def set_directory(directory: GroupDirectory) -> None:
    global _directory
    _directory = directory


def get_directory() -> GroupDirectory:
    return _directory
