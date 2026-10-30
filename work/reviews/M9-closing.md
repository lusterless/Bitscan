# M9 closing review (scan engine)

Verdict: APPROVED (round 2)

Reviewer: reviewer-m9, 2026-10-30. Gate record reviewed: `work/reports/M9-gate-test.md` (tester-m9b, TP-M9-20), including the round 2 G5 plant rows. Tree: worktree `Bitscan-m9`, branch `m9-scan-engine`, which is `d09c537` plus the uncommitted M9 files.

## Task reviews
All 23 tasks (TASK-186 to TASK-208) are APPROVED in `work/reviews/TASK-186.md` … `TASK-208.md`.

| Rounds | Tasks |
| --- | --- |
| 1 | 186, 187, 188, 189, 191 (on TEST r2), 192, 193, 194, 195 (TEST r1), 196, 197 (r1), 198, 199, 200, 201 (r1), 203 (r1), 204 (r1), 205 (r1), 206, 207 |
| 2 | 190 (test side), 202 (per-job savepoint), 208 (DST sentence) |

PD-39:
- TS §8.2 second approval: TASK-190, 195, 199 and 204. Each is APPROVED with no open blocking or should-fix finding.
- The user's second look: TASK-189, 198 and 205.
- Both are applied by `main` under the pre-authorisation.

## Whole-milestone checks (my own)
1. **Scope of the tree.** Every changed or new non-test file belongs to one of the 23 tasks, plus `services/audit/alerts.py` (added to TASK-198 by ruling (1)). There is no migration and no agent, unit, package, workflow or dependency change (G4 diff empty).
2. **Security invariants (`.claude/rules/security-invariants.md`).**
   - No ad-hoc command path. `execute` reaches a payload only from `scan_queue` (the snapshot) and `job_sweep` (the original's payload). Every M9 body is closed, and the planted `POST /scans/{id}/run` is red in G34.
   - No push or listening path, and no outbound import in the M9 modules.
   - Inventory cannot be disabled (the G2 section).
   - Operator and ExpectedResult stay in `eval_spec` (G30 component schemas identical to `d09c537`; CHK-M9-347, -379 red).
   - Agent routes are `bsa_` only and user routes `bsu_`/`bsk_` (CHK-M9-230, -365).
   - SQL is parameterised (S608 red in all 5 repositories), and `re` is banned in every pure module.
   - No stdout, stderr, `execute` or expected value appears in any log line (grep and the canary rows).
   - No UPDATE or DELETE on `scan_result`, and no write to `payload` or `eval_spec`.
3. **Lock order.** It is root then job everywhere a unit is touched, and queue lock then policy share for scans. The tick never waits on a policy while holding its schedule row. No cycle across intake, sweep, cancel, queue, schedule admin, the tick and M7's delete. The race suites are green.
4. **Static gates, re-run by me on Windows.** `ruff check manager`, `ruff format --check manager` (385 files) and `mypy --strict` on `manager/bitscan_manager` are clean. `openapi.json` sha256 `74182d35…` matches the one TASK-207's `schema.d.ts` came from.

## Gate record
- **Gates and plants.** G1–G6, G16, G18 (11,166/11,166, 0 skipped), G19, G30, G31, G33, G34 and G66–G70 are PASS, each with its plant red.
- **G5** is 98.53 %. Its plant p2 (83.99 %) exits 1, red.
- **Mutation table.** 63/63 red, with all 24 security rows marked.
- **G18 oracle updates.** The six first-run oracle updates (CHK-M9-235 to -239) follow from named M9 requirements under PD-40 rule (3). No gate is lowered.
- **Phase report.** `tests/m9/report.md` and the `tests/report.md` M9 row are folded by `main`.

## Findings
1. should-fix, round 1, **resolved**: the G5 plant had no recorded result. Now p2 (1,000 untested statements, 83.99 %) gives `--cov-fail-under=85` exit 1 (`M9-gate-test.md:140`).
2. should-fix, round 1, **resolved**: `tests/m9/report.md` and its index row are written by `main`.
3. nit, round 1, **resolved**: CHK-M9-330 is marked as a security row (24).
4. **Observation for `main`** (tooling, outside M9 scope; no gate lowered): at 84.99 %, which prints as 85.00 %, pytest-cov 7.1.0 prints "FAIL" but exits 0 (p1). The CI floor in `.github/workflows/manager.yml` therefore passes a run under 85 % by less than 0.005 points. The M9 tree is at 98.53 %, so it isn't affected. Optionally give impl-deploy a follow-up, for example a coverage `precision` setting so the comparison and the printed value agree.
5. Note: the G18 oracle fixes were confirmed by re-running their 6 node ids only. CI's full G18 on the PR is the backstop.
