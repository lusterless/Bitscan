# TASK-090 TEST: back-off and jittered intervals
**Verdict: PASS.** REQ-095, REQ-097, REQ-098; TP-M4-05, CHK-M4-050 to -055; mutation row CHK-M4-338. Full rigour (agent).
Commands: `go test ./internal/agent/schedule/` as root and as bstester; -race; `tester3_m4_plants.py t090`.
Counts: 12/12 (root, bstester, -race); 14/14 plants red.

| Criterion | Evidence |
| --- | --- |
| back-off 10, 20, 40, 80, 160, 300 … s, ±10 %, never > 330 s, no overflow (lead ruling) | CHK-M4-050; CHK-M4-338 (cap removed, cap 600), spread, no-jitter, first-5 s plants red |
| reset after a success | CHK-M4-051; plant red |
| heartbeat 300 ± 30 s, uniform | CHK-M4-052; jitter removed, ±60 and one-sided plants red |
| pull job_pull_seconds ± 30 s, clamp 60..3,600 | CHK-M4-053; clamp-low, clamp-high and ignores-input plants red |
| only the injected clock and randomness; context honoured | CHK-M4-054, -055; wall-clock and ignores-context plants red |

Not run here (belongs to TASK-101): the 503-driven retry sequence in the loops.
