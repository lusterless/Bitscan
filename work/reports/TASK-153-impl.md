# TASK-153 IMPL: M7 alert kinds, import-failure counter, importer alert builders

Implementer: impl-manager-m7c. REQ-162, REQ-165, REQ-166, REQ-167, REQ-168. Risk high (importer; two approvals). Spec: TS §8.4 L1288-L1291 (metric "import failures"; delivery; immediate and threshold alerts), TS §4.1 L530 (every import is audit-logged and alerts), TS §5.3 (entries go through the chain and the sink); open questions #100, #101, #103, #23, #20 (approved 2026-10-27 as recommended); `work/plans/TASK-154.md` §5 and §7.

## Files

| File | Change | Lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/audit/alerts.py` | `M7_ALERT_KINDS` added and joined into `ALERT_KINDS`; nothing else changed | +12 |
| `manager/bitscan_manager/services/audit/metrics.py` | `IMPORT_MODES`, `IMPORT_FAILURES` (exported from zero per mode); module docstring names import modes as a fixed label set | +14 |
| `manager/bitscan_manager/services/importer/alerts.py` (new) | Builders, `emit`, `count_failure` | 251 non-blank (217 without docstrings and comments) |

Over the 150 estimate and the ~200 limit. About 70 of the lines are ruff-format's one-key-per-line detail dicts. main decided on 2026-10-27 to keep it as one task (option (a)): it is one interface that TASK-152, 154, 157, 158 and 161 share.

`raise_alert`, `append_entry` and `services/audit/__init__.py` are unchanged. `raise_alert` still refuses an unknown kind with `ValueError`. `M7_ALERT_KINDS` is not re-exported from `services/audit/__init__.py`, which is not in this task's file list; import it from `services.audit.alerts`.

## Interface

`services/audit/alerts.py`:
- `M7_ALERT_KINDS = {policy_imported, policy_import_rejected, policy_deleted, policy_rebuilt, policy_reenabled, catalog_integrity_failed}` (#101).
- `ALERT_KINDS = M2 | M3 | M7` (34 kinds). Every kind is exported at 0 when the module is imported, through the existing loop.

`services/audit/metrics.py`:
- `IMPORT_MODES = ("auto", "manual", "rebuild")` (`bit_import.mode`, TS §5.2 L699).
- `IMPORT_FAILURES`: a Counter `bitscan_import_failures` (`_total` on the wire), label `mode`, in the shared `REGISTRY`. All three modes are exported at 0.

`services/importer/alerts.py`:
- `FLAG_WORDS = ("shadow", ".ssh", ".pem", ".key", "token", "credentials")`.
- `flags(execute) -> list[str]` returns the words found in `execute.casefold()`, in `FLAG_WORDS` order (#100 (c)). Casefold rather than lower makes Kelvin-sign or long-s spellings match too; flagging more is the safe direction for a hint.
- `AuditEvent(action, target, detail, kind=None)` is frozen. `kind` None means a plain audit entry, not an alert.
- `emit(repo, on_commit, event, *, actor) -> AppendedEntry`: with a kind it calls `raise_alert`, so the count is registered on commit; without one it calls `append_entry`. It always writes in the caller's transaction.
- `count_failure(on_commit, mode)` registers `IMPORT_FAILURES.labels(mode).inc` on commit (#101: "+1 per rejected import when its record commits"). An unknown mode raises `ValueError`. The caller calls it next to `emit(rejected(...))` in the record transaction (TASK-154 §5).
- `ChangedExecute` is a `Protocol` with read-only `plugin_uuid: UUID`, `plugin_name`, `execute` and `execute_sha256`. TASK-151's frozen `ChangedExecute` dataclass satisfies it structurally; nothing imports `store.py`.
- `Difference(subject, check)` is frozen. `subject` is `policy:<id>` or a path relative to the bits folder; `check` is TASK-158's fixed check name.

| Builder | action | kind | target | detail |
| --- | --- | --- | --- | --- |
| `imported(...)` | `policy.import` | `policy_imported` | `policy:<id>` | `policy_id, policy_name, version, mode, file_sha256, source_file, plugins_added, plugins_updated, plugins_retired, renamed_from, revived, changed_executes: [{plugin_uuid, plugin_name, execute, execute_sha256, flags}]` (TASK-154 §7.1; #100 (b), `execute` in full) |
| `rejected(...)` | `policy.import_rejected` | `policy_import_rejected` | `policy:<id>` if matched, else `file_name` (null if empty) (#101) | `import_id, mode, file_name, file_sha256, policy_id, finding_count, codes` (distinct codes in first-seen order; the findings stay in `bit_import.errors`) |
| `deleted(...)` | `policy.delete` | `policy_deleted` | `policy:<id>` | `policy_id, policy_name, source_file` (the file before the delete), `reason` ∈ {`deleted through the API`, `file removed`, `file now holds another policy`} |
| `moved(...)` | `policy.move` | none (not an alert) | `policy:<id>` | `{from, to}` (TASK-154 §7.2) |
| `status_change(...)` | `policy.status_change` | `policy_reenabled` only when `before == disabled` and `after == enabled`, else none | `policy:<id>` | `policy_id, policy_name, from, to, status_overridden, by` ∈ {`patch`, `file`} |
| `rebuilt(...)` | `bits.rebuild` | `policy_rebuilt` | `task:<uuid>` | `task_id, state` ∈ {`succeeded`, `failed`}, `files_imported, files_rejected, deleted_policy_ids, plugins_retired` |
| `integrity_failed(diffs)` | `catalog.integrity_check` | `catalog_integrity_failed` | null | `difference_count` (all), `differences` (first 100 of `{subject, check}`) (#103). An empty list raises `ValueError` (a clean catalog raises nothing). |

Choices for the reviewer (where #100, #101 and TASK-154 §7 are silent; all are internal audit JSON, with no new table, field or route):
- The detail keys of `rejected`, `deleted`, `status_change`, `rebuilt` and `integrity_failed`, the three delete reasons, and the target `task:<uuid>` for a rebuild are mine. They were sent to main.
- `status_change` serves both PATCH (TASK-161: every PATCH writes one entry, and only a re-enable alerts) and the file case (TASK-154 §7.4).
- `_storable()` replaces U+0000 and lone surrogates with U+FFFD in path-like fields (`source_file`, `file_name`, `from`, `to`, `subject`). Postgres `jsonb` refuses both (builder checklist 1), and an undecodable file name from disk would otherwise fail the catalog transaction. `policy_name` and `execute` come from XML, which cannot contain either, so they are not touched.
- Nothing here logs. The `Execute` text goes only into the audit detail, as TS §8.4 L1290 requires.

## Acceptance points (checked by a throwaway script with a fake repo and fake `on_commit`, not a test file)

1. Every M7 kind and every import mode shows at 0 in `generate_latest(REGISTRY)` after import.
2. Each builder gives the shape in the table. `json.dumps` with `allow_nan=False` (through `append_entry`) accepts each one.
3. `flags`: `/etc/SHADOW`, `~/.ssh/id_rsa`, `x.PEM`, `x.key`, `/run/Token` and `/etc/credentials` each give their word. `dpkg-query -W -f='${Status}' apparmor 2>/dev/null` and `grep x /etc/ssh/sshd_config` give none.
4. Hooks run only on commit: 7 hooks were registered (6 alerts plus 1 failure count, none for the move). After running them, each M7 kind is 1 and `bitscan_import_failures_total{mode="auto"}` is 1.
5. `raise_alert(kind="nope")`, `count_failure(mode="bogus")` and `integrity_failed([])` each raise `ValueError`.

## Static gates (Windows, `manager/.venv`)

- `ruff check` and `ruff format --check` on the three files: pass. On all of `manager/`, the only findings are in tester-owned `manager/tests/test_bit_parse.py`.
- `mypy --strict --config-file manager/pyproject.toml manager`: Success, no issues in 255 source files.

## For the tester (tester-m7, TP-M7-12, `manager/tests/test_import_alerts.py`)

Existing tests that **must** change, because new kinds and a new metric family are the point of this task:
- `manager/tests/test_alerts.py` `test_kinds_are_exactly_the_50_and_71_lists`: `ALERT_KINDS` is now `M2 | M3 | M7`, with 34 kinds (not 28).
- `manager/tests/test_alerts.py` `test_every_kind_is_exported_from_zero_in_the_shared_registry`: `REGISTRY_FAMILIES` gains `bitscan_import_failures`.
- `manager/tests/test_thresholds.py` `test_metric_families_and_labels`: the family set gains `bitscan_import_failures` (a counter), and `allowed` needs `"bitscan_import_failures": {"mode"}`.
- `test_metrics_api_pg.py` uses a subset check, so it is not affected.

The builders and the counter are pure units with fakes; the `FakeRepo` and `FakeTx` in `test_alerts.py` work. REQ-162 (4) and (5), rollback and the fake sink, are proved through TASK-154 on PostgreSQL. The existing `test_alerts_pg.py` shows `raise_alert` on PostgreSQL commits and rolls back with its hook.

## Round 2 (review CHANGES_REQUESTED, should-fix, `work/reviews/TASK-153.md`)

- **Fix:** with no matched policy, `rejected()`'s fallback audit target is now `file_name[:TARGET_MAX]` (`TARGET_MAX = 255`, the `audit_log.target VARCHAR(255)` of TS §5.2), and the empty name still gives null. The full name stays in `detail.file_name` (jsonb). Before this, a reconciled `uploaded/<250-character name>.bit` (259 characters) made the INSERT fail in the record transaction, losing the `bit_import` row, the alert and the count.
- Other targets are bounded by construction: `policy:<id>`, `task:<uuid>` and null. Actors are the fixed #101 forms.
- Gates: ruff and ruff format pass. `tests/test_import_alerts.py` still passes (51) on Windows. A 263-character name gives a 255-character target and keeps all 263 characters in the detail.

## Revision 3 (#100 (a) widened by the user, decisions 2026-10-27)

- New `ChangeReason = Literal["new", "changed", "reactivated"]`. The `ChangedExecute` Protocol gains a read-only `reason`.
- Each `changed_executes` entry in the `policy_imported` detail is now `{plugin_uuid, plugin_name, execute, execute_sha256, reason, flags}`. `execute` is still in full, and `flags` work as before.
- The r2 cut of the rejected target to 255 characters is kept, and nothing else changed.
- The store (TASK-151 r2) decides the reason; `imported()` copies it through.
- Gates: ruff, ruff format and CI mypy pass (270 files).

## Revision 4 (crash-window ruling, decisions 2026-10-27)

- `rebuilt()` gains the required keyword `removed_leftovers: Sequence[str]`: the `uploaded/` files of deleted policies that the rebuild removed, as relative paths.
  - The `policy_rebuilt` detail carries `removed_leftovers` as a list in the given order, each path through `_storable` like the other path fields.
  - An empty sequence gives `[]`.
- The r2 255-character target cut and the r3 `reason` are unchanged. No other builder changed.
- Check: two paths come through in order, and `[]` gives `[]`.
- Gates: ruff and ruff format pass. CI mypy reports one error, in tester-owned `manager/tests/test_import_alerts.py` L462: an existing `rebuilt(...)` call lacks the new required keyword. The test needs `removed_leftovers=[]` (or its case). No product code calls `rebuilt()` yet; TASK-157 will.
