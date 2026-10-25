# TASK-086 IMPL: agent wire types and strict decoding

REQ-091. TS §6.5 (L1159–L1190); `manager/openapi.json` agent components; the #60 field table (`work/plans/TASK-048.md`) with the 2026-10-23 rulings; plan `work/plans/TASK-086.md`. **Two approvals (TS §8.2, agent).**

**Size:** about 470 non-comment lines in 2 files, against an estimate of 190. The lead ruled on 2026-10-24 (`work/decisions.md`, "M4 W1 lead rulings") that it stays one task, as TASK-048 did. About 130 of those lines are the contract structs with their bound tags.

No tests were run (that is the tester's job). Before the hand-off I ran a throwaway copy of the package outside the tree against every manifest fixture (details below). It is deleted, and nothing from it is in the tree.

## Files (new; no other file touched)

| File | What |
| --- | --- |
| `agent/internal/agent/wire/wire.go` | The contract types: `EnrolRequest`, `EnrolResponse`, `HeartbeatRequest`, `HeartbeatResponse`, `JobsResponse`, `Job` (inventory or compliance), `PluginSpec`, `ResultsRequest`, `ResultItem`, `ResultsResponse`, `InventoryBody`, `OsInfo`, `PackageItem`, `RotateRequest`, `RotateResponse` and `Problem`. Also the format types `UUID`, `Time`, `AgentToken`, `MachineID`, `SHA256Hex`, `HelperName`, `IPAddress`, the enums `EnrolStatus`, `JobKind`, `ResultError` and their constants. |
| `agent/internal/agent/wire/decode.go` | `DecodeStrict[T]`, `Validate`, `Encode` and `DecodeProblem`, plus the shape walk and the RawValue walk. |

## API for later tasks

```go
func DecodeStrict[T any](body []byte, v *T) error // responses (and requests, in tests)
func Validate(v any) error                         // bounds, formats, variants
func Encode(v any) ([]byte, error)                 // Validate, then JSON (no HTML escaping, no trailing newline)
func DecodeProblem(body []byte) (Problem, error)   // lenient; an empty type becomes "about:blank"
func NewTime(t time.Time) Time; func (Time) Time() time.Time
```

- **Nullable keys are pointers** (`*string`, `*int64`, `*Time`, `*UUID`, `*ResultError`). Every key is always encoded, with `null` for a nil pointer, and no json tag drops empty values.
- **A non-pointer slice or map must not be nil.** `Validate` and `Encode` refuse a nil `runner_helpers`, `ip_addresses`, `packages`, `results`, `jobs` or `raw`, because it would encode as `null`. Builders must use `[]T{}` or `map[string]any{}`.
- **`Time`:** decoding checks the schema's RFC 3339 pattern (offset required, 1–9 fraction digits, `T`/`t` and `Z`/`z`), then `time.Parse`. A decoded value keeps its text, so it re-encodes unchanged (fixtures with `+08:00` stay JSON-equal). `NewTime` values are sent in UTC with `Z` (RFC3339Nano).
- **`UUID`:** the hyphenated 8-4-4-4-12 form only. Either case is accepted on input, and the value is held and sent in lowercase. The lead's ruling "a job whose `agent_id` is ours in upper case is ours" therefore holds with a plain `==` after decoding.
- **`AgentToken`:** `String` and `GoString` print `bsa_[redacted]`, so `%v`, `%s`, `%+v` and `%#v` never show the token, including inside a struct (checked in the scratch run). Use `string(tok)` only for the header and the state file. JSON encoding still writes the real value.
- **`Job`:** `plugins` and `redaction_patterns` (tag `only=compliance`) must be present exactly when `kind` is `compliance`. A compliance job needs at least 1 plugin, and an inventory job has neither key.
- **`OsInfo.Raw` (`map[string]any`)** may hold only `map[string]any`, `[]any`, `string`, `json.Number`, `float64`, `int`, `int64`, `bool` and `nil`. Any other Go type is refused as "unsupported value type" (TASK-094 must build `raw` from these). The rules: no U+0000 in keys or strings, finite numbers only (`1e400` is refused), and at most 32 container levels counted from the body root. That is the manager's `MAX_DEPTH` rule in `services/inventory/decode.py`: 32 levels are accepted and 33 refused (checked in the scratch run).
- **U+0000** is refused in every string except `stdout`, `stderr`, `execute` and `redaction_patterns`, which have no NUL pattern in the schema (results until M9, TASK-048 plan).
- **Not checked by `Validate` (lead ruling 2026-10-24):** the `list_sha256` value, duplicate packages and the 256 KiB `raw` cap. The hash-mismatch, duplicate-package and over-256-KiB fixtures therefore decode and re-encode like any valid fixture. The `raw` size cap is the collector's job (TASK-094, #77 (d)).

## How strict decoding works

1. `checkShape` walks the raw JSON alongside the Go type. Objects must have exactly their struct's keys: an unknown key, a missing key (nullable ones included) and an `only=` key under the wrong `kind` are all refused. `null` is allowed only for pointer fields. Arrays and objects must have the right JSON kind. The top-level `json.Unmarshal` also refuses trailing data.
2. A `json.Decoder` with `UseNumber` fills the struct. Go refuses `1.0`, `1e3`, a bool or a string for an integer field, and a negative or oversized value fails where Go's int range does.
3. `Validate` reads the `wire` tags: `min`/`max` (code points for strings, items for arrays, value for integers), `nul`, `uniq` and `only`. It also calls each named type's `check()`, which holds the schema's regexes (copied verbatim from `openapi.json`, `ip_addresses` included, so `fe80::1%eth0` is refused) and enums, plus the `Job` variant rule.

Error text is fixed words plus a path built from the Go field names (for example `wire: body.os_info.ip_addresses[]: bad format`). It never includes a value, except that a JSON syntax error or `time.Parse` error from the standard library may quote the offending character or text of the manager's answer. None of it can contain a token, because tokens are never in an error path.

## Scratch run against the fixtures (evidence, not a test)

A copy of the package in a temporary module ran every `manifest.json` fixture through its type, generating the `generate` entries as the manifest describes (`raw_bytes` skipped). Results:

- Every valid fixture decodes, and every valid request re-encodes to JSON that is `reflect.DeepEqual` to the fixture's.
- Every invalid fixture is refused, except the four `schema_gap: "lone surrogate"` files (Go decodes `\ud800` as U+FFFD), which the manifest allows.
- All eight `nan_inf` files are refused: NaN and Infinity as JSON syntax errors, and `1e400` by the finite-number rule (`wire: body.os_info.raw: number not finite`), because Go's scanner accepts `1e400` as number syntax. **Tester:** if TP-M4-01 asserts a parse error by its type (`*json.SyntaxError`), the two `1e400` files fail that check. They are refused by `DecodeStrict` either way.
- REQ-091 (3): an upper-case `agent_id`, `…T12:00:00.000000Z` and lowercase `t`/`z` are accepted. An extra key and trailing data are refused.

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l .`: prints nothing.
- `go vet ./...`, and `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./...` and `go build ./...`: clean.
- `GOOS=linux golangci-lint run ./...` (2.14.0): `0 issues`.
- `grep -rn omitempty agent/internal`: nothing, and no `//nolint`.

## Builder checklist

Items 1–3, 5 and 6 are covered by the decoder rules above: U+0000, the IPv6 zone and `NaN` are refused, the integer bounds are at most 2^53 − 1, the UUID form is hyphenated only, and the case-insensitive parts are UUIDs and the RFC 3339 `T`/`Z`. Items 11 and 12: the token never prints and error text is fixed. The other items (route order, DB concurrency, OpenAPI export) do not apply to this package.

## For the tester (TP-M4-01, G35)

- The jsonschema validator (PD-25, test-only) arrives with TASK-087's `go.mod`/`go.sum`.
- Decode requests in the contract test with `DecodeStrict` too: it runs `Validate`, so invalid request fixtures (the over-length, format, NUL and range files) are refused the same way.
- Re-encode with `Encode` (it validates first) and compare as parsed JSON.
- `RotateRequest{}` encodes as `{}`, and `null`, an array and any key are refused.
