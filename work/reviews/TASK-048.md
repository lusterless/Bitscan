# TASK-048 REVIEW: agent wire contract (Pydantic models, problem types)

Reviewer: reviewer. Date: 2026-10-23. REQ-060, REQ-088. Spec: TS §6.5 L1159–L1190 (bodies, Job variants, error types), §6.1 L1060–L1072 (six routes, at most 10 jobs), §3.5 L248 and L253 (Operator and ExpectedResult stay on the manager; batches of 50), §6.3 L1139 (RFC 3339 UTC, UUIDs), §8.3 L1277 (schemas shared with the Go agent); #59, #60. Rulings (`work/decisions.md`, 2026-10-23):
- nullable keys are required and may be null;
- `jobs` `maxItems` 10;
- NUL and lone surrogates are refused in every agent-sent string, `os_info.raw` keys and values included, except Results `stdout`/`stderr` (M9);
- UUIDs are hyphenated only;
- size accepted;
- the recursive `raw` schema uses a plain `$ref` (round 3, on my should-fix);
- lone surrogates and NaN/Infinity are model-only.

Inputs:
- `work/reports/TASK-048-impl.md`: round 1, revision 1 rounds 2 and 3, and the addendum;
- `work/reports/TASK-048-test.md`: PASS, then the revision re-tests. The round-3 re-test PASS covers CHK-M3-012-r3 and -012-depth.

Files reviewed:
- `manager/bitscan_manager/api/agent/__init__.py` (the problem-type constants);
- `manager/bitscan_manager/api/agent/schemas.py` (363 lines);
- the tester's `test_contract_agent.py`, `test_contract_fixtures.py` and `tests/contract/fixtures/`.

Verdict: APPROVED (round 3)

**Two approvals required** (TS §8.2; agent contract). This is the first one; the user's second approval is still needed.

## What was checked

- **Spec conformance.**
  - Each of the six routes has models with exactly the TS §6.5 keys, and every model has `extra="forbid"`, so every object schema has `additionalProperties: false`.
  - `Job` is a `kind`-discriminated union. The inventory variant has exactly `job_id`, `agent_id`, `kind`, `pickup_by`, so a `plugins` key is refused. The compliance variant adds `plugins` (exactly `plugin_uuid`, `execute`, `timeout_s`) and `redaction_patterns`. No reachable schema has `operator`, `expected_result`, `expected` or `eval_spec` (TS §3.5, CHK-M3-346).
  - The heartbeat response has exactly three keys (REQ-060 (2)). A Results item has the nine L1184 keys, `error` ∈ {null, `spool_overflow`, `runner_unavailable`}, and at most 50 items.
  - `AGENT_PROBLEM_TYPES` is exactly the eight L1190 values, plus the #59 generic set.
  - Field limits follow the #60 table. Integers and booleans are strict. Timestamps need an offset and are written as UTC `Z`. UUIDs are hyphenated, and the formats are checked with RE2.
- **Revision 1 (the rulings).**
  - `Text` (StrictStr + `_storable` + `^[^\x00]*$`) is used on every agent-sent free-text field. It refuses U+0000 in both model and schema, and lone surrogates in the model.
  - `raw` is `dict[RawKey, RawValue]`, where `RawValue` is a recursive `type` alias. Pydantic emits it as `$defs/RawValue` with plain `$ref`s, which FastAPI writes as `components/schemas/RawValue`.
  - `propertyNames` refuses NUL keys at every depth in the schema too. There is no `$dynamicRef`, no embedded `$id` and no export post-processing (checked: none appear in `model_json_schema()`).
  - The float branch has `allow_inf_nan=False`, so `NaN`, `Infinity` and `1e400` are refused (model-only, as ruled) and cannot reach `jsonb` as a 500.
  - A pathologically deep `raw` is a validation error, which answers 400, never 500 (CHK-M3-012-depth).
  - Results `stdout`/`stderr` stay plain `StrictStr`, per the ruling.
  - The source file has no NUL byte.
- **Security invariants (REQ-088).** No request model has `command`, `script`, `execute` or `plugins`; only the compliance Job response has `execute`. Nothing in a heartbeat response can carry a job. No signing or other mechanism was added.
- **Scope.** Two files. Size is accepted by the lead.
- **Tests (my run, Windows).** `test_contract_agent.py`, `test_contract_fixtures.py`, `test_token_check.py` and `test_openapi.py`: 711 passed. ruff and format are clean on `bitscan_manager` and `tests`, and `mypy --strict` is clean (152 files). The OpenAPI re-export is byte-identical. The fixtures were written from TS §6.5 and #60, not from the code, and every fixture is checked against both the model and its JSON Schema. The model-only gaps (lone surrogates, NaN/Infinity, `1.0` as an integer, calendar validity) are listed in the manifest's `schema_gaps` for M4.

## Findings

1. **should-fix (resolved in round 3)**, `schemas.py` (round 2 `raw` node). The recursive `raw` schema used an embedded URN `$id` with `$dynamicRef`/`$dynamicAnchor`. It did not resolve with `openapi.json` as the validation root, and Go Draft 2020-12 validators and OpenAPI tools (kin-openapi, oapi-codegen, openapi-typescript) handle it poorly, which put REQ-061 for the M4 Go agent and G16 at risk. It is now the plain `$ref` `RawValue` alias.
2. **should-fix (resolved in round 3)**, `schemas.py` (`RawValue` float branch). `NaN`, `Infinity` and `1e400` were accepted in `raw`. PostgreSQL `jsonb` cannot store them, so such an upload would have answered 500 instead of 400 (#59). It now has `allow_inf_nan=False`.

## Carry-overs

- **TASK-074 TEST (lead ruling).** Once the inventory route is exported, CHK-M3-016 must validate the `raw` fixtures, nested NUL keys and values included, against `components/schemas/RawValue` with the whole `openapi.json` as the validation root. That run is what proves the schema resolves for an OpenAPI-rooted validator, as the M4 Go agent will use it.
- **TASK-060.** NUL, lone-surrogate and NaN refusals are model validation errors and answer 400 `invalid_request` (ruling). The decoder must keep them apart from the #72 422 cases (length, count, duplicates, hash).
- **TASK-063/067/072/073/074/075.** Each route task re-runs CHK-M3-016/-017 (document half, no 422) and G6.
- **M9.** Results `stdout`/`stderr` can still carry NUL or a lone surrogate. The storage rule is decided with result intake.

## Revision 2 (2026-10-23, user ruling: JSON-safe 64-bit bounds)

Verdict for revision 2: APPROVED. Reviewed with TASK-072.

- **Why.** FastAPI exports `minimum` and `maximum` as floats, so the #60 bound 2^63 − 1 appeared in `manager/openapi.json` as `9.223372036854776e18`, which is exactly 2^63. The document then accepted `uptime_s = 2^63`, which the model refuses, so model and document disagreed and REQ-061 failed for the Go agent.
- **Change.** In `schemas.py` only, `I64 = 2**63 - 1` is replaced by `JSON_SAFE_MAX = 2**53 - 1` (9,007,199,254,740,991, exact in every JSON implementation, RFC 8259 §6). `Count64` now uses it, so it bounds heartbeat `uptime_s` and `spool_bytes`, and `os_info.uptime_s`. The 32-bit bounds are unchanged and exact as floats. No column is affected: the heartbeat fields are dropped (#25), and `os_info.uptime_s` is `BIGINT`, which 2^53 − 1 fits.
- **Checked.**
  - The exported `uptime_s` is `{"minimum": 0.0, "maximum": 9007199254740991.0, "type": "integer"}`, exactly 2^53 − 1.
  - My re-export is byte-identical.
  - The fixtures moved: 2^53 − 1 is valid, while 2^53 and 2^63 are refused in both the model and the document (tester-c, tester-d).
  - `mypy --strict` and ruff are clean.
- **nit.** The name `Count64` no longer describes its bound. `CountJsonSafe` (or similar) would read truer, but it is optional.
- **Carry-over (M4).** The Go agent must send these counters within 0..2^53 − 1. A 64-bit uptime or spool size larger than that would be refused, which is unrealistic in practice.
