# M9 test plan (scan engine: jobs, scans, schedules, result intake)

Owners: `tester-m9` (TP-M9-00, the pure modules TASK-186 to -192, the property suite, the low-risk batch TASK-207 and -208) and `tester-m9b` (PostgreSQL, routes, races, security suite and the gate: TASK-193 to -206, TP-M9-01, TP-M9-10 to -20). Written 2026-10-30 by tester-m9 from `work/tasks.md` "M9 scan engine" (TASK-186 to TASK-208 acceptance tests, design notes D1 to D4, TP-M9-00 to TP-M9-20, gate G66 to G70, mutation table CHK-M9-320 to -382), `work/requirements.md` REQ-206 to REQ-233, `work/plans/M9-breakdown.md`, `TASK-198.md`, `TASK-199.md`, `TASK-202.md`, `TASK-203.md`, the approved answers in `work/open-questions.md` "M9" (#121 to #129, PD-39, PD-40; #3, #18, #22, #12, #116, #117, #54 (c), #66 reused; `work/decisions.md` 2026-10-30: every recommended answer applies) and the spec (TS §3.3–§3.5, §4.1 L530, §4.3 L547–L550, §4.4 L555–L583, §4.5, §5.2 scanning tables and grants, §6.1–§6.5, §8.3, §8.4; SR §1.1). Written **before any M9 product code was read**: names below are the interfaces of the plans' §2 and §3; where the code names something differently the row keeps its expected value and the report says which name it bound to. Results go to [report.md](report.md) (folded by `main` from `work/reports/TASK-###-test.md`).

`bm/` means `manager/bitscan_manager/`; `mt/` means `manager/tests/`; `jobs/` means `bm/services/jobs/`.

## Conventions

- Type: **CODE** = static gate, unit or property test on the tree (no database). **APP** = the real code against a real PostgreSQL 16 through the Testcontainers harness (M1 bootstrap from TS §5.2, then `bitscan-manager db migrate`), or through the real routes.
- Where: **L** = Windows 11 + Git Bash, worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m9` (ruff, `ruff format`, `mypy --strict` only). **W** = WSL2 Ubuntu 24.04 (`wsl -d Ubuntu-24.04 -u root`), each tester in its own copy and venv: tester-m9 `/root/bstest-m9-<label>` with `/root/venv-m9`; tester-m9b its own. Tree copied without `.venv`, `node_modules`, `__pycache__`; `pip install --require-hashes -r manager/requirements-dev.txt`, then `pip install --no-deps -e <copy>/manager`; `PYTHONPATH` pinned to the copy; `CI=true` (nothing skipped); every run under `timeout`. **Python tests run on W only.** Unit runs use `-n 0`; Windows free memory ≥ 2,000 MB before a run (another tester runs PostgreSQL in parallel). **CI** = GitHub Actions only.
- PostgreSQL rows connect as `bitscan_app` for product code. Catalog, agents, scans, jobs and results that the code under test does not write are written by the test as **owner** through the TP-M9-01 builder.
- **Row checksum** = `md5(string_agg(t::text, '|' ORDER BY <pk>))` per table, read as owner. "Unchanged" = equal checksums.
- **Canary** = a fixed unique string `M9CANARY-<uuid4>` placed in `execute`, the expected value, stdout, stderr (and a redaction pattern) of fixture rows and requests; "leaves no trace" = absent from every `caplog` record (message and args), `capsys` out/err, every raised exception's `str()`/`repr()`, every audit `detail` and every API answer that is not a result view.
- **Time** is never waited out (decisions 2026-10-26): pure functions take the instant as an argument; services take `now` or a clock double. **Races** use two connections or threads at a `threading.Barrier` or a held lock, with a lock-wait probe on `pg_locks` / `pg_stat_activity` (`wait_event_type = 'Lock'`) polled at 20 ms with a 10 s bound; never a sleep for ordering.
- **Planted violations** are made in a throwaway copy (`/root/bstest-m9-mut-<id>` on W; `$TEMP/m9t-mut-<id>` on L for ruff and mypy rows), never in the worktree. The unmodified copy is green first. "Red" = non-zero exit **and** the named test fails for the planted reason.
- **Results are totals**: `passed/total`, plus failed, errors, skipped. A failing test is re-run alone by node id after the fix, as its own row (`1/1 passed`).
- Every expected value comes from the spec or an approved answer, never from the implementation. A behaviour the spec leaves open is **recorded, not asserted** and listed under "Questions".

## Expected values (spec and approved answers)

| Item | Expected | Source |
| --- | --- | --- |
| Job states | `queued`, `dispatched`, `running`, `completed`, `partial`, `failed`, `cancelled`, `expired`; final = {`completed`, `expired`, `cancelled`} | TS §4.4 L562–L582; REQ-206 |
| Allowed transitions | `queued → dispatched \| expired \| cancelled`; `dispatched → running \| failed \| cancelled`; `running → completed \| partial \| failed \| cancelled`; `failed \| partial → completed \| partial`; nothing else (a first batch on a `dispatched` job may go `dispatched → running → completed/partial` in one batch) | REQ-206; #127 (a) |
| Batch outcome | `dispatched` + any accepted batch → start (set `started_at`, `deadline_at` once); then `completed` if every plugin has a result (job or sibling), else `partial` if final, else `running`. `running` → `completed` / `partial` (final) / `running`. `failed`/`partial`: stored 0 → unchanged; else `completed` if all, else `partial`. `completed` → `completed`. Any other state refused | #127 (a); #124 (d); plan TASK-199 §2 |
| Deadline outcome | all have results → `completed`; some → `partial`; none → `failed` | #127 (b) |
| Deadline | `started + ceil(Σ timeout_s ÷ max_parallel_plugins) s + 600 s`, integer arithmetic; Σ95/2 → +648 s; Σ30/8 → +604 s; Σ3,000,000/1 → +3,000,600 s; `max_parallel_plugins` ∉ 1–8 or empty list → `ValueError` | TS §4.4 L575; REQ-206 (2) |
| Acceptance | compliance only; states `dispatched`, `running`, `failed`, `partial`, `completed`; `now ≤ dispatched_at + 7 days` (exactly 7 days accepted, + 1 µs refused); `queued`, `expired`, `cancelled`, inventory refused at any time | TS §6.1 L1071, §4.4 L578; #124 (a); REQ-206 (4) |
| Sweep boundaries | strictly past: `deadline_at < now`; never started `dispatched_at < now − 24 h` (at exactly 24 h nothing changes) | #127 (b); REQ-218 (2) |
| `finished_at` (job) | set on every entry into `completed`, `partial`, `failed`, `expired`, `cancelled`, and again on a late change | #127 (c); REQ-217 (6) |
| Scan derivation | per unit (original + retry). Some unit open → `queued` if every job is `queued`, else `running` (#22); else `completed` if every unit complete; else `partial` if any unit has results; else `cancelled` if any job cancelled; else `failed`. Never `dispatched` or `expired`. finished ⇔ no unit open. Empty unit list → `ValueError` | #127 (d); #22; #3; REQ-207 |
| Scan `finished_at` | set the first time no unit is open; kept when late results change the state; never cleared | #127 (e) |
| Targets | exactly one key. `agents`: 1–10,000 distinct UUIDs, hyphenated 8-4-4-4-12 only, stored lowercase. `tags`: 1–32 distinct, each 1–64 chars of `[A-Za-z0-9._:-]`. `all`: `true` only (a JSON boolean). Anything else → `InvalidTarget`, fixed message naming `target`, no input quoted | TS §4.4 L555; #122 (b); #68 |
| Resolution | status not `decommissioned`, not `awaiting_approval` (`enrolled`, `online`, `stale`, `offline` kept); tags any-of; unknown ids dropped; distinct, sorted | #122 (c); REQ-208 (3) |
| `scan.target` | the request object (agent ids lowercase) plus `"resolved_agents": [sorted lowercase uuid strings]` | #122 (d); REQ-208 (4) |
| Job payload | exactly `{job_id, agent_id, kind: "compliance", pickup_by, plugins, redaction_patterns}`; `job_id` = row id; plugins `{plugin_uuid (lowercase), execute, timeout_s}` = the active plugins in `sort_order`; `redaction_patterns` = the setting at queue time in stored order; `pickup_by` = `created_at` + 24 h as `YYYY-MM-DDTHH:MM:SSZ` (UTC, sub-second part dropped, so at most 1 s earlier than the column) | TS §6.5 L1165–L1182; #125 (a)–(c); REQ-209 (1) |
| Never in a payload | `operator`, `expected`, `expected_result`, `eval_spec`, `name` at any depth | TS §3.5 L248; REQ-209 (2) |
| `eval_spec` | `build_eval_spec()` of the same plugins in the same order; `name` = `v_plugin.display_name` (`<family name> - <plugin name>`) | #117; #125 (a); REQ-209 (3) |
| Unstorable text | U+0000 or a lone surrogate in any `execute`, name, expected or pattern → `UnstorableText` with one fixed message, nothing written; route 500 `about:blank` | #125 (g); REQ-209 (4) |
| SR §1.1 | family `CIS Ubuntu 24.04`, plugin `1.3.1.1 - Ensure AppArmor is installed`: name `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed`, operator `equals`, expected `install ok installed`; stdout `install ok installed` exit 0 → PASS; `""` exit 1 → FAIL | SR L87; REQ-209 (6); REQ-215 (6) |
| Retry | new job, same scan and agent, `retry_of` = original; only the original's plugins with no result in the unit, original order, original `execute`, `timeout_s`, `redaction_patterns`; matching `eval_spec` entries; new `job_id` (= row id); `pickup_by` = creation + 24 h; retry of a retry, or with nothing missing → `ValueError`; made in the deadline/never-started transaction; never for a `partial`-by-final-batch job, a retry or an inventory job; not when the policy is deleted or the agent decommissioned; made when the policy is only disabled | TS §4.4 L577, §4.1 L530; #126; REQ-210, REQ-218 |
| Intake plan | membership first (any uuid not in the payload or the `eval_spec` → whole batch refused); duplicates = in the unit's existing results or earlier in the batch (first in batch order wins); `accepted + duplicates = len(items)`; verdict = `result_verdict(entry, item)` with caps measured on the **received** text; `oversize` → stdout and stderr `""`; otherwise U+0000 and every lone surrogate (U+D800–U+DFFF code point) in stdout and stderr → U+FFFD, and the verdict is computed on that replaced text; snapshots `name`, `operator`, `expected` from `eval_spec`, `execute` from the payload | #121; #124 (a), (b); #116 (d); TS §4.5 L587, L599, L603; REQ-215, REQ-216 |
| Caps | stdout 65,536 UTF-8 bytes stored as sent, 65,537 → ERROR `oversize`; stderr 16,384 / 16,385 likewise | TS §4.5 L599; #116 |
| Runner errors | `runner_unavailable`, `spool_overflow` → ERROR with that detail | #12; #74; REQ-215 (3) |
| Cron | five-field crontab(5), ≤ 64 chars, ASCII; `*`, lists, ranges, steps, month and weekday names; weekday 0 and 7 = Sunday; no seconds, no `@` macros; both day fields restricted → refused; a cron that never fires → refused; `InvalidSchedule` with `field` `cron` | #128 (a), (c); REQ-223 (1), (3) |
| Time zone | IANA name known to `zoneinfo`, ≤ 64 chars, default `UTC`; `localtime`, paths, `..`, unknown → `InvalidSchedule` field `timezone` | #128 (b); REQ-223 (3) |
| `next_fire` | strictly after the given instant (also when the instant is a fire time); UTC-aware | #128 (d); REQ-223 (4) |
| DST (to record) | recommended reading: a local time that does not exist that day is skipped; a repeated one fires once. Record APScheduler 3.11's answer; a difference goes to `main`, the test is not adjusted | #128 (b); decisions 2026-10-30 |
| Idempotency | key optional, 1–255 printable ASCII (else 400); scope = user + key; 24 h in memory; ≤ 100,000 entries, oldest dropped first; same key + same parsed body → first 202 and body, no second scan, no second audit entry; same key + other body → 409 "Idempotency-Key was used with a different request."; concurrent repeat waits on a per-key lock (one scan); only 202 remembered | #123; REQ-222 |
| Routes | `POST /api/v1/scans` (operator; `bsu_`/`bsk_`) → 202 `{scan_id, state: "queued", policy_version, jobs}`; unknown policy 404; disabled 409; deleted 409; zero agents 422 `about:blank` "The target resolves to no host."; no active plugin 409; bad target or extra key 400; body > 1 MiB 413. Cancel `POST /api/v1/scans/{id}/cancel` → 200 `{scan_id, state, cancelled_jobs}`, idempotent (`cancelled_jobs: 0`), unknown 404, malformed id 400. Schedules CRUD `/api/v1/scan-schedules` per #122 (h), operator on every method, `policy_id` immutable (PATCH 400) | #122; #3; #48; REQ-221, REQ-224 |
| Audit | `scan.create` (actor `user:<id>` or `system`; target `scan:<id>`; detail keys exactly {`policy_id`, `policy_version`, `trigger`, `schedule_id`, `target_kind`, `jobs`, `cancelled_older`}), `scan.cancel` ({`cancelled_jobs`}), `scan_schedule.create`/`update`/`delete` (target `scan_schedule:<id>`). All-hosts + `bsk_`: the `scan.create` entry carries `detail.alert = true` and kind `all_hosts_scan_api_token`; never for a session, a tag target or a scheduled scan. No job, retry, batch or schedule-skip entry | #129 (a), (b); #128 (g); REQ-227 |
| Metric | `bitscan_plugin_results_total{result}` with `PASS`, `FAIL`, `ERROR`, each from zero; incremented after commit by rows inserted; no other label | #129 (c); REQ-226 |
| Refused post | 409 `job_not_acceptable`, nothing stored, no job change, one `agent.result_refused` entry (`reason`, `results`, `final`; never stdout/stderr); `eval_spec_invalid` reason for an unreadable `eval_spec`; a 409 for the agent's own `cancelled` job is not counted toward the flood (21 in 10 min → one `result_409_flood`) | #124 (a), (f), (g), (h); #54 (c); REQ-214 |
| Grants | `bitscan_app` cannot UPDATE `scan_job.agent_id`, `scan_id`, `payload`, `eval_spec`, `retry_of`, nor `scan.policy_id`, `policy_version`, `target`; cannot UPDATE or DELETE `scan_result` | TS §5.2 L1005–L1013; REQ-230 (3) |

## Gate map

| Gate | Checks |
| --- | --- |
| G1–G4 ruff (S608, `re` ban), ruff format, mypy --strict, hashed locks | CHK-M9-300, -301; plants -376, -383 |
| G5 services coverage ≥ 85 % incl. `services/jobs` and the new scheduler modules (W) | CHK-M9-302 |
| G6 OpenAPI byte-identical | CHK-M9-303 |
| G16 web client regenerated with no diff | CHK-M9-280 to -283 |
| G18 full W run, 0 skipped, `-n auto` | CHK-M9-305 |
| G19 schema diff (no migration) | CHK-M9-306 |
| G30 agent contract suite unchanged | CHK-M9-307 |
| G31, G33 M3 agent-auth and sweep/inventory suites | CHK-M9-308 |
| G34 route walk with the seven M9 operations | CHK-M9-309 |
| G66 M9 unit suite | CHK-M9-001 to -079 |
| G67 property suite | CHK-M9-080 to -099 |
| G68 M9 integration on PostgreSQL | CHK-M9-100 to -219 |
| G69 races and security | CHK-M9-150 to -152, -170 to -172, CHK-M9-270 to -279 |
| G70 API suites | CHK-M9-220 to -269 |

## TP-M9-02: job state rules (TASK-186; REQ-206, REQ-217 at rule level) — `mt/test_job_states.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-001 | CODE | `FINAL` is exactly {`completed`, `expired`, `cancelled`} and immutable; the accepting set (if exported) is exactly {`dispatched`, `running`, `failed`, `partial`, `completed`}; `get_args(JobState)` is the eight TS §4.4 states (matching the `scan_state` enum of TS §5.2 minus nothing) | W |
| CHK-M9-002 | CODE | Transition table: the module's set of allowed (from, to) pairs equals exactly the REQ-206 set (14 pairs: q→d, q→e, q→c, d→r, d→f, d→c, r→co, r→p, r→f, r→c, f→co, f→p, p→co, p→p); every one of the other 64 − 14 ordered pairs of the eight states (incl. self-pairs other than p→p, e.g. r→r, co→co as a *transition*) is refused (raises or returns False, whichever the interface does, consistently) | W |
| CHK-M9-003 | CODE | (state × event) table, REQ-206 (1): pull, empty batch, non-empty batch {final, not final} × {all have results, not}, deadline passed {none, some, all}, 24 h passed, cancel, pickup passed — for each of the eight states, the outcome is the #127 answer or a refusal. Encoded as an explicit expected table in the test (one row per pair, ≥ 8 × 10 rows), not computed | W |
| CHK-M9-004 | CODE | `after_batch` from `dispatched`: `start` True for an empty batch and for a non-empty one; state `running` (not all, not final), `partial` (final, not all), `completed` (all; also when `final` is False) | W |
| CHK-M9-005 | CODE | `after_batch` from `running`: `start` False (a second start notice changes neither `started_at` nor `deadline_at`, CHK-M9-334); `running` / `partial` (final) / `completed` (all); a non-final batch with plugins missing stays `running` (CHK-M9-337) | W |
| CHK-M9-006 | CODE | `after_batch` from `failed` and `partial`: `stored=0` → state unchanged and `start` False, whatever `final` and `all_have_results` say; `stored>0`, not all → `partial`; all → `completed`; REQ-217 (4): `failed` + non-final batch storing 1 of 3 → `partial`; the other 2 → `completed` | W |
| CHK-M9-007 | CODE | `after_batch` from `completed` → `completed`, `start` False, for every flag combination (CHK-M9-338); from `queued`, `expired`, `cancelled` → raises (callers check acceptance first) | W |
| CHK-M9-008 | CODE | `after_deadline`: (any=False, all=False) → `failed`; (True, False) → `partial`; (True, True) → `completed`; (False, True) is not a reachable input (record what happens; not asserted) | W |
| CHK-M9-009 | CODE | Deadline rows REQ-206 (2): Σ95 s with 2 → start + 648 s; Σ30 s with 8 → start + 604 s; Σ3,000,000 s (5,000 × 600) with 1 → start + 3,000,600 s exactly (equal `timedelta`, microseconds 0); ceil boundaries: Σ4/2 → +602 s, Σ5/2 → +603 s, Σ1/8 → +601 s, Σ8/8 → +601 s, Σ9/8 → +602 s; start with microseconds kept (start 12:00:00.123456 → deadline .123456); an aware non-UTC start gives the same instant | W |
| CHK-M9-010 | CODE | Deadline refusals: `max_parallel_plugins` 0, −1, 9, 100 → `ValueError`; 1 and 8 accepted; empty timeouts (list and tuple) → `ValueError`. Recorded, not asserted: `True` as `max_parallel_plugins`, a 0 or negative timeout | W |
| CHK-M9-011 | CODE | `accepts_results` REQ-206 (4): with `dispatched_at = D`, for each accepting state: `now = D`, `D + 7 d − 1 µs`, `D + 7 d` → True; `D + 7 d + 1 µs`, `D + 7 d + 1 s` → False. `queued`, `expired`, `cancelled` → False at `now = D` and at `D + 1 s`; kind `inventory` in every state → False; `dispatched_at` None → False; `now` before `D` → True (record) | W |
| CHK-M9-012 | CODE | Constants: `LATE_WINDOW == timedelta(days=7)`, `DEADLINE_SLACK == timedelta(minutes=10)` (if exported; else covered by -009/-011) | W |
| CHK-M9-013 | CODE | REQ-206 (5) import graph (AST over `jobs/states.py`): no import of `bitscan_manager.db`, `.repositories`, `.api`, `psycopg`, `logging`, `re`; no call to `datetime.now`, `datetime.utcnow`, `time.time`, `time.monotonic`, `date.today`; no `open`. Same check for every W1 pure module (`scan_state`, `targets`, `build`, `intake_plan`, `services/scheduler/cron.py`, `api/user/idempotency.py` — the latter may import `threading`, takes its clock as an argument) | W |
| CHK-M9-014 | CODE | Functions do no I/O: under a `sys.addaudithook` probe, 500 calls covering every branch of `states` see no `open`, `socket.*`, `subprocess.Popen`, `os.system` | W |

## TP-M9-03: scan state derivation (TASK-187; REQ-207) — `mt/test_scan_state.py`

`Unit(open, complete, has_results, any_cancelled, all_queued)`; `derive(units) -> (state, finished)`.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-015 | CODE | REQ-207 (1) table, each row as units built from job facts by a test helper (states of the original and retry, plugins with results): every job queued → (`queued`, False); one of two jobs dispatched → (`running`, False) (#22); one expired + one queued → (`running`, False); every unit complete → (`completed`, True); an original `partial` whose retry completed the missing plugins → that unit complete → `completed`; one unit complete + one failed without results → `partial`; no results + one cancelled → `cancelled`; no results, expired + failed, nothing cancelled → `failed`; cancelled after some results → `partial`; cancelled after every unit was complete → `completed` (CHK-M9-360) | W |
| CHK-M9-016 | CODE | Unit rule (CHK-M9-361): one host's original `partial` + retry `completed` covering the rest is **one** complete unit (scan `completed`), not "one job not completed" (`partial`); an original `failed` + retry still `queued` is open (`running`, not finished) | W |
| CHK-M9-017 | CODE | `queued` vs `running`: one unit open with `all_queued` and another unit closed (expired) → `running`; all units open and all queued → `queued`; a unit with its original ended and its retry queued → not `all_queued` → `running` | W |
| CHK-M9-018 | CODE | `cancelled` vs `failed` overlap (#127 (d)): no results, one unit cancelled, one expired → `cancelled`; no results, nothing cancelled → `failed`; results in any unit beat `cancelled` (`partial`) | W |
| CHK-M9-019 | CODE | REQ-207 (3): `derive([])` → `ValueError`; a tuple and a list of units give the same answer | W |
| CHK-M9-020 | CODE | The returned state is a member of the six scan states and never `dispatched`/`expired`, over all 2⁵ fact combinations of one unit and all pairs of two units (exhaustive, 32 + 1,024 cases) (CHK-M9-362) | W |
| CHK-M9-021 | CODE | `Unit` is frozen; `derive` does not mutate its input (a frozen tuple passed, identity and equality kept) | W |

## TP-M9-04: targets (TASK-188; REQ-208 (1), (2), (4)) — `mt/test_scan_targets.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-025 | CODE | The three forms parse: `{"agents": [u1, u2]}` → kind `agents`, agents in input order as `UUID`; uppercase input → lowercase when stored; `{"tags": ["a", "b"]}` → kind `tags`; `{"all": True}` → kind `all`, no agents, no tags | W |
| CHK-M9-026 | CODE | Boundaries: 1 and 10,000 agents accepted, 10,001 refused; 1 and 32 tags accepted, 33 refused; tag of 1 and 64 chars accepted, 65 refused, `""` refused; every char of `[A-Za-z0-9._:-]` accepted in a tag; `a b`, `a/b`, `a,b`, `é`, `a\x00`, `a\t`, `*` refused | W |
| CHK-M9-027 | CODE | REQ-208 (2) refusals (`InvalidTarget`, a `ValueError`): `{}`; `{"agents": [u], "tags": ["a"]}`; `{"all": True, "tags": ["a"]}`; `{"host": "x"}`; `{"all": False}`; `{"all": 1}`; `{"all": "true"}`; `{"all": None}`; `{"agents": []}`; `{"tags": []}`; a duplicate agent; a duplicate tag; a non-UUID (`"x"`, a 32-hex form, a braced form, `urn:uuid:` form, a 36-char string with hyphens moved); `{"agents": "u"}`, `{"tags": "a"}`, `{"agents": {u: 1}}`, `{"tags": [1]}`, `{"agents": [1]}`; non-dict values `None`, `[]`, `"all"`, `1` | W |
| CHK-M9-028 | CODE | Message: every refusal's `str()` names `target`, is one of a small fixed set, and contains no input (a canary tag `M9CANARY…` and a canary-bearing non-UUID are absent from `str()` and `repr()`) | W |
| CHK-M9-029 | CODE | `stored_target` REQ-208 (4): equals the request object (agent ids lowercase, input order kept) plus `resolved_agents` = sorted, lowercase, hyphenated strings; unsorted resolved input comes out sorted; for `all` → `{"all": True, "resolved_agents": [...]}`; for tags → `{"tags": [...], "resolved_agents": [...]}`; JSON-serialisable (`json.dumps` round trip equal) | W |
| CHK-M9-030 | CODE | Case-variant duplicate (`["AAAA…", "aaaa…"]`, one UUID) → `InvalidTarget` (UUIDs compare by value; ruling Q2, decisions "M9 early rulings" (3)) | W |
| CHK-M9-031 | CODE | Pure (covered by CHK-M9-013): `targets.py` imports no `api` module | W |
| CHK-M9-032 | CODE | The tag limits used by `targets.py` (max tags, max tag length, tag characters, whether copied or imported) equal `services/agents/admin.py` `MAX_TAGS` (32), `MAX_TAG_LENGTH` (64), `TAG_CHARACTERS`; `AGENTS_MAX == 10_000` (ruling, decisions "M9 early rulings") | W |

## TP-M9-05: job and retry builder (TASK-189; REQ-209 (1)–(4), (6), REQ-210 (1)–(4) as values) — `mt/test_job_build.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-037 | CODE | `payload(job_id, agent_id, created_at, built)` has exactly the six keys; `job_id`, `agent_id` are the lowercase hyphenated strings of the arguments; `kind == "compliance"`; validates against `api.agent.schemas.ComplianceJob` (strict) and the shared JSON Schema of `mt/contract` (the jobs response wrapping one job); `JobsResponse` of it validates | W |
| CHK-M9-038 | CODE | `plugins` order = input order (a 5-plugin input in a non-sorted uuid order keeps that order); each item exactly `{plugin_uuid, execute, timeout_s}`; `plugin_uuid` lowercase even for an uppercase-constructed `UUID`; `execute` byte-identical for awkward text (quotes, `$`, backslashes, newlines, non-ASCII, 16,384 chars if the model allows); `timeout_s` 1 and 600 copied | W |
| CHK-M9-039 | CODE | `pickup_by`: created `2026-10-30T12:00:00Z` → `2026-10-31T12:00:00Z`; created with microseconds `…12:00:00.999999` → `…T12:00:00Z` (sub-second dropped, never rounded up); created `23:59:59.5` on 2026-12-31 → `2027-01-01T23:59:59Z`; created in `+08:00` → the UTC text; pattern `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`; `pickup_text` (if exported) equals the payload's value (CHK-M9-350) | W |
| CHK-M9-040 | CODE | REQ-209 (2): a recursive walk of every built payload (normal, 5,000 plugins, retry) finds no key `operator`, `expected`, `expected_result`, `eval_spec`, `name`, and no value equal to a fixture's expected text or display name (the canary is in both) (CHK-M9-347) | W |
| CHK-M9-041 | CODE | REQ-209 (3): `parse_eval_spec(built.eval_spec_json)` succeeds; its entries' uuids equal the payload's plugin uuids one to one, in order; `name` = `display_name`, `operator`, `expected` copied; no `execute`/`timeout_s` in it; input in a non-sorted order keeps that order in both (CHK-M9-348) | W |
| CHK-M9-042 | CODE | `redaction_patterns`: copied in stored order (0, 1 and 50 patterns; a pattern with the canary); the payload list is not the caller's list object (mutating the input afterwards does not change a built payload) (CHK-M9-351 at value level) | W |
| CHK-M9-043 | CODE | REQ-209 (4): U+0000, `\ud800`, `\udfff` (and a reversed pair `\udc00\ud800`) in `execute`, `display_name`, `expected`, or one pattern → `UnstorableText`; the message is the same fixed text for all 16 cases and holds no input (canary absent); a valid astral character (`😀`) and U+FFFD are accepted (CHK-M9-349) | W |
| CHK-M9-044 | CODE | Limits from M8's `EvalSpec`: 1 and 5,000 plugins build; 0 plugins → `ValueError`; 5,001 → `ValueError`; duplicate `plugin_uuid` → `ValueError`; unknown operator → `ValueError` | W |
| CHK-M9-045 | CODE | REQ-209 (6) values: the SR §1.1 plugin given as a `CatalogPlugin` with display name `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed` gives that `name`, operator `equals`, expected `install ok installed` in `eval_spec`, and the SR `Execute` text and timeout in the payload | W |
| CHK-M9-046 | CODE | REQ-210 (1)–(3) `retry`: a 5-plugin original (payload from `payload()`, `eval_spec` from `plugins_and_spec`), missing {1, 3, 5} given as an unordered set → retry plugins exactly the original items 1, 3, 5 in that order (equal dicts: same `execute`, `timeout_s`); `redaction_patterns` equal to the original's; `job_id` = the new id; `agent_id` = the original's; `kind` compliance; `pickup_by` = new `created_at` + 24 h; `eval_spec` = the original's entries 1, 3, 5 in order, parses (CHK-M9-343, -344 at value level) | W |
| CHK-M9-047 | CODE | Retry inputs that differ from the catalog: a retry built from an original whose `execute` values and patterns differ from any `CatalogPlugin` in scope returns the original's values (the function has no catalog input; signature check: no parameter takes plugins or patterns) | W |
| CHK-M9-048 | CODE | REQ-210 (4): `original_is_retry=True` → `ValueError`; `missing` empty → `ValueError`; `missing` naming a uuid not in the payload → `ValueError`; all five missing → retry with all five (allowed: "with none → a retry with all 5") | W |
| CHK-M9-049 | CODE | Retry output validates against `ComplianceJob`; its payload keys are exactly the six; no forbidden key (CHK-M9-040 walk) | W |
| CHK-M9-050 | CODE | `CatalogPlugin`, `BuiltPlugins` are frozen; `UnstorableText` is a `ValueError` subclass | W |

## TP-M9-06: intake plan (TASK-190; REQ-214 to -216 at plan level) — `mt/test_intake_plan.py`

Items are `api.agent.schemas.ResultItem` objects built by `json.loads` + `model_validate` (as the route does); `spec` from M8's `EvalSpec`.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-053 | CODE | Membership (#124 (a)): a batch of 50 whose 50th item names a uuid not in `payload_plugins` → `PluginNotInJob` (nothing returned); also when it is the first item; a uuid in the payload but not in `eval_spec` → `PluginNotInJob`; a foreign uuid that is also in `existing` → `PluginNotInJob` (membership before duplicates) (CHK-M9-324) | W |
| CHK-M9-054 | CODE | Duplicates (#124 (b)): a uuid in `existing` → not stored, counted; two items for one plugin in one batch → the first (by batch order, told apart by stdout) is the row, the second counted (CHK-M9-323); three items for one plugin → 1 row, 2 duplicates; `accepted + duplicates == len(items)` | W |
| CHK-M9-055 | CODE | Rows are in batch order; an empty batch → `Plan((), 0)`; 50 distinct items → 50 rows | W |
| CHK-M9-056 | CODE | Verdict: for a matrix (each of the 14 operators with a passing and a failing input, exit 126/127/137/None, `timed_out`, `truncated`, `error` both values) each row's `(eval_code, eval_detail)` equals `result_verdict(entry, item)` code and `detail.value` (None for PASS/FAIL), computed by the test directly from M8 | W |
| CHK-M9-057 | CODE | Caps (#116, REQ-215 (2)): stdout 65,537 bytes → ERROR `oversize`, row `stdout == ""` and `stderr == ""` (CHK-M9-330); stdout 65,536 bytes → stored as sent, verdict from `classify`; stderr 16,385 → `oversize`, both streams `""`; 16,384 → as sent; multi-byte (`€` × 21,846 → oversize) | W |
| CHK-M9-058 | CODE | #121 order, caps first (CHK-M9-331): stdout = `"a" × 65,535 + "\x00"` (65,536 bytes as received) → **not** oversize; stored stdout `"a" × 65,535 + "\ufffd"` (65,538 bytes); stdout with 65,537 bytes containing NULs → oversize with `""` (no replacement visible) | W |
| CHK-M9-059 | CODE | #121 (c) evaluate the stored text: `equals` expected `"a\ufffdb"` with stdout `"a\x00b"` → PASS (raw evaluation would FAIL); `equals` expected `"\ufffd"` with stdout from `json.loads('"\\ud800"')` → PASS; `regex` `^x$` on `"\ud800\nx"` → PASS (raw lone surrogate gives M8's `cannot evaluate`); the row's stdout is the replaced text in each case | W |
| CHK-M9-060 | CODE | REQ-215 (4): the fixture `contract/fixtures/results/request_valid_nul_in_stdout_and_stderr.json` → every row's stdout and stderr hold U+FFFD where U+0000 was, no U+0000 left, and each encodes as strict UTF-8; stderr replaced too (not compared); the verdict equals `result_verdict` on a proxy with the replaced text | W |
| CHK-M9-061 | CODE | `storable`: identity on text with no U+0000 and no surrogate code point (same object or equal); `"\x00"` → `"\ufffd"`; `"\ud800"`, `"\udbff"`, `"\udc00"`, `"\udfff"` → `"\ufffd"`; a split pair given as two code points `"\ud83d\ude00"` → two U+FFFD (unstorable in UTF-8); `json.loads('"\\ud83d\\ude00"')` (= `😀`) unchanged; length preserved (one-for-one) | W |
| CHK-M9-062 | CODE | Snapshots (CHK-M9-332): `plugin_name_snap`, `operator_snap`, `expected_snap` = the `eval_spec` entry; `execute_snap` = `payload_plugins[uuid]` (a payload execute different from anything else in scope); `exit_code`, `timed_out`, `truncated`, `started_at`, `finished_at` as sent | W |
| CHK-M9-063 | CODE | REQ-215 (3): `error: "runner_unavailable"` (the 0.1.0 agent case) and `"spool_overflow"` → ERROR with that detail, streams stored as sent (not oversize) | W |
| CHK-M9-064 | CODE | REQ-215 (6) SR §1.1: stdout `install ok installed` exit 0 → PASS (0, None); `""` exit 1 → FAIL (1, None) | W |
| CHK-M9-065 | CODE | No plan output, exception or log record carries stdout, stderr or the expected value (canary in all; `caplog` at DEBUG; `PluginNotInJob` message fixed) | W |
| CHK-M9-066 | CODE | `ResultRow`, `Plan` frozen; `plan` does not mutate `existing` | W |

## TP-M9-07: cron and time zone (TASK-191; REQ-223) — `mt/test_cron.py`

Reference instants are fixed (`2026-10-28T12:00:00Z`, a Wednesday) unless a row says otherwise.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-067 | CODE | REQ-223 (1): `0 3 * * 0`, `0 3 * * 7`, `0 3 * * sun` in `UTC` → the next five fires are Sundays at 03:00 UTC (2026-11-01, -08, …); in `Asia/Kolkata` → Sundays 03:00 local = Saturdays 21:30 UTC; `0 3 * * 1` → Mondays 03:00 (CHK-M9-368) | W |
| CHK-M9-068 | CODE | crontab(5) weekday syntax: `1-5` → Mon–Fri only (over 14 days); `5-7` → Fri, Sat, Sun; `0-5` → Sun–Fri, not Sat; `0,6` → Sun and Sat; `*/2` → Sun, Tue, Thu, Sat (the step is not a weekday); `1-5/2` → Mon, Wed, Fri; `mon-fri` = `1-5`; `0-6` and `*` → every day; `sat,sun` = `6,7` | W |
| CHK-M9-069 | CODE | Other fields: `*/15 * * * *` → :00, :15, :30, :45; `0 0 1 jan *` → 2027-01-01 00:00; `0 0 31 * *` → only 31-day months; `0 0 29 2 *` → 2028-02-29 (fires within 5 years: accepted); `0 12 * * *` in `America/New_York` → 16:00 or 17:00 UTC by season | W |
| CHK-M9-070 | CODE | REQ-223 (2): `0 9 * * *` in `Asia/Kolkata` → 03:30 UTC (CHK-M9-370) | W |
| CHK-M9-071 | CODE | REQ-223 (2) DST, **recorded** (decisions 2026-10-30): Europe/London 2026-03-29 (01:00 GMT → 02:00 BST) and 2026-10-25 (02:00 BST → 01:00 GMT). Rows: `30 2 * * *` (the criterion as written; 02:30 exists once both days: expected 01:30 UTC on 03-29, 02:30 UTC on 10-25); `30 1 * * *`. **Superseded by the user decision** (decisions 2026-10-30, "DST behaviour for scheduled scans"): shift the gap and run the repeat once. So 03-29 fires once at 01:30 UTC (02:30 BST), and 10-25 fires once at 00:30 UTC (the first occurrence), then 10-26 01:30 UTC. Also asserted: from inside the repeated hour the next fire is the next day; `*/15 1 * * *` and `*/30 * * * *` across the repeat; `*/30` across the gap is strictly increasing; a UTC schedule is unchanged. APScheduler 3.11's raw answer (gap shifted, repeat fired twice) is recorded in the TASK-191 report | W |
| CHK-M9-072 | CODE | REQ-223 (3) refused, `InvalidSchedule.field == "cron"`: six fields `0 0 3 * * *`; four fields; `""`; `@daily`, `@reboot`; `0 0 1 * 1` (both day fields, CHK-M9-369), `0 0 1-5 * mon`; 65 chars (valid-looking, padded list); `0 0 30 2 *`, `0 0 31 4 *` (never); `61 * * * *`, `* 24 * * *`, `* * 0 * *`, `* * * 13 *`, `* * * * 8`; `0 0 ? * *`, `0 0 L * *`, `0 0 * * 1#2`, `0 0 15W * *`; non-ASCII digits `٠ * * * *`. Accepted at 64 chars (a valid padded expression) | W |
| CHK-M9-073 | CODE | REQ-223 (3) refused, `field == "timezone"`: `Mars/Base`, `localtime`, `../etc/passwd`, `/etc/UTC`, `Europe\London`, `""`, 65 chars; accepted: `UTC`, `Etc/UTC`, `Europe/London`, `Asia/Kolkata`, `America/New_York`. Messages fixed, no input (canary in a bad cron and a bad zone absent from `str`/`repr`) | W |
| CHK-M9-074 | CODE | REQ-223 (4): `next_fire(s, t)` > `t` for `t` = a fire time exactly (returns the next one), fire − 1 µs (returns the fire), fire + 1 µs; result is aware with UTC offset 0; for an `after` in a non-UTC zone the same instant gives the same answer | W |

## TP-M9-08: idempotency store (TASK-192; REQ-222 (1)–(3)) — `mt/test_idempotency.py`

A fake clock and a counting handler (returns a 202-like answer, or a refusal, or raises).

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-075 | CODE | REQ-222 (1): same user, key, body → the first answer (equal status and body), handler called once; another user, same key → handler called again; same key, other body → conflict (409 signal, fixed message `Idempotency-Key was used with a different request.`); bodies equal after parsing (`{"a":1,"b":2}` vs `{"b":2,"a":1}`) count as the same | W |
| CHK-M9-076 | CODE | Time: at first + 24 h − 1 s → remembered; at first + 24 h + 1 s → handler called again (new scan); exactly 24 h recorded, not asserted | W |
| CHK-M9-077 | CODE | Only 202 remembered: a first refusal (409 disabled) and a first raise are not stored; the same key and body then call the handler, and the per-key lock is released after the raise | W |
| CHK-M9-078 | CODE | REQ-222 (2) concurrency: two threads with the same user, key, body released by a `Barrier`; the handler blocks on an `Event` until both have entered the store; handler called once, both threads get the same answer. Per-key, not global: while key A's handler is blocked, key B (and user 2 with key A) complete (CHK-M9-367) | W |
| CHK-M9-079 | CODE | REQ-222 (3) key validation: 1 and 255 printable ASCII accepted; 256 chars, `""`, `"a\x00"`, `"a\x1f"`, `"a\x7f"`, `"a\n"`, `"é"` refused. Capacity: 100,000 entries kept; entry 100,001 drops the oldest (its key calls the handler again), the second-oldest is still remembered. Space inside a key: recorded | W |

## TP-M9-09: property suite (hypothesis) — `mt/test_jobs_property.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-080 | CODE | REQ-206 (3): random walks (≤ 20 events from the event alphabet of CHK-M9-003) from `queued` through the module's functions: no event leaves `completed`, `expired` or `cancelled`; `failed` and `partial` only reach `completed` or `partial`; `running` is never re-entered after leaving it; every step taken is in the allowed set; `started_at` is set at most once per walk (CHK-M9-338) | W |
| CHK-M9-081 | CODE | Deadline: for random timeouts (1–5,000 items of 1–600) and `max_parallel_plugins` 1–8, `deadline − start − 600 s` equals the integer ceiling `(Σ + mpp − 1) // mpp` and is ≥ `Σ / mpp` and < `Σ / mpp + 1` | W |
| CHK-M9-082 | CODE | REQ-207 (2): random unit sets (1–20 consistent units: `complete ⇒ has_results`, `all_queued ⇒ open ∧ ¬has_results ∧ ¬any_cancelled`): finished ⇔ no unit open; state never `dispatched`/`expired`; adding a result to one unit (`has_results` True, optionally `complete` True) never turns `partial` or `completed` into `failed` or `cancelled`; the answer is independent of unit order (CHK-M9-362) | W |
| CHK-M9-083 | CODE | REQ-216 accounting: random batches (0–50 items over a 1–60 plugin job, random repeats, random `existing` ⊆ job): for an accepted plan, `len(rows) + duplicates == len(items)`; row uuids are distinct and disjoint from `existing`; each row is the first item of its uuid in the batch; any foreign uuid → `PluginNotInJob` | W |
| CHK-M9-084 | CODE | `storable` on random text (incl. surrogates, NUL, astral): output encodes as strict UTF-8, contains no U+0000, has the input's length, and equals the input where the input was already storable; plan rows' stdout/stderr always encode | W |
| CHK-M9-085 | CODE | REQ-223 (4): for random valid crons (generated from field grammars, both-day-fields excluded), random zones from a fixed list and random instants 2026–2030, `next_fire` is strictly after the instant, and iterating it 10 times gives a strictly increasing sequence | W |
| CHK-M9-086 | CODE | `parse_target` on random JSON values never raises anything but `InvalidTarget`, and every accepted value round-trips through `stored_target` with exactly one form key | W |

## TP-M9-01: PostgreSQL fixtures (tester-m9b) — `mt/scan_pg_fixtures.py`, `mt/agent_sim.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-100 | APP | Catalog through M7's store: families incl. `CIS Ubuntu 24.04`; policies enabled, disabled and soft-deleted, version ≥ 3 for one; the SR §1.1 plugin; active and retired plugins with a chosen `sort_order` | W |
| CHK-M9-101 | APP | Agents in all six statuses (`awaiting_approval`, `enrolled`, `online`, `stale`, `offline`, `decommissioned`) with tags; real `bsa_` tokens for the simulated agent | W |
| CHK-M9-102 | APP | Owner-written scans, jobs (originals and retries, every state, `dispatched_at`/`started_at`/`deadline_at` chosen), results with `job_created_at = scan_job.created_at`, jobs in two months (two partitions) | W |
| CHK-M9-103 | APP | Clock double for services and the sweep; canary helper; row-checksum helper sensitive to a one-byte change | W |
| CHK-M9-104 | APP | Simulated agent: requests built from `mt/contract/fixtures/{jobs,results}` (valid fixtures only), sent with a real token through the real routes; gzip variant; a self-test pulls, posts a start notice and a final batch | W |

## TP-M9-10: repositories on PostgreSQL (TASK-193 to -197) — `mt/test_*_repo_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-110 | APP | TASK-193 REQ-208 (3) as `bitscan_app`: `all` → the `enrolled`, `online`, `stale`, `offline` agents, sorted; `tags ["a","b"]` → eligible holders of `a` or `b` (any-of, one agent holding both appears once) (CHK-M9-356); `agents [x, unknown, decommissioned]` → `[x]` (CHK-M9-354, -355) | W |
| CHK-M9-111 | APP | TASK-193 snapshot: version, status, `deleted_at` and active plugins in `sort_order` with `v_plugin.display_name` in **one** statement (statement spy); retired plugins absent (CHK-M9-352); the policy row is taken `FOR SHARE` (a concurrent `UPDATE policy` in a second session waits until commit, lock probe) (CHK-M9-353); the advisory queue lock serialises two sessions | W |
| CHK-M9-112 | APP | TASK-193 insert: N jobs in one INSERT (spy); each SQL-composed payload equals `build.payload()` for the same ids (dict equality after JSON decode), `job_id` = row id, lowercase ids, `created_at` = the scan's; `eval_spec` stored as given | W |
| CHK-M9-113 | APP | TASK-193 `cancel_older_queued`: only `queued` compliance jobs of earlier scans of **that** policy for the listed agents; dispatched jobs, other agents, another policy's queued jobs and every inventory job unchanged (checksums) (CHK-M9-358, -381) | W |
| CHK-M9-114 | APP | TASK-194 `unit_facts` against owner-written fixtures (originals with retries, results, every state) equal the hand-written expected `Unit`s; one statement per call (spy) | W |
| CHK-M9-115 | APP | TASK-194 `refresh_candidates`: excludes `completed` scans and finished scans created more than 8 days ago; includes any `finished_at IS NULL` scan whatever its age; includes a finished `partial` scan of 7 days (CHK-M9-363) | W |
| CHK-M9-116 | APP | TASK-194 `cancel_open_jobs`: only `queued`, `dispatched`, `running` jobs of that scan (originals and retries) → `cancelled` with `finished_at` (CHK-M9-359); `set_scan_state` updates only `state` and `finished_at` (`finished_at` never moved once set) | W |
| CHK-M9-117 | APP | TASK-195 `lock_unit`: a second session locking the same root (posting to the retry) waits (lock probe) (CHK-M9-320, -321); unknown id → None; posted job read with payload and `eval_spec` | W |
| CHK-M9-118 | APP | TASK-195 `insert_results`: N rows in one INSERT (spy); `job_created_at` accepted by the TS §5.2 trigger; `operator_snap` cast; `received_at` = the argument | W |
| CHK-M9-119 | APP | TASK-195 `start` writes `started_at`, `deadline_at` only while NULL (a second call changes nothing) (CHK-M9-334); `set_state` writes only `state`, `finished_at`; `sibling_id` for a `failed`/`partial` original finds its retry, for a retry returns `retry_of`, else None | W |
| CHK-M9-120 | APP | TASK-196 candidates follow the strict boundaries: `deadline_at = now` not a candidate, `now − 1 µs` is (CHK-M9-339); never-started at `dispatched_at = now − 24 h` not, `− 24 h − 1 s` is; measured from `dispatched_at`, not `created_at` (CHK-M9-340); inventory never | W |
| CHK-M9-121 | APP | TASK-196 `lock_for_sweep`: a root held by another session is skipped (None, no wait); `end_job` only from `dispatched`/`running` (second call returns False) (CHK-M9-346); `insert_retry` row has the given payload, `eval_spec`, `retry_of`; only progress columns of the original change | W |
| CHK-M9-122 | APP | TASK-197 CRUD round trip; cursor page by `schedule_id`; `due` skips rows another session holds (`SKIP LOCKED`) (CHK-M9-373); DELETE leaves its scans with `schedule_id` NULL; `previous_unfinished` uses the latest scan by `created_at` | W |
| CHK-M9-123 | APP | G1 on each new repository: a planted f-string query turns ruff S608 red (CHK-M9-376) | W, L |

## TP-M9-11: queue service and races (TASK-198; REQ-209 (5), REQ-211, REQ-212 (2), REQ-227) — `mt/test_queue_scan_pg.py`, `mt/test_queue_scan_race_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-150 | APP | Race: a policy delete committing during the scan (barrier at the lock) → the scan refuses `PolicyDeleted` or its jobs are cancelled; never a queued job of a deleted policy (CHK-M9-353) | W |
| CHK-M9-151 | APP | Race: an import changing an `Execute` and bumping the version during the scan → every job's commands, `eval_spec` and `scan.policy_version` belong to one version | W |
| CHK-M9-152 | APP | Race: two concurrent scans of one policy and agent → exactly one queued job | W |
| CHK-M9-153 | APP | REQ-211 (1): version 3, tag target over four tagged agents (decommissioned, awaiting, offline, online) → `(scan_id, "queued", 3, 2)`; one `scan` row (`policy_version` 3, `trigger`, `schedule_id`, `target` with `resolved_agents`, `requested_by`, `queued`), two queued jobs with the scan's `created_at` | W |
| CHK-M9-154 | APP | REQ-211 (2): disabled → `PolicyDisabled`; deleted → `PolicyDeleted`; unknown → `PolicyNotFound`; no eligible agent → `NoTargetAgents` (CHK-M9-357); no active plugin → `PolicyHasNoPlugins`; each leaves `scan`, `scan_job`, `audit_log` row counts unchanged (CHK-M9-352) | W |
| CHK-M9-155 | APP | REQ-211 (3): a second scan cancels the first's queued job for a shared agent (`finished_at` set) and leaves its dispatched jobs, its other-agent jobs, another policy's queued jobs and every inventory job untouched (CHK-M9-358, -381) | W |
| CHK-M9-156 | APP | REQ-211 (5), (6): jobs queued after an import carry the new `Execute`; already queued keep the old; disabling the policy afterwards leaves its queued jobs queued (#18) | W |
| CHK-M9-157 | APP | REQ-209 (1)–(3), (6) on stored rows: payload six keys, validates `ComplianceJob`, `pickup_by` = `created_at` + 24 h text, `redaction_patterns` = the setting (CHK-M9-351), SR §1.1 `name` from `v_plugin` | W |
| CHK-M9-158 | APP | REQ-209 (4): a catalog row made unstorable cannot exist, so the builder is fed through a monkeypatched snapshot holding U+0000 → `UnstorableText`, no row written | W |
| CHK-M9-159 | APP | REQ-209 (5): M8's `repositories.results.host_counts` on an M9-queued scan counts every plugin as not run | W |
| CHK-M9-160 | APP | REQ-212 (2): every `execute` of every queued job equals an active plugin's `execute` of that policy at queue time | W |
| CHK-M9-161 | APP | REQ-227 (1), (2) for create: one `scan.create` entry with the #129 (a) keys; all-hosts + API token → `detail.alert = true`, kind `all_hosts_scan_api_token`, fake sink receives it, `bitscan_alerts_total{kind=…}` grows after commit; session or tag target → no alert (CHK-M9-366); a rolled-back queue leaves no entry | W |

## TP-M9-12: intake service, first result wins, metric (TASK-199; REQ-214 to -217, REQ-226) — `mt/test_intake_pg.py`, `mt/test_first_result_wins_race_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-163 | APP | REQ-214 (1) refusals at service level (`Refused`, nothing stored, job unchanged): unknown job; another agent's; inventory (CHK-M9-328); `queued`, `expired`, `cancelled` (while dispatched and while running) (CHK-M9-325); `dispatched_at` + 7 d + 1 s; a 50-item batch with one foreign `plugin_uuid` (the 49 not stored) (CHK-M9-324); owner-corrupted `eval_spec` → `eval_spec_invalid` | W |
| CHK-M9-164 | APP | REQ-214 (2), (3): `dispatched`, `running`, `failed`, `partial`, `completed` → `Accepted` with the counts; `dispatched_at` + 7 d exactly accepted; the window is from `dispatched_at`, not `created_at` (CHK-M9-327) | W |
| CHK-M9-165 | APP | REQ-214 (6): a fault injected after the result insert leaves no row and the job unchanged | W |
| CHK-M9-166 | APP | REQ-215 (1): statement spy → one INSERT per batch; each row's `eval_code`/`eval_detail` = `result_verdict(entry, item)`; snapshots from `eval_spec` and payload (CHK-M9-332); `job_created_at` = `scan_job.created_at`; `received_at` = the manager's clock, not the item's `finished_at` (CHK-M9-333) | W |
| CHK-M9-167 | APP | REQ-215 (2)–(4), (6) stored: 65,537 → ERROR `oversize`, `''` streams (CHK-M9-330); 65,536 as sent; `runner_unavailable`, `spool_overflow`; the NUL fixture stored with U+FFFD and the verdict on the stored text; a lone surrogate through `json.loads` stored the same (CHK-M9-331); SR §1.1 PASS/FAIL | W |
| CHK-M9-168 | APP | REQ-215 (5) catalog change after queue: an import changes the plugin's `ExpectedResult` and `Execute`; the result is evaluated against the queued `eval_spec`; snapshots hold the queued values (CHK-M9-329) | W |
| CHK-M9-169 | APP | REQ-216 (1), (2), (5): same plugin twice to one job → `{0, 1}`, first row unchanged; original then retry and the reverse → stored once from the first post (CHK-M9-322); two items in one batch → first stored | W |
| CHK-M9-170 | APP | REQ-216 (3) race: two sessions post one plugin to the original and to the retry at once (barrier), 200 repetitions → exactly one row per plugin per unit and `host_counts` counts it once; with the root lock planted away the duplicate shows as M8's double count (CHK-M9-320, -321) | W |
| CHK-M9-171 | APP | REQ-216 (4): statement spy shows root `FOR UPDATE` before the INSERT; intake and sweep lock root then job; the race suite ends with no deadlock | W |
| CHK-M9-172 | APP | Canary through intake: stdout/stderr canary in no log record, exception or audit `detail`; intake log line carries `agent_id`, `job_id`, counts only (CHK-M9-375) | W |
| CHK-M9-173 | APP | REQ-217 (1)–(3): empty batch on dispatched → `running`, `started_at` = receive time, `deadline_at` per REQ-206 with the `max_parallel_plugins` setting then; a second start notice changes neither (CHK-M9-334); a first non-empty batch also starts; all → `completed`; final with missing → `partial`; non-final with missing → `running` | W |
| CHK-M9-174 | APP | REQ-217 (4)–(6): `failed` + non-final 1 of 3 → `partial`, the other 2 → `completed`; empty batch on `failed` changes nothing; `completed`, `expired`, `cancelled` never change; `finished_at` set on every entry into `completed`/`partial`/`failed`, incl. a late change | W |
| CHK-M9-175 | APP | REQ-226 (1)–(3): counter exported with `PASS`, `FAIL`, `ERROR` from zero; a batch of 2 PASS, 1 FAIL, 3 ERROR adds exactly those after commit; rollback, duplicates and refusals add nothing; no other label (CHK-M9-374) | W |

## TP-M9-13: cancel (TASK-200; REQ-220) — `mt/test_cancel_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-182 | APP | REQ-220 (1): a scan with one job in each state → only the queued, dispatched, running ones `cancelled` with `finished_at`; others unchanged (CHK-M9-359) | W |
| CHK-M9-183 | APP | REQ-220 (3): cancelled before any result → scan `cancelled`; after some results → `partial` (#127 (d)) (CHK-M9-360); derived at once | W |
| CHK-M9-184 | APP | REQ-220 (4), (5): a second cancel → `cancelled_jobs: 0`; one `scan.cancel` entry `{cancelled_jobs}`; chain verifies; nothing opens a connection to an agent | W |
| CHK-M9-185 | APP | REQ-229 (2): cancel leaves the agent's inventory job state unchanged | W |

## TP-M9-14: schedule management and scheduled runs (TASK-201, -203; REQ-224, REQ-225) — `mt/test_schedules_admin_pg.py`, `mt/test_scan_schedules_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-188 | APP | TASK-201 REQ-224 (1)–(3) service level: create → `next_run_at` = next fire after now; cron/timezone change recomputes; `enabled: false` stops runs; `enabled: true` recomputes from now; deleted policy on create or enable → conflict; disabled policy accepted | W |
| CHK-M9-189 | APP | TASK-201 REQ-224 (4), (6), (7): delete removes the row, its scans keep `schedule_id` NULL; one `scan_schedule.*` entry per change with changed fields; bad cron, zone, target, name (empty, 129 chars, U+0000, lone surrogate) refused; name of 128 chars accepted, stored as given | W |
| CHK-M9-195 | APP | TASK-203 REQ-225 (1): a due schedule → one scheduled scan (`trigger` `scheduled`, `schedule_id`, `requested_by` NULL, actor `system`), `last_run_at` = now, `next_run_at` = next fire | W |
| CHK-M9-196 | APP | REQ-225 (2), (3): previous scan `finished_at` NULL → no scan, `previous_unfinished` log, `next_run_at` moved on (CHK-M9-372); disabled policy → `policy_disabled`; zero agents → `no_target_agents`; none writes a scan or audit entry | W |
| CHK-M9-197 | APP | REQ-225 (4): clock jumps 3 h over two fire times → no scan for either, `missed` log, `next_run_at` in the future (CHK-M9-371); due 1 min 59 s late → runs; 2 min 1 s late → missed | W |
| CHK-M9-198 | APP | REQ-225 (5), (6): a disabled schedule never runs; two ticks at once (two sessions, barrier) → one scan (CHK-M9-373) | W |
| CHK-M9-199 | APP | REQ-225 (7): the `Asia/Kolkata` `0 9 * * *` schedule runs at 03:30 UTC and not at 09:00 UTC (CHK-M9-370) | W |
| CHK-M9-200 | APP | REQ-225 (8): a tick that raises is logged by job name and exception type only; the next tick runs; `SchedulerRunner` registers the 30 s `scan_schedules` job and `stop()` waits for a running tick | W |
| CHK-M9-201 | APP | A stored row whose cron no longer parses (owner write) → `invalid` log, schedule not disabled, `next_run_at` + 1 day (plan TASK-203 §5) | W |
| CHK-M9-202 | APP | Scheduled scans never raise the all-hosts alert, even with `{"all": true}` | W |

## TP-M9-15: sweep compliance steps and scan refresh (TASK-202; REQ-218, REQ-219, REQ-228, REQ-229) — `mt/test_sweep_compliance_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-204 | APP | REQ-218 (1): running past its deadline, 2 of 5 results → `partial` + one retry with the 3 others (original order, original commands); none → `failed` + retry with all 5 | W |
| CHK-M9-205 | APP | REQ-218 (2): dispatched, never started: at `dispatched_at` + 24 h nothing; 1 s later → `failed` + retry (CHK-M9-340) | W |
| CHK-M9-206 | APP | REQ-218 (3), (4): a retry past its deadline → `failed`/`partial`, no retry of it (CHK-M9-341); a job `partial` by a final batch → no retry (CHK-M9-342) | W |
| CHK-M9-207 | APP | REQ-218 (5): two sweeps at once (barrier) → one retry (CHK-M9-346); sweep + intake on one unit serialise without deadlock | W |
| CHK-M9-208 | APP | REQ-218 (6): deleted policy or decommissioned agent → `failed`/`partial`, no retry; disabled policy → retry made | W |
| CHK-M9-209 | APP | REQ-210 (1) end to end: after an import changed plugin 3's `Execute` and the redaction setting changed, the retry carries the original's (CHK-M9-344) | W |
| CHK-M9-210 | APP | Retry atomicity: a fault after `end_job` and before `insert_retry` rolls both back; the next sweep makes the retry (CHK-M9-345) | W |
| CHK-M9-211 | APP | REQ-218 (7), (8): M3 steps unchanged — inventory jobs fail after 30 min, never retried; queued compliance jobs past `pickup_by` expire; `bitscan_jobs_expired` grows after commit; a failing new step leaves the others applied | W |
| CHK-M9-212 | APP | REQ-219 (1)–(3): after the sweep, all completed → `completed` + `finished_at`; completed + expired → `partial`; all expired → `failed`; a finished `partial` scan whose failed job gets the missing results → `completed`, `finished_at` unchanged (CHK-M9-363); a policy delete cancelling the last queued jobs → `cancelled` or `partial` with `finished_at` | W |
| CHK-M9-213 | APP | REQ-219 (4), (5): one `scan_job` read per refresh step (spy), UPDATE only for changed scans; a `completed` scan and a finished scan older than 8 days are not read; no scan ever `dispatched`/`expired` | W |
| CHK-M9-214 | APP | REQ-228 (1), (2): a compliance job queued > 1 h for an online agent → `job_queue_age` once per hour, for an offline agent none; `agents_offline`, `inventory_stale` give the M3 answers with compliance jobs present | W |
| CHK-M9-215 | APP | REQ-229 (2): a compliance scan, a cancel and a newer scan of every agent leave each inventory job's state unchanged (CHK-M9-381) | W |
| CHK-M9-216 | APP | The sweep never writes `payload`/`eval_spec` of an existing job; a planted `UPDATE scan_job SET payload` surfaces as a grant refusal (CHK-M9-377) | W |

## TP-M9-16: agent job routes (TASK-204; REQ-213 to -216, REQ-229 (3)) — `mt/test_agent_jobs_api_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-220 | APP | REQ-213 (1): 6 inventory + 6 compliance queued → first pull the 10 oldest in creation order, next pull the other 2; each dispatched once with `dispatched_at` (CHK-M9-378) | W |
| CHK-M9-221 | APP | REQ-213 (2): each compliance job equals its stored payload and validates `ComplianceJob`; no `eval_spec`, `operator`, `expected` key anywhere in the response (CHK-M9-379) | W |
| CHK-M9-222 | APP | REQ-213 (3), (4): cancelled, expired, other agents' and past-`pickup_by` jobs never returned; two concurrent pulls never return the same job | W |
| CHK-M9-223 | APP | REQ-213 (5): REQ-072 (1), (3), (5), (6) still hold for inventory jobs | W |
| CHK-M9-224 | APP | REQ-214 (1) through the route: each refusal case → 409 `job_not_acceptable`, nothing stored, no job change, one `agent.result_refused` entry without stdout/stderr | W |
| CHK-M9-225 | APP | REQ-214 (2), (3): accepting states → 200 `{accepted, duplicates}` validating `ResultsResponse`; + 7 d exactly accepted | W |
| CHK-M9-226 | APP | REQ-214 (4): malformed body 400, over-cap 413, gzip, as REQ-066 | W |
| CHK-M9-227 | APP | REQ-214 (5): 21 counted 409s in 10 min → one `result_409_flood`; 21 for the agent's own cancelled job → none (CHK-M9-380) | W |
| CHK-M9-228 | APP | REQ-215 (3)–(5), REQ-216 (1)–(3) end to end: the 0.1.0 `runner_unavailable` fixture, the NUL fixture, catalog change after queue, first result wins through the route | W |
| CHK-M9-229 | APP | REQ-229 (3): results route refuses an inventory job id (409); inventory route refuses a compliance job id (409, #72 (d)) | W |
| CHK-M9-230 | APP | Token groups: `bsu_`/`bsk_` on both agent job routes → 401; another agent's `bsa_` → 409/401 as M3 | W |
| CHK-M9-231 | APP | PD-40 (TP-M9-19): REQ-072 (4) and REQ-073 (1) checks rewritten; old CHK id → new CHK id list in `tests/m9/report.md`; every other M3 assertion unchanged | W |

## TP-M9-17: scan and schedule routes (TASK-205, -206; REQ-212 (1), REQ-220 (2), REQ-221, REQ-222 (4), REQ-224) — `mt/test_scans_api_pg.py`, `mt/test_scan_schedules_api_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-240 | APP | REQ-221 (1): operator and admin → 202 `{scan_id, state: "queued", policy_version, jobs}` with a session and with an API token; viewer 403 (CHK-M9-364); `bsa_`, no token, revoked token → 401 (CHK-M9-365) | W |
| CHK-M9-241 | APP | REQ-221 (2): unknown policy 404; disabled 409; deleted 409; zero agents 422 (`about:blank`); malformed target 400; extra key (`plugins`, `execute`, `command`, `payload`, `eval_spec`) 400 and nothing written (REQ-212 (1), CHK-M9-382); body > 1 MiB 413 | W |
| CHK-M9-242 | APP | REQ-221 (3): `{"all": true}` + `bsk_` → `all_hosts_scan_api_token` alert (entry, sink, counter); session → none; tags + `bsk_` → none (CHK-M9-366) | W |
| CHK-M9-243 | APP | REQ-221 (4), REQ-220 (2): cancel operator 200, viewer 403, unknown 404, malformed id 400; cancelled queued job never pulled; posts for cancelled dispatched/running jobs 409 | W |
| CHK-M9-244 | APP | REQ-221 (5): `bm/api/user/scans.py` imports no repository (AST) | W |
| CHK-M9-245 | APP | REQ-222 (3), (4): `Idempotency-Key` of 256 chars or with a control char → 400; a repeat writes no second `scan` row and no second `scan.create` entry; other body → 409 | W |
| CHK-M9-246 | APP | Unstorable text through the route → 500 `about:blank`, no row, no input in the answer | W |
| CHK-M9-255 | APP | REQ-224 (1): create 201 with the item and `next_run_at`; list pages by `schedule_id` with `{items, next_cursor}`; get returns the item | W |
| CHK-M9-256 | APP | REQ-224 (2), (3): PATCH cron/timezone recomputes; enable/disable; `{"policy_id": …}` 400; deleted policy on create/enable 409; disabled policy accepted | W |
| CHK-M9-257 | APP | REQ-224 (4)–(7): DELETE 204, scans keep `schedule_id` NULL; viewer 403 on every operation, `bsa_` 401; an operator may change another operator's schedule; one `scan_schedule.*` entry per change; bad cron, zone, target, name → 400; extra keys (`execute`, `plugins`, …) → 400 (REQ-212 (1)) | W |

## TP-M9-18: security and boundary suite (tester-m9b) — `mt/test_security_m9.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-270 | APP | REQ-230 (5), REQ-227 (4): canary in stdout, stderr, `execute` and expected through every M9 path → no log record, exception message or audit `detail` holds it | W |
| CHK-M9-271 | CODE | Import graph: the pure modules import no `db`, `repositories`, `api`, psycopg; `api/user/scans.py` and `scan_schedules.py` import no repository | W |
| CHK-M9-272 | APP | REQ-230 (3) grant probes as `bitscan_app`: UPDATE `scan_job.agent_id`, `scan_id`, `payload`, `eval_spec`, `retry_of`, and `scan.policy_id`, `policy_version`, `target` refused; UPDATE/DELETE `scan_result` refused | W |
| CHK-M9-273 | APP | REQ-230 (2): statement spies over the M9 PG suites: no UPDATE/DELETE on `scan_result`; UPDATEs of `scan_job` and `scan` only on progress columns | W |
| CHK-M9-274 | CODE | REQ-212 (3): source grep — only `jobs/build.py`, `repositories/scan_queue.py`, `repositories/job_sweep.py` write a compliance `payload` | W |
| CHK-M9-275 | CODE | S608 and `re` plants on new modules (CHK-M9-376, -383) | L, W |
| CHK-M9-276 | APP | REQ-212 (4), REQ-229 (4): no-ad-hoc and inventory invariants (route walk, no listening socket, no outbound connection) with the M9 routes | W |

## TP-M9-low: low-risk batch (TASK-207, -208; REQ-232, REQ-233) — tester-m9

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-280 | CODE | TASK-207 G16: in a copy, `npm run gen:api` from `web/` leaves `web/src/api/schema.d.ts` byte-identical (no diff) | L or W |
| CHK-M9-281 | CODE | TASK-207: every path added in `schema.d.ts` and `manager/openapi.json` since `d09c537` starts with `/api/v1/`; the added paths are exactly `POST /scans`, `POST /scans/{id}/cancel` and the five `/scan-schedules` operations (no read view, no reevaluate, no `run`) | L |
| CHK-M9-282 | CODE | TASK-207: `npm run typecheck` and `npm run lint` from `web/` pass | L |
| CHK-M9-283 | CODE | TASK-207 G16 plant: a hand edit to `schema.d.ts` in a copy makes the regeneration diff non-empty (red) | L |
| CHK-M9-284 | CODE | REQ-232 (3): the `ComplianceJob`, `ResultsRequest`, `ResultsResponse` component schemas in `manager/openapi.json` are byte-identical to `d09c537` (`git show d09c537:manager/openapi.json`, JSON-extracted) | L |
| CHK-M9-285 | APP | TASK-208 REQ-233 (1): follow each new README section (start a scan through the API with each target form, the 202 answer, `Idempotency-Key` repeat and conflict; cancel; schedule create/list/get/patch/delete, cron and time zone, no back-fill, skips) against a WSL manager; each step behaves as written; any step that differs is a FAIL row with the observed answer | W |
| CHK-M9-286 | CODE | TASK-208 REQ-233 (2): the new README text holds no token (`bs[uakse]_[A-Za-z0-9_-]{20,}`), password, internal id, host path of a tester, or process note (agent names, TASK ids, "tester", "lead") | L |
| CHK-M9-287 | CODE | TASK-208: the README states that results views arrive with M11, the 24 h idempotency window and its loss on restart, and the scan-state lag of up to one sweep (plan TASK-203 §6) — each checked against the spec value it quotes | L |

## TP-M9-20: gate rows (tester-m9b at the gate)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M9-300 | CODE | `ruff check manager && ruff format --check manager` clean | L, W |
| CHK-M9-301 | CODE | `mypy --strict --config-file manager/pyproject.toml manager` clean; plant: an untyped function in `intake.py` → red | L, W |
| CHK-M9-302 | APP | G5 services coverage ≥ 85 % incl. `services/jobs` and the new scheduler modules; plant: an untested function in `jobs/intake.py` sized from the clean report → below 85 % | W |
| CHK-M9-303 | CODE | G6 OpenAPI byte-identical; plant: a route added without re-export → red | W |
| CHK-M9-305 | APP | G18 full suite `-n auto`, 0 skipped | W |
| CHK-M9-306 | APP | G19 schema diff green with no migration; plant: a throwaway migration adding `ix_job_scan` → red | W |
| CHK-M9-307 | CODE | G30 agent contract suite unchanged; plants: `operator` added to `ComplianceJob`; the NUL fixture made invalid → red | W |
| CHK-M9-308 | APP | G31, G33 M3 agent-auth and sweep/inventory suites green | W |
| CHK-M9-309 | CODE | G34 route walk with the seven operations; plant: `POST /scans/{id}/run` with an `execute` body → red | W |
| CHK-M9-310 | APP | REQ-227 (3): the audit chain verifies after the M9 suites | W |

## Mutation table (CHK-M9-320 to -382, `work/tasks.md`; plus tester extras)

Every row of `work/tasks.md` "M9 mutation table" is planted by the tester of its target task and must turn the named gate red; the checks above name the test expected to go red. Pure-module rows (tester-m9, G66/G67): -323, -324, -325, -326, -330, -331, -334, -335, -336, -337, -338, -343, -344, -347, -348, -349, -350, -351, -360, -361, -362, -367, -368, -369, -370 (pure part). Extra tester plants:

| CHK | Plant | Red in | Target |
| --- | --- | --- | --- |
| CHK-M9-383 | `import re` added to a pure M9 module | G1 | TASK-186 to -192 |
| CHK-M9-384 | `storable` replaces only U+0000 (surrogates kept) | G66 (CHK-M9-059, -061) | TASK-190 |
| CHK-M9-385 | `plan` evaluates the received text, stores the replaced one | G66 (CHK-M9-059) | TASK-190 |
| CHK-M9-386 | crontab weekday step translated as a weekday (`*/2` → `*/tue`) | G66 (CHK-M9-068) | TASK-191 |
| CHK-M9-387 | `next_fire` returns ≥ instead of > the instant | G66 (CHK-M9-074) | TASK-191 |
| CHK-M9-388 | idempotency entry kept forever (no 24 h expiry) | G66 (CHK-M9-076) | TASK-192 |
| CHK-M9-389 | idempotency remembers a refused first answer | G66 (CHK-M9-077) | TASK-192 |
| CHK-M9-390 | `accepts_results` ignores `kind` | G66 (CHK-M9-011) | TASK-186 |
| CHK-M9-391 | `derive` returns `cancelled` before checking results | G66 (CHK-M9-015, -018) | TASK-187 |
| CHK-M9-392 | `parse_target` accepts `{"all": 1}` (truthiness instead of `is True`) | G66 (CHK-M9-027) | TASK-188 |
| CHK-M9-393 | `pickup_by` rounded up to the next second | G66 (CHK-M9-039) | TASK-189 |
| CHK-M9-073a | the exact `available_timezones()` check removed (TASK-191 r2) | G66 on Windows (`utc `, `utc`, `UTC ` accepted) | TASK-191 |
| CHK-M9-386a | the fall-back repeat dedupe dropped (TASK-191 r1) | G66 (CHK-M9-071 repeat rows) | TASK-191 |
| CHK-M9-392a, -392b | targets: duplicates compared as strings; the hex-digit check dropped | G66 (CHK-M9-030, -027) | TASK-188 |
| CHK-M9-331c, -335b, -350b, -367b | variants of their table rows (caps measured after replacement; `max_parallel_plugins` ignored; `pickup_by` without `Z`; no per-key lock) | G66 | TASK-190, 186, 189, 192 |

## Questions (sent to `main` 2026-10-30)

- **Q1 (REQ-223 (2), #128 (b)).** `30 2 * * *` in `Europe/London` is neither in the spring gap nor in the autumn repeat (both are 01:00–01:59 local). **Answered** (decisions "M9 early rulings" (2)): keep the `30 2` London rows (each fires once); add `30 1 * * *` Europe/London on 2026-03-29 (the gap: skipped) and 2026-10-25 (the repeat: fires once). Record APScheduler 3.11's actual behaviour; a difference from #128 (b) goes to `main`, the test is not adjusted.
- **Q2 (REQ-208 (2)).** Is one UUID given in two letter cases a duplicate? **Answered** (decisions "M9 early rulings" (3)): yes, refused; CHK-M9-030 asserts it. Also added CHK-M9-032 (tag constants equal `admin.py`).

## Not run in M9 (with the milestone)

The runner executing plugins, redaction and truncation (**M10**); the nightly end-to-end scan → results on VMs, the read views, CSV, re-evaluation route and retention of scans (**M11**); load tests (deferred by the user).
