# TASK-151 plan: import store algorithm (SR §3.6)

Planner: planner-m7, 2026-10-27, from design note D3 (`work/tasks.md`, M7). Risk: high (importer; two approvals). Files: `manager/bitscan_manager/services/importer/store.py` and, after the §7 split, `services/importer/store_decide.py`. Depends on TASK-140 (model), TASK-148 (`repositories/catalog.py`) and TASK-150 (`repositories/catalog_admin.py`). Consumers: TASK-144 (builds `Candidate` and `RuleKeys`), TASK-154 (pipeline), TASK-157 (rebuild). Answers applied: #14, #15, #21, #98 (j), #101, #104, #106.

## 1. Spec

- SR §3.6 (SR L237–L246), steps 1 to 6, within one transaction (a savepoint in a rebuild).
- SR §4.1 BIT007 (SR L261) and BIT015 (SR L268); TS §4.1 L522 (409 `policy_managed_on_server`), L524 (one folder per policy, the server folder wins); TS §4.3 L548 (the override is never undone by a file), L549 (rename), L550 (revival as a new version).
- TS §5.2 grants: INSERT and UPDATE on `policy`, `family`, `plugin`; INSERT and DELETE on `policy_plugin`; USAGE on sequences. Never DELETE on `policy`.

## 2. Types (defined in `store.py`; TASK-144 builds them)

```python
@dataclass(frozen=True)
class CandidatePlugin:
    plugin_uuid: UUID; line: int            # line of <PluginId>, for BIT015
    plugin_name: str; control_ref: str | None
    plugin_description: str
    execute: str                            # trimmed
    execute_sha256: str                     # sha256(execute.encode()).hexdigest()
    operator: str                           # lowercase, one of the 14
    expected_result: str                    # trimmed
    timeout_s: int                          # 1..600, default 60

@dataclass(frozen=True)
class Candidate:                            # only built when no Reject finding remains
    policy_name: str; policy_name_line: int
    policy_description: str
    file_status: Literal["enabled", "disabled"]
    family_name: str
    format_version: str                     # "1.0"
    plugins: tuple[CandidatePlugin, ...]    # document order

@dataclass(frozen=True)
class RuleKeys:                             # built whenever the structure passed, for the database rules
    policy_name: str | None                 # None if PolicyName itself is invalid
    policy_name_line: int
    plugin_ids: tuple[RuleId, ...]          # the valid, distinct ids

@dataclass(frozen=True)
class RuleId:                               # as built (impl-manager-m7c; accepted by main 2026-10-27)
    plugin_uuid: UUID
    line: int                               # line of <PluginId>
    index: int                              # 1-based plugin position, for the BIT015 element path

@dataclass(frozen=True)
class Target:
    kind: Literal["server", "upload"]
    source_file: str | None                 # server: path relative to the bits folder, e.g. "cis.bit"; upload: None
    file_sha256: str

class PolicyManagedOnServer(Exception):     # upload of a name whose live policy is in the server folder
    policy_id: int

@dataclass(frozen=True)
class Decision:
    case: Literal["update", "rename", "move_server", "move_upload", "revive", "insert", "rejected"]
    policy_id: int | None                   # the policy this file becomes; None for insert
    displaced_id: int | None                # policy X that loses the file (#106), deleted on apply
    old: PolicyRow | None                   # the locked row (TASK-148 type) before the change
    findings: tuple[Finding, ...]           # BIT007 only

@dataclass(frozen=True)
class ChangedExecute:
    plugin_uuid: UUID; plugin_name: str; execute: str; execute_sha256: str
    reason: ChangeReason   # Literal["new", "changed", "reactivated"]; #100 (a) as widened by the user, 2026-10-27
                           # As built (TASK-151 r2, TASK-153 r3): `ChangeReason` is defined in
                           # services/importer/alerts.py and imported by store.py.

@dataclass(frozen=True)
class StoreResult:
    policy_id: int; policy_name: str; version: int
    plugins_added: int; plugins_updated: int; plugins_retired: int
    changed_executes: tuple[ChangedExecute, ...]
    renamed_from: str | None
    moved_from: str | None                  # previous source_file on a move
    revived: bool
    reenabled: bool                         # effective policy_status went disabled -> enabled
    deleted_policy_ids: tuple[int, ...]     # displaced policies soft-deleted here (alerts raised by the caller)
    remove_after_commit: tuple[str, ...]    # relative paths the caller deletes after commit (the uploaded copy)
    source_file: str
```

## 3. Functions

```python
def decide(conn, rules: RuleKeys, target: Target, file_exists: Callable[[str], bool]) -> Decision
def check_ownership(conn, decision: Decision, rules: RuleKeys) -> tuple[Finding, ...]   # BIT015
def is_unchanged(decision: Decision, target: Target) -> bool                              # for the auto skip
def apply(conn, decision: Decision, cand: Candidate, target: Target, now: datetime) -> StoreResult
```

Each takes the open connection of the caller's transaction (or savepoint). None of them commits, rolls back, takes the catalog lock, writes audit entries or touches files. If `decide` or `check_ownership` returns findings, the caller must roll back: nothing has been written by then, but the caller does not rely on that. `apply` raises only on a database error, and the caller rolls back.

### 3.1 `decide` (locks with `SELECT … FOR UPDATE`)

`N` = `rules.policy_name`. `byname` = the policy with `policy_name = N`, in any state. `byfile` = for a server target, the non-deleted policy with `source_file = target.source_file`. A server-folder `source_file` is one that starts with neither `uploaded/` nor `deleted/`.

If `N` is None (an invalid `PolicyName`), the outcome is `rejected` with no extra finding: the file-local finding already rejects it.

**Upload target:**

| `byname` | Decision |
| --- | --- |
| live, in the server folder | raise `PolicyManagedOnServer` |
| live, in `uploaded/` | `update` |
| deleted | `revive` |
| none | `insert` |

**Server target `S`.** `X` = `byfile` when it exists and is not `byname`. In every case that sets `displaced_id`, `X` loses `S` and is soft-deleted on apply (#106).

| `byname` | Decision |
| --- | --- |
| `byname.source_file == S` | `update` |
| live, at another server file that `file_exists` | `rejected`, with BIT007 at `policy_name_line`: "PolicyName '<N>' is already imported from <other file>." (#15: the caller orders new files) |
| live, at another server file that is gone | `move_server` (`moved_from` = old file); `displaced_id` = `X` |
| live, in `uploaded/` | `move_upload` (server folder wins); `remove_after_commit` = the old uploaded path; `displaced_id` = `X` |
| deleted | `revive` at `S`; `displaced_id` = `X` |
| none, and `byfile` exists | `rename` in place of `byfile`; `renamed_from` = its old name |
| none, and no `byfile` | `insert` |

### 3.2 `check_ownership` (BIT015)

For each `RuleId` in `rules.plugin_ids`, look up the existing plugin's `owner_policy_id` `O`. It conflicts when `O` is not the deciding policy (`decision.policy_id`; none for an insert), not `decision.displaced_id`, not deleted, and still lists the plugin (a `policy_plugin` row `(O, uuid)`). Each conflict is a BIT015 finding at `line`: "PluginId <uuid> belongs to policy '<O name>'.", element `Policy/PluginsGroups/Plugin[<index>]/PluginId`. One query covers all ids (TASK-148 `owners_of`).

### 3.3 `is_unchanged`

True when the decision is `update`, `old.source_sha256 == target.file_sha256`, `old.source_file == target.source_file` and `old` is not deleted. Only TASK-154's `auto` mode uses it.

**r3 (2026-10-27, Crash window and reviewer-m7):**
- For an upload target (whose `source_file` is None), the `source_file` comparison is dropped. It is true when the decision is `update`, `old` is not deleted and the hashes are equal. TASK-156 reconciles an `uploaded/policy-<n>.bit` only after checking that the file is that live policy's `source_file`.
- `Target` also raises `ValueError` for a server target whose `source_file` contains `/`, so `uploaded/…` and `deleted/…` paths never reach the server-folder rows of §3.1 (`move_server`, BIT007).

### 3.4 `apply`, in this order

0. **Prior plugin state, first of all.** Read `prior_sha = catalog_plugins.current_plugins(conn, uuids)` and `prior_retired = catalog_plugins.retired_among(conn, uuids)` for the candidate's uuids **before step 1**, in the same transaction (or savepoint) and under the catalog lock the caller holds (confirmed by main, 2026-10-27). Step 1's displaced delete retires the displaced policy's plugins in this same transaction, and a later read would wrongly show plugins this policy takes over from it as `retired → active` (raised by impl-manager-m7c, 2026-10-27). So "reactivated" means retired when this import started and active after it.
1. **Displaced policy.** If `displaced_id` is set, call `catalog_admin.soft_delete_effects(conn, displaced_id, now)` (TASK-150: `deleted_at`, `source_file = 'deleted/<id>'`, queued compliance jobs cancelled, schedules disabled, owned plugins retired) and add the id to `deleted_policy_ids`. This frees `S` before step 3 (UNIQUE `source_file`).
2. **Family.** `family_id = catalog.upsert_family(conn, cand.family_name, now)`: `INSERT … ON CONFLICT (family_name) DO NOTHING`, then `SELECT`. Family rows are never changed or removed (#104 (e)).
3. **Policy.**
   - `insert`: `policy_id = catalog.next_policy_id(conn)` (`nextval` on the serial; the app has USAGE). Then INSERT with `source_file` = `S`, or `uploaded/policy-<id>.bit` for an upload; `policy_status = file_status`, `status_overridden = false`, `version = 1`, `format_version`, `source_sha256`, `imported_at = updated_at = now`.
   - Every other case: one UPDATE of the locked row, setting:
     - `policy_name = N` (a rename);
     - `policy_description`, `family_id`, `format_version`, `file_status = :fs`;
     - `policy_status = CASE WHEN status_overridden THEN policy_status ELSE :fs END`, written in the statement itself, so a concurrent PATCH, which waits on the row lock, is never lost;
     - `version = version + 1` when `source_sha256 <> :sha` or the case is `revive` (#14);
     - `source_file` (`S`, or `uploaded/policy-<id>.bit` for an upload), `source_sha256 = :sha`, `deleted_at = NULL`, `imported_at = now`;
     - `updated_at = now` only when a stored column changed (#104 (d)).
     `status_overridden` is never written (#14). `RETURNING` gives the new `version` and `policy_status`. `reenabled` = old effective status `disabled` and new `enabled` (`old` comes from `decide`'s locked row).
4. **Plugins.**
   - Use `prior_sha` and `prior_retired` from step 0; nothing is read again here.
   - Upsert each plugin with `owner_policy_id = policy_id`, `family_id`, its values and `state = 'active'`, through `INSERT … ON CONFLICT (plugin_uuid) DO UPDATE SET … , updated_at = now WHERE (owner_policy_id, family_id, plugin_name, control_ref, plugin_description, execute, execute_sha256, operator, expected_result, timeout_s, state) IS DISTINCT FROM (EXCLUDED.…)`, `RETURNING plugin_uuid, (xmax = 0) AS inserted`.
   - `plugins_added` = the inserted rows; `plugins_updated` = the returned rows that were not inserted (#21). Rows with nothing changed are not returned.
   - `changed_executes` (#100 (a), widened by the user on 2026-10-27) holds every candidate plugin that is:
     - `new`: inserted by this upsert;
     - otherwise `changed`: `prior_sha[uuid]` differs from the candidate's `execute_sha256`;
     - otherwise `reactivated`: the decision is `revive`, or the uuid is in `prior_retired`.
     The first that applies is the `reason`. Every other plugin is left out. The list keeps document order, with each plugin at most once. A revived policy's plugins were retired by its delete, so they appear as `reactivated` either way. A plugin this policy takes over from the policy displaced in step 1 is not reactivated, because it was active when the import started.
   - Send the upserts as batches of at most 500 rows per statement (5,000 plugins = at most 10 statements). Always parameterised: `psycopg.sql` for any identifier, no f-string SQL (S608).
5. **Membership.** `DELETE FROM policy_plugin WHERE policy_id = :id`, then INSERT the rows with `sort_order` 1..n in document order (#104 (a): a deleted policy's rows are untouched, because this always targets the live policy).
6. **Retire.** One UPDATE for every `active` plugin that no non-deleted policy lists: `state = 'retired'`, `updated_at = now`, `RETURNING plugin_uuid`; `plugins_retired` = the count (#104 (b), #21). This includes plugins retired by step 1's displaced delete only if this statement retired them. Step 1's own retirements count toward that delete, not toward this import.
7. Return the `StoreResult`.

## 4. Repository functions this uses (as built in W1)

Confirmed by impl-manager-m7b on 2026-10-27; details in `work/reports/TASK-148-impl.md`. Each is a module function that takes `conn` first. Where these differ from §3.4, these govern.

`repositories/catalog.py` (TASK-148):
- `policy_by_name_for_update(conn, name)`, `policy_by_source_file_for_update(conn, path)`, `policy_by_id_for_update(conn, policy_id)` → `PolicyRow | None` (every `policy` column), each with `FOR UPDATE`.
- `upsert_family(conn, name, now) -> int`.
- `next_policy_id(conn) -> int`.
- `insert_policy(conn, policy_id, PolicyValues, now) -> PolicyRow`.
- `update_policy(conn, policy_id, PolicyValues, now) -> PolicyRow | None`. It adds 1 to `version` **itself** when `source_sha256` differs or the row was deleted (the revival, #14), so the store passes no version flag. It keeps the override `CASE`, never writes `status_overridden`, and moves `updated_at` only on a stored change. `None` (row gone) is an internal error for the store.
- `owners_of(conn, uuids) -> list[Owner]`, where `Owner` is `(plugin_uuid, owner_id, owner_name, owner_deleted, owner_lists)`.

`repositories/catalog_plugins.py` (TASK-148's second file):
- `PluginValues` (the store maps each `CandidatePlugin` to it).
- `current_plugins(conn, uuids) -> dict[UUID, str]` (uuid → stored `execute_sha256`).
- `retired_among(conn, uuids) -> frozenset[UUID]`: the given ids whose `state` is `retired`. This is **new** for #100 (a) widened (2026-10-27): an additive function in `catalog_plugins.py`, one parameterised `SELECT`, with `current_plugins` unchanged.
- `upsert_plugins(conn, plugins, *, family_id, owner_policy_id, now) -> list[tuple[UUID, bool]]`. It batches 500 rows per statement itself and returns only inserted or changed rows; `inserted` comes from a statement-snapshot CTE, not `xmax`. §3.4 step 4's SQL sketch is therefore replaced; the counting rule is unchanged: added = `inserted`, updated = returned and not `inserted`.
- `replace_membership(conn, policy_id, uuids)` (in document order; `sort_order` 1..n).
- `retire_unreferenced(conn, now) -> list[UUID]`; `plugins_retired = len(...)`.

`repositories/catalog_admin.py` (TASK-150):
- `soft_delete_effects(conn, policy_id, now) -> DeleteEffects | None`, where `DeleteEffects` is `(cancelled_job_ids, disabled_schedule_ids, retired_plugin_uuids)`. `None` means unknown or already deleted, with nothing changed. In §3.4 step 1 the displaced policy was locked live by `decide`, so `None` there is an internal error: raise, and the caller rolls back.

## 5. Edge cases

- Two plugins in one file with the same uuid cannot reach `apply` (BIT005 rejects first). `RuleKeys.plugin_ids` holds only distinct, valid ids.
- A file that lists a plugin it owned and that was retired: the upsert sets `active` again and counts it as updated (#21).
- A move with identical content keeps `version` (the hash is equal), and the move is audited by the caller.
- A rename whose old name is later uploaded creates a new policy, because the old name is free.
- A policy whose family changes: the old family row stays, and its plugins get the new `family_id` (counted as updated).
- An upload's `source_file` is `uploaded/policy-<id>.bit` in every case, including a revival of a policy deleted from the server folder.

## 6. Tests (TP-M7-11; tester file `manager/tests/test_import_store_pg.py`; PostgreSQL as `bitscan_app`, with `Candidate` and `RuleKeys` built in the test)

1. REQ-158 (1): the SR §1.1 candidate as `x.bit`: every column and the `v_plugin` display name.
2. REQ-158 (2): the same candidate and sha again gives version 1 and counts 0/0/0; another sha gives version 2.
3. REQ-158 (3): the override kept. And a concurrent PATCH: a second connection holds a status UPDATE and commits after `decide` is blocked; the final `policy_status` is the PATCH's.
4. REQ-158 (4): reorder (updated 0); drop one plugin (retired 1, row kept); change one `Execute` (updated 1, `changed_executes` length 1, reason `changed`). #100 (a) widened:
   - a dropped plugin listed again gives one entry with reason `reactivated`, and its `Execute` unchanged;
   - a revived policy lists every plugin, each `reactivated` unless new or changed;
   - an unchanged, still-active plugin is never listed;
   - a plugin both retired and with a changed `Execute` gives reason `changed`;
   - the #106 case: a plugin this policy takes over from the displaced `X`, active when the import started, is not listed (unless new or changed).
5. REQ-158 (5): `apply` interrupted after 3 plugins (a fault-injecting repository wrapper); after the test's rollback every catalog table checksum is unchanged.
6. REQ-158 (6) and #14: a revival keeps the id, gets version + 1 with an identical sha, and keeps `status_overridden`.
7. Every `decide` row in §3.1 for both target kinds, including `PolicyManagedOnServer`, BIT007 with the other file present, and the move when it is gone (`file_exists` fake).
8. #106: `X` at `a.bit` now named `Y` with `Y` (a) in `b.bit` present (BIT007), (b) uploaded (`move_upload`, `X` deleted, `remove_after_commit`), (c) deleted (`revive`, `X` deleted), (d) absent (`rename`, same id, scan rows still point at it).
9. BIT015: owner live and listing gives a finding naming it; owner deleted, owner not listing, owner = the displaced `X`, and owner = self give none; after a claim, `owner_policy_id` moves and the old deleted policy's membership row remains (#104 (c)).
10. #21 counts on a mixed file (2 new, 1 changed, 1 unchanged, 1 dropped) are 2/1/1.
11. `reenabled`: true for a file going disabled → enabled without an override; false with an override.
12. No statement deletes from `policy` (statement log checked); ruff S608 passes.

Plants: CHK-M7-335 (BIT015 removed), -338 (commit per plugin), -369 (override ignored; version + 1 on an identical hash outside a revival) must turn rows 9, 5, 3 and 2 red.

## 7. Budget

About 200 lines. **The split is applied** (impl-manager-m7c, accepted by main 2026-10-27; `work/reports/TASK-151-impl.md`):
- `services/importer/store.py` holds the §2 types, `in_server_folder()` and `apply`.
- `services/importer/store_decide.py` holds `decide`, `check_ownership` and `is_unchanged`. It imports the types from `store.py`, never the other way.
- Two small additions to §2: `Decision.findings` defaults to `()`, and `Target` raises `ValueError` when `kind` and `source_file` disagree (a server target needs a path, an upload target must have none).
