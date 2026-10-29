# TASK-154 IMPL: import pipeline `import_one` (design note D4)

Implementer: impl-manager-m7. REQ-150, REQ-155, REQ-157, REQ-160, REQ-162, REQ-176. Risk high (importer; two approvals). Plan: `work/plans/TASK-154.md`. Spec: TS §4.1 L516–L532, §8.1, §8.4 L1288–L1291; SR §3.5, §3.6 (L244–L246), §4 (L250). Answers and rulings applied: #23, #98 (d) and (j), #99 (b) and (e), #100 (a) as widened, #101, #110, the BIT016 ruling (only BIT001 and BIT002 stop the content rules), the catalog-session autocommit fix (TASK-147 r2: audit appends work inside `session.transaction()`), the TASK-153 255-character target cut (`alerts.rejected` does the cut; every other target here is `policy:<id>`), and main's "TASK-154 and TASK-165 rulings" (decisions 2026-10-28).

## Files

| File | Lines (total / non-blank / code) | Content |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/pipeline.py` (new) | 158 / 148 / 130 (34 imports) | `prepare`; `import_one` (with the `policy.import_refused` entry and the record-after-commit `finally`); `__all__` re-exports the public names |
| `manager/bitscan_manager/services/importer/pipeline_record.py` (new, the plan §11 split) | 267 / 236 / 213 (19 imports) | Types `Actor`, `FileInput`, `Prepared`, `ImportOutcome`; `Abort`, `ordered`, `store_file` (the transaction 1 body), `_audit` (§7), `success`, `store_in_savepoint` and `record` (§8) |

No other file is changed. `services/importer/__init__.py` is not touched, because the plan doesn't ask for an export there. Callers import every public name from `services.importer.pipeline`: `Actor`, `FileInput`, `ImportOutcome`, `Mode`, `Prepared`, `import_one`, `prepare`, `record`, `store_in_savepoint`.

**Split (main's ruling, 2026-10-28):** one task id, two files. Imports go one way only: `pipeline` imports from `pipeline_record`, and `pipeline_record` imports nothing from `pipeline`.
- The ruling names `_audit`, `store_in_savepoint` and `record`. Keeping the imports one-way meant moving two more things with them:
  - the transaction 1 body (`_store`, now `store_file`), which both `import_one` and `store_in_savepoint` run and which calls `_audit`;
  - the four types, `ordered` and `Abort`, which both files use.
- `_store`, `_success`, `_Abort` and `_ordered` became `store_file`, `success`, `Abort` and `ordered`, because `pipeline` imports them across the module boundary. They are still not in `pipeline.__all__`.
- Nothing else changed: it is a cut and paste, and the scratch flow output is identical before and after.

**Size:** before the split it was one file of 322 code lines. Now `pipeline.py` has 130 code lines and `pipeline_record.py` 213, about 70 of them ruff-format expansion of the builder and `ImportRecord` keyword calls.

## Interface (what TASK-155 to TASK-158 call, all from `pipeline`)

```python
Mode = repositories.imports.Mode          # Literal["auto", "manual", "rebuild"], re-exported
@dataclass(frozen=True) class Actor:      audit: str; user_id: int | None
@dataclass(frozen=True) class FileInput:  data: bytes | None; sha256: str; file_name: str; target: Target
@dataclass(frozen=True) class Prepared:   findings; rules: RuleKeys | None; candidate: Candidate | None
@dataclass(frozen=True) class ImportOutcome:
    import_id: int | None; outcome: Outcome
    policy_id / policy_name / policy_version: ... | None = None
    plugins_added / plugins_updated / plugins_retired: int = 0
    findings: tuple[Finding, ...] = (); store: StoreResult | None = None
    matched_policy_id: int | None = None   # rejected only: the alert target (#101)

def prepare(data: bytes | None) -> Prepared
def import_one(session, clock, bits_dir: Path, file, *, mode, actor, file_exists,
               prepared: Prepared | None = None,
               before_commit: Callable[[int], None] | None = None,
               after_commit: Callable[[ImportOutcome], None] | None = None) -> ImportOutcome
def store_in_savepoint(session, tx, clock, file, prepared, *, actor, file_exists) -> ImportOutcome
def record(tx, file, mode, actor, pending: ImportOutcome, *, now: datetime) -> int
```

Differences from plan §3. Main accepted all of them as built (decisions 2026-10-28):
1. **`bits_dir: Path` instead of `folders: Folders`.** No `Folders` type exists in `config/startup.py`. It is used only for `delete.remove_after_commit(bits_dir, StoreResult.remove_after_commit)`, the same helper and argument as TASK-152.
2. **`Mode` is the existing Literal** from `repositories/imports.py`, not a `StrEnum`. `alerts.imported`, `alerts.rejected`, `alerts.count_failure` and `ImportRecord` all take that Literal.
3. **`prepared=` keyword on `import_one`.** `prepare` is meant to run before the lock (plan §4), so a caller that holds the lock passes `prepared`. Without it, `import_one` calls `prepare` itself.
4. **`store_in_savepoint` takes `session` as well as `tx`,** because `savepoint()` belongs to `CatalogSession`. **`record` takes `now`,** because `imports.insert_import` needs it.
5. **The pending outcome is an `ImportOutcome` with `import_id=None`,** not a separate `Pending` class. `matched_policy_id` carries the rejected alert's target, while `policy_id` stays None for a rejection (#98 (d)).
6. **`policy.import_refused` is built here** as an `AuditEvent` (no TASK-153 builder exists). It has target `policy:<id>`, no alert kind, and detail `{policy_id, mode, file_sha256}`, with no client text.
7. **`after_commit` raising:** the record transaction runs in a `finally`, so a committed import always gets its `success` row attempted, and then the exception propagates. TASK-155 owns what happens next: start-up finishes the rename (TS §4.1 L528).

## How each plan point is met

- **`prepare` (plan §4, `pipeline.py`), pure, no database argument:**
  - `None` → BIT001 "The file is larger than 5 MiB.", no rules, no candidate (#99 (b)).
  - `parse_bit` finding → returned alone. `structure.check` with BIT002 → only BIT002, no rules.
  - Otherwise BIT016 (if any) and the `validate` findings are joined, and `bit102.check_execute` runs on every plugin's **trimmed** `Execute` whose length passed BIT008 (1–16,384). It gets `line` = the `Execute` start-tag line and `element` = `plugin_path(n, "Execute")`.
  - All findings are sorted by `(line or 0, Code table order)`, stable (REQ-155 (5)).
  - The candidate is None if any finding rejects, which covers BIT016 and BIT102 even though `validate` built one.
- **Transaction 1 (`pipeline_record.store_file`), in order:**
  1. No rules → `Abort` (rejected).
  2. `store_decide.decide`. `PolicyManagedOnServer` propagates.
  3. `auto` and `is_unchanged` → `Abort` (skipped, `policy_version` NULL since revision 1, no findings).
  4. `check_ownership`. The prepared, BIT007 and BIT015 findings are merged and re-sorted.
  5. No candidate, or any Reject → `Abort` (rejected, `matched_policy_id` = `decision.policy_id`).
  6. The displaced row is read (name and file, before its delete).
  7. `store.apply`, then the §7 entries in `_audit`: `policy.import`/`policy_imported` with `changed_executes` passed through unchanged (reactivated ones included); `policy.move` when `moved_from` is set (both move cases); `policy.delete`/`policy_deleted` with reason "file now holds another policy" for the displaced policy; `policy.status_change`/`policy_reenabled` with `by: "file"` when `reenabled`.
  8. Then, in `import_one`, `before_commit(policy_id)`, the last step before COMMIT.
- **`Abort`** is raised inside the `with session.transaction()`, so tx1 rolls back and its hooks never run. The record transaction then writes the row. For a rejection, `record` also writes `alerts.rejected` and calls `alerts.count_failure` (+1 on commit). A skip writes no audit entry (#23).
- **Refusal (#99 (e)):** tx1 rolls back. One `policy.import_refused` entry is written in its own transaction, with no row and no alert. Then the exception is re-raised for the 409.
- **Internal errors (#98 (j)):** a database error or an `OSError` from `before_commit` in tx1 propagates, so there is no row and no alert. A record-transaction error on the reject or skip path also propagates, since nothing has committed. After a committed success, a record failure is logged as `bit_import record failed: <type>` and `import_id` is None; the catalog stands.
- **After the commit:** `remove_after_commit` (logs and continues on `OSError`), then `after_commit(outcome)`, with `import_id` still None at that point, then the record.
- **Rebuild (§8):** `store_in_savepoint` runs `store_file` in mode `rebuild` (never skips) inside `session.savepoint()`. A rejection rolls back to the savepoint, which drops its entries and hooks (TASK-147), and the pending outcome is returned. `record` writes the row, and for a rejection the alert and the count. `PolicyManagedOnServer` propagates out of the rolled-back savepoint, and TASK-157 handles it.
- **Logging:** the only log line is the record-failure line in `pipeline.py`, which holds the exception type. No file content, findings, file names or `Execute` text are logged; `pipeline_record` logs nothing.

## Static gates (Windows, `manager/.venv`, after the split)

- `ruff check manager`: All checks passed. `ruff format --check manager`: 281 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 281 source files.

## Scratch checks (outside the tree, `%TEMP%\m7-154-scratch`; not tests; re-run after the split)

- `prepare` over all 174 `bits/tests/manifest.json` fixtures without placeholders gave 0 mismatches:
  - the code set equals the manifest's minus BIT007/BIT015 (the database codes);
  - `candidate is None` exactly when a Reject is present;
  - lines come out sorted.
- `prepare` on other inputs:
  - both `bits/samples/*.bit` give no findings and a candidate;
  - SR §1.1 with `formatVersion` `2.0` or `1.1` plus a bad `PolicyStatus` gives `[(2, BIT016), (5, BIT003)]` with rules built;
  - an extra element plus a bad status gives only BIT002 and no rules.
- `import_one` with a fake session and stubbed store and repositories: the BEGIN/COMMIT/ROLLBACK order, hook timing and entries came out as the plan says for every flow, and are identical before and after the split:
  - `manual` success;
  - `auto` skip (only a `skipped` row, no audit);
  - `auto` changed;
  - move with a displaced policy and a re-enable (four entries, `before_commit` after them);
  - a file-local reject targeting the matched policy;
  - an oversize file targeting the file name;
  - a BIT015 reject;
  - a `before_commit` that raises (rollback, no row);
  - a record failure after commit (`import_id` None);
  - an upload refused (no row, a `policy.import_refused` entry, re-raised);
  - an `after_commit` that raises (row still written, then raised);
  - a 3-file rebuild with the second rejected (its savepoint entries and hooks gone, three rows, one rejected alert, `FAILCOUNT rebuild`).

## For the tester (tester-m7, TP-M7-14, `test_import_pipeline_pg.py`, `test_import_fuzz_pg.py`; PostgreSQL in WSL)

- Import everything from `bitscan_manager.services.importer.pipeline`.
- Build a `FileInput(data, sha256(data), file_name, Target(...))` and call `prepare(data)` before taking `catalog_lock(session)`. Then call `import_one(session, clock, bits_dir, file, mode=..., actor=Actor("system", None), file_exists=..., prepared=...)` inside the lock.
- For plan §10 row 7, call `store_in_savepoint(session, tx, clock, file, prepare(data), actor=..., file_exists=...)` for each file inside one `session.transaction()`. Then, in a second transaction, call `record(tx2, file, "rebuild", actor, pending, now=...)` for each file.
- **Monkeypatch targets moved with the split.** The store, decide, catalog, imports and alerts calls are now looked up in `pipeline_record`. So:
  - the plan §10 row 6 fault in the record transaction is injected through `pipeline_record.imports.insert_import`, or by patching `repositories.imports.insert_import` itself (any `Exception` after a committed tx1 is caught and logged);
  - `remove_after_commit` and the `policy.import_refused` emit are still looked up in `pipeline`.
- Plants (mutation rows for TASK-154), with the file each one is made in after the split:
  - **CHK-M7-333** (BIT102 skipped in `rebuild` mode or for uploads), in `pipeline.py` or `pipeline_record.py`: make `prepare` skip `check_execute` (`pipeline.py`), or make `store_in_savepoint` drop the BIT102 findings (`pipeline_record.py`) → rows 7 and 2 red with a `bits/tests/bit102/` fixture.
  - **CHK-M7-339** (`bit_import` written in tx1), in `pipeline.py`: move the `record(...)` call into the tx1 `with` in `import_one`, before the `Abort` → a reject loses its row (row 2 red).
  - **CHK-M7-340** (a late exception swallowed and tx1 committed), in `pipeline.py`: wrap the `before_commit` call in `try/except OSError: pass`, or catch `Abort` inside the `with` → row 6 red, and the fuzz row 9 should catch a partial import.
  - **CHK-M7-349** (no `policy_imported`), in `pipeline_record.py`: delete the first `put(...)` in `_audit` → row 1 red.
  - **CHK-M7-350** (no rejected alert or count), in `pipeline_record.py`: delete the `alerts.emit` or the `count_failure` line in `record` → row 2 red.
  - **CHK-M7-369** (`auto` not skipping, or `manual` skipping), in `pipeline_record.py`: in `store_file`, drop `mode == "auto" and`, or change it to `mode != "auto"` → row 3 red.
- Plan §10 row 4 now reads: BIT016 with BIT003 in one `rejected` row, and the database rules run; BIT002 with BIT003 gives only BIT002.

## Open

- TEST waits on TASK-144 and TASK-146 being APPROVED. TASK-146 r2 (impl-manager-m7b) changes only the BIT102 rules (`bit102.py`, `bit102_wrappers.py`); `check_execute`'s signature is unchanged.
- Observation for the reviewer, from the order plan §5 sets: the `auto` skip is decided before the file-local findings are looked at. So a file whose hash equals its last successful import is `skipped` in `auto` mode even if a later rule change (for example TASK-146 r2) would now reject it. Manual imports and rebuilds re-validate it (TS §4.1 L532).

## Revision 1 (main's ruling "TASK-154 test questions", decisions 2026-10-28)

`bit_import.policy_version` is NULL unless `outcome` is `success`: SR §3.5 says "after the import, if it succeeded". This supersedes plan §5's "policy_version = the current one" for a skipped row.

The change is in `manager/bitscan_manager/services/importer/pipeline_record.py` only, 2 places:
- `store_file`: the `auto` skip's `ImportOutcome` no longer carries `old.version`. It keeps `policy_id` and `policy_name`, so `import_one`'s returned skipped outcome has `policy_version` None, matching its row.
- `record`: the row's `policy_version` is `pending.policy_version if pending.outcome == "success" else None`. So no pending outcome a caller builds, a rebuild's included, can write a version on a skipped or rejected row.

**Rejected rows are confirmed NULL,** as before. The three ways a rejection is built never set a version:
- no rules (BIT001 or BIT002);
- a Reject finding or no candidate;
- a rebuild file rolled back to its savepoint (the same `Abort`).

`record` now also enforces it.

**Unchanged:**
- the #101 rejected target: `policy:<id>` when a policy was matched, else the file name, cut to 255 by `alerts.rejected`;
- the `auto` skip is still decided before the findings (TS §4.2);
- every other behaviour, and `pipeline.py`.

**Gates:** `ruff check manager` passes, `ruff format --check manager` passes (284 files), and the CI mypy command gives Success with no issues in 284 source files.

**Scratch flow re-run:** the `auto` unchanged case now gives `ROW skipped v=None` and an outcome whose `policy_version` is None. The success rows keep `v=4` and every rejected row is `v=None`. Transaction order and the audit entries are unchanged.

**For the tester:**
- Re-pin the skipped-row assertion (CHK-M7-192 / plan §10 row 3) to `policy_version IS NULL`.
- A plant for it: write `pending.policy_version` unconditionally in `record` and give the skip `old.version` again. The skipped-row assertion goes red.

## Revision 2 (decisions 2026-10-28, "TASK-157 rulings" (2))

A rebuild writes `policy.import` / `policy_imported` only for a policy whose catalog rows it changed (#23 agreed, REQ-166 (6)). Manual and `auto` imports are unchanged: every successful one is audited and alerts (TS L530). Only `pipeline_record.py` changed, and it is now 305 / 270 / 236 lines (total / non-blank / code).

- **`store_file`, in `rebuild` mode only:**
  - after `decide` (rows locked) and before `store.apply`, it reads `before = _fingerprint(tx, decision.policy_id)`;
  - after `apply` it writes the §7 entries (`_audit`) only if `_changed(...)`.
  - In `manual` and `auto` mode, `_audit` runs as before and neither fingerprint is read.
- **`_fingerprint(tx, policy_id)`:** the policy's catalog state, read through the existing `catalog_admin.detail` (TASK-150), one statement and one snapshot, under the catalog lock. No new SQL.
  - It holds the policy row: name, description, `policy_status`, `file_status`, `status_overridden`, family, format version, `version`, `source_file`, `updated_at`, `deleted_at`. `imported_at` is excluded, because every import sets it.
  - It holds the `policy_plugin` rows: membership and `sort_order`.
  - It holds each listed plugin: name, `control_ref`, description, `execute`, `execute_sha256`, operator, expected result, timeout, `state`, `updated_at`.
  - It is None when there is no such policy (an insert).
- **`_changed(...)`** is true when any of these hold, as the ruling lists them:
  - the decision is anything but `update` (new, revived, renamed, either move);
  - a policy was displaced (`deleted_policy_ids`);
  - plugins were added, updated or retired;
  - there are `changed_executes`;
  - or `before != _fingerprint(tx, result.policy_id)`, which also covers a version bump.
- **The REQ-166 (1) corruptions** are each caught:
  - a changed `execute` → `plugins_updated` and `changed_executes`;
  - a deleted `policy_plugin` row → the plugin list in the fingerprint;
  - a plugin set `retired` → `plugins_updated` and `reactivated`;
  - `policy_status` flipped without an override → the fingerprint's policy row.
  - Corruptions the fingerprint doesn't read (`owner_policy_id`, a plugin's `family_id`, `source_sha256`) show up as `plugins_updated` (#21 counts owner and family) or as a version bump.
- **When a rebuild file is unchanged,** nothing is written for it in the savepoint: no import, move, delete or re-enable entry. All four need a change. Its outcome is still `success`, it still gets its `bit_import` row through `record`, and it is listed in `task.result` and the `bits.rebuild` entry (TASK-157).
- **Gates:** `ruff check manager` passes, `ruff format --check manager` passes (293 files), and the CI mypy command gives Success with no issues in 293 source files. The 293 include my in-progress TASK-158 files, which are clean.
- **Scratch** (`%TEMP%\m7-154-scratch\check_r2.py`, stubbed `detail`, `store_in_savepoint` in `rebuild` mode):
  - only `imported_at` differs → no entry;
  - `policy_status` restored → entry;
  - a plugin retired elsewhere → entry;
  - a changed Execute → entry;
  - a rename → entry;
  - a `manual` import with nothing changed still writes its entry.
- **For the tester:**
  - Rebuild rows:
    - an unchanged rebuild file gives no `policy.import` entry and no `policy_imported` count;
    - each REQ-166 (1) corruption gives exactly one `policy_imported` for its policy;
    - a rebuild that changes nothing gives none.
  - Plant for this revision:
    - drop `or before != _fingerprint(...)` → the `policy_status` corruption row goes red;
    - make `_changed` always true → the unchanged row goes red.
  - The REQ-162 manual and auto rows apply unchanged.
