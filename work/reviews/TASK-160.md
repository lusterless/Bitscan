# TASK-160 REVIEW: catalog service and `serve` wiring

Verdict: APPROVED (revision 1)

Reviewer: reviewer-m7, 2026-10-28. REQ-164, REQ-165 (5), (6), REQ-172. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed, per `work/reports/TASK-160-impl.md` including "Revision 1":
- `manager/bitscan_manager/services/importer/service.py`: new, 123 non-blank lines.
- `manager/bitscan_manager/runtime.py`: +18 / −1, the `Catalog` Protocol and `Runtime.catalog`.
- `manager/bitscan_manager/cli/serve.py`: +17 / −7.

Three files. `manager/openapi.json` is unchanged.

TEST: PASS on r1 (`work/reports/TASK-160-test.md`, tester-m7).
- Round 1 FAILED CHK-M2-257: SIGTERM with the database refusing took 10.3 s against the 10 s bound, because `catalog.stop()` waited up to 10 s on a thread blocked in `db.session()`.
- r1 cut `STOP_WAIT_S` to 2 s per thread. The gate wasn't changed.
- Round 2: 92/92 (80 for this task). 10/10 plants red, including sw (`STOP_WAIT_S` back to 10 s), which turns CHK-M2-257 red again.

Spec read: TS §4.1 L526, L528, §4.2 L540; REQ-056; #102 (d), (e); decisions 2026-10-28 "W6 pre-read rulings", "TASK-158 readings", "TASK-158 test questions"; CHK-M2-257 (TASK-071 r1).

## Checks
1. **Gate (#102 (d), REQ-165 (5)).**
   - `upload`, `delete` and `start_rebuild` raise `CatalogStarting` until `startup.run` has returned a report. The text and `Retry-After` are fixed per #102 (d); the 503 itself belongs to TASK-162 to 164.
   - The read routes and `/healthz` don't use the service, and `ServeLifecycle.start` never waits for it (REQ-056; CHK-M7-243 with the database down).
   - A stop before the start-up ends leaves the gate closed (plants g1 and g2).
2. **Order (TASK-159 and TASK-158 carries).** The `catalog` thread opens the watcher, runs the start-up sequence, opens the gate, and only then runs the watcher, so changes made during the reconcile are queued and handled (plant g3).
3. **Rebuild worker (REQ-172).**
   - `start_rebuild` writes the task row on the caller's thread, so the route can answer 202 with its id at once.
   - The one `catalog-rebuild` worker runs rebuilds one at a time (plant g7). Each rebuild takes its own catalog lock and re-checks its task (TASK-157 r2).
4. **Stop.**
   - The stop event ends the start-up retry wait and the watcher's poll, and a sentinel stops the worker.
   - Each join is bounded at 2 s, and a thread still alive is logged by name. Both threads are daemons, so a thread blocked on the advisory lock can't hold up exit, and exit closes its connection, which releases the lock (plants g4 and g5).
   - `ServeLifecycle.stop` stops the catalog first, before the scheduler, the shipper and the pool (plants g6 and g8).
   - The pool's `close()` waits only for its own workers, not for connections still in use, so a thread cut off at the join adds no further wait.
5. **Layering and security.** The service only gates and delegates to the approved `uploads.upload`, `delete.delete_policy` and `rebuild`. It runs nothing ad hoc, logs only exception types, and holds no secrets. The `Catalog` Protocol imports the importer types only under `TYPE_CHECKING`, so there's no cycle at run time.

## Findings
None blocking or should-fix (the round 1 FAIL is fixed in r1 and pinned by plant sw).

1. nit, `service.py:140-143`: when `rebuild.run` raises because it can't get a session, its task stays `running` until the next `serve` start-up, which could be days later. `GET /tasks/{id}` would show `running` all that time. Marking the task `failed` from the worker once a session can be had again, or noting the behaviour in the TASK-167 README, would make it clearer. TS §4.2 L540 only requires the start-up step, so this isn't a deviation.
2. nit: a queued rebuild's task row says `running` while it waits behind another rebuild. #20 and #98 (g) have no `queued` state, so that is what the model allows.
3. Carried to TASK-162 to 164: map `CatalogStarting` to 503 `about:blank` with `STARTING_DETAIL` and `Retry-After: RETRY_AFTER_S`, and the internal errors (`DatabaseUnavailable`, `OSError`, `FileExistsError`) to 503 (#98 (j)).
