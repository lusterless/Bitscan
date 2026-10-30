# TASK-204 REVIEW: agent job routes for compliance jobs

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-213 to REQ-216, REQ-229 (3). High risk, full rigor. **PD-39: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-204-impl.md` (with r1):
- `manager/bitscan_manager/repositories/jobs.py`;
- `manager/bitscan_manager/services/jobs/pull.py`;
- `manager/bitscan_manager/api/agent/jobs.py`.

`services/jobs/__init__.py` is back to its `d09c537` content in r1 (no diff). `manager/openapi.json` is unchanged by this task (the export is byte-identical). The four source files changed by +99/−38.

TEST: PASS on r1 (`work/reports/TASK-204-test.md`). 20/20 end to end with the simulated agent, and the security, invariant, OpenAPI and contract run is 622/622. Plants CHK-M9-378, -379, -380 (two variants), -325 and -328 are red at route level. PD-40 (a) old-to-new: CHK-M3-247 is replaced by CHK-M9-221 and CHK-M3-249 by CHK-M9-225. Every other M3 assertion is unchanged. The REQ-226 oracle updates are CHK-M9-233 and -234.

Spec read: TS §6.1 L1064, L1065, L1069–L1072, §3.3 L203, L210–L214, L222, L224, §6.5 L1165–L1190, §4.4 L567, L578, L581, §8.4 L1287, L1291; #54 (c), #124 (a)–(h); PD-40.

My re-run (Windows): ruff and `mypy --strict` are clean on `manager/bitscan_manager` (178 files). In a fresh `python -I`, importing each of `states`, `scan_state`, `targets`, `build` and `intake_plan` loads no `psycopg`, `repositories`, `api` or `db` module.

## Checks
1. **Agent routes, `bsa_` only (TS §6, security invariant).** The router and its token dependency are unchanged. `bsu_` and `bsk_` get 401, and another agent's path gets 403 (CHK-M9-230). Builder checklist item 4 is still met: token check, then the path id (`agent_uuid`, hyphenated only), then the capped body read, then decode.
2. **Pull (REQ-213, TS §6.1 L1064, §3.3 L214).**
   - Only the `kind` filter is dropped. It keeps the same `SKIP LOCKED` dispatch-once, the 10-job limit, oldest first, and `pickup_by > now`.
   - The body is the stored payload, never `eval_spec` (CHK-M9-379 red).
   - The closed `JobsResponse` model is a second guard: an extra key would fail validation rather than reach the agent.
   - Inventory pulls are unchanged.
3. **No push or ad-hoc path.** No route, parameter or outbound call is added. The pull only hands out rows built by the scheduler, the scan queue or the sweep.
4. **Results (REQ-214, #124).**
   - A well-formed batch goes to `intake.accept_results`.
   - A `Refused` writes one `agent.result_refused` entry in its own transaction (reason `job_not_acceptable` or `eval_spec_invalid`) and answers 409 `job_not_acceptable` with fixed text (builder checklist item 12).
   - The flood is skipped only for the agent's own cancelled job (#124 (f), CHK-M9-227).
   - 400 and 413 behave as REQ-066.
5. **Logs (TS §8.4 L1287, REQ-230).** The accept line has `accepted` and `duplicates`, with `agent_id` and `job_id` from the request context. The canary through every path appears in no log line.
6. **r1, package init.** Importing the pure modules no longer pulls in the repositories or psycopg. That restores the M9 pure-module rule and removes the repository/service import cycle I noted in TASK-193.

## Findings
None open.

1. should-fix (raised before review, by `main` and in the TASK-186 and 193 reviews), **resolved in r1**: `services/jobs/__init__.py` re-exported `intake`, so every pure `services.jobs` module loaded repositories and psycopg. It's fixed by importing `services.jobs.intake` directly in `api/agent/jobs.py`. Verified above, and CHK-M9-271 is green.
