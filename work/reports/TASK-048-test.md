# TASK-048 TEST report: agent wire contract

**Verdict: PASS** (2026-10-23, tester), against the agreed #59 and #60 answers. Two approvals are needed. REQ-060 (1) to (4) at the model level, REQ-061 (3) and (4) for the model and its JSON Schema, REQ-088 (1), (4). Plan checks: CHK-M3-011 to -019. Code tested: `bm/api/agent/__init__.py`, `bm/api/agent/schemas.py` (`work/reports/TASK-048-impl.md`).

## Tests added
- `manager/tests/test_contract_agent.py` (TP-M3-02, G30), drafted before the code existed. It checks every TP-M3-01 fixture against the model and the model's JSON Schema, walks the schema for the Job, heartbeat and results shapes and the forbidden keys, and checks the problem constants and the output form. A document half checks `manager/openapi.json` once agent routes are exported.
- `manager/tests/contract/fixtures/manifest.json`: rotate request model named (`RotateRequest`).

## Commands (L)
- `PY -m pytest tests/test_contract_agent.py tests/test_contract_fixtures.py` → 523 passed. ruff, format and mypy clean.
- Plants (throwaway copies; control 523 passed): 14 of 15 red:
  - CHK-M3-346, CHK-M3-345;
  - the three G30 plants (heartbeat `extra="forbid"` removed, a field renamed, and `operator` = CHK-M3-346);
  - all models open;
  - lax integers;
  - timestamp schema loosened;
  - machine-id case;
  - batch 51;
  - plugins 5,001;
  - patterns 51;
  - `error` enum widened;
  - inventory Job carrying `plugins`;
  - an extra problem type.

  The 15th (`jobs` unbounded) stays green pending main's ruling on `maxItems: 10`.

## Acceptance criteria
- "Every valid TP-M3-01 fixture parses with its model and every invalid one is refused": CHK-M3-011 PASS.
- "the job-pull response's `model_json_schema()` has the two Job variants with exactly the TS §6.5 keys, `additionalProperties: false` and no `operator`, `expected_result` or `eval_spec` property": CHK-M3-013 PASS.
- "the heartbeat response schema has exactly its three keys": CHK-M3-014 PASS.

## Notes for M4 (the Go side of G30), from the impl report and confirmed here
- JSON Schema counts `1.0` as an integer and the model does not. Python `jsonschema` `pattern` lets `$` match before a trailing newline, and Go RE2 does not. Calendar validity (30 February) is in the model and in my format checker, not in the schema pattern. No fixture uses these shapes as "invalid in both"; the Go tests should assert formats the same way.
- Pending main: nullable keys required versus optional (built required-but-nullable); `jobs` maxItems; NUL characters in strings.

## Revision 1 re-test (2026-10-23): PASS (round 2) — SUPERSEDED
- Superseded by round 3 (lead, 2026-10-23): the `$dynamicRef` form is replaced by a plain `$ref` to `RawValue` (reviewer should-fix). Kept for the record; the round-3 re-test replaces it.
- Round 1 FAIL (CHK-M3-012-r1): 7 invalid fixtures passed the schema. Main ruled lone surrogates model-only; NUL in `raw` had to fail the schema.
- 21 NUL and lone-surrogate fixtures plus 3 valid ones were added. The manifest has 265 entries, with `schema_gaps` documenting the lone-surrogate gap for M4, and the schema test now expects schema acceptance for those 4.
- Round 2: the recursive `raw` node refuses NUL at every depth. 634 passed. 4 recursion plants red, and the round-1 plants (CHK-M3-048-open, the 10-job bound, the Q2 optional-key plants, the NUL removed from the `Text` model or from `raw`) red.
- M4 notes:
  - the Go validator needs Draft 2020-12 `$dynamicRef`;
  - lone surrogates are model-only;
  - the round-1 M9 note: a lone surrogate in Results `stdout` can reach Python through `json.loads`.

## Revision 1 re-test, round 3 (2026-10-23): PASS
- `raw` is a recursive `RawValue` (plain `$ref`). NUL in keys and values is refused by model and schema at every depth.
- Model-only per main's rulings: lone surrogates (4 fixtures), and NaN, ±Infinity and 1e400 (8 fixtures; not strict JSON). Both are documented in `manifest.json` `schema_gaps` for M4.
- Depth: a too-deep `raw` is always a ValidationError and a 400 on a route, never a 500. The behaviour is pinned, not pydantic's numbers. Even 200,000-level bodies give 400.
- 656 passed. All 6 round-3 plants red. Rounds 1 and 2 are superseded.
