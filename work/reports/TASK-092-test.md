# TASK-092 TEST: D-Bus policy and package metadata

**Verdict: PASS** (tester-m4, 2026-10-24). REQ-106 (2), TS §3.1 L159, §3.7 L412–L431. Standard rigor (packaging metadata); CHK-M4-361 (metadata half) and CHK-M4-362 planted red.

## Commands and counts
| Run | Where | Result |
| --- | --- | --- |
| `python -I deploy/tests/check_units_verbatim.py agent` / `all` / `manager` | L | 6/6, 10/10, 4/4 files identical; 0 failed, 0 errors, 0 skipped |
| same, `all` | W | 10/10 |
| `python -I deploy/tests/check_debian_meta.py` | L, W | 59/59 checks passed; 0 failed |
| verbatim plants (CHK-M4-070, -071) | L | 12/12 red as expected (control green) |
| metadata plants (CHK-M4-072 to -074) | L | 16/16 red as expected (control green) |
| `make -n` of the two `rules` targets; `dpkg-parsechangelog`; 5 `dpkg --compare-versions`; `systemd-analyze verify` (5 units); XML parse | W | all as expected (5/5 version relations true; verify exit 0, only "not executable") |

## Acceptance criteria
| Criterion | Checks | Result |
| --- | --- | --- |
| Policy byte-identical to TS §3.7 (block L413–L430, fences L412/L431), extended verbatim check | [CHK-M4-070, -071, -070-xml](../../tests/m4/report.md) | PASS |
| `rules`: `--no-enable` for `bitscan-runner.service`, `--no-enable --no-start` for both capread units (and the agent service and runner socket enabled and started) | [CHK-M4-072](../../tests/m4/report.md) | PASS |
| Metadata: `control`, `changelog` 0.x, `copyright` (PD-26 (a), amd64 only) | [CHK-M4-073, -074](../../tests/m4/report.md) | PASS (exec bit of `rules`: TASK-102) |
| Units still verify | [CHK-M4-075](../../tests/m4/report.md) | PASS |

## Notes (no defect)
- The impl report is right that the block is TS L413–L430; `work/tasks.md` cites it with its fences (L412–L431). The test plan uses the fence lines.
- `rules` is stored without the executable bit (Windows checkout); TASK-102 must `chmod 0755` it in the staging tree, and the build test (TP-M4-17) will check it.
- `bitscan-runner.service` gets `--no-enable` only, so the debhelper snippet starts (and on upgrade restarts) it; this is what TS L159 says and REQ-106 (3) only needs "not enabled". TP-M4-15 (CHK-M4-167) records whether it is active after install.
- lintian, the build and `dpkg-deb -c` need TASK-096 and TASK-102 (TP-M4-17, -20).
