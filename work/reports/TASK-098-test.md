# TASK-098 TEST: enrolment and the start-up decision
**Verdict: PASS.** REQ-096; TP-M4-13, CHK-M4-140 to -148; mutation row CHK-M4-341. Full rigour (agent).
Commands: `go test ./internal/agent/enrol/` as root and as bstester; `tester3_m4_plants.py t098`.
Counts: 53/53 (root and bstester); plants 17 of 18 red, plus 1 equivalent survivor (the lowercase is already done by wire.UUID).

| Criterion (REQ-096) | Evidence |
| --- | --- |
| (1) enrolled: one call, files as REQ-093 (1), enroll.token removed | CHK-M4-140; CHK-M4-341 red, os_id-dropped and not-strict plants red |
| (2) awaiting_approval persists the files and starts the loops (heartbeat waits are TASK-101) | CHK-M4-141; awaiting-is-failure plant red |
| (3) 401 of any type: stop with the exact text, enroll.token kept, nothing written | CHK-M4-142; delete-on-401 and 401-retried plants red |
| retries 429/5xx/network with back-off and the same token and body (#76); others not retried | CHK-M4-143, -146; five plants red |
| (4) machine-id must be 32 lowercase hex | CHK-M4-144; plant red |
| (5) neither file: refused naming both; #81 (c) decision | CHK-M4-145; four plants red |
| crash order and bad answers | CHK-M4-147, -148; delete-before-write and not-strict plants red |

For the reviewer: enrol answers 403 pending_approval with back-off (as a Wait). The spec expects 200 awaiting_approval for a held enrolment, so this path is defensive. ReadMachineID opens without a type check, so a FIFO at /etc/machine-id would block. That is not required by CHK-M4-144 and is left to your call.
