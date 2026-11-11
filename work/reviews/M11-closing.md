# M11 closing review (gate)

Reviewer: reviewer-m11, 2026-11-09. Round 1.

Verdict: CHANGES_REQUESTED. Do not merge yet. One blocking finding (REQ-275 and REQ-276 are not met at fleet size), and one gate exception needs the user. Everything else in the gate is approved.

## Scope reviewed

- **Gate report:** `work/reports/M11-gate-test.md` (tester-m11g, tree `c090303`, docs re-runs on `c62da73`).
- **Gate test changes:**
  - `manager/tests/test_security_m11.py` (new, TP-M11-15, G83, 1,052 lines);
  - the CHK-M9-276 (M11) rewrite in `manager/tests/test_security_m9.py` (PD-51);
  - the binding note in `tests/m11/test-plan.md`.
- **Task reviews:** all 29 M11 task reviews in this folder (TASK-232 to TASK-260) are APPROVED, with no open blocking or should-fix finding.
- **Checked against:** the M11 gate table and the NOT RUN rule in `work/tasks.md` ("M11 gate"), `.claude/rules/testing.md`, the security invariants, decisions 2026-11-08 and 2026-11-09.

## What I checked myself

- **Frozen-file pins:** all 38 pins in `test_security_m11.py` (`FROZEN`) match `git show 6efe0fb:<path> | sha256sum`; 0 mismatches. The frozen folders gain no file except the three M11 `services/jobs` modules.
- **CHK-M9-276 (M11):**
  - It is still an equality. M9's seven operations plus exactly M11's five under `/scans` (`GET /agents/{id}/scans` is outside the prefix, as the comment says).
  - The five are now also checked to take no request body.
  - Every earlier body and parameter assertion is kept, and loops over all twelve operations.
  - The sixth-operation plant is red.
  - This is a correct PD-51 rewrite.
- **G83 suite:** it re-uses the task suites' worlds and is not tautological.
  - The one-writer row parses SQL strings, not docstrings, and checks the AST for `reevaluate_scan` references.
  - The token-group row puts a `bsa_`/`bse_` hash in `user_token` and a `bsk_`/`bsu_` hash in `agent`. That isolates the per-router prefix check (TS §6, security invariant "enforce this per router"); it is not a hash miss.
  - The retention row builds the runner as `serve` does, with both pools, and spies `current_user`.
  - Lint: `ruff check` and `ruff format --check` on both test files are clean.
  - The CODE rows I ran on Windows: 35 passed and 16 failed, all S608 and `re`-ban rows. Every failure is a Windows encoding artefact (finding 4), not a product or test-logic fault. The gate ran them in WSL, as the rules require.
- **Plant -322 green in G83:** accepted. The planted `stdout: null` in the service mapping is dropped by the route's viewer model `ScanResultItem` before any byte reaches a viewer. G83 tests what a viewer can observe, and nothing is observable there. The mutation table lists -322 as red in G80 and G82, not G83, and it is red in both: TASK-233's view rows and TASK-244's `-322-route` variant. Two layers stand between the fault and a viewer. That is the defence in depth plan TASK-235 §3 asked for.
- **The G30 and G33 plant-form notes:**
  - The heartbeat-request plant form is caught by G6 rather than G30, and the response form is caught by G30.
  - -341 is not observable in G33's sweep suites and is red in G81 and G83.
  - Both are honest notes on where each fault is caught. No gate is lowered, and the planner can fix the table wording.
- **The rest of the gate:**
  - G1 to G6, G12 to G16, G18 (11,908/11,908, 0 skipped), G19, G30 to G34, G37, G38, G40, G41, and G80 to G84 are each green, each with its plant red. G85 to G87 cite the hosted runs, with the G87 plants -373 and -374 red.
  - Services coverage is 98.5920 %.
  - The one G18 timing flake (`test_bit_parse` 35,015 elements under shared WSL load) passed twice alone. It is recorded, not hidden.

## Findings

1. **blocking: CHK-M11-387, retention at fleet size (REQ-275, REQ-276; TS §5.3 L1049; #151).**
   - **The finding:** tester-m11t measured that each deleted `scan_job` costs a sequential read of `scan_job` (`retry_of` self-reference, no index) and of `scan_result_reeval` (`job_id` FK, `ON DELETE CASCADE`, no index). As a result:
     - one 1,000-job inventory chunk is cancelled at the 300 s `statement_timeout`;
     - so is one scan of about 1,000 hosts, a single `DELETE FROM scan` statement.
   - **Consequences:**
     - Inventory jobs are never deleted.
     - A fleet scan of more than about 600 hosts can never be deleted. Because it is the oldest, every later scan stays behind it.
     - This is not the "slow but working" retention the user accepted for v1 (decisions 2026-11-08 (2)). REQ-275 (1) does not hold at fleet size.
   - **For the decision:** the user's fallback in decisions 2026-11-09 (3), halving `SCAN_CHUNK`, does not fix this.
     - The cost is per job, not per scan. A chunk of one large scan is already one statement over the limit, and `SCAN_CHUNK` can't go below one scan.
     - A smaller `JOB_CHUNK` would help inventory only while the table stays small, since each job's cost grows with table size.
   - **The fixes I can see all need the owner:**
     - (a) #151 option (b): amend TS §5.2 with `CREATE INDEX ON scan_job (retry_of)`, `ON scan_job (scan_id)` and `ON scan_result_reeval (job_id)`, plus a migration. This is a spec edit and is outside M11's "no migration" rule.
     - (b) Delete a large scan's jobs in batches over several transactions before the scan row. TS §5.3 says whole scans are "deleted together", so this needs the owner's reading of "together".
     - (c) A separate, longer `statement_timeout` for the retention pool. This only delays the problem as the tables grow.
   - **Recommendation:** (a). It is the only option that bounds the cost, and it is the one #151 already named.
2. **should-fix (process, for the merge): G39 NOT RUN after a safety-check refusal.**
   - The tester stopped at the refusal and did not work around it, which is right.
   - Under the M11 gate rule (`work/tasks.md`, "M11 gate": "M11 does not merge with such a row until the user decides whether it is a gate exception", the M10 rule), the user must decide. They can accept the PR's `package.yml` "Double build is byte-identical" job as the cover, given that the agent source is unchanged since M10's identical builds. This is not a defect in the tree.
3. **should-fix (process, for M12): no full manager suite ran at the wave ends.**
   - The speed rules ask for the full suite per wave and at the gate.
   - Only targeted runs were recorded, so the stale CHK-M9-276 (red since TASK-232 in W1) was first seen here. It is resolved now by the PD-51 rewrite and G18's 11,908/11,908.
   - It is listed so the next milestone runs G18 at each wave end. Nothing to change in M11's tree.
4. **nit: `manager/tests/test_security_m11.py:331` `ruff()` runs `subprocess.run(..., text=True)` with no `encoding`.**
   - On Windows, stdin is encoded as cp1252. A module with non-ASCII text, such as `§` in docstrings, then reaches ruff as invalid UTF-8 ("stream did not contain valid UTF-8"), so the S608 and `re`-ban rows fail locally.
   - These rows are Linux-run by rule and green in WSL and CI. `encoding="utf-8"` on that call would make them portable.
   - Builder checklist 19 is the same kind of Windows-only test trap.
