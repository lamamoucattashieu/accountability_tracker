"""Points outbox: queue points changes locally, deliver them to Points afterwards.

enqueue_* runs inside the caller's transaction, so a check-in (or rejection)
and its outbox row commit together or not at all. deliver_pending runs after
that commit, on its own connection. Delivery is at-least-once: a row whose
call timed out may already have reached Points and is sent again later, which
is safe because Points ignores repeats (idempotent receiver).
"""

import json
import logging

from app.checkins import repository
from app.checkins.points_client import PointsRejected, PointsUnavailable, get_client
from app.config import OUTBOX_BATCH
from app.shared.timeutils import utc_now_iso

logger = logging.getLogger(__name__)


def enqueue_record(conn, completion: dict) -> None:
    repository.insert_outbox(
        conn, "record", completion["checkin_id"], completion["group_id"],
        json.dumps(completion), utc_now_iso(),
    )


def enqueue_revoke(conn, checkin_id: int, group_id: int, revoked_at: str) -> None:
    repository.insert_outbox(
        conn, "revoke", checkin_id, group_id, json.dumps({"revoked_at": revoked_at}), utc_now_iso(),
    )


def _send(row) -> None:
    payload = json.loads(row["payload"])
    if row["kind"] == "record":
        get_client().record(payload)
    else:
        get_client().revoke(row["checkin_id"], payload["revoked_at"])


def deliver_pending(conn, limit: int = OUTBOX_BATCH) -> None:
    """Send pending rows oldest first; stop at the first one Points can't take right now.

    Stopping keeps the order: a revoke never overtakes its record. A row Points
    rejects (4xx) is marked failed and skipped, so one bad payload can't block
    every later row. Each row's outcome commits on its own.
    """
    for row in repository.pending_outbox(conn, limit):
        try:
            _send(row)
        except PointsRejected as exc:
            logger.error("points rejected outbox row %s: %s", row["id"], exc)
            repository.mark_outbox_failed(conn, row["id"], utc_now_iso(), str(exc))
            conn.commit()
            continue
        except PointsUnavailable as exc:
            logger.warning("points unavailable, outbox row %s stays pending: %s", row["id"], exc)
            repository.note_outbox_error(conn, row["id"], str(exc))
            conn.commit()
            return
        repository.mark_outbox_sent(conn, row["id"], utc_now_iso())
        conn.commit()
