# Test reports (index)

Owner: tester. Per-task verdicts are in `work/reports/TASK-###-test.md`; per-check rows are in the phase report.

| Phase | Report | Summary |
| --- | --- | --- |
| M0 scaffolding | [m0/report.md](m0/report.md) | All 10 tasks TEST PASS. Lead re-run in WSL2 with Docker (see the end of m0/report.md): full pytest suite **58 passed, 0 skipped** with `CI=true`, PostgreSQL tests pass, Ryuk and postgres images pull by digest, real Linux hashed install OK. `systemd-analyze verify` on the nine units is clean on systemd 255 (Ubuntu 24.04, WSL) and goes red on four planted defects; the three Linux ELF stubs run as specified. **Live GitHub Actions on PR #1: all four workflows (manager, web, agent, units) green on their first run**: pytest 58 passed with 0 skipped on the runner, `systemd-analyze verify` clean, stubs run. Only arm64 stub execution remains open (deferred to M6) |
| M1 database and audit core | [m1/report.md](m1/report.md) | All 12 tasks TEST PASS and review APPROVED. WSL2 with Docker, clean copy, `CI=true`: **547 passed, 0 skipped**, services coverage 100 %, 0 leftover containers (CHK-M1-240-r2). Windows gate (CHK-M1-241): ruff, format and `mypy --strict` clean; 366 passed, 181 skipped (`not run: Docker unavailable` only), coverage 98.15 %. The coverage gate goes red on a planted untested function (CHK-M1-201). Known NOT RUN: CHK-M1-256 (live PRs; needs pushes). Per-PR-head runs (CHK-M1-242, 2026-10-21, WSL, fresh venv per head, `CI=true`): `m1-pr1` 308, `m1-pr2` 331, `m1-pr3` 341, `m1-pr4` 371, `m1-pr5` 547 passed, each 0 failed, 0 skipped, 0 leftover containers |
| M2 to M11 | not started | |

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

## M1 per task (TASK-019 to TASK-022; TASK-011 to TASK-018 are in m1/report.md)

| Task | Verdict | Rounds | Checks | NOT RUN locally |
| --- | --- | --- | --- | --- |
| TASK-019 `db maintain` | PASS | 1 + revision 1 (clock guard, naive clock, run lock) + revision 2 (guard (c), after the CHK-M1-186 finding) | CHK-M1-170 to -191, -055-r2 | none |
| TASK-020 audit append | PASS | 1 | CHK-M1-200 to -209, -228 | none |
| TASK-021 audit verifier | PASS | step 1 + revision 1 (failure priority) + step 2 (repository read) | CHK-M1-220 to -230 | none |
| TASK-022 CI migration gate | PASS (local) | 1 + revision 2 (`edited` trigger, stacked PRs) | CHK-M1-250 to -255 | CHK-M1-256 (live PRs) |

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
