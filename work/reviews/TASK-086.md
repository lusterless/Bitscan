# TASK-086 REVIEW: agent wire types and strict decoding

Verdict: APPROVED

Reviewer: reviewer, 2026-10-24. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed:
- `agent/internal/agent/wire/wire.go` and `agent/internal/agent/wire/decode.go` (`work/reports/TASK-086-impl.md`).
- Checked against TS §6.5 L1159–L1190, the agent components of `manager/openapi.json`, the #60 table, and the rulings of 2026-10-23 and 2026-10-24: 2^53 − 1 counters, hyphenated UUIDs, nullable keys required, NUL refused except results output, nan_inf and lone-surrogate fixtures model-only, and a size of about 470 lines kept as one task.

TEST: PASS from tester-m4 (by message). 20/20 plants are red. The control run is 363/367 with 4 named skips, the lone-surrogate fixtures that the rule says to assert nothing for. Rows CHK-M4-010 to -019 and -013b are in `tests/m4/report.md`.

## Checks
1. Spec conformance. I compared every one of the 16 components with `openapi.json` field by field: required sets, `additionalProperties: false`, string length bounds (counted in code points, as JSON Schema counts them), integer bounds, `maxItems`, `uniqueItems`, enums and the patterns.
   - The UUID, token, machine-id, SHA-256, helper, date-time and IP patterns are copied verbatim.
   - `ComplianceJob` has `minItems` 1. `InventoryJob` has no `plugins` or `redaction_patterns` key.
   - `stdout`, `stderr`, `execute` and `redaction_patterns` carry no NUL pattern, matching the document.
   - `raw` depth is counted from the body root, so `raw` itself is level 3; 32 levels are accepted and 33 refused, as the manager's `MAX_DEPTH` does.
   - No field is invented, and no `omitempty` is used.
2. Security:
   - `AgentToken` prints `bsa_[redacted]` through `String` and `GoString`, while JSON still writes the value. The tester's sweep covers `%v`, `%+v`, `%#v`, `%s` and `%q`, also inside a struct.
   - Error text is fixed words plus field paths. The only standard-library text that can appear is a JSON syntax error, which quotes at most one character of the manager's answer.
   - No `unsafe`, no `//nolint`, no network.
3. Scope: 2 new files. The size was ruled by the lead.
4. Tests: the 276-entry manifest is run through the Go types and checked against the jsonschema/v6 validator (Draft 2020-12, format assertion). There are REQ-091 (3) boundary cases (time forms, UUID forms, trailing data, BOM, case-variant keys), integer-bound tables, problem-body robustness, and the agent-built requests validated against the schema. The 20 plants show the tests can fail.
5. Re-run by the reviewer (Windows):
   - `GOOS=linux go vet ./internal/agent/wire/`: clean.
   - `GOOS=linux golangci-lint run ./internal/agent/wire/...`: 0 issues.
   - `go mod verify`: all modules verified.
   - The contract tests themselves are Linux evidence (tester).
   - `gofmt -l agent` lists only `internal/agent/transport/client_test.go`, the TASK-093 test file that is still in testing. That is outside this task, and I have noted it for TASK-093.

## Findings
1. nit, `decode.go:200`. `Validate` does not look inside `Time`, so a zero `wire.Time{}` in a request (`clock`, `started_at`, `finished_at`) encodes as `0001-01-01T00:00:00Z` and passes the self-check. The manager would read that as a 2,000-year clock skew. Optional fix: have `validate` refuse a zero `Time` that has no decoded text. Otherwise TASK-101 and TASK-103 must always set the value; their tests would catch a missing one.
2. nit, `decode.go:92`. `checkShape` decodes objects into a `map`, so a duplicate key in a manager answer is accepted with last-wins semantics, the same as the manager's own `json` parser. No change; recorded so a later reviewer does not count it as a strictness gap.
