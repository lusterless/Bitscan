# Test reports (index)

Owner: tester. Per-task verdicts are in `work/reports/TASK-###-test.md`; per-check rows are in the phase report.

| Phase | Report | Summary |
| --- | --- | --- |
| M0 scaffolding | [m0/report.md](m0/report.md) | All 10 tasks TEST PASS. Lead re-run in WSL2 with Docker (see the end of m0/report.md): full pytest suite **58 passed, 0 skipped** with `CI=true`, PostgreSQL tests pass, Ryuk and postgres images pull by digest, real Linux hashed install OK. `systemd-analyze verify` on the nine units is clean on systemd 255 (Ubuntu 24.04, WSL) and goes red on four planted defects; the three Linux ELF stubs run as specified. Still NOT RUN: the live GitHub Actions runs (CI is the final proof for the systemd patch level and for file modes) |
| M1 to M8 | not started | |

## M0 per task

| Task | Verdict | Rounds | Checks | NOT RUN locally |
| --- | --- | --- | --- | --- |
| TASK-001 manager config and locks | PASS | 1 + revisions 2 and 3 re-checked | CHK-M0-001 to -013, -012-r2, -011-r3 | real Linux `pip install` (proxy CHK-M0-013 PASS) |
| TASK-002 manager skeleton | PASS | 1 | CHK-M0-020 to -045 | pg tests (TASK-003); the `git diff` form of G6 (CI) |
| TASK-003 PostgreSQL harness (tester-implemented; TEST by tester-b) | PASS | 1 | CHK-M0-050 to -057 | CHK-M0-050, -051, -052, -057 (Docker) |
| TASK-004 Go module, lint, stubs | PASS | 3 (round 1 FAIL on CHK-M0-076) | CHK-M0-060 to -079, -076-ctl, -076-r3, -076-r3-ctl, -076-r3-nolint, -070-r2, -070-r3 | ELF run and `file` (CI, CHK-M0-146) |
| TASK-005 web toolchain | PASS | 2 (review findings 1 to 4) | CHK-M0-090 to -105, -101-r2, -093-r3 | none |
| TASK-006 generated API client | PASS | 1 | CHK-M0-110 to -114 | the `git diff` form (CI) |
| TASK-007 agent units verbatim | PASS | 1 | CHK-M0-120, -122, -123 | CHK-M0-124, -125 (systemd) |
| TASK-008 manager units verbatim | PASS | 1 | CHK-M0-121, -122, -123 | CHK-M0-124, -125 (systemd) |
| TASK-009 CI manager and web | PASS | 1 | CHK-M0-130 to -137 | CHK-M0-136 and live -137 (Actions); pg with Docker; Ryuk pull |
| TASK-010 CI agent and units | PASS | 3 (stubs-run step; asm/syso listing) | CHK-M0-140 to -147, -142-sub | CHK-M0-144 (Actions), real `systemd-analyze` (G17), ELF run |

## Carried to the first PR run

- G17: `systemd-analyze verify deploy/systemd/*` must print nothing on ubuntu-24.04. Any warning is a spec question, and must not be filtered.
- G5 with Docker: the 3 `pg` tests must pass (PostgreSQL 16, three extensions, debversion ordering), and no container may be left behind.
- The stubs-run step on linux/amd64. arm64 binaries are built but never executed (no arm64 runner yet).
- `git diff --exit-code` for G6 and G16 against real commits.
- The Ryuk `name:tag@digest` pull.

## Follow-ups for M1 (from TEST and review notes)

- A pytester test for the conftest skip/exit hook (tester-b, reviewer TASK-003 nit 1).
- Switch the harness to the app roles after the TS §5.2 Bootstrap (reviewer TASK-003 nit 6).
- Confirm `baseUrl: ""` against the first real `/api/v1` route (TASK-006).
