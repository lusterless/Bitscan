# TASK-154 REVIEW: import pipeline `import_one`

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-150, REQ-155, REQ-157, REQ-160, REQ-162, REQ-176. High risk (importer; two approvals, PD-35).

Scope reviewed: frozen worktree at `00b8e4e`, product code from `82a6836`. Per `work/reports/TASK-154-impl.md`:
- `services/importer/pipeline.py` (new, 249 lines);
- `services/importer/pipeline_record.py` (new, 167 lines).

The split (307 code lines → 199 + 135) is the one plan §11 foresees, and the lead ruled it ("TASK-154 split and interface rulings"). It is two files with imports in one direction only, so it is not a finding. The five interface changes in that ruling are each forced by approved code, and I accept them.

TEST: PASS (`work/reports/TASK-154-test.md`; 202/202 new, 2829/2829 affected, 19/19 plants red, 100 % line coverage of both files).

Re-run by me: the three new PostgreSQL files gave 202 passed. `ruff check`, `ruff format --check` (286 files) and `mypy --strict manager` are clean.

Spec read: TS §4.1 L516–L532, §5.2 (`bit_import`), §8.4 L1290–L1291; SR §3.6, L250; D4; plan §3–§11. Answers applied: #23, #98 (j), #99 (b)/(e), #100 (a) as widened, #101, #110.

## Checks
1. **Order (D4, TS §4.1).**
   - `prepare` runs on the one buffer: BIT001, then BIT002 (which stops the content rules), then the content rules with BIT016 carried on, then BIT102 on every `Execute` that passed BIT008. It does no I/O, and the caller passes `prepared=` from before the lock.
   - Transaction 1 runs `decide`, then the `auto` skip, then BIT007/BIT015, then `apply`, then the success audit entries, then `before_commit`.
   - Commit is followed by `remove_after_commit` and `after_commit`, then transaction 2 (the record, the rejected alert and the count on commit).
2. **Whole file.**
   - Any Reject, file-local or from the database, raises `_Abort`. Transaction 1 rolls back with its entries and counters, because the alert counters run on commit (P01 and P02 red).
   - The rebuild path uses one savepoint per file, never skips, and drops a rejected file's entries.
3. **Internal errors (#98 (j)).**
   - A database error, or an error from `before_commit`, propagates and writes no row.
   - If transaction 2 fails after a committed success, it logs the exception type only and returns `import_id=None`.
   - If transaction 2 fails for a rejected or skipped file, the error propagates.
4. **Records.**
   - Every finding goes to `errors`, warnings included (#110), sorted by line with a stable sort.
   - A rejection's target is `policy:<id>` or the file name cut to 255 characters (checklist 16).
   - The metric is counted once per rejection, with its mode.
5. **Logs (checklist 11).** There are two fixed log lines with counts and ids only. The canary test shows no `Execute` text, name, client file name or token reaches a log.
6. **Invariants.** It adds no command path; it never deletes `policy` and never edits `bit_import`; it has no `re` import; and BIT102 runs in every mode and for every target (CHK-M7-333 red).

## The points main raised
1. **Lock held only by contract (tester note 1): nit, carried to the callers.**
   - An entry guard would need either new state on the approved TASK-147 `CatalogSession`, or a `pg_locks` query that knows the key from `catalog_lock.py`. Either widens this task.
   - The lock is the callers' job by design (D4). Each caller (TASK-155 to 158) is high risk and gets its own review and two approvals.
   - TS §8.3 already requires "concurrent upload and rebuild serialise". The test plan must have a test per caller that runs two imports at a barrier and proves they serialise; I will check it in each of those reviews.
   - If main wants a guard anyway, the cheapest is `SELECT … FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()` in `repositories/catalog_lock.py`, checked at the start of transaction 1, failing closed.
2. **`FileInput.sha256` trusted (tester note 2): nit, carried to TASK-155 and 156.**
   - `FileInput` carries the hash twice: `sha256` goes into `bit_import` and the alerts, and `target.file_sha256` goes into `source_sha256` and the `auto` skip. Nothing makes them agree with each other or with `data`.
   - No caller exists yet, so this is not a defect today.
   - Fix (3 lines, here or in TASK-155): `FileInput.__post_init__` raises `ValueError` unless `sha256 == target.file_sha256` and, when `data` is not None, `sha256 == hashlib.sha256(data).hexdigest()`. Hashing 5 MiB costs a few milliseconds.
   - If it is not added here, the TASK-155 and 156 reviews will require it.
3. **Deviation (5), the success row kept after a failed rename: agreed.**
   - The catalog committed, and TS §4.1 L520 / SR §3.6 put a record after every catalog transaction. REQ-160 (4) keeps the committed catalog.
   - Writing no row would hide a live version. The 500 tells the admin, a manual retry never skips, and TASK-155's start-up step finishes the rename (the temp file's hash equals `source_sha256`).
   - Carry for main (the spec is silent): until the next start-up, a rebuild (TASK-157) would re-import the stale `uploaded/policy-<id>.bit` and put back the older version. It would alert, so the revert is not silent. I suggest the rebuild finish or clean interrupted temp files under the lock first, as start-up step 1 does.
   - A related carry for TASK-156: if the COMMIT itself fails after `before_commit` wrote the temp file, the caller must delete it ("only a successful import keeps the file").
4. **`policy.import_refused` detail (tester note 4): agreed.**
   - The detail is `{policy_id, mode, file_sha256}`, the target is `policy:<id>`, and there is no alert, per #99 (e) and #101.
   - No client text appears in it (checklist 12, canary checked).
5. **No `sink_gate.wake`: nit.**
   - The other alerting paths wake the shipper on commit, while this one and `delete.py` rely on the poll. `POLL_S` is 1.0 s (`shipper.py:34`), so "Alerts, immediate" (TS §8.4 L1290) is still met within about a second.
   - If wanted later, wire the wake through the runtime in TASK-155..157, where the callers have `runtime`.

## Findings
None blocking or should-fix. Nits 1, 2 and 5 are above.

6. nit, `pipeline.py:85` and `validate.py:110`: the two sort keys differ for a null `line` (0 here, −1 there). Both put file-level findings first, so behaviour is the same.
