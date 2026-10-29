# TASK-154 plan: import pipeline, catalog lock and transactions

Planner: planner-m7, 2026-10-27, from design note D4 (`work/tasks.md`, M7). Risk: high (importer; two approvals). File: `manager/bitscan_manager/services/importer/pipeline.py` only. Depends on:
- TASK-141 parse, TASK-143 structure, TASK-144 validate (with `Candidate` and `RuleKeys`), TASK-146 BIT102;
- TASK-147 session and lock, TASK-149 import records, TASK-151 store, TASK-153 alerts.

Consumers: TASK-155 uploads, TASK-156 folders, TASK-157 rebuild, TASK-158 start-up.

Answers applied: #23, #98 (d), (j), #99 (b), (e), #100, #101, #110.

## 1. Spec

- TS §4.1 L516–L520: read once, parse, validate, store in one transaction, then record in its own transaction.
- TS §4.1 L526: the lock is held "before its transaction" until the rename or deletion is done.
- TS §4.1 L530: every import is audit-logged and alerts.
- TS §4.1 L532: automatic imports skip unchanged files; manual imports and rebuilds never skip.
- SR §3.6 (SR L244–L246): any error rolls back the whole file, then `bit_import` is inserted in its own transaction.
- TS §8.4 L1290–L1291: the "policy imported" alert carries every changed `Execute`; any rejected import alerts; the "import failures" metric.

## 2. Session and lock (interface from TASK-147)

TASK-147 is in W1. Its implementer gives it this shape, or tells the planner before W2:

```python
class CatalogSession(Protocol):                 # one pinned bitscan_app connection
    def transaction(self) -> AbstractContextManager[Tx]: ...   # same Tx as runtime.Tx; hooks after COMMIT
    def savepoint(self) -> AbstractContextManager[None]: ...   # inside an open transaction (rebuild)

class SessionDatabase(Protocol):                # added to AppDatabase
    def session(self) -> AbstractContextManager[CatalogSession]: ...

@contextmanager
def catalog_lock(session: CatalogSession) -> Iterator[None]: ...
# pg_advisory_lock(hashtext('catalog')) in autocommit, before any transaction;
# pg_advisory_unlock(...) in finally; the lock also ends with the connection
```

`session.transaction()` may be entered several times in a row on one session; it is never nested.

As built in W1 (impl-manager-m7, `work/reports/TASK-147-impl.md`), two additions that this plan relies on:
- `CatalogSession.conn` is a read-only property: the pinned connection, in autocommit outside `transaction()`. Only `catalog_lock()` uses it, to run `pg_advisory_lock` and `pg_advisory_unlock`; the SQL stays in `repositories/catalog_lock.py`. The pipeline, the store and every other caller use only `tx.conn`, inside a transaction.
- `savepoint()` drops the on-commit hooks registered inside it when it rolls back. So a rejected rebuild file's alert counters and sink wake-ups never run, which section 8 depends on: that file's entries vanish with its savepoint and are never counted.

## 3. Interface

```python
class Mode(StrEnum): AUTO = "auto"; MANUAL = "manual"; REBUILD = "rebuild"

@dataclass(frozen=True)
class Actor:
    audit: str                 # "user:<id>", "cli:root" or "system" (#101)
    user_id: int | None        # bit_import.imported_by

@dataclass(frozen=True)
class FileInput:
    data: bytes | None         # the one read buffer; None for an oversize folder file
    sha256: str                # of data, or of the streamed oversize file
    file_name: str             # bit_import.file_name: the relative path, or the #99 (d) client name
    target: Target             # TASK-151

@dataclass(frozen=True)
class Prepared:                # pure; no database
    findings: tuple[Finding, ...]          # file-local findings, warnings included
    rules: RuleKeys | None                 # None when BIT001 or BIT002 failed
    candidate: Candidate | None            # None when any file-local Reject

@dataclass(frozen=True)
class ImportOutcome:
    import_id: int | None                  # None only if the record transaction failed (logged)
    outcome: Literal["success", "skipped", "rejected"]
    policy_id: int | None; policy_name: str | None; policy_version: int | None
    plugins_added: int; plugins_updated: int; plugins_retired: int
    findings: tuple[Finding, ...]          # everything stored in bit_import.errors
    store: StoreResult | None              # success only

def prepare(data: bytes | None) -> Prepared
def import_one(
    session: CatalogSession, clock: Clock, folders: Folders, file: FileInput, *,
    mode: Mode, actor: Actor, file_exists: Callable[[str], bool],
    before_commit: Callable[[int], None] | None = None,   # upload: write the temp file for policy_id
    after_commit: Callable[[ImportOutcome], None] | None = None,  # upload: rename
) -> ImportOutcome
def store_in_savepoint(tx: Tx, clock: Clock, file: FileInput, prepared: Prepared, *,
                       actor: Actor, file_exists: Callable[[str], bool]) -> Pending   # rebuild
def record(tx: Tx, file: FileInput, mode: Mode, actor: Actor, pending: Pending) -> int  # rebuild
```

`Folders` (bits folder and `uploaded/`) is the small value type from `config/startup.py` (`bits_dir`, `uploads_dir`). The caller of `import_one` already holds `catalog_lock(session)`. `import_one` never takes or releases the lock, so an upload's rename stays inside it.

## 4. `prepare(data)`

1. If `data` is None, return BIT001 "The file is larger than 5 MiB." with no rules and no candidate (#99 (b): an oversize folder file is a rejected import).
2. `parse_bit(data)` (TASK-141). On a finding, return it.
3. Turn `pi_lines` and the tree into a `ParsedPolicy` with `structure.check(...)` (TASK-143). Only BIT001 and BIT002 stop the content rules (SR L250).
   - With a BIT002 finding, `parsed` is None: return the findings with no rules and no candidate.
   - BIT016 (`@formatVersion`) is an ordinary Reject rule. `structure.check` returns it together with a `ParsedPolicy`, and the pipeline carries it on to step 4. So BIT016 and the content faults are all reported, the database rules still run, and the candidate is None because a Reject remains. (Corrected 2026-10-27 after impl-manager-m7's TASK-143 report, `work/reports/TASK-143-impl.md`.)
4. `validate.validate(parsed)` (TASK-144) gives the file-local findings, `rules` and `candidate`. They are added to any BIT016 finding from step 3.
5. BIT102 (TASK-146) on every plugin: `bit102.check_execute(execute, line=<Execute start-tag line>, element=plugin_path(n, "Execute")) -> list[Finding]`, with the **trimmed** `Execute` (as stored) and `n` the 1-based plugin position. The findings join. If any BIT102 finding exists, `candidate` becomes None. Run it only for plugins whose `Execute` passed BIT008, so an empty or over-long command is not lexed.
6. Sort the findings by `(line or 0, rule order)` (REQ-155 (5)).

`prepare` is pure and runs **before** the lock, so parsing a 5 MiB file never holds up other catalog work.

## 5. `import_one` data flow

```text
prepared = prepare(file.data)                                  # caller may have done it already
with session.transaction() as tx1:                             # transaction 1
    if prepared.rules is None: -> go to REJECT (no database rule can run)
    decision = store_decide.decide(tx1.conn, prepared.rules, file.target, file_exists)
        # PolicyManagedOnServer propagates; see section 6
    if mode is AUTO and store_decide.is_unchanged(decision, file.target): -> SKIP
    findings = prepared.findings + decision.findings + store_decide.check_ownership(...)
    if any Reject in findings or prepared.candidate is None: -> REJECT
    result = store.apply(tx1.conn, decision, prepared.candidate, file.target, clock.now())
    write the audit entries and alerts (section 7) in tx1
    if before_commit: before_commit(result.policy_id)          # temp file, O_EXCL|O_NOFOLLOW
# COMMIT; on_commit hooks run (alert counters, sink wake)
remove result.remove_after_commit files (log and continue on error; the start-up integrity check reports leftovers)
if after_commit: after_commit(outcome)                         # rename the upload
with session.transaction() as tx2:                             # transaction 2: the record
    import_id = imports.insert_import(..., outcome="success", errors=findings)
return outcome
```

**REJECT** and **SKIP** leave tx1 by raising a private `_Abort` inside the `with`, so tx1 rolls back (it may hold locks or the displaced delete). Then:
- **REJECT:** tx2 inserts a `rejected` row with every finding. It raises the `policy_import_rejected` alert, `target` = `policy:<id>` if a policy was matched, else the `file_name` (#101). An on-commit hook adds 1 to `bitscan_import_failures_total{mode}`.
- **SKIP:** tx2 inserts a `skipped` row (no findings, counts 0, `policy_version` = the current one) and writes **no** audit entry (#23).

**Internal errors (#98 (j)):** a `DatabaseUnavailable`, a psycopg error or an `OSError` from `before_commit` in tx1 rolls back and propagates. No row is written. The upload's temp file is deleted by TASK-155's own `finally`. If tx2 fails after tx1 committed, the catalog stands: log `bit_import record failed: <type>` and return `import_id=None`. The catalog change is not undone.

## 6. Refusals

- `PolicyManagedOnServer` (upload of a server-folder name, #99 (e)): roll back tx1. Write one `policy.import_refused` audit entry (no alert, no `bit_import` row) in its own transaction, then re-raise for the route's 409.
- No other refusal exists here. Role and route checks belong to the routes.

## 7. Audit and alerts written in tx1 on success (#100, #101)

Each uses `raise_alert` or `append_entry` with `PgAuditRepo(tx1.conn)` and `tx1.on_commit`:

1. `policy.import`, the `policy_imported` alert, target `policy:<id>`. The detail is built by TASK-153: `policy_id`, `policy_name`, `version`, `mode`, `file_sha256`, `source_file`, the three counts, `renamed_from`, `revived`, and `changed_executes` with their `flags` and their `reason` (`new`, `changed` or `reactivated`, #100 (a) as widened by the user on 2026-10-27). The pipeline passes `StoreResult.changed_executes` to `alerts.imported(...)` unchanged. The reactivated plugins are already in that list (TASK-151 §3.4 steps 0 and 4), so the pipeline adds no parameter and derives nothing.
2. If `moved_from` is set, or the case is `move_upload`: one `policy.move` entry (no alert), detail `{from, to}`.
3. For each id in `deleted_policy_ids`: one `policy.delete` entry with the `policy_deleted` alert, detail `{reason: "file now holds another policy"}`.
4. If `reenabled`: one `policy.status_change` entry with the `policy_reenabled` alert, detail `{by: "file"}`.

A rebuild (`store_in_savepoint`) writes the same entries inside its savepoint. A rejected file's savepoint is rolled back, so its entries vanish with it. That is why the rejected alert is written in the record step (`record`), never in the savepoint.

## 8. Rebuild support (TASK-157 uses these)

`store_in_savepoint` runs the tx1 body of section 5 inside `with session.savepoint():` within the rebuild's single transaction. It never skips (mode `rebuild`). A rejection rolls back to the savepoint only. It returns a `Pending` (the outcome fields without `import_id`). After the rebuild transaction commits or rolls back, TASK-157 opens one more transaction and calls `record(...)` for each `Pending`. Each call writes the row, plus the rejected alert and the failure counter for a rejected file. So the rows exist even when the rebuild ends `failed` (TS §4.1 L520), and a failed rebuild's success rows say `rejected`. TASK-157 passes the final outcome; this function only writes it.

## 9. Edge cases

- **The reconcile path and the crash window** (user ruling 2026-10-27; `work/tasks.md` TASK-156). Folder files reach `import_one` only through TASK-156's classification:
  - a server-folder file arrives as `Target("server", "<name>.bit", sha)`;
  - a live policy's `uploaded/policy-<n>.bit` arrives as `Target("upload", None, sha)`, and in `auto` mode it is `skipped` when unchanged (TASK-151 r3);
  - a leftover of an interrupted delete (its policy has `deleted_at` set) **never reaches the pipeline**: TASK-156 removes it and reports it, with no `bit_import` row.
  So `import_one` itself needs no special case. It never builds a target, and it must never be given a server target with a `/` in its path (`Target` refuses one).
- The `auto` skip compares with the policy at the same `source_file` (the last success for that file). A file that was rejected earlier is tried again on every event and start-up, as TS §4.1 L532 says.
- A manual re-import of identical bytes is `success` with counts 0/0/0, and still writes `policy.import` with an empty `changed_executes` ("every import alerts").
- `before_commit` runs after every audit entry, so its file write is the last step before COMMIT. A failure there rolls back everything in tx1.
- The pipeline never logs file content, findings' quoted values or `Execute` text. Its log lines carry only `source_file` or `import_id`, the outcome and the counts.

## 10. Tests (TP-M7-14; tester files `manager/tests/test_import_pipeline_pg.py`, `manager/tests/test_import_fuzz_pg.py`; PostgreSQL in WSL)

1. The SR §1.1 example as a server file, mode `manual`: one `success` row (all columns), one `policy_imported` alert with one changed `Execute`, `bitscan_alerts_total{kind="policy_imported"}` + 1 after commit.
2. Each `bits/tests/` code fixture: a `rejected` row whose `errors` equals the expected findings, one `policy_import_rejected` alert, `bitscan_import_failures_total{mode}` + 1, catalog checksums unchanged.
3. The same file again in `auto` mode: a `skipped` row and no new audit entry. In `manual` and `rebuild` modes: `success`.
4. BIT015 and BIT007 reported together with a file-local BIT003 in one `rejected` row (structure passed, so the database rules ran). A file with `formatVersion="2.0"` (and, likewise, `"1.1"`) and a bad `PolicyStatus` gives one `rejected` row holding both BIT016 and BIT003 (the lead's ruling, 2026-10-27, SR L250); a file with a BIT002 fault and a BIT003 fault holds only BIT002.
5. `PolicyManagedOnServer` for an upload: no row, one `policy.import_refused` entry, the exception re-raised.
6. A `before_commit` that raises: nothing committed, no row, no alert. A tx2 failure (a fault-injecting import repository): the catalog committed and `import_id` None.
7. `store_in_savepoint` with three files, the second rejected: after commit, the other two are stored, the second's savepoint entries are absent, and `record` writes three rows and one rejected alert.
8. A displaced policy (#106) gives its `policy_deleted` alert; a move gives a `policy.move` entry; a file re-enabling a policy gives `policy_reenabled`.
9. Fuzz, no partial import (REQ-176 (2)): 500 Hypothesis-generated files (mutations of valid files). After each, the catalog checksums equal either the state before or a fresh reference import of the same file.
10. `prepare` takes no database argument and passes with a `None` runtime (purity).

Plants: CHK-M7-333 (BIT102 skipped in rebuild mode), -339 (record written in tx1), -340 (an exception swallowed and tx1 committed), -349 and -350 (alerts removed), -369 (`auto` not skipping, or `manual` skipping) must turn rows 7, 2, 9, 1, 2 and 3 red.

## 11. Budget

About 200 lines. If it grows past that, move sections 7 and 8 (the audit writers and the rebuild helpers) into `services/importer/pipeline_record.py`, as one extra file, with the lead's agreement.
