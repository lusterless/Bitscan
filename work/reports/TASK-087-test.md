# TASK-087 TEST: agent.yaml loader and the first Go dependencies

**Verdict: PASS** (round 2, after revision 1). REQ-092, REQ-105; TP-M4-02, CHK-M4-020 to -028; mutation rows CHK-M4-320, -342, -343, -365. Full rigour (agent).

Round 1 FAIL: `TestLoadCAFile/a_FIFO_(must_not_block)`: Load hung on a FIFO ca_file. Revision 1 (config.go: stat first, then open O_RDONLY|O_NONBLOCK, fstat again) fixed it.

Commands (WSL, Go 1.27.2): re-run of the failing subtest (root), TestLoadCAFile (root), the whole package as bstester and as root, `tester3_m4_plants.py t087`, `tester3_m4_modverify.sh` (fresh module caches) and `go version -m`.

Counts: FIFO subtest 1/1; TestLoadCAFile 5/5; bstester 98/99, with one test bug of mine fixed and re-run 1/1; root 98/98; TestNoEnvironmentOverride (extended) 1/1; plants 15/15 red (the env override was first green: a test gap I fixed and re-planted red).

| Acceptance criterion | Evidence |
| --- | --- |
| REQ-092 (1) TS §3.6 example loads exactly | CHK-M4-020 PASS; default-600 plant red |
| REQ-092 (2) each refusal one line naming the key, with no value | CHK-M4-021 PASS; CHK-M4-320 and -343 red, value-echo, range, pin, duplicate, second-document and float plants red |
| boundaries accepted | CHK-M4-022 PASS; `>=8` plant red |
| REQ-092 (4) the agent never writes agent.yaml | CHK-M4-023 PASS (r1 static check fixed); CHK-M4-342 red (WriteFile and O_RDWR) |
| no environment override | CHK-M4-024 PASS (test extended to Load); plant red |
| REQ-092 (5) ca_file missing, unreadable (non-root) or non-regular refused, FIFO without blocking | CHK-M4-020..025-r1, -r1b, -u PASS; ca_file-unchecked and FIFO-regression plants red |
| REQ-105 go.mod and go.sum, go mod verify | CHK-M4-026 PASS; CHK-M4-027/-365 PASS (an altered zip hash is caught by build, test and download, not by `go mod verify` alone: CI note) |
| REQ-105 (3) only yaml linked, no test-only module | CHK-M4-028 PASS on a proxy binary; the tree binary half waits for TASK-106 |

Not run here: the yaml dep line in the real bitscan-agent (TASK-106 links config).
