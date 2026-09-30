"""Points & Forfeits domain: the only functions the check-ins domain may call.

This is the seam where a future service split would put an HTTP call or a
published event. Only IDs (and the shared connection, so both domains' writes
commit in one transaction) cross it.
"""


def revoke_completion(conn, checkin_id: int) -> None:
    """Take back the points a check-in earned, because it was rejected by vote.

    Must be idempotent: revoking a check-in that was never recorded, or was
    already revoked, is a no-op. Phase 4 implements this; until then there are
    no points to revoke.
    """
