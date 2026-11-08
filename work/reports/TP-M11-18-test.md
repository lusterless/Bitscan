# TP-M11-18 TEST: nightly end-to-end harness (REQ-285) — PASS

Tester: tester-m11e, 2026-11-09. Rows: `work/reports/M11-e2e-test.md` (sections "TP-M11-18", "Counted rows on hosted runners", "Counted gate runs in WSL"). Plan: `tests/m11/test-plan.md` CHK-M11-294 to -303, plants CHK-M11-370 and -371.

## Verdict

**PASS.** The counted run is e2e run **42488215323** on `5671c82` (TASK-244 committed): the `nightly` job gave **19/19 PASS, 0 FAIL, 0 NOT RUN**, every expected row present, and 0 token-shaped strings in the artifacts. Each of the two planned plants turns exactly the results rows red.

## Commands and counts

| Run | Where | Result |
| --- | --- | --- |
| n1 to n3 | WSL, committed 66a2f7e | Harness development. Fixed: an environment problem (PyPI timeout) and a test bug (`status` instead of `outcome`). n3: 13/19, the six results rows FAIL on 404 (the routes were not there yet) |
| n4 | WSL, 06ad471 plus the then-uncommitted TASK-244 file | 19/19 PASS (development) |
| **counted** | hosted, `5671c82`, run 42488215323 (`nightly` job) | **19/19 PASS** |
| CHK-M11-370 plant (n5 r2) | WSL; the runner never emits its result | Red as required: CHK-M11-302 per host and the CSV FAIL (ERROR, errors 1, score null); the viewer row and the sweep green |
| CHK-M11-371 plant (n6) | WSL; a `5671c82` copy whose results route keeps only the first host | Red as required: CHK-M11-302 u2204 FAIL (no items); u2404, the CSV and the viewer row green |

## Acceptance criteria (REQ-285)

| Criterion | Rows | Result |
| --- | --- | --- |
| (1) every step for both hosts, each PASS with evidence | CHK-M11-294 to -302, hosted run | PASS |
| (2) plants: no runner results → the results row FAIL; a results route leaving out a host → FAIL | CHK-M11-370, -371 | PASS (both red as required) |
| (3) the token and password sweep over the report and logs finds nothing | CHK-M11-303 (every run) | PASS (0 hits) |

## Notes

- The counted `.deb` is `0.2.0~pre1-1`: TASK-253's `0.2.0~pre2-1` changelog was not in `5671c82`. M11 changes no agent code, so the agent is the same; the nightly re-runs on each later commit.
- Known gap: there is no Hyper-V form of `guests.sh`, so the standing-approval fallback to the local VMs cannot run (M11-e2e-test.md, TP-M11-20).
