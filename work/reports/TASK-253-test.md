# TASK-253 TEST: PASS

Tester: tester-m11d, 2026-11-09. Docs (`deploy/runbooks/manager-operations.md` §1, §6, §7; `deploy/debian/changelog` `0.2.0~pre2-1`). REQ-289, REQ-290. Walked together with TASK-252 and TASK-259; full evidence in `work/reports/TASK-252-test.md`.

| Check | Result | Evidence (details in TASK-252-test.md) |
| --- | --- | --- |
| CHK-M11-384 | PASS | `dpkg-parsechangelog -S Version` → `0.2.0~pre2-1`. `check_debian_meta.py` OK 82/82, with CHK-M10-318 and -319 green. `dpkg --compare-versions`: `0.1.0-1` < `0.2.0~pre1-1` < `0.2.0~pre2-1` < `0.2.0-1` |
| CHK-M11-383 | PASS | Against a real WSL `serve`: §1's agent-version SQL runs. §6's journal grep on the serve log gives the seven `retention step done` lines in order, `skipped` null, shaped as the example line; the first run comes 10 min after start (602 s by the log); the checkpoint SQL runs (none on a young database). §7 checked statically against `release.yml` and `e2e.yml`; its `gh` and `git` commands were not run (the release owner's) |
| CHK-M11-382 | PASS | `check_runbook_text.py`: `OK 24 sh blocks, 0 findings`; no secret, token, DSN or process note |

The M6 harness indexes into §1 were not re-run here; impl-deploy checked them against the `ops_walk.sh` regex (blocks 0–2 unchanged), and the new block is fourth. They belong to the M11 gate's full run.
