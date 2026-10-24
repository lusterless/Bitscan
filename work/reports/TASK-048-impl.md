# TASK-048 IMPL report: agent wire contract (Pydantic models, problem types)

REQ: REQ-060, REQ-088. Spec: TS §6.5 L1159–L1190, §6.1 L1060–L1072, §3.5 L248 and L253, §6.3 L1139, §5.2 (column sizes); #59, #60 (the plan's field table, agreed 2026-10-23). Plan: `work/plans/TASK-048.md`. This task needs **two approvals** (agent contract).

## Files (2)

- `manager/bitscan_manager/api/agent/__init__.py`: new, 29 lines. It holds only the package docstring and two constants. The router comes in TASK-063.
  - `AGENT_PROBLEM_TYPES`: the eight TS §6.5 L1190 values.
  - `AGENT_GENERIC_PROBLEM_TYPES`: `unauthorized`, `forbidden`, `invalid_request`, `about:blank` (#59).
- `manager/bitscan_manager/api/agent/schemas.py`: new, 305 physical lines (236 code). Over the 190 estimate; a ruling was asked of the lead.

## Models (all `extra="forbid"`, so every JSON Schema has `additionalProperties: false`)

| Route | Request | Response |
| --- | --- | --- |
| `POST /agent/enroll` | `EnrolRequest` | `EnrolResponse` |
| `POST /agent/{id}/heartbeat` | `HeartbeatRequest` | `HeartbeatResponse`, exactly 3 fields |
| `GET /agent/{id}/jobs` | none | `JobsResponse {jobs: list[Job]}`, `maxItems` 10 (TS §6.1 L1064) |
| `POST /agent/{id}/jobs/{job_id}/results` | `ResultsRequest` (≤ 50 `ResultItem`) | `ResultsResponse` |
| `PUT /agent/{id}/inventory` | `InventoryBody` (`OsInfo`, ≤ 50,000 `PackageItem`) | 204 |
| `POST /agent/{id}/token/rotate` | `RotateRequest` (empty: `{}` only) | `RotateResponse` |

`Job` is a discriminated union on `kind`: `InventoryJob` has exactly `job_id`, `agent_id`, `kind`, `pickup_by`, and `ComplianceJob` has those four plus `plugins` (`PluginSpec`: exactly `plugin_uuid`, `execute`, `timeout_s`) and `redaction_patterns`. An inventory job sent with a `plugins` key is refused as an extra key. No model has an `operator`, `expected_result`, `expected` or `eval_spec` field.

## Field rules (#60 table; every rule also appears in the JSON Schema)

**Types:**
- Strict scalars: `StrictInt`, `StrictBool`, `StrictStr`. `true` is not an integer, `1.0` is not an integer, `"1"` is not an integer, and `1` is not a boolean.
- Timestamps (`Timestamp`): accept an aware `datetime`, or a string matching RFC 3339 with an explicit offset (`T` and `Z` may be lower case; at most 9 fraction digits). Input is normalised to UTC; output is `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
  - Refused: naive values, date-only values, Unix numbers or digit strings, impossible dates such as 30 February, and out-of-range results such as `0001-01-01T00:00:00+01:00`, which is refused rather than raising.
  - Schema: `{"type": "string", "format": "date-time", "pattern": …}`. The pattern checks every field's range: month 01–12, day 01–31, hour 00–23, minute and second 00–59, offset hours 00–23 and minutes 00–59.
- UUIDs (`AgentUuid`): hyphenated 8-4-4-4-12 hex, either case. No braces, no URN, no 32-character form. Serialised lowercase.

**Formats (all checked with RE2):**
- `machine_id`: `^[0-9a-f]{32}$`.
- `list_sha256`: `^[0-9a-f]{64}$`.
- `agent_token`: `^bsa_[A-Za-z0-9_-]{43}$`.
- `runner_helpers`: 0–8 distinct strings matching `^[a-z][a-z0-9_-]{0,31}$`. The schema adds `uniqueItems: true`, and the order sent is kept.
- `ip_addresses`: 0–256 strings, each an IPv4 address or one of the standard IPv6 text forms, with an optional prefix (/0–32 or /0–128). The schema has the same pattern. The model also passes each value through `ipaddress.ip_interface`, so a probe of 200,000 random strings found nothing the pattern accepts that Python refuses. The pattern is a subset of what Python accepts; for example `1::2:1.2.3.4` and zone ids (`fe80::1%eth0`) are refused by both the model and the schema.

**Lengths and ranges:** code points, from the column sizes in the plan's table (hostname 1–255, versions 1–32, `os_*` 0–32/16/128, `last_error` 0–1,024, package fields 1–255/1–255/1–16/1–64, `source` 0–255).
- Integers: `uptime_s` and `spool_bytes` 0..2^63−1; `cpu_count`, `memory_mb` and `installed_size_kb` 0..2^31−1; `exit_code` −2^31..2^31−1; `timeout_s` 1–600.
- Heartbeat response: `job_pull_seconds` 60–3,600, `max_parallel_plugins` 1–8.
- `plugins` 1–5,000 items; `redaction_patterns` 0–50; `results` 0–50.

**Nullability:** nullable keys are **required but may be null** (ruling asked). They are `os_id`, `os_version_id`, `os_pretty_name`, `last_pull_at`, `current_job_id`, `last_error`, `exit_code`, `error`, the `os_info` scalars, `source` and `installed_size_kb`.

**Other:** `raw` is any JSON object; its 256 KiB limit belongs to the decoder (TASK-060). `error` is one of null, `spool_overflow`, `runner_unavailable`.

## Local gates (Windows)

- `ruff check manager`, `ruff format --check manager` and `mypy --strict --config-file manager/pyproject.toml manager`: pass.
- `pytest -q`: 1033 passed, 451 skipped at the time of this task.
- OpenAPI re-export: byte-identical. No route uses the models yet; TASK-063 onwards attach them.
- **Your TP-M3-01 fixtures** (224 files, `manager/tests/contract/fixtures/`), checked read-only by a scratch script:
  - every fixture validated with its manifest model gives exactly its `valid` flag: **0 mismatches**;
  - every fixture validated against `model_json_schema()` with `jsonschema` (Draft 2020-12) also matches: **0 mismatches**.

  The first run had one schema mismatch (`heartbeat/request_invalid_clock_bad_month.json`), which the tightened timestamp pattern fixed. The OpenAPI component schemas are not checked here, because no route references the models yet.
- To get `jsonschema` I synced `manager/.venv` to the new dev lock with `uv pip install --require-hashes -r requirements-dev.txt`, which added only the seven TASK-058 pins.
- Scratch probe outside the tree: valid bodies for every route were accepted, and every refusal listed above was refused. A `kind: "inventory"` job with `plugins`, and a compliance job with `operator`, were refused. `model_json_schema()` for `JobsResponse` has both variants with exactly their keys and `additionalProperties: false`. `HeartbeatResponse` has exactly its three properties.

## For the tester (JSON Schema versus model, where JSON Schema cannot match exactly)

1. JSON Schema counts `1.0` as an `integer`; the model refuses it (as Go's `encoding/json` does for an int field). A fixture `"uptime_s": 1.0` passes the schema and fails the model.
2. Python `jsonschema` uses stdlib `re.search` for `pattern`, where `$` also matches before a final `\n`. A value such as `"<32 hex>\n"` passes that schema check and fails the model (RE2 `fullmatch`). Go's RE2 does not have this gap.
3. The timestamp pattern checks field ranges but not the calendar: `2026-02-30T00:00:00Z` passes the schema and fails the model. Month 13, hour 24 and the like fail both.
4. `uniqueItems` is checked by JSON Schema too, so duplicate helpers fail both.

Avoid these four shapes as "invalid in both" fixtures, or mark them model-only.

## Open points sent to the lead (affect the fixtures)

1. Whether nullable keys may be absent; built as required-but-nullable.
2. `jobs` `maxItems` 10 comes from TS §6.1 L1064 and is not in the #60 table.
3. NUL characters and lone surrogates in strings: not refused, since #60 says nothing. PostgreSQL cannot store NUL, so a later task must refuse it, or the contract must.

## Deviations

None pending the lead's ruling on the three points.

## Revision 1 (rulings of 2026-10-23)

The rulings:
- **Nullable fields:** the key is required and its value may be null. Kept as built.
- **`jobs` `maxItems` 10:** kept (lead ruling).
- **UUIDs:** hyphenated form only on input, lowercase on output. Kept as built.
- **Size:** accepted as one task.
- **NUL and lone surrogates:** refused, implemented as follows.

**Change: `manager/bitscan_manager/api/agent/schemas.py` only.**

- `Text = Annotated[StrictStr, AfterValidator(_storable), Field(json_schema_extra={"pattern": NO_NUL_PATTERN})]` is now the type of every free-text string the agent sends.
  - Enrol: `hostname`, `agent_version`, `os_id`, `os_version_id`, `os_pretty_name`.
  - Heartbeat: `agent_version`, `last_error`.
  - `OsInfo`: the five `os_*`, `kernel_release`, `architecture` strings.
  - `PackageItem`: `name`, `version`, `architecture`, `status`, `source`.

  `_storable` refuses U+0000, and any lone surrogate (found by `str.encode("utf-8")` failing; json.loads joins a valid escaped surrogate pair into one code point, so astral characters such as U+1F600 are accepted).
- `OsInfo.raw` gets `_storable_tree`, which walks every string **key and value** at any depth without recursion, through nested objects and arrays. Its schema gains `propertyNames: {"pattern": NO_NUL_PATTERN}`, which covers the top-level keys. Deeper keys and values are refused only by the model, because a pattern cannot express them.
- Pattern-typed strings already exclude NUL through their ASCII patterns: `machine_id`, helpers, `list_sha256`, tokens, INET, UUIDs and timestamps.
- **Not restricted** (ruling): Results `stdout` and `stderr` stay plain `StrictStr` until M9. Manager-sent strings are also unchanged: compliance `execute` and `redaction_patterns`.
- **Schema:** `NO_NUL_PATTERN` is `^[^\x00]*$`, written with the `\x00` escape, which ECMA-262, Python `re` and Go RE2 all read the same way. A surrogate range cannot be written portably (RE2 has no surrogates), so **lone surrogates are model-only**: a fixture holding one passes the JSON Schema and fails the model.
- **Status:** a refusal is a validation error, so on a route it becomes 400 `invalid_request` through the existing handler. For TASK-060: the plan maps `InventoryBody` model failures to 422. The ruling makes NUL and lone surrogates 400 instead, so the decoder must tell these apart from the length and type failures.
- A raw NUL byte briefly entered the source file during the edit (an escaping slip in my edit script), and was replaced by the `\x00` escape before hand-off. The file has no NUL bytes.

**Gates (Windows):**
- ruff, ruff format and `mypy --strict` pass (143 files).
- `pytest -q`: 1866 passed, 610 skipped.
- Your 244 fixtures (Q2 and Q3 cases included): 0 model mismatches and 0 schema mismatches.

**Probe:**

| Input | Model | JSON Schema |
| --- | --- | --- |
| hostname with NUL | refused | refused |
| hostname with a lone surrogate | refused | accepted (model-only, as above) |
| hostname with an emoji | accepted | accepted |
| NUL in a nested `raw` value | refused | |
| NUL in a top-level `raw` key | refused | |
| lone surrogate in a deep `raw` key | refused | |
| a `raw` value 500 levels deep holding NUL | refused | |
| NUL in Results `stdout`, lone surrogate in `stderr` | accepted (until M9) | |
- **Addendum to revision 1:** the `raw` schema also gains `additionalProperties: {"pattern": NO_NUL_PATTERN}`, so a NUL in a **top-level string value** fails the schema too. Non-string values are unaffected, because `pattern` applies only to strings.
- **Model-only cases** (by design: a pattern cannot express them, so the schema accepts and the model refuses):
  - lone surrogates in any string (4 of your fixtures);
  - NUL in a `raw` key or value below the top level (2 fixtures).

  They are what your `test_model_json_schema_agrees` reports: 6 failing, 534 passing.
- OpenAPI export: unchanged, since no route uses `OsInfo` yet.

### Revision 1, round 2 (lead rulings 2026-10-23, after CHK-M3-012-r1 FAIL)

The two rulings:
- **Lone surrogates** are model-only. No schema change; the tester expects the schema to accept them.
- **NUL anywhere in `os_info.raw`** is now refused by the schema too, at every depth, for keys and values.

The `raw` schema (`RAW_JSON_SCHEMA` in `schemas.py`) is a recursive node in its own embedded resource:

```json
{"type": "object",
 "allOf": [{"$dynamicRef": "urn:bitscan:agent:os-info-raw-node#node"}],
 "$defs": {"node": {"$id": "urn:bitscan:agent:os-info-raw-node", "$dynamicAnchor": "node",
                    "pattern": "^[^\x00]*$",
                    "items": {"$dynamicRef": "#node"},
                    "propertyNames": {"pattern": "^[^\x00]*$"},
                    "additionalProperties": {"$dynamicRef": "#node"}}}}
```

How it works:
- `pattern` applies only to strings, `items` only to arrays, and `propertyNames` and `additionalProperties` only to objects, so numbers, booleans and null pass at any depth.

Why `$dynamicRef` rather than `$ref`:
- pydantic processes every `$ref` in a generated schema, and raises `KeyError` on one it did not define. So the self-reference uses the Draft 2020-12 `$dynamicRef` to the node's `$dynamicAnchor`.
- There is only one dynamic anchor named `node`, so it resolves exactly as a static `$ref` would.

Where it resolves:
- It is emitted byte-identical in `model_json_schema()` and in a FastAPI OpenAPI document (checked with a scratch app that has an `InventoryBody` route).
- In a validator whose root is the model or component schema (as in `tests/test_contract_agent.py`), the embedded `$id` resource is found by the normal subresource crawl.
- **Note for the OpenAPI-component checks of the route tasks (G30, TASK-074):** if a validator's root resource is the *whole OpenAPI document*, `referencing` does not crawl into `components/schemas`, because they are not schema keywords. The URN is then unresolvable. Register the component schema itself as the resource, or use it as the root.
- Python `jsonschema` 4.26 supports this, and Go's `santhosh-tekuri/jsonschema` supports `$dynamicRef` for M4.

Alternative I tried and rejected:
- A pydantic recursive `TypeAliasType` for `raw`, which would give plain `#/$defs` pointers.
- Rejected because pydantic emits `patternProperties`, which does not refuse a key that fails the pattern.
- Its recursion limit also refuses a `raw` about 400 levels deep with hundreds of errors, which changes what the model accepts.

Gates and checks:
- ruff, ruff format and `mypy --strict` pass (148 files).
- `pytest -q`: 1926 passed, 629 skipped, 0 failed.
- `tests/test_contract_agent.py`: 540 passed, including `nul_raw_top_value`, `nul_raw_nested_value` and `nul_raw_nested_key`.
- OpenAPI export unchanged (no route yet).

### Revision 1, round 3 (lead ruling on the reviewer's should-fix)

The round 2 node (URN `$id` with `$dynamicRef`) is **replaced**, because it does not resolve with `openapi.json` as the root and is poorly supported by kin-openapi, oapi-codegen and openapi-typescript.

The new definition:

```python
RawKey = Annotated[StrictStr, AfterValidator(_storable)]
type RawValue = (Text | StrictInt | StrictFloat | StrictBool | None
                 | list[RawValue] | Annotated[dict[RawKey, RawValue], _NoNulKeys()])
raw: Annotated[dict[RawKey, RawValue], _NoNulKeys()]
```

- **The alias** is the Python 3.12 `type` statement, which is a `typing.TypeAliasType`. Ruff UP040 asks for this form instead of calling `TypeAliasType(...)`, and pydantic treats both the same.
- **`_NoNulKeys`** is a small metadata class that adds `propertyNames: {"pattern": "^[^\x00]*$"}` to each object schema. The keys themselves carry no pattern, so pydantic emits `additionalProperties: {$ref}` rather than `patternProperties`, and `propertyNames` refuses NUL keys.
- **One schema:**
  - `model_json_schema()` holds `$defs/RawValue` with plain `"$ref": "#/$defs/RawValue"`.
  - FastAPI emits `components/schemas/RawValue` with `#/components/schemas/RawValue`.
  - With the reference prefix normalised, the two are identical: checked on a `create_app()` test route.
  - There is no export post-processing.
- **`_storable_tree` is removed.** The alias alone refuses every NUL case: strings through `Text`, keys through `RawKey`.
- **NUL results:**

  | `raw` | Model | Schema |
  | --- | --- | --- |
  | `{"a": "v\0"}` | refused | refused |
  | NUL in a nested value | refused | refused |
  | NUL in a nested key | refused | refused |
  | NUL in a top-level key | refused | refused |
  | lone surrogate | refused | accepted (model-only, as ruled) |
  | `{"a": {"b": [1, 2.5, null, true, "ok", {"d": []}]}}` | accepted | accepted |
  | `{}` | accepted | accepted |

- **Depth limit:** this is pydantic-core's recursion guard, measured on pydantic 2.14.1.
  - Objects: `raw` nested **100 objects deep is accepted, and 101 is refused**.
  - Lists: lists nested 98 deep inside `raw` are accepted.
  - A too-deep `raw` is a validation error, so the route answers **400 `invalid_request`** ("Invalid request: body.os_info.raw: invalid key"), never 500. This was checked through `create_app()`'s handlers on a test route. A NUL in `raw` also answers 400.
  - A different pydantic version could move the limit, so the tester's depth case should pin the behaviour (400 at depth 101) rather than the number alone.
- **Gates:**
  - ruff, ruff format and `mypy --strict` pass (151 files).
  - `tests/test_contract_agent.py` plus `tests/test_contract_fixtures.py`: 628 passed.
  - Full `pytest -q`: 1926 passed, 704 skipped, 0 failed.
  - OpenAPI export unchanged, since no route uses `InventoryBody` yet; TASK-074 will add `RawValue` to `components/schemas`.

### Revision 1, round 3: addendum (reviewer should-fix, and corrected depth numbers)

- **NaN and Infinity (reviewer should-fix):** the float branch of `RawValue` is now `Annotated[StrictFloat, Field(allow_inf_nan=False)]`, because PostgreSQL `jsonb` cannot store NaN or ±Infinity.
  - `raw` holding NaN, Infinity, -Infinity, or `1e400` (which parses as inf) is refused, both through `json.loads` plus the model and through `model_validate_json`, including when nested.
  - 2.5 and 1 are still accepted.
  - This is **model-only**: the JSON Schema says `{"type": "number"}`, and JSON itself has no NaN or Infinity. On a route it answers 400.
- **Depth limit, corrected:** my round 3 numbers counted `raw` itself as level 1, on `OsInfo`. With the tester's helper (`_inventory_with_raw({"top": <depth nested {"k": …} objects>})` on `InventoryBody`), measured on pydantic 2.14.1:

  | Path | Accepted | Refused |
  | --- | --- | --- |
  | `InventoryBody.model_validate` (Python mode, what FastAPI uses for a route body) | depth 98 | depth 99 |
  | `InventoryBody.model_validate_json` (pydantic-core's guard differs by mode) | depth 197 | depth 198 |

  A too-deep body is still a `ValidationError`, so the route answers 400. Pin the behaviour, not the exact number; the decoder (TASK-060) will choose its path.
- **Gates:** ruff, ruff format and `mypy --strict` pass for `bitscan_manager`. The only mypy error is in `tests/test_contract_agent.py:398` (`no-any-return`), which is the tester's file. The OpenAPI export is unchanged.

## Revision 2 (user ruling 2026-10-23: JSON-safe 64-bit bounds)

- **Why:** FastAPI's OpenAPI models type `minimum` and `maximum` as floats. The #60 bound 2^63 − 1 was exported to `openapi.json` as `9.223372036854776e18`, which is exactly 2^63, so the document accepted 2^63 while the model refused it. tester-c's `heartbeat/request_invalid_uptime_2_63` showed this once TASK-072 put `HeartbeatRequest` into the document.
- **Change:** `bm/api/agent/schemas.py` only. The constant `I64 = 2**63 - 1` is replaced by **`JSON_SAFE_MAX = 2**53 - 1`** (9,007,199,254,740,991), the largest integer every JSON implementation holds exactly (RFC 8259 §6). `Count64` now uses it. It bounds heartbeat `uptime_s` and `spool_bytes`, and `os_info.uptime_s`. The 32-bit bounds are unchanged; they are exact as floats.
- **Re-export:** `openapi.json` was re-exported after TASK-072's export and is byte-stable.
- **Agreement check:** every `minimum` and `maximum` of `EnrolRequest`, `EnrolResponse`, `HeartbeatRequest` and `HeartbeatResponse` in `model_json_schema()` equals the exported value exactly, with 0 mismatches. The document shows `maximum: 9007199254740991.0`, exactly 2^53 − 1. `InventoryBody` and `OsInfo` enter the document with TASK-074. For `uptime_s`:

  | Value | Model | Document |
  | --- | --- | --- |
  | 2^53 − 1 | accepted | accepted |
  | 2^53 | refused | refused |
  | 2^63 | refused | refused |

- **Gates:** ruff, ruff format and `mypy --strict` pass.
- **Contract suites:** 652 passed and 5 failed. The 5 are fixtures that still use the old boundary: `heartbeat/request_valid_boundaries` and `inventory/request_valid_max_lengths` (2^63 − 1 is now invalid), and the document test with its 2^63 case. These fixture moves are tester-c's.
