# M8 closing review: the evaluator

Verdict: APPROVED (round 2, 2026-10-29). Round 1 was CHANGES_REQUESTED on the gate only, for G18 (CHK-M2-232). That is now fixed with a test-only change under the lead's ruling, and G18 is green.

Reviewer: reviewer-m8, 2026-10-29. Gate report: `work/reports/M8-gate-test.md` (tester-m8, final, including "CHK-M2-232 fix" and "G18 final row"). Task reviews: `work/reviews/TASK-176.md` to `TASK-185.md`, all APPROVED with 0 blocking and 0 should-fix. PD-38: one review per task, full rigor.

## What I verified myself
- **Unit suites on Windows (M7 venv, imports checked to resolve to the M8 tree).** All six M8 unit files pass: model and normaliser 102, operators 397, evaluate, property and security 537, verdict, eval_spec, score and property 216, and `test_eval_spec.py` alone 102 after the gate row. Whole-tree `ruff check`, `ruff format --check` (337 files) and `mypy --strict` are clean.
- **PostgreSQL suites in WSL** (the tester's base copy; product and test files checked byte-identical to the worktree):
  - results, re-evaluation repository and scores: 60/60;
  - re-evaluation service and races: 38/38.
- **Scope sweep over the 12 M8 product files.**
  - No `re`, `regex`, `logging`, `print` or `getLogger` import.
  - No SQL f-string; the only f-strings are the audit actor and target.
  - No UPDATE, DELETE, TRUNCATE, MERGE or `FOR UPDATE`.
  - `git diff 67a6dfa` is empty over `api/`, `db/`, `openapi.json`, the requirements files, `pyproject.toml`, `docs/spec` and `.claude/`. So M8 adds no route, migration, dependency or spec edit.
- **The CHK-M2-232 diff** (`git diff 67a6dfa -- manager/tests/test_users_api_pg.py`): it is test-only. Every original assertion is kept:
  - 200 at 14:59;
  - 503 `audit_sink_unavailable` for every method at 15:00;
  - `/api-tokens` still 200 during the outage;
  - `refusing()` False after recovery, then 200.

  Added: one audited `POST /users` (so the shipper always has something to deliver), a "not refusing before 15 minutes" assertion, and a drain loop bounded by `count(audit_log) // BATCH + 5` that fails when the bound is hit. That matches the decisions row "CHK-M2-232 test isolation fix". Both plants are red: refusal disabled, and never cleared.

## Spec conformance (TS §4.5, §5.2, §8.3; SR §1.1, §2.4)
| Item | Where | Status |
| --- | --- | --- |
| Exactly the 14 operators, nothing added (#11) | TASK-176, 177 | met |
| Exact `evaluate(operator, expected, stdout, exit_code, timed_out, truncated) -> 0\|1\|2` (L600) | TASK-178 | met |
| ERROR checks before any comparison, in #112 (c) order; the exit code never decides otherwise (L593, L598; #113, #114) | TASK-178 | met |
| No false PASS: `not_regex`, `ne`, negated spellings, NULL stdout, unrecognised stored ERROR details (decisions 2026-10-29) | TASK-177, 178, 185 | met |
| Normalisation: one-pass CRLF → LF, ASCII trim, case-sensitive (L597, #115, one-pass ruling) | TASK-176 | met |
| Server caps in UTF-8 bytes, strictly over, whatever the agent claims, before the runner error (L599, #116) | TASK-179 | met |
| RE2 only, multiline search, linear time (L600; security invariants) | TASK-177 | met |
| `eval_spec`: Operator and ExpectedResult manager-side only; no `execute`; strict parse (L587, L880, #117) | TASK-180 | met |
| Score = PASS ÷ (PASS + FAIL), NULL at 0; ERROR and Not run excluded (L602, #120) | TASK-181, 184 | met |
| Latest row = highest `reeval_id`, else original; SQL and pure rule agree (L601, #119) | TASK-181, 182, 184 | met |
| Re-evaluation: rows only added, one transaction, serialised per scan, one-statement definitions, chunked, intake details kept, dropped plugins left alone, one `scan.reevaluate` audit entry (L601, L1005–L1006, L1049; #12, #118) | TASK-183, 185 | met |
| Parameterised SQL only; nothing from stdout, stderr or tokens in logs (TS §8.1, L1052) | all | met (S608 plants red; canary suites) |
| TS §8.3 Unit and Integration ("re-evaluation adds rows only") | G62–G65 | met; "verdict uses the queued `eval_spec` after a catalog change" end to end is M9, proven here at API level (by design) |

## Gate report check
- G1–G6, G34 and G62–G65 PASS, each with a planted violation that turned it red.
  - G5 is 98.50 % in the final G18 run, and the plant brings it to 84.67 %.
  - G34 stays green on the route plant by design (decisions 2026-10-29 "M8 gate row G34"), with G6 carrying the no-route proof.
- G18 on the final tree (`-n 0`, `CI=true`, web build present): 10,228/10,228 passed, 0 failed, 0 errors, 0 skipped.
  - The M5 web tests had first failed without a web build. That build is git-ignored and made by CI, and M8 changes no web file. They pass with the build present.
- Mutation table: 45/45 red, and all 22 security rows red.
- NOT RUN items are by design, with their milestones named: M9 intake, M11 end to end, load deferred, and CI, which can't run without a push.

## Findings
1. **should-fix (gate), resolved in round 2.** G18 had a red test, CHK-M2-232 (`test_users_api_pg.py::test_sink_outage_refuses_every_method_after_15_minutes`), which was order-dependent and also failed alone on `67a6dfa`.
   - Cause (tester's probe): alone, `audit_log` was empty, so no outage started; in the full suite, a 3,000-row backlog couldn't drain in 5 fixed cycles.
   - Fixed test-only, with every assertion kept (above): alone 3/3, its file 31/31, `-n 2` with its neighbours 97/97, and G18 green.
2. **nit (tester), resolved.** `eval_spec.py` L92–93 is now covered by a 36-character non-hex `plugin_uuid` row. `eval_spec.py` is at 100 %.
3. **note for the PR (no change asked).** The full G18 under `-n 2` wasn't run locally: free memory was below the 3,000 MB floor. CI's `-n auto` run on the PR is the remaining check of the worker split.

## Carry-overs to later milestones (from the task reviews)
- **M9:**
  - the job builder stops a lone surrogate or U+0000 before writing `eval_spec` (JSONB refuses both, so the insert would fail with a 500; builder checklist item 1);
  - pin the TS §6.5 payload shape, which the counts SQL casts;
  - first-result-wins tests must see the deliberate double count in `host_counts`.
- **M11:** `POST /scans/{id}/reevaluate` must enforce admin, a TOTP-verified session and no API tokens, and must apply the 15-minute sink gate. The service has no check of its own.
- The M8 PR also carries the M2 test change (`manager/tests/test_users_api_pg.py`). Name it in the PR text as a test-only isolation fix (decisions "CHK-M2-232 test isolation fix").

## Builder checklist
No M8 finding recurred across tasks, so nothing is added to `work/reviews/builder-checklist.md`.
