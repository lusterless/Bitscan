# TASK-086 TEST: agent wire types and strict decoding

**Verdict: PASS.** REQ-091; TP-M4-01 (G35), CHK-M4-010 to -019; mutation rows CHK-M4-353, -354. Full rigour (agent).

Commands (WSL Ubuntu 24.04, Go 1.27.2, root, copies of the tree): `go test ./internal/agent/wire/ -count=1` (tester-m4 r0, rows CHK-M4-010 to -019 and -013b); `tester3_m4_plants.py t086` (20 plants in throwaway copies, rows CHK-M4-010..019-mut); `golangci-lint run` GOOS=linux (row CHK-M4-301-w1).

Counts: unmodified copy 363/367 passed, 0 failed, 0 errors, 4 skipped (the four lone-surrogate schema_gap fixtures, ruled "assert nothing"). Plants: 20/20 red for the planted reason. Lint: 0 issues.

| Acceptance criterion (REQ-091) | Evidence |
| --- | --- |
| (1) every valid response fixture decodes and validates; every invalid one is refused | CHK-M4-011, -012 PASS; plants: unknown keys, checkShape off, missing nullable key allowed, naive pickup_by, renamed field: all red |
| (2) requests re-encode to the fixture body, nullable keys as null, self-check refuses invalid ones | CHK-M4-013, -014, -013b PASS; plants: omitempty or omitzero (CHK-M4-353), NUL, uniq, 2^53 bounds: all red |
| (3) extra key and missing nullable key refused; fractions and uppercase UUIDs accepted; output lowercase UUIDs and UTC Z | CHK-M4-016 PASS; plants: no fractions, 32-hex UUID, uppercase out, naive out: all red |
| (4) no omitempty, json names equal to the TS §6.5 keys | CHK-M4-017 PASS; CHK-M4-353 red |
| integers strict, bounds; problems lenient; token never printed | CHK-M4-018, -019 PASS; integer bounds off, strict problems, printing token: all red |
| generate ops equal Python loader output | CHK-M4-010 PASS; 4,999-plugin generate plant red |

Observation (not a defect against REQ-091): wire.Encode of a decoded inventory Job emits `"plugins": null`, which InventoryJob refuses. The agent never encodes jobs; a fake manager must not build job responses with wire.Encode.
