# Test plans (index)

Owner: tester. One folder per phase; each holds `test-plan.md` (checks with ids `CHK-Mn-###`, type APP or CODE, command, planted violation, local or not) and `report.md` (one row per check run).

| Phase | Plan | Status |
| --- | --- | --- |
| M0 scaffolding | [m0/test-plan.md](m0/test-plan.md) | drafted 2026-10-20 from `work/tasks.md` and `work/requirements.md` |
| M1 database and audit core | [m1/test-plan.md](m1/test-plan.md) | drafted 2026-10-20 from `work/tasks.md` (TP-M1-00 to -16, gates G1 to G6, G18 to G24) and REQ-018 to REQ-033; extended for TASK-019 revisions 1 and 2 (amendments to #44: CHK-M1-180 to -191), TASK-021 revision 1 and step 2 (CHK-M1-229, -230), and TASK-022 stacked PRs and actionlint (CHK-M1-254, -255). All checks run except CHK-M1-256 (live PRs) |
| M2 auth core and API plumbing | [m2/test-plan.md](m2/test-plan.md) | drafted 2026-10-21 from `work/tasks.md` (TP-M2-00 to -25, gates G1 to G6, G16, G18, G25 to G29), REQ-034 to REQ-059 and the answered questions (#5, #7, #8, #24, #34, #47 to #58; decisions 2026-10-21), before any M2 code was read. Includes the security mutation table (CHK-M2-320 to -349). Updated 2026-10-21 for the lead's answers ("M2 test-plan answers": CHK-M2-019, -101, -143, -164, -165, -220), CHK-M2-133 (stale-tmp modes, TASK-034), CHK-M2-185 (OpenAPI error contract, TASK-038), CHK-M2-186 (sign-in memory bound, TASK-038) and CHK-M2-249 (/readyz bounded with the database paused, TASK-044). Updated 2026-10-22 for the TASK-046 ruling (a), "no DSN content in output": CHK-M2-035a (pool), CHK-M2-263c (serve), CHK-M2-269a (CLI) |
| M3 to M11 | not yet drafted | drafted at each phase start |
