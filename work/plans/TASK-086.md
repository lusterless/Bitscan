# TASK-086 plan: agent wire types and strict decoding

REQ-091. Owner: impl-agent. **Two approvals (TS §8.2, agent).** Files: `agent/internal/agent/wire/wire.go`, `agent/internal/agent/wire/decode.go`. Tests: TP-M4-01 (G35, tester), mutation rows CHK-M4-353, 354. Depends on PD-25 for the test-only schema validator.

## Sources (frozen)

- TS §6.5 L1159–L1190; the field table in `work/plans/TASK-048.md` as agreed (#60) and amended on 2026-10-23: nullable keys are required keys whose value may be null; U+0000 and lone surrogates refused in agent-sent strings (Results `stdout`/`stderr` excepted until M9); UUIDs hyphenated RFC 9562 on input, lowercase on output; 64-bit counters 0..2^53 − 1; `raw` inside the decoder's 32-container limit; `JobsResponse.jobs` at most 10.
- `manager/openapi.json` components (`EnrolRequest`, `EnrolResponse`, `HeartbeatRequest`, `HeartbeatResponse`, `JobsResponse` with `InventoryJob` and `ComplianceJob`, `ResultsRequest`, `ResultItem`, `ResultsResponse`, `InventoryBody`, `OsInfo`, `PackageItem`, `RawValue`, `RotateRequest`, `RotateResponse`, `Problem`).
- `manager/tests/contract/fixtures/manifest.json`: the Go test asserts nothing for `schema_gap` entries (`lone surrogate`: Go's `encoding/json` turns `\ud800` into U+FFFD; `nan_inf`: not JSON, and Go refuses `NaN`).

## Interface

```go
package wire

type EnrolRequest struct {
    Hostname     string  `json:"hostname"`
    MachineID    string  `json:"machine_id"`
    AgentVersion string  `json:"agent_version"`
    OsID         *string `json:"os_id"`          // nullable: always present, may be null
    OsVersionID  *string `json:"os_version_id"`
    OsPrettyName *string `json:"os_pretty_name"`
}
type EnrolResponse struct { AgentID UUID; AgentToken string; IssuedAt, ExpiresAt Time; Status string }
type HeartbeatRequest struct {
    AgentVersion string; UptimeS, SpoolBytes Count53; LastPullAt *Time; CurrentJobID *UUID
    LastError *string; RunnerHelpers []string; Clock Time
}
type HeartbeatResponse struct { JobPullSeconds, MaxParallelPlugins int; ServerTime Time }
type Job struct { JobID, AgentID UUID; Kind string; PickupBy Time; Plugins []Plugin; RedactionPatterns []string } // kind-checked
type JobsResponse struct { Jobs []Job }
type ResultItem struct { ... } ; type ResultsRequest struct { Results []ResultItem; Final bool }
type ResultsResponse struct { Accepted, Duplicates int64 }
type InventoryBody struct { OsInfo OsInfo; Packages []PackageItem; ListSHA256 string }
type RotateResponse struct { AgentToken string; IssuedAt, ExpiresAt Time }
type Problem struct { Type, Title, Detail, Instance string; Status int }

type UUID string   // validated 8-4-4-4-12 hex on decode; always lowercase on encode
type Time time.Time // RFC 3339 with offset on decode (fractions allowed); UTC "Z" on encode
type Count53 uint64 // 0..2^53-1

func DecodeStrict[T any](body []byte, v *T) error // unknown key, missing key, wrong type, bound, format -> error
func (r *X) Validate() error                       // the agent's self-check before sending (REQ-091 (2))
```

## Decoding approach

`encoding/json` with `DisallowUnknownFields` refuses extra keys but cannot tell a missing key from `null` or a zero value. `decode.go` therefore decodes each object twice: once into `map[string]json.RawMessage` to check the exact key set of that type (all keys required, nullable ones included), once into the struct; then `Validate()` checks bounds, enums, formats and the inventory/compliance variant rules (an inventory job has no `plugins` or `redaction_patterns` key; a compliance job has both). Numbers are decoded with `UseNumber` so `1.0`, `1e3` and values above 2^53 − 1 are refused as integers, as the schema says. Strings with U+0000 are refused. Only responses are decoded; the agent never decodes its own request bodies except in tests.

Encoding: no `omitempty` anywhere on a contract field (nullable fields encode as `null`); UUIDs lowercase; times in UTC with `Z`; the encoder uses `SetEscapeHTML(false)` so `<`, `>`, `&` reach the manager unchanged (byte-equivalence with fixtures is JSON-equivalence, not text).

## Edge cases

- `pickup_by` comes back as `…T12:00:00.000000Z` (decisions 2026-10-23); `time.Parse(time.RFC3339Nano, …)` accepts it.
- A `Problem` body is decoded leniently (only `type` and `status` are used for classification), because problem bodies are not part of the agent's strict contract.
- `RawValue` is `any` built only from `map[string]any`, `[]any`, `string`, `json.Number`, `bool`, `nil`; the self-check counts nesting from the body root, so `raw` stays inside the decoder's 32-container limit.
