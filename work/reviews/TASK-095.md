# TASK-095 REVIEW: dpkg list and the inventory body

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.** Reviewed under the drain, as the review already in progress.

Scope reviewed:
- `agent/internal/inventory/dpkg.go` and `agent/internal/inventory/body.go`.
- Checked against TS §3.4 L235 and L240, §6.5 L1186, REQ-100, REQ-101, #72 (a), #77 (d), and the lead rulings Q2 to Q5 of 2026-10-24.

TEST: PASS (`work/reports/TASK-095-test.md`; rows CHK-M4-110 to -114):
- the inventory package passes 112/113 with 1 named skip;
- `-race` passes 66/66;
- both ubuntu:22.04 containers pass 15/15;
- 28/28 plants are red.

## Checks
1. Spec:
   - Each line has six tab-separated fields, as dpkg-query prints them.
   - An empty Source or Installed-Size becomes null.
   - A non-integer size becomes null and is counted (Q3).
   - A line without 6 fields is skipped, and only its count goes into `raw.errors["dpkg_query"]`, never its content (Q4).
   - A dpkg-query failure is an error with no upload (Q2), so an empty list can never wipe a host's packages.
   - Rows are sent exactly as printed, without bound checks: the manager answers 422 and the agent never hides a package (#77 (d), Q5). os_info is still validated strictly.
2. `list_sha256`:
   - It is computed from the lines `name\tversion\tarchitecture\tstatus\n`, sorted by bytes, as TS §6.5 L1186 specifies.
   - It is hashed over the same text that encoding/json sends: invalid UTF-8 bytes are replaced with U+FFFD before hashing. The manager therefore recomputes the same value (CHK-M4-111 against loader.py).
3. **HTML escaping, checked by reading as the lead asked** (one unreproduced `TestBuildBodyRoundTrip` failure, "HTML escaping applied", followed by 23 green runs). `BuildBody` has no nondeterministic path:
   - **One encoder.** `body.go:61-62` is the only encoder of the body, with `SetEscapeHTML(false)`. There is no second `json.Marshal` of the body and no `RawMessage`. `fitRaw` uses its own encoder only to measure size (`osinfo.go:337-338`, also without HTML escaping), and it never writes into the body.
   - **Types with their own MarshalJSON.** `wire.UUID` and `wire.Time` call `json.Marshal` internally, which escapes HTML. encoding/json then compacts their output under the outer encoder's setting. The values of those types cannot contain `<`, `>` or `&`: UUIDs are hex checked by `Validate`, and times match `timeRe` or come from `RFC3339Nano`. No other type in `InventoryBody` has its own marshaller.
   - **Map order.** encoding/json writes map keys sorted, so map order cannot vary between runs. `maps.Clone` and `fitRaw`'s largest-first dropping with ties to the lowest key are deterministic too, and the test's fixture is fixed.
   - **The assertion also fires on any `\u00` escape,** so a control character in the data would trip it as well. The fixture has none.

   I find no product path that could escape `<`, `>` or `&`. The single failure most likely ran against a tree copied mid-edit, before `SetEscapeHTML(false)` was in place. tester-m4b should check the timestamp of that first run's copy against `body.go`'s modification time. If it is not explained that way, re-run the test 200 times under `-count=200 -race` before the M4 gate.
4. Security: no line content enters `raw.errors` or any error (canary `CANARY-badline` test). The body is gzip at the default level, as #72 (a) says, and the caller sets `Content-Encoding: gzip` (TASK-104).
5. Scope: 2 files, about 170 lines.

## Findings
None blocking.
1. nit, `dpkg.go:57-58`. `strconv.ParseInt` accepts a leading `+` or `-`. The extra `strings.Trim(f[5], "0123456789") == ""` check therefore refuses any sign, so only plain decimal digits count as a size, and `-5` and `+5` become null and are counted. That is correct for dpkg's Installed-Size. A short comment saying why the second check is there would help the next reader.
