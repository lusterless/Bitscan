"""bitscan-manager serve (TS §8.7 L1343-L1371, §8.6; REQ-057; plan
work/plans/TASK-045.md).

One process: HTTPS only (TLS 1.2+), SIGHUP reloads the certificate on the
same socket, proxy headers ignored, no uvicorn access log or log config
(RequestLog and the JSON handler log instead). The lifecycle opens the app
pool and the retention pool (bitscan_retention, used only by the scheduler's
retention job), starts the audit shipper, the failed-check flusher, the
scheduler (inventory runs, offline_sweep, scan schedules and retention,
REQ-080, REQ-277) and the catalog (its start-up sequence, then the folder
watcher, and the rebuild worker; #102 (d)), and on SIGTERM first stops the
catalog (a bounded wait), then the scheduler (waiting for a running job, so
none starts after the pools closed), closes the retention pool, then flushes
the failed-check counts, stops the shipper (the queue stays on disk) and
closes the vault client and the app pool. BITSCAN_MIGRATE_DSN_FILE is never
read.
"""

import asyncio
import contextlib
import logging
import signal
import ssl
import sys
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

import uvicorn
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr
from uvicorn.server import HANDLED_SIGNALS

from bitscan_manager.api import webui
from bitscan_manager.api.ratelimit import FailedChecks, RateLimiter
from bitscan_manager.api.request_log import configure_logging
from bitscan_manager.app import create_app
from bitscan_manager.auth.vault import VaultCipher
from bitscan_manager.config import ConfigError, ServeConfig, load_serve_config
from bitscan_manager.db.pool import AppDatabase
from bitscan_manager.repositories.audit_log import PgAuditRepo
from bitscan_manager.runtime import Runtime, SystemClock
from bitscan_manager.services.audit import append_entry, raise_alert
from bitscan_manager.services.audit.disk_queue import DiskQueue, QueueError
from bitscan_manager.services.audit.shipper import DbOutageAudit, PgAuditTail, Shipper
from bitscan_manager.services.audit.sink_transport import transport_from_url
from bitscan_manager.services.importer.service import CatalogService
from bitscan_manager.services.scheduler.runner import SchedulerRunner

log = logging.getLogger(__name__)

AUDIT_QUEUE_DIR: Final = Path("/var/lib/bitscan/audit-queue")  # TS §8.7 L1344
FLUSH_EVERY_S: Final = 10.0
HELD_MAX: Final = 10_000
# Per-connection bounds (decisions 2026-10-21, "Database time bounds"). A frozen
# server whose network stack still answers is caught by statement_timeout only.
DB_BOUNDS: Final = {
    "keepalives": "1",
    "keepalives_idle": "60",
    "keepalives_interval": "15",
    "keepalives_count": "4",
    "tcp_user_timeout": "300000",
}
STATEMENT_TIMEOUT: Final = "-c statement_timeout=300000"


def bounded_dsn(dsn: SecretStr) -> SecretStr:
    params = conninfo_to_dict(dsn.get_secret_value())  # already parsed at load
    options = str(params.get("options") or "")
    params.update(DB_BOUNDS, options=f"{options} {STATEMENT_TIMEOUT}".strip())
    return SecretStr(make_conninfo(**{k: str(v) for k, v in params.items()}))


def make_tls_context(cert: Path, key: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)  # no client certificates
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


def reload_certificate(context: ssl.SSLContext, cert: Path, key: Path) -> bool:
    """Validate the new pair first; keep the current one if it is bad."""
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
        context.load_cert_chain(cert, key)
    except (OSError, ssl.SSLError) as exc:
        log.error(
            "tls reload failed, keeping the current certificate (%s)",
            type(exc).__name__,
        )
        return False
    log.info("tls certificate reloaded")
    return True


class FailedCheckFlusher:
    """Writes the aggregated failed-token-check entries (REQ-047 (4)). Entries
    whose write fails are held, in order, and written first next time; at most
    HELD_MAX are held, oldest dropped first."""

    def __init__(self, limits: RateLimiter, db: AppDatabase, wake: Shipper) -> None:
        self._limits, self._db, self._shipper = limits, db, wake
        self._held: list[FailedChecks] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="failed-checks", daemon=True
        )

    def flush(self, *, final: bool = False) -> None:
        self._held.extend(self._limits.drain(final=final))  # also prunes old keys
        if len(self._held) > HELD_MAX:
            dropped = len(self._held) - HELD_MAX
            del self._held[:dropped]
            log.error("failed-check entries dropped: %d", dropped)
        while self._held:
            entry = self._held[0]
            try:
                with self._db.transaction() as tx:
                    repo = PgAuditRepo(tx.conn)
                    if entry.alert:
                        raise_alert(
                            repo,
                            tx.on_commit,
                            kind="token_check_failures",
                            actor="system",
                            action=entry.action,
                            detail=entry.detail,
                        )
                    else:
                        append_entry(
                            repo,
                            actor="system",
                            action=entry.action,
                            detail=entry.detail,
                        )
                    tx.on_commit(self._shipper.wake)
            except Exception as exc:
                log.error("failed-check entries not written (%s)", type(exc).__name__)
                return
            self._held.pop(0)

    def _loop(self) -> None:
        while not self._stop.wait(FLUSH_EVERY_S):
            self.flush()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(FLUSH_EVERY_S + 5)
        self.flush(final=True)


class ServeLifecycle:
    def __init__(
        self,
        db: AppDatabase,
        shipper: Shipper,
        flusher: FailedCheckFlusher,
        cipher: VaultCipher,
        tls: tuple[ssl.SSLContext, Path, Path],
        scheduler: SchedulerRunner | None = None,
        catalog: CatalogService | None = None,
        *,
        retention_db: AppDatabase | None = None,
    ) -> None:
        self._db, self._shipper, self._flusher, self._cipher = (
            db,
            shipper,
            flusher,
            cipher,
        )
        self._tls = tls
        self._scheduler = scheduler
        self._catalog = catalog
        self._retention_db = retention_db

    async def start(self) -> None:
        self._db.open()  # does not wait for the database
        if self._retention_db is not None:
            self._retention_db.open()  # nor does this one
        self._shipper.start()
        self._flusher.start()
        if self._scheduler is not None:
            self._scheduler.start()
        if self._catalog is not None:
            self._catalog.start()  # in the background: /healthz never waits
        if hasattr(signal, "SIGHUP"):
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGHUP, reload_certificate, *self._tls
            )

    async def stop(self) -> None:
        if hasattr(signal, "SIGHUP"):
            asyncio.get_running_loop().remove_signal_handler(signal.SIGHUP)
        if self._catalog is not None:
            self._catalog.stop()  # bounded; before the pool closes
        if self._scheduler is not None:
            self._scheduler.stop()  # before the pools close (REQ-080 (3))
        if self._retention_db is not None:
            self._retention_db.close()  # only the scheduler uses it
        self._flusher.stop()
        self._shipper.stop()
        self._cipher.close()
        self._db.close()


def build_runtime(config: ServeConfig, tls: ssl.SSLContext, queue_dir: Path) -> Runtime:
    clock = SystemClock()
    db = AppDatabase(bounded_dsn(config.db_dsn))
    transport = transport_from_url(config.audit_sink)  # plain transports refused
    queue = DiskQueue(queue_dir)
    shipper = Shipper(PgAuditTail(db), queue, transport, clock, DbOutageAudit(db))
    cipher = VaultCipher(config.vault_addr, config.totp_key_ref, config.vault_token)
    limits = RateLimiter(clock)
    flusher = FailedCheckFlusher(limits, db, shipper)
    # Retention connects only as bitscan_retention, through its own pool
    # (BITSCAN_RETENTION_DSN_FILE; TS §5.3 L1051, §8.6 L1309); one run at a time.
    retention_db = AppDatabase(
        bounded_dsn(config.retention_dsn),
        min_size=0,
        max_size=1,
        name="bitscan_retention",
    )
    scheduler = SchedulerRunner(
        db,
        clock,
        shipper.wake,
        retention_db=retention_db,
        shipped_through=shipper.shipped_through,
    )
    catalog = CatalogService(db, clock, config.bits_dir, wake=shipper.wake)
    lifecycle = ServeLifecycle(
        db,
        shipper,
        flusher,
        cipher,
        (tls, config.tls_cert_file, config.tls_key_file),
        scheduler,
        catalog,
        retention_db=retention_db,
    )
    return Runtime(clock, db, cipher, shipper, limits, lifecycle, catalog=catalog)


class _Server(uvicorn.Server):
    """uvicorn re-raises the caught SIGTERM after shutting down, so the
    process would end killed by it; here a graceful stop exits 0."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        original = {
            sig: signal.signal(sig, self.handle_exit) for sig in HANDLED_SIGNALS
        }
        try:
            yield
        finally:
            for sig, handler in original.items():
                signal.signal(sig, handler)


def serve_main(environ: Mapping[str, str], *, queue_dir: Path = AUDIT_QUEUE_DIR) -> int:
    configure_logging()
    try:
        config = load_serve_config(environ)
    except ConfigError as exc:
        for line in str(exc).splitlines():
            print(f"serve: {line}", file=sys.stderr)
        return 2
    tls: ssl.SSLContext | None = None
    try:
        tls = make_tls_context(config.tls_cert_file, config.tls_key_file)
    except (OSError, ssl.SSLError):
        pass
    if tls is None:  # outside the except block: no key material is chained
        print(
            "serve: BITSCAN_TLS_CERT_FILE and BITSCAN_TLS_KEY_FILE are not a usable "
            "certificate and key",
            file=sys.stderr,
        )
        return 2
    try:
        runtime = build_runtime(config, tls, queue_dir)
    except (ConfigError, QueueError) as exc:  # messages name the setting only
        print(f"serve: {exc}", file=sys.stderr)
        return 2
    scheme = config.audit_sink.split(":", 1)[0]
    log.info(
        "serving on %s:%d, TLS 1.2+, audit sink %s",
        config.listen_host,
        config.listen_port,
        scheme,
    )
    ui = webui.load(webui.DEFAULT_WEBUI_DIR)
    if ui.index is None:
        log.info("web ui not built; serving the API only")
    server = _Server(
        uvicorn.Config(
            create_app(runtime, webui=ui),
            host=config.listen_host,
            port=config.listen_port,
            workers=1,
            lifespan="on",
            ssl_context_factory=lambda _config, _default: tls,
            proxy_headers=False,  # #55 (d): the TCP peer is the client
            server_header=False,
            access_log=False,  # RequestLog writes access records without queries
            log_config=None,  # keep configure_logging's JSON handler
        )
    )
    server.run()
    return 0 if server.started else 1
