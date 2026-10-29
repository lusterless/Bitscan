# TASK-154 REVIEW: import pipeline (`import_one`, design note D4)

Verdict: APPROVED (revision 2)

Reviewer: reviewer-m7, 2026-10-28. REQ-150, REQ-155, REQ-157, REQ-160, REQ-162, REQ-176. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed, per `work/reports/TASK-154-impl.md` (including "Revision 1" and "Revision 2"). Two new files:
- `manager/bitscan_manager/services/importer/pipeline.py`: 148 non-blank lines.
- `manager/bitscan_manager/services/importer/pipeline_record.py`: about 270 non-blank lines after r2.

The plan §11 split was accepted by the lead (decisions 2026-10-28, "TASK-154 and TASK-165 rulings"), together with the seven interface differences. Imports go one way only.

TEST: PASS on r0, r1 and r2 (`work/reports/TASK-154-test.md`, tester-m7).
- r0: 217/217 on PostgreSQL (216 pipeline tests, plus a fuzz of 500 files checked against an independent defusedxml read); 14 plants red, each named plant (CHK-M7-333, -339, -340, -349, -350, -369) in both of its forms.
- r1: 217/217. The r1 plant is red, and 350 a, 350 b and 339 are red again.
- r2: 224/224. Plants r2a and r2b are red. r2c (the gate applied in every mode) is equivalent alone, and the claim holds: outside rebuild mode `before` is None, so the gate is always true. r2c is red combined with r2d.
- Five BIT102 fixtures (`R2_PENDING`) are NOT RUN until TASK-146 r2 is approved. They don't depend on pipeline code, because the BIT102 wiring is proven on every entry point with `rm x` and by plant 333 a and b.

My checks: `ruff check`, `ruff format --check` and `mypy --strict` (CI config) are clean on both files after r2. The only log call is `bit_import record failed: <type>`.

Spec read: TS §4.1 L512–L532, §4.2, §8.4 L1288–L1291; SR §3.5, §3.6, §4 (L250); #23, #98 (j), #99 (b), (e), #100 (a) widened, #101, #110; the BIT016 ruling (decisions L317); decisions 2026-10-28 "TASK-154 test questions" and "TASK-157 rulings" (2); `work/plans/TASK-154.md`.

## Checks
1. **Read once, then parse and validate (TS L515–L517).** `prepare(data)` is pure and works from the one buffer.
   - BIT001 or BIT002 stops the content rules.
   - BIT016 is reported with the content findings.
   - BIT102 runs on every trimmed `Execute` that passed BIT008, in every mode, because `prepare` is mode-independent. TASK-157 calls `prepare` per file.
   - Any Reject drops the `Candidate`. That closes my TASK-144 carry: `format_version` is never stored from a BIT016 file.
2. **Transactions (TS L518–L520, SR L244–L246).**
   - Transaction 1 holds `decide`, the `auto` skip, `check_ownership`, `apply`, the audit entries, and then `before_commit` as the last step.
   - A skip or a rejection leaves through `Abort` inside the `with`, so it rolls back and its on-commit hooks never run (builder checklist 7).
   - Transaction 2 writes the row, plus the rejected alert and the failure count on commit.
   - An internal error writes no row (#98 (j)).
   - After a committed success, the record is always attempted in a `finally`, and a record failure is logged by type only.
3. **Skip (TS L532, §4.2).** The skip is decided from the state read under the catalog lock in transaction 1 (checklist 9). Only `auto` skips, and only on the last successful hash for the same `source_file`; a deleted policy is revived, not skipped. The skip comes before the findings, which conforms: TS L532 and §4.2 define the automatic skip by hash ("imports new or changed files only"), and manual imports and rebuilds re-validate. The lead ruled the same way (test questions (3)).
4. **Lock (TS L526).** `import_one` never takes or releases the lock, so the caller's lock covers the post-commit removals and `after_commit` (proved by the lock row and its plant).
5. **Audit and alerts (TS L530, §8.4; #100, #101).**
   - `policy.import` carries `changed_executes` unchanged from the store.
   - `policy.move` is written on every move.
   - `policy.delete` and `policy_deleted` are written for the displaced policy. `store.apply` deletes no other policy, so every delete alerts.
   - `policy_reenabled` is written when the file re-enables a policy.
   - A rejection alerts in the record transaction, so a rebuild savepoint rollback can't drop it. Its target is `policy:<id>` when a policy matched, else the file name cut to 255 (test questions (1); checklist 16).
   - `policy.import_refused` has no alert and no client text.
6. **Security invariants.** There is no XML or regex code here and no SQL text; the repositories are parameterised. No file content, `Execute`, name or finding reaches a log (tested, including the `rm x` canary). There is no path that runs, queues or signs anything.
7. **Revision 1 (test questions (2), SR §3.5: `policy_version` only when the import succeeded).**
   - The skip `ImportOutcome` no longer carries `old.version`.
   - `record` writes `policy_version` only when `outcome == "success"`, so no caller-built pending outcome, a rebuild's included, can put a version on a skipped or rejected row.
   - CHK-M7-192 is re-pinned to NULL; CHK-M7-191 and the fuzz assert NULL on every non-success row.
8. **Revision 2 ("TASK-157 rulings" (2), #23, REQ-166 (6)).** In `rebuild` mode, the §7 entries are written only if `_changed(...)`.
   - What counts as a change: a case other than `update`, a displaced policy, plugins added, updated or retired, any `changed_executes`, or a before/after difference in `_fingerprint`.
   - The fingerprint comes from `catalog_admin.detail`, read under the lock in the same transaction. It holds the policy row without `imported_at` (`policy_status` and `version` included), `deleted_at`, and every listed plugin with its `sort_order`, `execute` and `state`. So each REQ-166 (1) corruption is caught: status, membership, `execute`, retired state and version. A corrupted `source_sha256` shows up as a version bump, and a wrong owner as `plugins_updated`; the test proves all six.
   - `updated_at` in the fingerprint can't mark an unchanged file as changed. The policy UPDATE moves it only on a real change (`catalog.py` L165–L169), and the plugin upsert writes only rows that differ.
   - Manual and `auto` imports never read the fingerprint and always audit (L120–L124; plant r2c + r2d).

## Findings
None blocking or should-fix.

1. nit, `pipeline.py:111`: when a caller omits `prepared`, the 5 MiB parse runs under the catalog lock. Every current caller passes `prepared=` (`upload`, `import_path`, and the rebuild through `store_in_savepoint`). Consider making it required.
2. Carried and closed: TASK-157 calls `prepare` per file and catches `PolicyManagedOnServer` outside the savepoint; TASK-155 leaves the temp file when `after_commit` fails.
3. Carried to the TASK-146 r2 batch: tester-m7 adds the five `R2_PENDING` BIT102 fixtures to `REJECTING` and re-runs CHK-M7-191 as a targeted run after 146 r2 is approved.
