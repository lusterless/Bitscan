# TASK-154 IMPL: import pipeline `import_one`

Implementer: impl-manager-154. REQ-150, REQ-155, REQ-157, REQ-160, REQ-162, REQ-176. Risk high (importer; needs two approvals). Spec: TS §4.1 L516–L532, §8.4 L1290–L1291, §5.2 (`bit_import` INSERT only; `policy` never deleted); SR §3.6, SR L250. Design: D4 in `work/tasks.md` and `work/plans/TASK-154.md`. Open questions #23, #98 (j), #99, #100 (a) (widened 2026-10-27), #101, #110.

## Files

| File | Change | Physical / non-blank / code lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/pipeline.py` (new) | `Prepared`, `ImportOutcome`, `prepare`, the transaction-1 body `_store`, `store_in_savepoint`, `import_one`; re-exports the shared types | 249 / 224 / 199 |
| `manager/bitscan_manager/services/importer/pipeline_record.py` (new) | `Mode`, `Actor`, `FileInput`, `Pending`; `audit_success` (plan §7), `audit_refused` (plan §6), `record` (plan §8) | 167 / 147 / 135 |

"Code lines" leaves out docstrings and comments. The split follows plan §11, and main approved it on 2026-10-27. `record` lives in `pipeline_record.py` and `store_in_savepoint` stays in `pipeline.py`, because `store_in_savepoint` needs `_store` and splitting the other way would make the two modules import each other. Import everything from `services.importer.pipeline`. No other file changed, and `services/importer/__init__.py` is unchanged.

## Interface (as built)

```python
class Mode(StrEnum): AUTO, MANUAL, REBUILD
Actor(audit: str, user_id: int | None)
FileInput(data: bytes | None, sha256: str, file_name: str, target: Target)
Prepared(findings, rules: RuleKeys | None, candidate: Candidate | None)
Pending(outcome, policy_id, policy_name, policy_version, plugins_added, plugins_updated, plugins_retired, findings, store)
ImportOutcome(Pending) + import_id: int | None

prepare(data) -> Prepared                                                    # pure
import_one(session, clock, bits_dir, file, *, mode, actor, file_exists,
           prepared=None, before_commit=None, after_commit=None) -> ImportOutcome
store_in_savepoint(session, tx, clock, file, prepared, *, actor, file_exists) -> Pending
record(tx, clock, file, mode, actor, pending) -> int
```

### Changes from the plan's interface (main accepted them on 2026-10-27; see the last row of `work/decisions.md`)

1. `import_one` takes `bits_dir: Path` instead of `folders`. `config/startup.py` has no `Folders` type, only `ServeConfig.bits_dir` and `uploads_dir`. `delete.delete_policy` takes the same argument. It is needed for `remove_after_commit`.
2. New keyword `prepared: Prepared | None = None`. Without it `import_one` would have to run `prepare` itself, which means parsing under the caller's lock and breaks plan §4 ("prepare … runs before the lock"). If it is omitted, `prepare(file.data)` runs inside.
3. `store_in_savepoint` takes `session` as well as `tx`, because `savepoint()` exists on `CatalogSession` and not on `Tx`. It needs the TASK-147 hook-dropping savepoint.
4. `record` takes `clock`, because `imports.insert_import` needs `now`.
5. `after_commit` receives the `Pending`, not an `ImportOutcome`. The rename runs before transaction 2, so there is no `import_id` yet. `ImportOutcome` is a subclass of `Pending`, so every other field is the same.

### Choices for the reviewer

- **(5) Success row even if the rename fails** (plan §5, "remove …; after_commit; with tx2"). `import_one` lines 226–241: after transaction 1 commits, `remove_after_commit` and `after_commit` run inside `try`, and transaction 2 runs in its `finally`. If the upload rename raises an `OSError`, the `success` row is still written, and then the error propagates to the route, which answers 500. Reason: the catalog has already committed. TS §4.1 L520 and SR §3.6 say the record follows every catalog transaction, and REQ-160 (4) says the committed catalog stands. Without the `finally`, a committed import would have no `bit_import` row. TASK-155's start-up step finishes an interrupted rename.
- **`policy.import_refused` detail** (plan §6; #99 (e), #101). `pipeline_record.py:120`. Target `policy:<id>`. Detail `{policy_id, mode, file_sha256}`, with no alert. #101 names the action but defines no detail. I left out the client file name so that no client text reaches the entry, which also needs no `_storable` cleaning.
- **No `sink_gate.wake`.** The plan's interface has no SinkGate, and `delete.py` (TASK-152) does not wake the sink either. The shipper picks the entries up on its normal cycle. If a caller wants an immediate wake, it can register one itself on the transactions it opens. `import_one` opens its own, so that would mean a new parameter, which I have not added.

## How the acceptance items are met

| Acceptance (task row) | Where |
| --- | --- |
| Read-once buffer, hash, parse, structure, validate, BIT102 | `prepare` (`pipeline.py:88`): BIT001 for `None`, then `parse_bit`, `structure.check` (BIT002 stops, BIT016 is carried on), `validate`, and `bit102.check_execute` on the trimmed `Execute` of every plugin that passed BIT008, at the `Execute` start-tag line with path `Plugin[n]/Execute`. A stable sort by line keeps rule order within a line. The candidate is None if any finding rejects. The caller hashes the one buffer into `FileInput.sha256` and `Target.file_sha256` (plan §3). `prepare` never reads the file again. |
| Store with the DB rules | `_store` (`pipeline.py:117`): `decide` (row locks; `PolicyManagedOnServer` propagates), then `check_ownership` (BIT015). BIT007 comes from `decision.findings`. All findings are merged and sorted again. If any finding rejects or there is no candidate, the file is rejected. Otherwise the displaced row is read (already locked by `decide`) and `store.apply` runs. |
| `auto` skip | `_store`: only when `mode is AUTO` and `store_decide.is_unchanged(...)`. The `skipped` Pending has no findings, counts 0, the current `version`, and writes no audit entry (#23). `manual` and `rebuild` never skip. `store_in_savepoint` always uses REBUILD. |
| Transaction 1 with the success alert | `audit_success` (`pipeline_record.py:62`), in transaction 1 or the savepoint, in this order: `policy.import` (the `policy_imported` alert, `StoreResult.changed_executes` passed unchanged, so the reasons are new, changed or reactivated); `policy.move` if `moved_from`; `policy.delete` (the `policy_deleted` alert, "file now holds another policy") for a displaced policy; `policy.status_change` (the `policy_reenabled` alert, `by: "file"`) if `reenabled`. `before_commit(policy_id)` runs after them, last before COMMIT. A reject or a skip raises the private `_Abort`, so transaction 1 rolls back and none of its entries or counters survive. |
| Transaction 2: record, rejected alert, metric | `record` (`pipeline_record.py:137`): `insert_import` with every finding, warnings included (#110), and `imported_by = actor.user_id`. For a rejection it also writes the `policy_import_rejected` alert (target `policy:<id>` when a policy matched, else the file name) and `count_failure`, which runs on commit. |
| Internal error is not a rejection (#98 (j)) | A database error or an `OSError` from `before_commit` propagates out of transaction 1 and no row is written. If transaction 2 fails after a committed success, the failure is logged by exception type only, `import_id=None` is returned, and the catalog stays committed. If transaction 2 fails for a `rejected` or `skipped` file (nothing committed), the error propagates. |
| Caller holds the lock | `import_one` never calls `catalog_lock`. The rename (`after_commit`) and the removal of `remove_after_commit` run inside the caller's lock, before the record. |
| `PolicyManagedOnServer` (#99 (e)) | `import_one`: transaction 1 rolls back, one `policy.import_refused` entry is written in its own transaction, and the exception is re-raised. No row and no alert. `store_in_savepoint` lets it propagate (the savepoint rolls back), and TASK-156 and TASK-157 handle it. |
| No log of content | The only log lines are `bit import <outcome>: import_id=… added=… updated=… retired=…` and `bit_import record failed: <type>`. No file name, finding or `Execute` text is logged. |

## Gate results (repo root)

- `ruff check manager && ruff format --check manager`: pass (281 files).
- `mypy --strict --config-file manager/pyproject.toml manager`: pass (281 files).
- Regression set, run from `manager/` with CI=true and the RYUK variable: `test_import_store_pg.py test_import_alerts.py test_import_alerts_pg.py test_imports_repo_pg.py test_catalog_lock_pg.py test_policy_delete_pg.py test_bit_validate.py`: **845 passed**.
- Throwaway smoke checks, run from the scratchpad and not kept as tests:
  - `prepare` over every non-placeholder `bits/tests/manifest.json` fixture gives exactly the manifest codes, with BIT007 and BIT015 excluded because they need the database. 0 mismatches.
  - On PostgreSQL, the SR §1.1 example: `manual` gives `success` (v1, 1 added, 1 changed Execute); `auto` gives `skipped` with no new entry; `rebuild` gives `success` with an empty `changed_executes`.
  - `bit003-on.bit` in `auto` mode gives `rejected` with `[BIT003]` and a `policy.import_rejected` entry targeted at the file name.
  - An upload of the server-folder name raises `PolicyManagedOnServer`, writes one `policy.import_refused` entry and no row.
  - `store_in_savepoint` with files a, b (rejected) and c: a and c are stored, b leaves no entry, and `record` writes three rows plus one rejected alert.

## Cases the tester should cover (beyond plan §10)

- Pass `prepared=` to `import_one`, and show that `prepare` alone does no database work (plan §10 row 10).
- An `after_commit` that raises after a successful commit: there is still one `success` row, the exception propagates, and the catalog is committed.
- A failing transaction 2 (fault-injected `imports.insert_import`) for a **rejected** file: the error propagates, with no row and no alert. For a **success**: `import_id is None` and the catalog is committed (REQ-160 (4)).
- `before_commit` gets the new `policy_id` on an upload insert, and its exception rolls back the policy, the plugins, every audit entry and `bitscan_alerts_total` (REQ-162 (4)).
- A rejection whose BIT007 matched a policy has the target `policy:<id>`. A rejection with no valid `PolicyName` has the target `file_name`, cut to 255 characters (builder checklist 16).
- The order of findings when BIT007 or BIT015 sit with file-local findings: by line, stable (REQ-155 (5)).
- A `data=None` folder file gives one `rejected` row with the single BIT001 "larger than 5 MiB" finding (#99 (b)).
- `mode` passed as the plain string `"auto"` behaves like `Mode.AUTO` (`Mode(mode)` converts it).
- A re-enable by file (`file_status` disabled → enabled with `status_overridden` false) gives `policy_reenabled` with `status_overridden: false` and `by: "file"`. With `status_overridden` true there is no status-change entry.

## Revision 1 (2026-10-28, lead's "W6 rulings" Q1, `work/decisions.md`)

**What changed.** In `rebuild` mode, `policy.import` (the `policy_imported` alert) is now written only for a changed policy, as the approved #23 says ("a rebuild alerts once plus per changed policy"). The pipeline used to alert for every file it stored.
- `pipeline.py` `_store` (about line 144): `quiet = mode is Mode.REBUILD and store_decide.is_unchanged(decision, file.target)`. It is computed **before** `store.apply`, from the rows that `decide` has just locked, and then passed on as `audit_success(..., announce=not quiet)`.
- `pipeline_record.py` `audit_success`: a new keyword `announce: bool = True`. When it is False, the `policy.import` event is left out. The `policy.move`, displaced `policy.delete` and `policy.status_change` entries are written as before. A file that `is_unchanged` accepts is always the `update` case with no displaced policy, so a move or delete cannot happen for it; a status change could only come from a corrupted row.
- `auto` and `manual` are unchanged: `auto` still skips unchanged files, and `manual` still alerts on every import. `store.py` and `rebuild.py` are untouched. The change is +12/−7 lines, and pipeline.py is now about 202 code lines.

**Edge for the lead / reviewer.** The ruling keys the decision on `is_unchanged`: same live policy, same file and same hash. In a corrupted catalog, one where a plugin of a live, unchanged policy was retired or its row edited by hand, the rebuild reactivates or rewrites that plugin, and `StoreResult.changed_executes` is not empty. Under the ruling as written, that rebuild raises no `policy_imported` alert, even though a command goes live on hosts again. If the lead prefers it, the condition can become `is_unchanged(...) and not result.changed_executes` (one line, decided after `apply`). I implemented the ruling literally and have not made that change.

**Gates.** `ruff check` and `ruff format --check` pass (296 files), and so does `mypy --strict` (296 files).

**Suites** (pipeline, fuzz, samples, store, folders, uploads, uploads_pg): 557 passed, 3 failed.
- `test_import_pipeline_pg.py::test_sr_example_imports_with_one_success_row_and_one_alert_then_auto_skips` fails as **expected**. Its loop asserts one `policy.import` entry for an identical-bytes re-import in `rebuild` mode, which is the old behaviour. The tester needs to change the `rebuild` step to expect no entry; the `manual` step stays as it is.
- `test_folders_pg.py::test_a_leftover_that_cannot_be_removed_is_retried_and_reported_once_gone[no-op, unlink-raises]` is **not caused by this revision**. It fails in the same way with my two files restored to HEAD (`git stash` of only those files). The working tree holds someone else's uncommitted `folders.py` change (TASK-156 r5 in progress, I assume), and that is the likely cause.

**Throwaway smoke check** on PostgreSQL, the SR §1.1 example as a server file, counting `policy.import` entries per call:

| Call | Outcome | New `policy.import` entries |
| --- | --- | --- |
| manual, new | success | 1 |
| rebuild, same bytes | success | 0 |
| manual, same bytes | success | 1 |
| rebuild, changed bytes | success | 1 |
| rebuild, same changed bytes | success | 0 |

**Cases for the tester (revision 1):**
- A rebuild of an unchanged file (same live policy, same `source_file`, same hash) gives a `success` row with counts 0/0/0 and its version unchanged. There is no `policy.import` entry, and `bitscan_alerts_total{kind="policy_imported"}` does not change. Check it through both `import_one(mode=rebuild)` and `store_in_savepoint`.
- A rebuild of a changed file (new hash) gives exactly one `policy_imported` alert, and so does a rebuild of a new file (insert).
- A rebuild of a revived file (a deleted policy coming back) gives one alert with the plugins' `reason: "reactivated"`. Its case is `revive`, not `update`, so it is never quiet.
- Rebuild with a rename in place, a move (server file replaces an uploaded copy) or a displaced policy: each still writes its `policy.import`, plus its `policy.move` or `policy.delete` entry, because none of them is the `update` case.
- `auto`: an unchanged file is still `skipped` with no entry; a changed file gets one alert.
- `manual`: identical bytes still give `success` and one `policy.import` with an empty `changed_executes`.
- A plant that turns `announce` back on in rebuild mode, and one that silences `manual`, must each turn a row red.
