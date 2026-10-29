# TASK-185 REVIEW: re-evaluation service (revision 1)

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-200, REQ-201, REQ-202, REQ-204 (2). High risk (evaluator; interface for M11). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-185-impl.md` (with "Revision 1"): one new file, `manager/bitscan_manager/services/evaluator/reevaluate.py` (149 lines).

TEST: PASS r1 (`work/reports/TASK-185-test.md`, tester-m8). 38/38, 16/16 plants red, and 1,345/1,345 across all M8 files. The 8 r1 failures were a test bug: `succeeded` isn't a `scan_state`. They passed on the re-run.

Spec read: TS §4.5 L601; §2.2 L114; §5.2 L929–L938, L1005–L1006; §5.3 L1049, L1052; §8.1 L1243; SR §2.4 L154; #12, #118 (a)–(h), #119; plan `TASK-185.md` §2–§4 (now aligned); decisions 2026-10-29 "A NULL `scan_result.stdout` on re-evaluation", "TASK-185 re-evaluation order" and "Re-evaluation fails closed on an unrecognised stored ERROR detail".

My re-run:
- WSL, PostgreSQL 16, the tester's base copy (product and test files checked identical to the worktree): `pytest tests/test_reevaluate_pg.py tests/test_reevaluate_race_pg.py` gives 38 passed.
- Windows: whole-tree `ruff check`, `ruff format --check` and `mypy --strict` are clean.

## Checks
1. **One transaction (REQ-200 (6)).**
   - The lock, the scan read, the definitions, every chunk's insert and the audit entry all run inside one `db.transaction()`.
   - `ScanNotFound` and `PolicyDeleted` are raised inside it, so nothing is written (CHK-M8-194).
   - A fault after the first chunk's real insert leaves no row and no entry (CHK-M8-195). CHK-M8-359 (the entry in its own transaction) is red.
   - `wake` is registered with `on_commit` only, and the early-wake plant is red.
2. **Serialised per scan (REQ-201 (1), (5)).** The lock comes first, before any read, so a second run waits and then gets the higher `reeval_id`s, and its verdicts become the latest (CHK-M8-210). Other scans don't wait (-214). CHK-M8-358 (race) is red.
3. **One snapshot of definitions (REQ-201 (2)).** The definitions are read once, in one statement, before any result. Each row records `defs.policy_version`, the version whose definitions were used, never the scan's. An import committed at three different points never mixes versions (CHK-M8-211; -354 race form and x185-version red).
4. **Rows only added (TS L1005–L1006, L1049; REQ-200 (2), (9)).**
   - The only writes are the `unnest` INSERT and the audit insert.
   - Checksums of `scan_result` (all partitions), `scan` and `scan_job` are identical before and after, and earlier re-evaluation rows are unchanged.
   - CHK-M8-353 (an UPDATE) fails on the grant, and the test sees the failure.
5. **Per-result rules, in the decided order.**
   1. A plugin the current version doesn't list gets no row and is counted in `not_in_version` (#118 (b); -356 red).
   2. An intake detail is kept (#12; -355 red).
   3. An ERROR whose stored detail isn't a `Detail` value (NULL, a case or padding variant, unknown text) becomes `cannot evaluate`.
   4. A NULL stdout becomes `cannot evaluate`.
   5. Otherwise `classify()` runs on the stored stdout, exit code and flags.

   Rules 3 and 4 close the false-PASS path `''` under `empty`. The order-swap, drop-step-3 and COALESCE plants are red.
   The stored text is only ever tested for membership in a frozenset, never passed to `Detail(text)`, so no stored value can raise mid-run. That resolves the item I carried from TASK-176.
6. **Deleted versus disabled (#118 (c), (d)).** Deleted is refused (`PolicyDeleted`; -357 red). Disabled is re-evaluated normally (CHK-M8-197).
7. **Audit (#118 (g), REQ-200 (4)).**
   - There's exactly one entry: actor `user:<id>`, action `scan.reevaluate`, target `scan:<uuid>` (41 characters, under 255, builder checklist item 16).
   - The detail holds only ids and counts. There's no alert, and the chain verifies.
   - The entry is written last, so the chain lock is held only briefly, at the end of a long run.
8. **Chunked (REQ-201 (3), (4)).** At most one chunk of `StoredResult` and one batch of `ReevalInsert` are held at a time. 20,000 results of 4,000 bytes each peak under 64 MiB, and every insert is at most 1,000 rows (-360 red). A late result stored during a run gets no row until the next run (-212).
9. **Output (REQ-202 (2), TS L1052).** No `logging` import. The exceptions carry no arguments, and details are #112 constants. The canary is in no log record, exception, audit detail or re-evaluation row, and -362 is red.
10. **Authorisation boundary.** The admin TOTP-session check and the 15-minute sink gate are M11's route (`require_totp_session("admin")`), as the plan says. The service trusts its caller, like M7's delete service. That has to be checked in M11's review.

## Findings
None blocking or should-fix.

1. Carried to M11: `POST /scans/{id}/reevaluate` must refuse API tokens and non-admins, require a TOTP-verified session, and apply the sink-outage gate (security invariants "Authorisation"; TS §6.2). This service has no check of its own.
