# TASK-204 IMPL: agent job routes for compliance jobs

Implementer: impl-manager-m9b, 2026-10-30. REQ-213, REQ-214, REQ-215, REQ-216, REQ-229. Open items #124, PD-40. TS §8.2 second approval (PD-39).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/repositories/jobs.py` | `pull()` drops `AND kind = 'inventory'`: queued inventory and compliance jobs together, same lock, limit and order; docstrings say who builds which payload |
| `manager/bitscan_manager/services/jobs/pull.py` | `refuse_results(..., count_flood: bool = True)`; the flood counts the 409 reasons `job_not_acceptable` and `eval_spec_invalid` unless `count_flood` is False; docstring for M9 |
| `manager/bitscan_manager/services/jobs/__init__.py` | also exports `Accepted`, `Refused`, `accept_results` |
| `manager/bitscan_manager/api/agent/jobs.py` | the results route calls `accept_results()` in a thread; a `Refused` writes the refusal entry in its own transaction and answers 409; an `Accepted` logs counts and answers `{accepted, duplicates}` |
| `manager/openapi.json` | **not changed**: the export is byte-identical to the committed file, twice (no route shape, docstring or response changed) |

Diff: +99 / −38 over the four source files.

## How it meets the acceptance points

- **REQ-213 pull:** `UPDATE scan_job … FROM (SELECT job_id … WHERE agent_id = %(agent)s AND state = 'queued' AND pickup_by > %(now)s ORDER BY created_at, job_id LIMIT 10 FOR UPDATE SKIP LOCKED)`, kind no longer filtered, so 6 + 6 queued jobs give the 10 oldest and then 2; each is dispatched once with `dispatched_at`; cancelled, expired, other agents' and past-`pickup_by` jobs never match. The body is the stored `payload` only (never `eval_spec`), validated by `JobsResponse` (the `ComplianceJob` model, closed). Inventory pulls are unchanged (REQ-072 (1), (3), (5), (6)).
- **REQ-214 results:** the M3 order is unchanged (token check, `agent_uuid` for the path id, after-auth 1.5 MiB cap, gzip, 400 on a malformed body, 413 with a `too_large` entry). A well-formed batch goes to `accept_results(runtime.db, agent_id, job_id, batch, now=runtime.clock.now())`. On `Refused`: one `agent.result_refused` entry with `reason` = `job_not_acceptable` or `eval_spec_invalid` (#124 (h)), `results` and `final`, in its own transaction (`sink_gate.wake` on commit), then 409 `job_not_acceptable` "This job does not accept results.". The flood window is skipped only when `own_cancelled` (the agent's own cancelled job, #124 (f)); every other 409 counts, as in M3.
- **REQ-215 / REQ-216:** stored and decided by TASK-199 (one transaction, root then job lock, one INSERT).
- **REQ-229 (3):** an inventory job id on the results route is refused by `states.accepts_results` (kind check) → 409; the inventory route is unchanged.
- **Logs:** an accepted batch logs `result batch accepted` with `{"accepted", "duplicates"}`; `agent_id` and `job_id` come from the request context (`agent_id_var`, `job_id_var`). No stdout, stderr, command or expected value is logged or put in an entry.
- No new route, parameter or push path; no inventory switch.

## Gates (Windows, worktree venv)

- `ruff check`, `ruff format --check`, `mypy --strict` (Windows and `--platform linux`) on `manager/bitscan_manager`: green (175 files).
- On the whole `manager` tree, `ruff check` and `ruff format --check` currently fail **only in tester files** under `manager/tests/` (in-progress M9 suites: `test_job_states.py`, `test_intake_plan.py`, `test_job_build.py`, `test_cron.py`, `scan_pg_fixtures.py`, `agent_sim.py` and others, mostly E501 and one TID251 `xml.sax` import in `scan_pg_fixtures.py`). Not mine to edit.
- OpenAPI: `python -m bitscan_manager.app <tmp>` twice, both byte-identical to `manager/openapi.json`.
- Each changed module imports cleanly first in a fresh interpreter (`services.jobs` → `intake` → `repositories.job_intake` → `intake_plan`; no cycle failure).

## For the tester (PD-40)

- Superseded M3 checks: REQ-072 (4) (compliance job not returned) and REQ-073 (1) (every well-formed post 409). Everything else in the M3 suites should still pass (`test_jobs_api_pg.py` refusal entry, flood, 400, 413, no stdout in logs).
- `refuse_results` keeps its M3 call shape; `count_flood` is keyword-defaulted.

## Plants (mutation table)

- CHK-M9-378: put `AND kind = 'inventory'` back in `JobRepo.pull`.
- CHK-M9-379: return `payload || jsonb_build_object('eval_spec', eval_spec)` from `pull` (the closed `ComplianceJob` model and G30 must catch it).
- CHK-M9-380: pass `True` (or `False`) instead of `not outcome.own_cancelled`; or drop `eval_spec_invalid` from `_FLOOD_REASONS`.
- CHK-M9-328: covered with TASK-199 (inventory id accepted).

## Revision 1 (2026-10-30, lead's heads-up before review)

**Cause:** `services/jobs/__init__.py` imported `intake`. A package's `__init__` runs on every `import bitscan_manager.services.jobs.<x>`, so the pure modules (`states`, `scan_state`, `targets`, `build`, `intake_plan`) pulled in `repositories` and psycopg, against the M9 pure-module import rule.

**Fix:**
- `services/jobs/__init__.py` is back to its committed M3 content (`FLOOD_PER_10_MIN`, `pull_jobs`, `refuse_results`; `pull.py` imports only the standard library). It now has no diff against `d09c537`.
- `api/agent/jobs.py` imports `bitscan_manager.services.jobs.intake` directly and uses `intake.accept_results`, `intake.Accepted` and `intake.Refused`.

**Checked:**
- In a fresh interpreter (`python -I`), importing each of the five pure modules loads no `psycopg`, `bitscan_manager.repositories`, `bitscan_manager.db` or `bitscan_manager.api` module.
- `repositories.job_intake` and `services.jobs.intake` import without a cycle, and so does the app.
- Gates are green on `manager/bitscan_manager`. The OpenAPI export is still byte-identical to `manager/openapi.json`.

The files list above changes accordingly: `services/jobs/__init__.py` is no longer modified.

Plant: re-add `from bitscan_manager.services.jobs.intake import ...` to `services/jobs/__init__.py`. The pure-module import-graph tests (REQ-206 (5) and the like) must turn red.
