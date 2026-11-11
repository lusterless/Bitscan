# Test reports (index)

Owner: tester. Per-task verdicts are in `work/reports/TASK-###-test.md`; per-check rows are in the phase report.

| Phase | Report | Summary |
| --- | --- | --- |
| M0 scaffolding | [m0/report.md](m0/report.md) | All 10 tasks TEST PASS. Lead re-run in WSL2 with Docker (see the end of m0/report.md): full pytest suite **58 passed, 0 skipped** with `CI=true`, PostgreSQL tests pass, Ryuk and postgres images pull by digest, real Linux hashed install OK. `systemd-analyze verify` on the nine units is clean on systemd 255 (Ubuntu 24.04, WSL) and goes red on four planted defects; the three Linux ELF stubs run as specified. **Live GitHub Actions on PR #1: all four workflows (manager, web, agent, units) green on their first run**: pytest 58 passed with 0 skipped on the runner, `systemd-analyze verify` clean, stubs run. Only arm64 stub execution remains open (deferred to M6) |
| M1 database and audit core | [m1/report.md](m1/report.md) | All 12 tasks TEST PASS and review APPROVED. WSL2 with Docker, clean copy, `CI=true`: **547 passed, 0 skipped**, services coverage 100 %, 0 leftover containers (CHK-M1-240-r2). Windows gate (CHK-M1-241): ruff, format and `mypy --strict` clean; 366 passed, 181 skipped (`not run: Docker unavailable` only), coverage 98.15 %. The coverage gate goes red on a planted untested function (CHK-M1-201). Known NOT RUN: CHK-M1-256 (live PRs; needs pushes). Per-PR-head runs (CHK-M1-242, 2026-10-21, WSL, fresh venv per head, `CI=true`): `m1-pr1` 308, `m1-pr2` 331, `m1-pr3` 341, `m1-pr4` 371, `m1-pr5` 547 passed, each 0 failed, 0 skipped, 0 leftover containers |
| M2 auth core and API plumbing | [m2/report.md](m2/report.md) | All 25 tasks (TASK-023 to TASK-047) TEST PASS and review APPROVED; auth tasks have the second approval. Exit gate PASS (2026-10-22): WSL2 with Docker, clean copy, `CI=true`: **1520 passed, 0 skipped**, services coverage 99.32 %, 0 leftover containers (CHK-M2-305). Windows: ruff, format and `mypy --strict` clean; 1033 passed, 451 skipped (Docker and Linux-only only), coverage 97.13 % (CHK-M2-303, -306). G25 to G29 and the new security suite (CHK-M2-290 to -294) are red on their plants; the defined G5 plant no longer turns G5 red at 97 % (lead ruling 2026-10-22; a 120-statement plant does). Known NOT RUN: the `git diff` forms of G6 and G16, G8 on Linux, G17 and live CI (need commits and pushes) |
| M3 agent API and scheduler (inventory only) | [m3/report.md](m3/report.md) | in progress (W1): TP-M3-01 fixtures; TASK-048 to TASK-058 TEST PASS (TASK-053 with revision 1); WSL W1 full run 2459 passed, 0 skipped, services 99 % |
| M4 Go agent and pre-release `.deb` | in the `Bitscan-m4` worktree: `tests/m4/report.md` | in progress |
| M5 minimal host UI and package search | [m5/report.md](m5/report.md) | TASK-108 to 127 TEST PASS (121, 126, 127 after a revision); TASK-128 and the M5 gate pending |
| M6 first-release gate | [m6/report.md](m6/report.md) (plan: [m6/test-plan.md](m6/test-plan.md)) | TASK-129 to 138 TEST PASS (TASK-132 and 138 at full rigor). **Gate TP-M6-14: PASS with one named exception** (tester-m6d, 2026-10-27; the "Gate TP-M6-14" section at the end of m6/report.md). G18 **4824/4824 passed, 0 skipped**, services 99.41 % (WSL, `CI=true`, one PostgreSQL container per worker); wheel, install walk, release workflow and cursor plants red; end to end on real Ubuntu 22.04 and 24.04 hosts and on a fresh 24.04 with the final RC `d98ef8c3…` (= the local release build). **Exception (user sign-off, decisions 2026-10-27):** the six VM plants CHK-M6-340..345 are NOT RUN, because the session safety check blocked them; they run before any M7 code. Other NOT RUN: GitHub runs (no push), load/soak/timing tests (deferred), `new_packages_burst` on a real host, the browser approval, Debian 12 and arm64 (dropped) |
| M7 compliance catalog | [m7/report.md](m7/report.md) (plan: [m7/test-plan.md](m7/test-plan.md)) | TASK-139 to 175 TEST PASS. **Gate PASS** (tester-m7, 2026-10-29): full manager suite 8,866 passed, 0 skipped; services coverage 95.34 %; mutation table CHK-M7-320..371 red; closing review APPROVED. Named exception (user, 2026-10-29): TASK-146 (BIT102) ships as the tested r1; its review, second approval and the r2 gap closure move to M10. Merged as PR #15 |
| M8 evaluator | [m8/report.md](m8/report.md) (plan: [m8/test-plan.md](m8/test-plan.md)) | TASK-176 to 185 TEST PASS (183 and 185 at revision 1), full rigor. **Gate PASS** (tester-m8, 2026-10-29): full manager suite 10,228/10,228, 0 skipped; services coverage 98.50 % (evaluator 99.42 %); mutation table CHK-M8-320..364 all red (22 security rows); closing review APPROVED in round 2. Includes the test-only CHK-M2-232 isolation fix |
| M9 scan engine | [m9/report.md](m9/report.md) (plan: [m9/test-plan.md](m9/test-plan.md)) | TASK-186 to 208 TEST PASS, full rigor (revisions: 191 r2, 195 r1, 197 r1, 201 r1, 202 r1, 203 r1, 204 r1, 205 r1, 208 r1). **Gate PASS** (tester-m9b, 2026-10-30): full manager suite 11,166/11,166, 0 skipped (first run 6 failed: M2/M3 checks superseded by M9 requirements, updated under the PD-40 rule); services coverage 98.53 %; G66–G70 green; mutation table CHK-M9-320..382 red. Defects found and fixed before merge: first result wins missing a completed original's retry (195), a schedule-tick deadlock with policy delete (203), one bad job stalling the sweep (202) |
| M10 compliance runner | [m10/report.md](m10/report.md) (plan: [m10/test-plan.md](m10/test-plan.md)) | TASK-209 to 229 and 231 TEST PASS, full rigor (revisions: 209 r1, 212 r1, 220 r1, 221 r1 and r2, 223 r1, 224 r1 and r2, 229 r1 and r2). **Gate PASS** (tester-m10c, 2026-11-01): agent WSL `-race` 1335/1341 (6 skipped), delegated as bitscan-runner 37/37, G36 64/64; Windows 1023/1052 (25 pre-existing M4 Windows-only rows); full manager suite 11,211/11,211, services coverage 98.53 %; mutation table CHK-M10-320..393, all 74 red. The runner ran in WSL under all 37 verbatim service and 5 socket directives. Old-to-new rewrites: CHK-M4-223 → CHK-M10-271, CHK-M4-100 → CHK-M10-272, CHK-M6-100 → CHK-M10-318 (+ CHK-M10-319). Defects found and fixed before merge: the spool's in-flight batch blocked overflow during an outage (220, 223), a plugin that left its cgroup hung the runner past its timeout (224), dropped capture errors could send cut output as complete (224), the runner's main thread was left at nice 10 (221). **Named exception (user, 2026-11-01), now cleared (2026-11-02/03):** G41 PASS (23/23, plant red); G79 PASS on `bitscan-u2404`; TASK-231 runbook walk PASS on both Hyper-V VMs with the §6 upgrade; G76 PASS on stand-in QEMU VMs (counted, user 2026-11-03; 34 PASS, 0 FAIL, 2 NOT RUN by design); G77/TASK-230 `sandbox.yml` green (run 6, 29/29 jobs); G78 host part PASS; VM plants 24 red, 333/382/340 not red with reasons. Three sandbox gaps found and fixed by user decision 2026-11-03 (runner unit `/dev/shm` read-only and `/tmp` noexec; cramfs sample). PR #20 reviewed (round 2 APPROVED) and merged 2026-11-04; the manager half of CHK-M10-344 closed by user decision 2026-11-07 (runner half enough). **M10 closed 2026-11-07.** Record: `work/reports/M10-vm-test.md`. G38 is evidenced by the PR's package.yml run |
| M11 | not started | |
| Release 0.2.0 (TASK-262, TASK-263) | [release/report.md](release/report.md) (plan: [release/test-plan.md](release/test-plan.md)) | in progress |

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
