# Test plans (index)

Owner: tester. One folder per phase; each holds `test-plan.md` (checks with ids `CHK-Mn-###`, type APP or CODE, command, planted violation, local or not) and `report.md` (one row per check run).

| Phase | Plan | Status |
| --- | --- | --- |
| M0 scaffolding | [m0/test-plan.md](m0/test-plan.md) | drafted 2026-10-20 from `work/tasks.md` and `work/requirements.md` |
| M1 database and audit core | [m1/test-plan.md](m1/test-plan.md) | drafted 2026-10-20 from `work/tasks.md` (TP-M1-00 to -16, gates G1 to G6, G18 to G24) and REQ-018 to REQ-033; extended for TASK-019 revisions 1 and 2 (amendments to #44: CHK-M1-180 to -191), TASK-021 revision 1 and step 2 (CHK-M1-229, -230), and TASK-022 stacked PRs and actionlint (CHK-M1-254, -255). All checks run except CHK-M1-256 (live PRs) |
| M2 to M11 | not yet drafted | drafted at each phase start |
