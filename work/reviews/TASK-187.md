# TASK-187 REVIEW: scan state derivation (pure)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-207 (and REQ-219's derivation rule). High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-187-impl.md`: one new file, `manager/bitscan_manager/services/jobs/scan_state.py` (49 lines).

TEST: PASS (`work/reports/TASK-187-test.md`, tester-m9). 53/53, with plants CHK-M9-360, -362 and -391 red. CHK-M9-361 (per job instead of per unit) cannot be planted in this module. It moves to TASK-194's `unit_facts`, and I'll check it there.

Spec read: TS §4.4 L579–L580; #22, #127 (d), (e); #3; `jobs-and-scans.md:37-40`.

My re-run: 298/298 across the M9 state, scan-state and property files (Windows). ruff is clean.

## Checks
1. **Rule order (#127 (d)).** The order is: any unit open gives `queued` (only when every unit is all-queued, #22) or `running`. Otherwise, all complete gives `completed`, then any results gives `partial`, then any cancelled gives `cancelled`, and anything else gives `failed`. This matches the approved answer. It resolves the two spec-internal overlaps (a `partial` original whose retry completed it, and `cancelled` versus `failed`) and the own question at `jobs-and-scans.md:40` (cancelled after results gives `partial` or `completed`).
2. **Never `dispatched` or `expired`** (`jobs-and-scans.md:37`). `ScanState` cannot hold either value. The exhaustive 1,024-pair check (CHK-M9-020) and the property suite (CHK-M9-082) confirm it.
3. **Finished (#127 (e)).** `finished` is True exactly when no unit is open. Setting `finished_at` once is the repository's job (TASK-194), not this module's.
4. **Empty input** raises `ValueError` (#3, a scan always has a job).

## Findings
None blocking or should-fix. The five facts aren't cross-checked for consistency, for example `all_queued` without `open`. That's correct for a pure function: TASK-194's SQL owns the consistency, and that is where I'll check it.
