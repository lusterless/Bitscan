# TP-M11-19 TEST: N / N−1 rows (REQ-287, REQ-288) — PASS

Tester: tester-m11e, 2026-11-09. Rows: `work/reports/M11-e2e-test.md` (sections "TP-M11-19", "Counted rows on hosted runners", "Counted gate runs in WSL"). Plan: `tests/m11/test-plan.md` CHK-M11-304 to -309, plant CHK-M11-372.

## Verdict

**PASS.** N−1 is the v0.1.0 release; each of its files was checked against the SHA256SUMS text on the release page (#153 (a)).

| Pairing | Run | Result |
| --- | --- | --- |
| Manager N with agent 0.1.0 (CHK-M11-304, -305, -306, -309) | hosted, `5671c82`, run 42488215323, `compat-a` | **10/10 PASS.** CHK-M11-306: every plugin is ERROR `runner_unavailable` with exit_code null; score null; errors 1, equal to the plugin count. This matches v0.1.0's `Unavailable.Handle` (`agent/internal/agent/loops/jobs.go`) |
| Agent N with manager 0.1.0 (CHK-M11-304, -308, -309) | hosted, `compat-b` | **8/8 PASS**: enrol, approve, heartbeat, inventory. No compliance job: `POST /scans` answers 404 on 0.1.0, and the runner never starts |
| Upgrade walk, once at the gate (CHK-M11-307, #153 (d)) | WSL, `5671c82` with the CI `.deb` (`compat.py --phase upgrade`) | **16/16 PASS.** Manager 0.1.0 with agent 0.1.0 → manager-operations.md §1 to N (all 196 files at the N wheel's hashes) → heartbeats and inventory go on without re-enrolment → agent upgraded to N → the scan ends `completed`, PASS |
| Plant CHK-M11-372 (a manager that refuses the 0.1.0 heartbeat body) | WSL, r3 | **Red as required** at the CHK-M11-305 heartbeat row: still `enrolled`, no heartbeat after 423 s. r1 and r2 failed on a test bug in the install check; fixed |

## Acceptance criteria

| Criterion | Result |
| --- | --- |
| REQ-287 (1): each row PASS with its evidence | PASS |
| REQ-287 (2): plant: a manager refusing the 0.1.0 heartbeat body → that row FAIL | PASS |
| REQ-288 (1): agent N with manager 0.1.0, the row PASS (the user answered the N / N−1 marker "yes", decisions 2026-11-08) | PASS |

## Notes

- The upgrade walk ran in WSL, not on hosted runners: by design, `e2e.yml` does not run `compat --phase upgrade` (#153 (d): once at the gate).
- Both wheels carry version 0.1.0 (PD-50), so the harness tells the installed code apart by the wheel's file hashes.
