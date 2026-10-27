"""The catalog lock (TS §4.1 "Locking"; design note D4).

Every import, rebuild and policy delete holds the session-level
`pg_advisory_lock(hashtext('catalog'))` from before its first transaction
until after the upload's rename or the file's deletion, so they run one at a
time. It is taken and released in autocommit on a pinned session, never
inside a transaction.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from bitscan_manager.runtime import CatalogSession

log = logging.getLogger(__name__)


@contextmanager
def catalog_lock(session: CatalogSession) -> Iterator[None]:
    """Wait for the catalog lock, then hold it for the block."""
    session.conn.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
    try:
        yield
    finally:
        try:
            session.conn.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
        except Exception as exc:
            # Closing the connection ends the backend, and with it the lock.
            log.warning("catalog unlock failed: %s", type(exc).__name__)
            session.conn.close()
