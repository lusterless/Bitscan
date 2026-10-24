# TASK-048 plan: agent wire contract (TS §6.5)

REQs: REQ-060, REQ-088. Owner: impl-manager. **Two approvals (TS §8.2 L1268, agent routes; decisions 2026-10-20).** Depends on: nothing in code; **blocked on #60** (field table below) and **#59** (problem types). Files: `bm/api/agent/__init__.py` (package docstring and the `AGENT_PROBLEM_TYPES` constant only; the router is TASK-063), `bm/api/agent/schemas.py`. Tests: TP-M3-01 (fixtures, tester, written from this table and TS §6.5, not from the code), TP-M3-02 (G30).

## Spec quotes

- TS §6.5 L1159: "The OpenAPI document carries the full JSON Schemas; the Go agent and the Python manager are both generated from or tested against it."
- L1161 Enrol: request `{ "hostname", "machine_id", "agent_version", "os_id", "os_version_id", "os_pretty_name" }` → `{ "agent_id", "agent_token", "issued_at", "expires_at", "status": "enrolled" | "awaiting_approval" }`.
- L1163 Heartbeat: request `{ "agent_version", "uptime_s", "last_pull_at", "current_job_id", "spool_bytes", "last_error", "runner_helpers": ["capread"], "clock": "<RFC 3339>" }` → `{ "job_pull_seconds": 300, "max_parallel_plugins": 2, "server_time": "<RFC 3339>" }`.
- L1165–L1182 Job: `job_id`, `agent_id`, `kind`, `pickup_by`, `plugins` (`plugin_uuid`, `execute`, `timeout_s`), `redaction_patterns`; "Inventory jobs have `kind: "inventory"` and no `plugins` or `redaction_patterns`."
- L1184 Results: `{ "results": [ { "plugin_uuid", "exit_code", "stdout", "stderr", "started_at", "finished_at", "timed_out", "truncated", "error": null | "spool_overflow" | "runner_unavailable" } ], "final": true | false }` → `{ "accepted": n, "duplicates": n }`.
- L1186 Inventory: `{ "os_info": { … "raw": {} }, "packages": [ { "name", "version", "architecture", "status", "source", "installed_size_kb" } ], "list_sha256": … }` → 204.
- L1188 Rotate → `{ "agent_token", "issued_at", "expires_at" }`. L1190 error types.
- TS §3.5 L253: "batches of at most 50 results and at most 1.5 MB". TS §6.3 L1139: RFC 3339 UTC, UUID strings.

## Field table (recommended answer to #60; every line is a proposal until the owner answers)

Strings are counted in Unicode code points, as in M2 (#56). "Column" means the TS §5.2 column the value is stored in. All request models use `extra="forbid"`; all timestamps are the M2 `UtcDatetime` type on output and, on input, RFC 3339 with an explicit offset (naive values refused), normalised to UTC.

| Body | Field | Type and constraint | Nullable | Source |
| --- | --- | --- | --- | --- |
| Enrol req | `hostname` | string 1–255 | no | `agent.hostname` VARCHAR(255) L715 |
| | `machine_id` | exactly 32 characters `[0-9a-f]` (machine-id(5) form) | no | `agent.machine_id` CHAR(32) L714 |
| | `agent_version` | string 1–32 | no | VARCHAR(32) L716 |
| | `os_id` | string 0–32 | yes | `os_info.os_id` L782; not stored at enrolment (no column; spec note) |
| | `os_version_id` | string 0–16 | yes | L783; not stored at enrolment |
| | `os_pretty_name` | string 0–128 | yes | `enrollment_request.os_pretty_name` L768 |
| Enrol resp | `agent_id` | UUID string | no | |
| | `agent_token` | `bsa_` + 43 base64url | no | #56 (a) |
| | `issued_at`, `expires_at` | timestamp | no | |
| | `status` | `enrolled` or `awaiting_approval` | no | |
| Heartbeat req | `agent_version` | string 1–32 | no | |
| | `uptime_s` | integer 0–2^63−1 | no | |
| | `last_pull_at` | timestamp | yes (no pull yet) | |
| | `current_job_id` | UUID string | yes | |
| | `spool_bytes` | integer 0–2^63−1 | no | |
| | `last_error` | string 0–1,024 | yes | no column (#25) |
| | `runner_helpers` | array of 0–8 distinct strings `^[a-z][a-z0-9_-]{0,31}$` | no | `agent.runner_helpers` JSONB L728 |
| | `clock` | timestamp | no | |
| Heartbeat resp | `job_pull_seconds` | integer 60–3,600 | no | TS §8.6 L1322 |
| | `max_parallel_plugins` | integer 1–8 | no | L1325 |
| | `server_time` | timestamp | no | |
| Job (both) | `job_id`, `agent_id` | UUID string | no | |
| | `kind` | `inventory` or `compliance` (discriminator) | no | |
| | `pickup_by` | timestamp | no | |
| Job (compliance only) | `plugins` | array of 1–5,000 (TS §4.1 L517) items, each exactly `plugin_uuid` (UUID), `execute` (non-empty string), `timeout_s` (integer 1–600, L682) | no | |
| | `redaction_patterns` | array of 0–50 strings (TS §8.6 L1324) | no | |
| Results req | `results` | array of 0–50 items | no | TS §3.5 L253 |
| | item `plugin_uuid` | UUID string | no | |
| | item `exit_code` | integer −2^31..2^31−1 | yes (timed out, runner error) | `scan_result.exit_code` L902 |
| | item `stdout`, `stderr` | string, may be empty, no schema maximum (the server caps of TS §4.5 L599 make an oversize result ERROR `oversize`, they do not refuse the batch) | no | |
| | item `started_at`, `finished_at` | timestamp, always required | no | `scan_result` NOT NULL L911–L912 |
| | item `timed_out`, `truncated` | boolean | no | |
| | item `error` | null, `spool_overflow`, `runner_unavailable` | yes | |
| | `final` | boolean | no | |
| Results resp | `accepted`, `duplicates` | integer ≥ 0 | no | |
| Inventory | `os_info.os_id` 0–32, `os_version_id` 0–16, `os_pretty_name` 0–128, `kernel_release` 0–64, `architecture` 0–16 | string | yes | L782–L786 |
| | `os_info.cpu_count`, `memory_mb` | integer 0–2^31−1 | yes | INTEGER L787–L788 |
| | `os_info.ip_addresses` | array of 0–256 strings, each an IPv4 or IPv6 address with an optional `/prefix` (PostgreSQL `INET` input) | no | INET[] L789 |
| | `os_info.uptime_s` | integer 0–2^63−1 | yes | BIGINT L790 |
| | `os_info.raw` | JSON object; serialised compactly in UTF-8 at most 256 KiB (413 above, #72) | no | JSONB L791 |
| | `packages` | array of 0–50,000 items (422 above, #72) | no | |
| | item `name` 1–255, `version` 1–255, `architecture` 1–16, `status` 1–64 | string | no | L797–L799, L809 |
| | item `source` | string 0–255; empty string stored as NULL | yes | `source_name` L800 |
| | item `installed_size_kb` | integer 0–2^31−1 | yes | INTEGER L810 |
| | `list_sha256` | 64 characters `[0-9a-f]` | no | CHAR(64) L820 |
| Rotate | request | no body (an empty body or `{}`); anything else 400 | | |
| | response | `agent_token`, `issued_at`, `expires_at` as for Enrol | no | |

The inventory model is used by the decoder (TASK-060) after decompression and for the OpenAPI document; the route itself reads the raw stream (TASK-074). Its byte limits are not schema constraints.

## Interface

```python
# bm/api/agent/__init__.py
AGENT_PROBLEM_TYPES: Final = frozenset({"pending_approval", "enrollment_rejected", "token_revoked",
    "token_expired", "machine_id_mismatch", "job_not_acceptable", "too_large", "rate_limited"})
# plus the #59 generic values used on agent routes (unauthorized, forbidden, invalid_request, about:blank)

# bm/api/agent/schemas.py  (Pydantic v2)
class EnrolRequest(BaseModel): ...        ; class EnrolResponse(BaseModel): ...
class HeartbeatRequest(BaseModel): ...    ; class HeartbeatResponse(BaseModel): ...   # exactly 3 fields
class InventoryJob(BaseModel): kind: Literal["inventory"]; ...                           # exactly 4 fields
class PluginSpec(BaseModel): plugin_uuid: UUID; execute: str; timeout_s: int
class ComplianceJob(BaseModel): kind: Literal["compliance"]; plugins: list[PluginSpec]; redaction_patterns: list[str]; ...
Job = Annotated[InventoryJob | ComplianceJob, Field(discriminator="kind")]
class JobsResponse(BaseModel): jobs: list[Job]
class ResultItem(BaseModel): ...          ; class ResultsRequest(BaseModel): results: list[ResultItem]; final: bool
class ResultsResponse(BaseModel): accepted: int; duplicates: int
class OsInfo(BaseModel): ...              ; class PackageItem(BaseModel): ...
class InventoryBody(BaseModel): os_info: OsInfo; packages: list[PackageItem]; list_sha256: str
class RotateResponse(BaseModel): agent_token: str; issued_at: UtcDatetime; expires_at: UtcDatetime
```

Response models also use `extra="forbid"`, so `model_json_schema()` emits `additionalProperties: false` and the Go agent can refuse unknown keys. The compliance variant exists now only so the OpenAPI document holds it from M3 on (TASK-073 references `JobsResponse`); nothing in M3 builds one.

## Edge cases

- `kind` is the discriminator: a body with `kind: "inventory"` and a `plugins` key fails (extra key), so the inventory variant can never carry commands.
- No model anywhere in `api/agent/` has a field named `operator`, `expected_result`, `expected` or `eval_spec` (G30 plant CHK-M3-346).
- Integer fields refuse booleans and floats (`strict` for ints), so `true` is not 1.
- `runner_helpers` duplicates are refused (set semantics); order is kept as sent for storage.
- The heartbeat `clock` may be far off (that is what the skew alert detects): it is validated as a timestamp only, never compared to bound acceptance.
