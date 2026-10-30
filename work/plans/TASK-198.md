# TASK-198 plan: queue a scan (design note D1), with the TASK-188, 189 and 193 interfaces

Planner: planner-m9, 2026-10-30. REQ-208, REQ-209, REQ-210, REQ-211, REQ-212, REQ-227. Open items: #3, #18, #122, #125, #126 (a)–(b), #129 (a)–(b).

## 1. Spec quotes

- TS §2.3 L133: "Role checked; one job per host is built from the policy's current plugins."
- TS §3.3 L213: "The manager builds jobs only from the active plugins of enabled policies. There is no API to queue an ad-hoc command."
- TS §3.5 L248: "A compliance job carries the plugins to run (`{plugin_uuid, execute, timeout_s}`) and the redaction patterns (§6.5). Operator and ExpectedResult stay on the manager."
- TS §4.4 L555: targets are "exactly one of … resolved when the scan is queued, to agents that are not decommissioned or awaiting approval. Offline agents still get jobs … The request and the resolved list are stored in `scan.target`."
- TS §4.4 L558: "a newer queued job for the same agent and policy cancels the older queued one." L559: "a scan of a disabled policy returns 409." L560: "each scan records the `policy.version` it was built from."
- TS §4.4 L566: `queued` "with `pickup_by` = creation + 24 h".
- TS §4.1 L530: "jobs queued afterwards use it, and jobs already queued keep the commands they were built with."
- TS §4.3 L550 (delete): "its queued jobs are cancelled".

## 2. Pure interfaces (TASK-188, TASK-189)

`bm/services/jobs/targets.py` (TASK-188):

```python
TargetKind = Literal["agents", "tags", "all"]
AGENTS_MAX: Final = 10_000
TAGS_MAX: Final = admin.MAX_TAGS            # 32, services/agents/admin.py
class InvalidTarget(ValueError): ...        # message: "Invalid request: target" (+ fixed sub-field), never input

@dataclass(frozen=True, slots=True)
class Target:
    kind: TargetKind
    agents: tuple[UUID, ...] = ()           # distinct, input order kept
    tags: tuple[str, ...] = ()

def parse_target(value: object) -> Target
def stored_target(target: Target, resolved: Sequence[UUID]) -> dict[str, Any]
    # {"agents": [...]} | {"tags": [...]} | {"all": True}, plus "resolved_agents": sorted lowercase strings
```

`parse_target` takes the decoded JSON value (the route passes the raw `target` from a strict body model with `target: dict[str, Any]`). Exactly one key; `all` is `True` (`type(v) is bool`); lists non-empty, distinct, within limits; UUIDs in the hyphenated form only (reuse `api/agent/schemas.UUID_PATTERN` semantics, but the module must not import `api`: copy the one-line check through `uuid.UUID` plus a length-36 and hyphen-position test, as `eval_spec._uuid` does but case-insensitive); tags by `admin.TAG_CHARACTERS` and `MAX_TAG_LENGTH`.

`bm/services/jobs/build.py` (TASK-189):

```python
@dataclass(frozen=True, slots=True)
class CatalogPlugin:          # one active plugin of the policy, from the snapshot
    plugin_uuid: UUID
    display_name: str         # v_plugin.display_name
    execute: str
    timeout_s: int
    operator: str
    expected: str

class UnstorableText(ValueError): ...      # fixed message

@dataclass(frozen=True, slots=True)
class BuiltPlugins:
    plugins_json: list[dict[str, Any]]     # [{"plugin_uuid", "execute", "timeout_s"}] in order
    eval_spec_json: dict[str, Any]         # build_eval_spec(EvalSpec(...))
    patterns: list[str]

PICKUP_WINDOW = services.scheduler.inventory.PICKUP_WINDOW   # 24 h, reused
def pickup_text(created_at: datetime) -> str               # (created_at + 24 h) UTC, "%Y-%m-%dT%H:%M:%SZ"
def plugins_and_spec(plugins: Sequence[CatalogPlugin], patterns: Sequence[str]) -> BuiltPlugins
def payload(job_id: UUID, agent_id: UUID, created_at: datetime, built: BuiltPlugins) -> dict[str, Any]
def retry(original_payload: Mapping[str, Any], original_eval_spec: Mapping[str, Any],
          missing: Collection[UUID], *, job_id: UUID, created_at: datetime,
          original_is_retry: bool) -> tuple[dict[str, Any], dict[str, Any]]
```

- `plugins_and_spec` checks every `execute`, `display_name`, `expected` and pattern for `"\x00"` and for `str.encode("utf-8")` failure → `UnstorableText` (M8 carry). It builds the `EvalSpec` (which also enforces 1–5,000 plugins, operators, lengths, distinct uuids) and calls `build_eval_spec`. Empty `plugins` → `ValueError` (the service maps the snapshot case to #125 (h) before calling).
- `payload` returns exactly `{"job_id", "agent_id", "kind": "compliance", "pickup_by", "plugins", "redaction_patterns"}`. It is the reference the tests compare SQL-composed payloads against (REQ-209 (1)).
- `retry` keeps the original's items whose uuid is in `missing`, in original order; copies `redaction_patterns`; filters `eval_spec["plugins"]` to the same uuids in the same order, then round-trips it through `parse_eval_spec`/`build_eval_spec`; raises `ValueError` when `original_is_retry` or `missing` is empty or names a uuid not in the payload.

## 3. Repository interface (TASK-193, `bm/repositories/scan_queue.py`)

```python
@dataclass(frozen=True)
class PolicySnapshot:
    policy_id: int
    version: int
    status: str                      # 'enabled' | 'disabled'
    deleted: bool
    plugins: list[CatalogPlugin]     # active only, sort_order

def lock_policy_queue(conn, policy_id: int) -> None
    # SELECT pg_advisory_xact_lock(hashtext('scan_queue:' || %s::text))
def policy_snapshot(conn, policy_id: int) -> PolicySnapshot | None
    # step 1: SELECT 1 FROM policy WHERE policy_id = %s FOR SHARE   (None if no row)
    # step 2: ONE statement: policy version/status/deleted_at LEFT JOIN policy_plugin
    #         JOIN v_plugin (state = 'active') ORDER BY sort_order
def resolve_agents(conn, kind: str, agents: Sequence[UUID], tags: Sequence[str]) -> list[UUID]
    # status NOT IN ('decommissioned','awaiting_approval'); tags via agent_tag (any of);
    # unknown ids drop out by the join; ORDER BY agent_id; one statement
def insert_scan(conn, *, policy_id, policy_version, trigger, schedule_id, target_json,
                requested_by, created_at) -> UUID
def insert_jobs(conn, *, scan_id, agent_ids, job_ids, created_at, pickup_by,
                pickup_text, plugins_json, patterns, eval_spec_json) -> int
    # one INSERT … SELECT FROM unnest(%s::uuid[], %s::uuid[]) AS t(job_id, agent_id)
    # payload = jsonb_build_object('job_id', t.job_id, 'agent_id', t.agent_id,
    #   'kind', 'compliance', 'pickup_by', %(text)s, 'plugins', %(plugins)s::jsonb,
    #   'redaction_patterns', %(patterns)s::jsonb)  -- job_id/agent_id cast to text
def cancel_older_queued(conn, *, policy_id, agent_ids, new_scan_id, now) -> list[UUID]
    # UPDATE scan_job j SET state='cancelled', finished_at=%(now)s FROM scan s
    # WHERE j.scan_id = s.scan_id AND s.policy_id = %(p)s AND j.kind = 'compliance'
    #   AND j.state = 'queued' AND j.agent_id = ANY(%(a)s) AND j.scan_id <> %(new)s
    # RETURNING j.job_id
```

Notes: `jsonb_build_object` with `agent_id`/`job_id` must emit the lowercase hyphenated text (`::text` of a uuid does). JSONB key order is irrelevant (the pull returns a dict, validated by `JobsResponse`). Job ids are generated in Python (`uuid4`) so the payload and the row agree without a second statement. `FOR SHARE` needs UPDATE privilege on one column of `policy`, which `bitscan_app` holds.

## 4. Service (`bm/services/jobs/queue.py`)

```python
class PolicyNotFound(Exception); class PolicyDisabled(Exception); class PolicyDeleted(Exception)
class NoTargetAgents(Exception); class PolicyHasNoPlugins(Exception)

@dataclass(frozen=True)
class ScanQueued:
    scan_id: UUID; state: Literal["queued"]; policy_version: int; jobs: int

def queue_scan(tx: Tx, *, policy_id: int, target: Target, trigger: Literal["manual","scheduled"],
               schedule_id: int | None, requested_by: int | None, actor: str,
               via_api_token: bool, now: datetime) -> ScanQueued
```

No `settings` parameter: `queue_scan` reads the settings itself, with `read_settings(SettingsRepo(tx.conn))` inside the caller's transaction (decisions 2026-10-30, "M9 builder rulings" (6); REQ-221 (5)).

Order inside the caller's transaction (the route or the schedule tick opens it; `tx.on_commit(runtime.sink_gate.wake)`):
1. `lock_policy_queue`; 2. `policy_snapshot` → None: `PolicyNotFound`; deleted: `PolicyDeleted`; disabled: `PolicyDisabled`; no plugins: `PolicyHasNoPlugins`.
3. `built = plugins_and_spec(snapshot.plugins, read_settings(SettingsRepo(tx.conn)).redaction_patterns)`.
4. `resolved = resolve_agents(...)`; empty → `NoTargetAgents`.
5. `insert_scan` (state defaults to `queued`), `insert_jobs`, `cancel_older_queued`.
6. Audit: detail `{policy_id, policy_version, trigger, schedule_id, target_kind, jobs, cancelled_older}`; if `target.kind == "all" and via_api_token`: `audit.alert("all_hosts_scan_api_token", actor, "scan.create", f"scan:{id}", detail)`, else `audit.audit(actor, "scan.create", …)`.

Every refusal raises before any write, so the caller's rollback leaves nothing (REQ-211 (2)). The service never reads a command from its arguments: `execute` only comes from `policy_snapshot` (REQ-212).

## 5. Edge cases and races (tests: TP-M9-11)

- Delete during queue: the delete's `UPDATE policy` waits on our `FOR SHARE`; after our commit its `UPDATE scan_job … state='queued'` sees our jobs and cancels them. If the delete commits first, our `FOR SHARE` returns the updated row (`deleted_at` set) → `PolicyDeleted`.
- Import during queue: the import's `UPDATE policy` waits likewise; the single snapshot statement means version and plugin rows come from one snapshot even under READ COMMITTED.
- Two scans of one policy: the queue lock serialises them; the second cancels the first's queued job for shared agents.
- Inventory jobs: `cancel_older_queued` filters `kind = 'compliance'` (REQ-229 (2)).
- A scan of 10,000 agents is three INSERT/UPDATE statements; the `plugins` JSON is passed once.
