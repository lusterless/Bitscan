# TASK-160 IMPL: catalog service and `serve` wiring

Implementer: impl-manager-m7. REQ-164, REQ-165 (5), (6), REQ-172. Risk high (importer; two approvals). No per-task plan; built from:
- the TASK-160 row;
- #102 (d), (e);
- REQ-056 (`/healthz` never waits for the database);
- the decisions rows "W6 pre-read rulings", "TASK-158 readings" and "TASK-158 test questions" (2026-10-28).

Carries applied:
- open the watcher before the start-up reconcile and run it after (TASK-159);
- a stop that can't hang on a thread waiting for the catalog lock (TASK-159 review; the W1 lock-waiter note).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/services/importer/service.py` (new, 143 / 123 / 98 lines total / non-blank / code) | `CatalogService`, `CatalogStarting`, `STARTING_DETAIL`, `RETRY_AFTER_S`, `STOP_WAIT_S` |
| `manager/bitscan_manager/runtime.py` | +18 / −1: a `Catalog` Protocol (importer types under `TYPE_CHECKING`, so there's no import cycle at run time) and `Runtime.catalog: Catalog \| None = None` |
| `manager/bitscan_manager/cli/serve.py` | +17 / −7: `ServeLifecycle(catalog=...)` starts and stops it; `build_runtime` builds `CatalogService(db, clock, config.bits_dir, wake=shipper.wake)` and passes it to the lifecycle and to `Runtime(catalog=...)` |

Size: about 115 hand-written lines against the estimate of 180. `manager/openapi.json` is unchanged: an export compared byte-identical.

## Interface (for TASK-162, TASK-163 and TASK-164)

```python
class CatalogStarting(Exception)          # #102 (d)
STARTING_DETAIL = "The catalog is starting; retry shortly."
RETRY_AFTER_S = 10

class CatalogService:                     # also the runtime.Catalog Protocol
    def __init__(self, db, clock, bits_dir, *, wake=lambda: None, watcher=None)
    ready: bool                           # property
    def upload(self, data: bytes, client_name: bytes | str | None, actor: Actor) -> ImportOutcome
    def delete(self, policy_id: int, actor: str) -> DeleteResult
    def start_rebuild(self, requested_by: int | None, actor: Actor) -> UUID
    def start(self) -> None
    def stop(self, wait_s: float = STOP_WAIT_S) -> None
```

- **The routes** get it as `runtime.catalog`; it is None in tests and the OpenAPI export.
- **On `CatalogStarting`,** a route answers 503 `about:blank` with `STARTING_DETAIL` and `Retry-After: RETRY_AFTER_S`.
- **The other errors propagate unchanged.** That includes `PolicyManagedOnServer`, `PolicyNotFound` and `PolicyAlreadyDeleted`, plus `DatabaseUnavailable` and `OSError` as 503 per #98 (j).
- **Each call:**
  - `upload` calls `uploads.upload` (manual mode, its own lock and staging);
  - `delete` calls `delete.delete_policy` (its own lock);
  - `start_rebuild` writes the task row (`rebuild.start_task`) and queues `rebuild.run` on the worker; the route answers 202 with the returned id.
  - Each call wakes the audit shipper afterwards.
- **The read routes** (`GET /policies`, `/imports`, `/tasks/{id}`) don't use the service, so they are served during start-up (#102 (d)).

## Threads and lifecycle

- **`catalog` thread:**
  1. `watcher.open()` adds the inotify watches. Done **before** the start-up reconcile, so changes made during it are queued (TASK-159 carry). Where inotify is missing it logs one line and returns False (REQ-164 (5)).
  2. `startup.run(db, clock, bits_dir, stop)` (TASK-158): finish uploads, fail running tasks, reconcile, integrity, all under one lock. It is retried every 10 s while the database is down (REQ-165 (6)). It returns None if stopped first, and the thread then ends without opening the gate.
  3. The gate opens (`ready` True), with one log line.
  4. `watcher.run(stop)` runs **after** the reconcile, if the watcher opened.
- **`catalog-rebuild` thread,** the one worker: it takes `(task_id, actor)` jobs from a queue and calls `rebuild.run` one at a time. A second rebuild request waits its turn, and its task row is already `running`. When stop is set, queued jobs aren't started; their tasks stay `running` until the next start-up fails them (TS §4.2 L540). A `run` that can't get a session is logged by type.
- **`ServeLifecycle.start`:** after `db.open()` (which doesn't wait), the shipper, the flusher and the scheduler, it calls `catalog.start()` and returns. Nothing waits for the database, so `/healthz` and `/readyz` answer at once (REQ-056).
- **`ServeLifecycle.stop`:** first `catalog.stop()`, before the scheduler, the shipper and the pool. That sets the stop event, which ends the start-up retry wait and the watcher's 1 s poll, posts the worker's sentinel, and joins each thread for at most `STOP_WAIT_S` (10 s).

**The lock-waiter carry:** a thread blocked on `pg_advisory_lock` has no timeout (TS §4.1 gives none). That can be the watcher handling an event, or a rebuild waiting behind a CLI rebuild (#102 (e)).
- The join is bounded. A thread still alive is logged by name ("catalog thread still running at stop: catalog-rebuild"), and the stop continues.
- Both threads are daemons. A blocked thread can't hold up process exit, and exit closes its connection, which ends the session and releases the session-level advisory lock.
- `concurrent.futures` was avoided on purpose: its worker threads are joined at interpreter exit, so a blocked one would hang it.
- A rebuild cut off this way leaves its task `running`, and the next start-up marks it `failed`.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager` passes, and `ruff format --check manager` passes (299 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 299 source files.
- `python -m bitscan_manager.app` export: byte-identical to `manager/openapi.json`.

## Scratch check (outside the tree, `%TEMP%\m7-154-scratch\check_service.py`; fakes; not a test)

- The order of events is: `watcher.open`, `startup.begin`, `startup.done`, `wake`, `watcher.run`, `upload`, `wake`, `start_task`, `rebuild.run`.
- Before the start-up completed, `upload` raised `CatalogStarting` (`ready` False). Afterwards it went through.
- The rebuild ran on the worker.
- With the worker blocked inside `rebuild.run`, `stop(wait_s=0.5)` returned in 0.5 s and logged the still-running `catalog-rebuild` thread.

## For the tester (tester-m7, TP-M7-20, `manager/tests/test_catalog_service.py`, `manager/tests/test_serve_catalog_linux.py`)

- **With fakes:**
  - inject `watcher=` with `open()`/`run(stop)`, and patch `service.startup.run`, `service.uploads.upload`, `service.delete_policy`, `service.rebuild.start_task` and `service.rebuild.run`;
  - a call before the start-up completes raises `CatalogStarting`, and the same call succeeds afterwards;
  - a started rebuild runs on the worker, and against PostgreSQL its task ends `succeeded`;
  - `ServeLifecycle.stop` stops the watcher (its `run` returns), waits for the worker, and returns within the bound even with a worker blocked on the lock.
- **On Linux:** `serve` with a temporary bits folder imports a folder file at start-up, and `/healthz` stays 200 with the database down.
- **Suggested plants:**
  - open the gate before `startup.run` returns → the before-ready row goes red;
  - open the watcher after the reconcile → a file written during the reconcile is missed (the TASK-159 order row);
  - an unbounded `join()` → the blocked-worker stop row hangs (red by timeout);
  - non-daemon threads → the process doesn't exit while a worker waits on the lock.

## Revision 1 (tester-m7's FAIL on CHK-M2-257; main's instructions, 2026-10-28)

**The regression:** `test_serve_scheduler_linux.py::test_sigterm_with_the_database_refusing_exits_promptly`, the existing 10 s SIGTERM bound with the database refusing, took 10.2–10.3 s. `ServeLifecycle.stop` calls `catalog.stop()` first. The `catalog` thread was inside `startup.run` → `run_once` → `db.session()`, waiting on the pool's connect timeout, and `stop` waited up to 10 s for it before the scheduler, flusher and shipper stops. The gate is unchanged; the code is fixed.

**The fix**, in `service.py` only (1 line and 2 comment lines): `STOP_WAIT_S` drops from 10.0 to **2.0** s per thread. The worst case, both threads blocked, is about 4 s of joins, well inside the 10 s bound. A longer wait buys nothing: both threads are daemons, so a thread still blocked is logged by name and process exit closes its connection, which releases the session lock. A rebuild cut off this way leaves its task `running`, and the next start-up fails it.

**Point (2), noticing stop promptly, needed no change to `startup.py` (TASK-158 isn't touched):**
- `startup.run` already waits between attempts on the stop event (`stop.wait(retry_s)`), never in a sleep, and returns None at once when it is set.
- There is no other acquire loop on that thread. The only wait that can't be interrupted is one `db.session()` inside an attempt, which the pool bounds to its connect timeout (`connect_timeout_s` 5 s), and the 2 s join now covers it.
- The watcher's `run` polls every 1 s and checks stop each time.

**Gates:** `ruff check manager` passes, `ruff format --check manager` passes (304 files), and the CI mypy command gives Success (304 files).

**Scratch:** with `startup.run` stubbed to block for 30 s, standing in for a connect that never returns, `stop()` returned in 2.0 s and logged "catalog thread still running at stop: catalog". Before the fix it waited 10 s.

**Not run here:** `test_serve_scheduler_linux.py` is Linux only, and the Python tests run in WSL, which only the tester uses. tester-m7 re-runs it by node id along with the rest of its TASK-160 set.

**Plant for the tester:** put `STOP_WAIT_S` back to 10.0 → CHK-M2-257 goes red again, at about 10.3 s with the database refusing.
