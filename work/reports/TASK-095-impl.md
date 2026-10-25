# TASK-095 IMPL: dpkg list parser, `list_sha256`, gzip inventory body

REQ-100, REQ-101. TS §3.4 L235, L240; §6.5 L1186. #72, #77; lead rulings 2026-10-24 "TASK-094/095" Q2–Q5. **Two approvals (TS §8.2, agent).** No tests were run (tester's job).

## Files (new)

| File | Code lines (approx.) | What |
| --- | --- | --- |
| `agent/internal/inventory/dpkg.go` | 77 | `Packages{Items, BadLines, BadSizes}`, `ListPackages(ctx)`, `ParseDpkg(out)`, `ListSHA256(items)`. |
| `agent/internal/inventory/body.go` | 62 | `CollectBody(ctx) ([]byte, error)` and `BuildBody(info, pkgs) ([]byte, error)`. |

`body.go` calls `fitRaw` and uses `dpkgQueryCmd` from TASK-094's `osinfo.go` and `command.go`. The `agent/.golangci.yml` G204 exclusion (TASK-094) covers `command.go` only; lint found nothing in these two files.

## Behaviour

- **Parse:** split on `\n`, ignoring the empty piece after the final newline, then split on `\t` into exactly 6 fields. Any other count is skipped and counted (Q4). An empty `Source` becomes null. An empty `Installed-Size` becomes null. An `Installed-Size` that is not plain decimal digits (or overflows int64) becomes null and is counted, and the row is still sent (Q3). Digits above 2^31−1 are sent as they are. Bytes that are not valid UTF-8 are replaced, one U+FFFD per byte, which is exactly what `encoding/json` would send. As a result `list_sha256` is computed over the text the manager receives.
- **`ListPackages` (Q2):** any failure of dpkg-query (not found, failed, timed out, over 16 MiB, or `ctx` ended) returns an error, and the caller uploads nothing.
- **`list_sha256`:** the lines `name\tversion\tarchitecture\tstatus\n` sorted with `bytes.Compare`, concatenated, SHA-256, lowercase hex. This matches `manager/bitscan_manager/services/inventory/decode.py` `list_sha256`.
- **Body (Q5):** `raw.errors["dpkg_query"] = "<N> lines not in the 6-field format"` and `raw.errors["installed_size_kb"] = "<N> values not a decimal integer"` are added when nonzero. The caller's map is cloned, not modified. Then `fitRaw` runs again, and `os_info` is checked strictly with `wire.Validate`. Package rows are not bound-checked, so the manager answers 422. The body is compact JSON with HTML escaping off and no trailing newline, gzip at the default level. A nil package list is sent as `[]`. The `Content-Encoding: gzip` header is TASK-104's.
- Real outputs: Ubuntu 22.04 and 24.04 only (Debian 12 dropped by the user, 2026-10-24).

## Checks run (Windows, golangci-lint 2.14.0)

`gofmt -l agent` prints nothing. `GOOS=linux go vet` and `golangci-lint run` (GOOS=linux and windows) over every package except `internal/agent/enrol` (impl-agent's in-progress TASK-098 file does not compile yet): 0 issues. `CGO_ENABLED=0 GOOS=linux go build ./internal/inventory/` succeeds.

## For the tester

TP-M4-10; CHK-M4-350. `ParseDpkg` and `ListSHA256` are exported, so the cross-check with the manager decoder's fixtures can call them directly.
