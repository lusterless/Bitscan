# TASK-160 TEST: PASS (round 2, on revision 1)

Tester: tester-m7, 2026-10-28. Full rigor (importer). REQ-164, REQ-165 (5) (the CatalogStarting gate; the 503 itself is TASK-162–164's), REQ-172; TS §4.1 L526, L528, §4.2 L540; #102 (d), (e); CHK-M2-257 (SIGTERM within 10 s with the database refusing; TASK-071 r1 ruling). Code under test: `bm/services/importer/service.py` (r1: `STOP_WAIT_S` 2 s per thread), `bm/runtime.py` (`Catalog`, `Runtime.catalog`), `bm/cli/serve.py` (`ServeLifecycle` starts and stops the catalog; `build_runtime`). New test files: `manager/tests/test_catalog_service_pg.py` (11 tests: fakes for the gate, worker and stop; PostgreSQL for the rebuild and lock rows; the real watcher for the reconcile row) and `manager/tests/test_serve_catalog_linux.py` (2 tests, the real `serve`).

## Rounds

| Round | Run (W, `-n 0` or `-n 2` per the memory floor, `CI=true`) | Count |
| --- | --- | --- |
| 1 (r0) | `test_catalog_service_pg`, `test_serve_catalog_linux`, `test_serve_linux`, `test_serve_scheduler_linux`, `test_runtime` (`-n 2`) | 79/80 passed, **1 failed**: `test_serve_scheduler_linux.py::test_sigterm_with_the_database_refusing_exits_promptly[closed-port]`, 10.3 s against the 10 s bound. A re-run alone gave 10.2 s for `wrong-password`. A plant without the catalog in `ServeLifecycle` passed 2/2, so the catalog's stop caused it: up to 10 s waiting for a thread blocked in `db.session()`. Sent to impl-manager-m7 → **FAIL** |
| 2 (r1) | the failing test by node id | **2/2 passed** |
| 2 (r1) | the whole set above plus `test_cli_bits_pg.py` (TASK-166) (`-n 0`) | **92/92 passed** (80 for this task), 0 failed, 0 errors, 0 skipped |
| plants | 10 plants (`/root/bstest-m7-mut-<id>`, removed after each) | 10/10 red |
| static (L) | whole-tree ruff, ruff format, `mypy --strict` (CI form) | clean (304 files) |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-242 gate | APP | W | round 2 | PASS | Until `startup.run` returns, `upload`, `delete` and `start_rebuild` each raise `CatalogStarting`, nothing reaches the importer and the shipper isn't woken. After it returns, each goes through with its arguments, and the shipper is woken after each. The texts are the #102 (d) ones ("The catalog is starting; retry shortly.", `Retry-After` 10). A stop before the start-up ends leaves the gate closed. Without a watcher (open False) the gate still opens | 2026-10-28 |
| watcher order | APP | W | round 2 | PASS | Fakes: `watcher.open`, `startup.run`, `startup.done`, then `watcher.run`. Real watcher: a file written after the start-up reconcile's import pass, before the gate opens, is imported afterwards (queued since the watch was added first) | 2026-10-28 |
| worker | APP | W | round 2 | PASS | Three `start_rebuild` calls return at once: the task row is written on the caller's thread. The rebuilds run one at a time (peak 1) on `catalog-rebuild`. A failing run is logged by type (`rebuild did not start: OSError`, no message) and the next one runs. On PostgreSQL the real start-up imported the folder file, and a started rebuild's task ended `succeeded` with `requested_by` 51 | 2026-10-28 |
| stop | APP | W | round 2 | PASS | With the worker blocked (a fake, and also the real catalog lock held by another session), `stop(wait_s=1)` returns in about 1 s. It logs `catalog thread still running at stop: catalog-rebuild`, the watcher's `run` has returned, and the blocked task stays `running`; the real-lock one finishes once the lock is released. Both threads are daemons. `2 × STOP_WAIT_S ≤ 5` (r1: 2 s), so both joins fit well inside the 10 s SIGTERM bound | 2026-10-28 |
| lifecycle | APP | W | round 2 | PASS | `ServeLifecycle.start`: db, shipper, flusher, scheduler, then catalog. `stop`: catalog first, then scheduler, flusher, shipper, cipher and db | 2026-10-28 |
| CHK-M7-243 | APP | W | round 2 | PASS | Real `serve` with `BITSCAN_BITS_DIR` a temporary folder: the folder file gets its `success` row within 30 s, the log says `catalog ready`, and SIGTERM exits 0. With the database down (a closed port): `/healthz` stays 200 over 3 s, the catalog never becomes ready and the file gets no row, and SIGTERM exits 0 within 15 s | 2026-10-28 |
| CHK-M2-257 | APP | W | round 2 | PASS | The existing gate: SIGTERM within 10 s with the database refusing the login or down, 2/2 on r1 (it failed on r0) | 2026-10-28 |
| plant g1 | APP | W | the gate check removed | PASS (red) | 2 failed: a call before ready succeeded | 2026-10-28 |
| plant g2 | APP | W | ready set before the start-up | PASS (red) | 3 failed | 2026-10-28 |
| plant g3 | APP | W | the watcher opened after the start-up | PASS (red) | 3 failed, among them the real "changed during the reconcile" row (missed) | 2026-10-28 |
| plant g4 | APP | W | unbounded `join()` | PASS (red) | 1 failed: stop did not return within 10 s with the worker blocked | 2026-10-28 |
| plant g5 | APP | W | non-daemon threads | PASS (red) | 1 failed | 2026-10-28 |
| plant g7 | APP | W | the rebuild run on the request thread | PASS (red) | 1 failed: `MainThread` instead of `catalog-rebuild`. The whole file deadlocks against the held lock, so it was run on that row | 2026-10-28 |
| plant g6 | APP | W | `ServeLifecycle.stop` doesn't stop the catalog | PASS (red) | 1 failed: lifecycle order | 2026-10-28 |
| plant g8 | APP | W | `ServeLifecycle.start` doesn't start the catalog | PASS (red) | 2 failed: lifecycle, and `serve` imports nothing | 2026-10-28 |
| plant sw (r1) | APP | W | `STOP_WAIT_S` back to 10 s | PASS (red) | 3 failed: both CHK-M2-257 cases (10.3 s) and the budget pin | 2026-10-28 |

## Acceptance (TASK-160 row)

- With fakes, refused before and succeeding after → gate.
- A started rebuild runs on the worker and its task ends `succeeded` → worker.
- `ServeLifecycle.stop` stops the watcher and waits for the worker, bounded even with the worker blocked on the lock → stop and lifecycle.
- On Linux, `serve` imports at start-up and `/healthz` stays 200 with the database down → CHK-M7-243.
- REQ-165 (5) → the gate. The watcher opening before the reconcile → watcher order.

Every security row and the gate have a plant that went red.

## Notes (no defect)

- Without `BITSCAN_BITS_DIR` and with `/var/lib/bitscan/bits` missing, as in the older `serve` tests in WSL, the start-up retries every 10 s and the catalog stays closed. It fails closed, and each retry logs only the error type.
- Shared venv: `/root/venv-m7`'s editable install points at the last folder installed. Console-script subprocesses (`run_cli`) therefore import that tree, not the plant copy. I set `PYTHONPATH` for those plants and told main.

## Shared-venv check (lead, 2026-10-28)

No TASK-160 row or plant uses the console script. The `serve` rows (g6, g8, CHK-M7-243) start `serve_main` through `python -c` from the tree under test, and the service rows run in-process. The plant results stand. Of my earlier M7 files only `test_cli_bits_pg.py` uses `run_cli` (see TASK-166). The module databases' `db migrate` also uses the console script, but no M7 change touches migrations.
