# M9 breakdown: the scan engine (jobs, scans, schedules, result intake)

Planner: planner-m9, 2026-10-30. Worktree `Bitscan-m9`, branch `m9-scan-engine`, from main `d09c537` (M8 merged). The M9 sections are appended at the end of `work/requirements.md`, `work/tasks.md` and `work/open-questions.md`. Phase A only: no code has been written.

## Counts

| Item | M9 range | Count |
| --- | --- | --- |
| Requirements | REQ-206 to REQ-233 | 28 (REQ-228 and REQ-231 are test requirements) |
| Micro-tasks | TASK-186 to TASK-208 | 23 (21 high risk, 2 low) |
| Test-plan items | TP-M9-00 to TP-M9-20 | 21 |
| Waves | W1 to W6, then the gate | 6 |
| New gates | G66 to G70 | 5 (plus G1–G6, G16, G18, G19, G30, G31, G33, G34 re-run) |
| Mutation rows | CHK-M9-320 to CHK-M9-382 | 63 (24 security rows) |
| New open questions | #121 to #129 | 9, plus #3, #18, #22, #12, #116, #117, #54 (c), #66 reused and two own-question markers now numbered |
| New process decisions | PD-39, PD-40 | 2 |
| Design plans | `TASK-198.md` (queue; 188, 189, 193 interfaces), `TASK-199.md` (intake; 186, 190, 195), `TASK-202.md` (sweep and scan state; 187, 194, 196), `TASK-203.md` (schedules; 191, 197, 201) | 4 |

Owners: impl-manager for 22 tasks; impl-web for TASK-207 (regenerate `schema.d.ts`).

**Migrations: none. Agent or contract change: none. New dependencies: none.** Seven user operations are added (`POST /scans`, `POST /scans/{id}/cancel`, five on `/scan-schedules`); both agent job routes change behaviour, not shape. M9 only updates the progress columns of `scan_job` and `scan`, never a result.

**Spec deviations: none.** Six spec-internal points are reported for the owner (open-questions "M9 spec-internal notes").

## What M9 builds

- **Job building** (`services/jobs/build.py`, `repositories/scan_queue.py`, `services/jobs/queue.py`): one compliance job per resolved host from the active plugins of an enabled, non-deleted policy, in one consistent snapshot (queue lock, policy `FOR SHARE`, one statement); payload exactly TS §6.5 with `pickup_by` and the redaction setting; M8's `eval_spec` at queue time; unstorable text refused (M8 carry); the payload shape pinned against M8's counts SQL (M8 carry); the newer job cancels the older queued one.
- **Targets** (`services/jobs/targets.py`): agents, tags (any of) or all; resolved at queue time; stored with `resolved_agents`.
- **Result intake** (`services/jobs/intake_plan.py`, `repositories/job_intake.py`, `services/jobs/intake.py`): root-then-job locks, first result wins across original and retry, one INSERT per batch with M8's `result_verdict()`, snapshots, `oversize` with empty streams, NUL and lone surrogates replaced (#121), 7-day late window, 409 for cancelled, foreign, inventory, queued, expired jobs and plugins outside the job; the `bitscan_plugin_results_total{result}` metric.
- **States and the sweep** (`services/jobs/states.py`, `scan_state.py`, `repositories/job_sweep.py`, `scan_progress.py`, `services/scheduler/sweep.py`): deadline, start notice, completed/partial/failed, the 24 h never-started rule, exactly one retry (original commands kept), scan state per host unit, scan refresh in the sweep.
- **Cancel** (`services/jobs/cancel.py`): manager-side only.
- **Schedules** (`services/scheduler/cron.py`, `schedules_admin.py`, `scan_schedules.py`, `repositories/schedules.py`): crontab(5) on APScheduler 3 with time zones, a 30 s tick, no back-fill (2-minute grace), the three skip rules.
- **Routes**: the agent pull and results (`api/agent/jobs.py`), `POST /scans` with `Idempotency-Key` and cancel (`api/user/scans.py`, `api/user/idempotency.py`), CRUD `/scan-schedules`.

## Waves

| Wave | Tasks | What |
| --- | --- | --- |
| W1 | 186–192 (pure), 193–197 (SQL) | every interface: states, scan derivation, targets, builder, intake plan, cron, idempotency; the five repositories; tester plan and fixtures |
| W2 | 198, 199, 200, 201 | queue, intake (+ metric), cancel and schedule-admin services |
| W3 | 202, 203, 204 | sweep steps and scan refresh; scheduled runs and the tick; agent job routes |
| W4 | 205 | scan routes |
| W5 | 206 | schedule routes |
| W6 | 207, 208 | web client regeneration; README |
| Gate | tester, reviewer | G66 to G70, re-runs, mutation table, closing review |

Files are disjoint within every wave; the only shared files (`api/user/__init__.py`, `manager/openapi.json`) are in different waves (PD-24). Two impl-manager instances can split W1 (pure versus SQL).

## Dependency spine

`{186, 190, 195} → 199 → 204`; `{188, 189, 193} → 198 → {203, 205}`; `{187, 194} → 200 → 205`; `{186, 187, 189, 194, 196} → 202`; `{188, 191, 197} → 201 → 206`; `192 → 205`; `{204, 205, 206} → 207`; `{205, 206} → 208`. Acyclic; interfaces in W1.

## Approvals (PD-39, recommended)

TS §8.2 second approval: TASK-204 (agent job routes) and the intake path behind it (TASK-190, 195, 199), applied under the pre-authorisation on a clean TEST PASS and APPROVED review. Lead's second look: TASK-189 and TASK-198 (the commands every host runs) and TASK-205 (RBAC and the API-token alert). No auth code changes.

## Top risks

1. **First result wins under concurrency.** A missing or misordered lock stores two results for one host and plugin. Mitigated by one lock order (root, then job) in intake and sweep, a 200-repetition barrier race, and M8's deliberate double count in `host_counts` as the detector (CHK-M9-320 to -322).
2. **An ad-hoc or stale command reaching hosts.** Commands come only from the catalog snapshot (or a retry's original); a policy delete or import racing a scan is closed by `FOR SHARE` and one snapshot statement; extra body keys are 400; a source grep pins who writes `payload`.
3. **State-machine edge cases with retries.** The spec's own rules conflict (an original stays `partial` after its retry completes; `cancelled` vs `failed`). #127 defines one unit rule; table and property tests cover it.
4. **No `scan_job` index on `scan_id` or `retry_of`** (the DDL is fixed). Scan derivation runs once per sweep (≤ 60 s lag in scan state and `finished_at`) and the retry lookup only for posts to `failed`, `partial` or `completed` originals (#127 (f)). Load is deferred, so the cost at 10,000 hosts is unmeasured.
5. **APScheduler 3 cron semantics differ from crontab(5)** (weekday numbering, day-of-month/day-of-week combination, DST). Translated weekdays and both day fields refused (#128); DST per the user's decision of 2026-10-30 (gap run shifted, repeat run once; TASK-191 r1), pinned by tests.
6. **M3 checks superseded** (pull inventory-only, results always 409). Rewritten by requirement with an old → new CHK list (PD-40), never silently dropped.
7. **Output leaks.** stdout, stderr, `execute` or expected values in logs or audit detail; a canary suite covers every M9 path.

## Open questions and recommendations

None blocks the planning; all have recommended answers the lead may apply (pre-authorised).

| Item | Recommendation | Needed by |
| --- | --- | --- |
| #121 NUL / lone surrogate in stdout, stderr | Accept; caps on received text; replace with U+FFFD; evaluate and store the replaced text; no contract change | W1 |
| #122 route bodies and statuses | TS §6.4 202 body; targets 1–10,000 agents / 1–32 tags / `all: true`; unknown ids dropped; `scan.target` + `resolved_agents`; 404 unknown, 409 disabled or deleted (answers `api.md:44`), 422 zero agents; cancel 200 idempotent; schedule CRUD with `policy_id` fixed; operator on every route | W1 |
| #123 `Idempotency-Key` | Per user and key, in memory 24 h, same body → first 202, other body → 409, concurrent → one scan, only 202 remembered | W1 |
| #124 intake details | Accepting states and 7-day boundary inclusive; whole batch 409 for a foreign plugin; one transaction root→job; start notice on ended job is a no-op; manager clock; cancelled-job 409s not counted toward the flood | W1 |
| #125 job building | Active plugins in `sort_order`; setting patterns at queue time; queue lock + `FOR SHARE` + one snapshot; only new scans cancel older queued jobs; unstorable text refused (500) | W1 |
| #126 retries | Original's commands and patterns for the missing plugins; same transaction as the deadline end; none for deleted policy or decommissioned agent; made for a disabled policy | W1 |
| #127 states | Unit rule (original + retry); strict boundaries; scan derivation per unit; cancelled after results → `partial` (answers `jobs-and-scans.md:40`); refresh in the sweep, inline on create and cancel | W1 |
| #128 schedules | crontab(5) translated for APScheduler; both day fields refused; IANA zones; DST (b) superseded by the user's decision (gap shifted, repeat once); 30 s tick, 2 min grace, three logged skip rules; scheduled scans by `system`; create and enable take the policy `FOR SHARE` (decisions "M9 builder rulings" (5)) | W1 |
| #129 audit and metric | `scan.create`, `scan.cancel`, `scan_schedule.*`; alert kind `all_hosts_scan_api_token` on the `scan.create` entry; `bitscan_plugin_results_total{result}` | W2 |
| #3, #18, #22 and the others reused | As agreed (422 for zero agents; disabling cancels nothing; `running` once a job left `queued`) | W1 |
| PD-39 approvals | As above | W1 |
| PD-40 superseded M3 checks | Tester rewrites only those checks with an old → new list | W3 |

Full text, sections and alternatives: `work/open-questions.md`, section "M9".

## Coverage

Covered: TS §2.2 pull-only, first result wins, immutable results; §2.3 steps 1–3, 5, 6; §3.3 pull rules, sweep timeouts and retries, the start notice, answers to posts; §3.5 job content; §4.1 L530 queued jobs keep commands; §4.3 disable and delete effects on jobs and schedules; §4.4 entirely; §4.5 storing results with verdicts and snapshots (L587, L593, L599, L603); §5.2 scanning tables and grants; §5.3 L1052; §6.1 job and result routes; §6.2 `POST /scans`, cancel, CRUD `/scan-schedules`, no ad-hoc command or inventory disable; §6.3 problems, paging, `Idempotency-Key`, caps; §6.4; §8.1 unintended commands, rogue agents, SQL injection; §8.3 Unit, Integration, Security ("first result wins under concurrent retries"), Contract; §8.4 plugin ERROR rate, the all-hosts API-token alert, the threshold alerts with compliance jobs; plus the M8 carry-overs (unstorable text, payload shape, the double count, "verdict uses the queued `eval_spec` after a catalog change" end to end).

Uncovered by design, with the milestone:
- **M10:** the runner, sandbox, redaction, truncation and the `truncated` flag; real plugin execution (M9 uses simulated agents from the contract fixtures).
- **M11:** `GET /scans`, `GET /scans/{id}`, `/scans/{id}/results(.csv)`, `GET /agents/{id}/scans`, `POST /scans/{id}/reevaluate`, scan and schedule screens, CSV exports, the score display, the nightly end-to-end run, and scan retention (TS §5.3 L1047). No M9 acceptance test needs these routes, which is why they stay in M11.
- **Deferred by the user:** load tests (the cost of the full `scan_job` reads at fleet scale).

## Files written by the planner

- `work/requirements.md` (section "M9 scan engine")
- `work/tasks.md` (section "M9 scan engine": design notes D1 to D4, tasks, owner notes, test plan, waves, gate, mutation table, open items, coverage)
- `work/open-questions.md` (section "M9")
- `work/plans/TASK-198.md`, `work/plans/TASK-199.md`, `work/plans/TASK-202.md`, `work/plans/TASK-203.md`
- `work/plans/M9-breakdown.md` (this file)
