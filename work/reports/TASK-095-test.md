# TASK-095 TEST: dpkg list parser, list_sha256, gzip body

**Verdict: PASS** (round 1).

REQ-100, REQ-101; TS §3.4 L235, §6.5 L1186; #33, #72, #77 (d); lead rulings 2026-10-24 Q2–Q5. Tester: tester-m4b. Full rigor (agent). Test file: `agent/internal/inventory/dpkg_test.go` (new). The oracle for list_sha256 is the manager's `loader.list_sha256` (Python).

## Commands
- W: `go test -count=1 -v -run 'Dpkg|ListSHA256|BuildBody' ./internal/inventory/` (inside the 112/113 package run); `-race` included in the 66/66.
- W-c 22.04 plain and systemd: TestDpkgRealHostList 1/1 each.
- Plants Q01–Q13: 13/13 red (Q03–Q06 = CHK-M4-350).

## Acceptance criteria
- Real dpkg-query output parses one item per line with null empty fields, on 24.04 and 22.04: PASS (CHK-M4-110).
- Edge lines (field counts, sizes, UTF-8, CRLF, duplicates): PASS (CHK-M4-111).
- list_sha256 equals the manager for every fixture, edge lists and the generated 50,000: PASS (CHK-M4-112).
- The body is compact gzip JSON, valid, round-trips, duplicates kept: PASS (CHK-M4-113).
- 50,000 rows in under 5 s and under 10 MiB; 50,001 sent untruncated: PASS (CHK-M4-114).
- Debian 12: NOT RUN (dropped from v1 by the user).

## Note
One TestBuildBodyRoundTrip failure in the very first run ("HTML escaping applied") was not reproduced in 23 later runs, with no product change between them. The check now prints the bytes around any escape so a recurrence carries evidence. It is not counted as a defect.
