# M9 test report

Phase report for M9 (scan engine). Each section is folded by the lead, unchanged, from the tester's per-task report `work/reports/<id>-test.md` (the source); headings are demoted one level. The harness blocks tester sub-agents from writing this file (user ruling 2026-10-27).

| Report | Verdict line | Source |
| --- | --- | --- |
| TASK-186 | TASK-186 TEST: PASS | `work/reports/TASK-186-test.md` |
| TASK-187 | TASK-187 TEST: PASS | `work/reports/TASK-187-test.md` |
| TASK-188 | TASK-188 TEST: PASS | `work/reports/TASK-188-test.md` |
| TASK-189 | TASK-189 TEST: PASS | `work/reports/TASK-189-test.md` |
| TASK-190 | TASK-190 TEST: PASS | `work/reports/TASK-190-test.md` |
| TASK-191 | TASK-191 TEST: PASS (revision 2) | `work/reports/TASK-191-test.md` |
| TASK-192 | TASK-192 TEST: PASS | `work/reports/TASK-192-test.md` |
| TASK-193 | TASK-193 TEST: PASS | `work/reports/TASK-193-test.md` |
| TASK-194 | TASK-194 TEST: PASS | `work/reports/TASK-194-test.md` |
| TASK-195 | TASK-195 TEST: PASS (r1; round 1 FAIL) | `work/reports/TASK-195-test.md` |
| TASK-196 | TASK-196 TEST: PASS | `work/reports/TASK-196-test.md` |
| TASK-197 | TASK-197 TEST: PASS (incl. r1) | `work/reports/TASK-197-test.md` |
| TASK-198 | TASK-198 TEST: PASS | `work/reports/TASK-198-test.md` |
| TASK-199 | TASK-199 TEST: PASS (on TASK-195 r1; round 1 FAIL through TASK-195) | `work/reports/TASK-199-test.md` |
| TASK-200 | TASK-200 TEST: PASS | `work/reports/TASK-200-test.md` |
| TASK-201 | TASK-201 TEST: PASS (incl. r1) | `work/reports/TASK-201-test.md` |
| TASK-202 | TASK-202 TEST: PASS (r1) | `work/reports/TASK-202-test.md` |
| TASK-203 | TASK-203 TEST: PASS (incl. r1) | `work/reports/TASK-203-test.md` |
| TASK-204 | TASK-204 TEST: PASS (r1) | `work/reports/TASK-204-test.md` |
| TASK-205 | TASK-205 TEST: PASS (r1) | `work/reports/TASK-205-test.md` |
| TASK-206 | TASK-206 TEST: PASS | `work/reports/TASK-206-test.md` |
| TASK-207 | TASK-207 TEST: PASS | `work/reports/TASK-207-test.md` |
| TASK-208 | TASK-208 TEST: PASS | `work/reports/TASK-208-test.md` |
| M9-gate | M9 gate (TP-M9-20): PASS | `work/reports/M9-gate-test.md` |

### TASK-186


Tester: tester-m9, 2026-10-30. Full rigor (job state rules, high risk). REQ-206, REQ-217 at rule level; TS §4.4 L562–L582, §3.3 L222, §6.1 L1071; #124 (a), (d), #127 (a)–(c). Code under test: `bm/services/jobs/states.py` (impl-manager-m9, `work/reports/TASK-186-impl.md`; sha256 `57d2f6ed1463afee…`). Test files (new): `manager/tests/test_job_states.py`, and in `manager/tests/test_jobs_property.py` `test_state_machine_walks` and `test_deadline_is_the_integer_ceiling`. Plan rows: CHK-M9-001 to -014, -080, -081 (`tests/m9/test-plan.md`). The tests were written from the plan's expected values before the code was read. Then they were bound to the interface: `allowed(old, new)` is the transition check, and the module also has `TRANSITIONS`, `NEVER_STARTED_AFTER` and `MAX_PARALLEL_MIN/MAX`.

#### Runs

| Run | Command (W: `/root/bstest-m9-base`, venv `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned to the copy, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_job_states.py tests/test_jobs_property.py::test_state_machine_walks tests/test_jobs_property.py::test_deadline_is_the_integer_ceiling` | **240/240 passed**, 0 failed, 0 errors, 0 skipped |
| r0 (all M9 unit and property files, for context) | `pytest` over the 8 M9 unit and property files | 672/674 passed, 2 failed (both TASK-191 DST rows), 0 errors, 0 skipped |
| plants | 9 plants, each in its own `/root/bstest-m9-mut-<id>` (removed after each; the import path was checked to be the copy) | 9/9 red |
| CHK-M9-383 (L) | `import re` prepended to each of the 7 W1 pure modules in `$TEMP/m9t-mut-383`, then `ruff check --config manager/pyproject.toml` | red: 7 × TID251 |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict --config-file manager/pyproject.toml` on `states.py` and the test files | clean |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-001 | CODE | W | r1 | PASS | `FINAL` = {completed, expired, cancelled} and `ACCEPTING` = {dispatched, running, failed, partial, completed}, both frozensets. `get_args(JobState)` is the eight TS §4.4 states | 2026-10-30 |
| CHK-M9-002 | CODE | W | r1 | PASS | All 64 ordered pairs of the eight states: `allowed()` is True for exactly the 14 REQ-206 pairs (p→p included, r→r refused). `TRANSITIONS` equals that set and is read-only (`TypeError` on assignment). No pair leaves a final state. Unknown names → False | 2026-10-30 |
| CHK-M9-003 | CODE | W | r1 | PASS | A hand-written (state × event) table: 8 states × 13 events (pull, 6 batch shapes, deadline none/some/all, 24 h, cancel, pickup) = 104 pairs. 97 are asserted and the table has exactly 7 n/a rows. Those are running × 24 h, and failed/partial × the three deadline events. The sweep's candidate filter applies them (CHK-M9-120, tester-m9b). Every batch move is an allowed transition | 2026-10-30 |
| CHK-M9-004 | CODE | W | r1 | PASS | From `dispatched`, an empty batch and a non-empty one both give `start=True`. The state is running / partial (final) / completed (all, even when not final) | 2026-10-30 |
| CHK-M9-005 | CODE | W | r1 | PASS | From `running`, `start` is never True (0/1/50 stored × all × final). A non-final batch with plugins missing stays running | 2026-10-30 |
| CHK-M9-006 | CODE | W | r1 | PASS | From `failed` and `partial`, `stored=0` leaves the state unchanged whatever the flags say. `stored>0` gives partial, or completed when all have results. The REQ-217 (4) rows hold | 2026-10-30 |
| CHK-M9-007 | CODE | W | r1 | PASS | `completed` → completed for all 8 flag combinations. `queued`, `expired`, `cancelled` and `bogus` raise `ValueError`. `BatchOutcome` is frozen | 2026-10-30 |
| CHK-M9-008 | CODE | W | r1 | PASS | `after_deadline`: (F,F) → failed, (T,F) → partial, (T,T) → completed | 2026-10-30 |
| CHK-M9-009 | CODE | W | r1 | PASS | REQ-206 (2): Σ95/2 → +648 s, Σ30/8 → +604 s, Σ3,000,000/1 → +3,000,600 s exactly (microsecond 0). Ceiling boundaries 4/2, 5/2, 1/8, 8/8, 9/8, 3,000,000/8 and 600/7 hold. The start's microseconds are kept. A `+08:00` start gives the same instant. A tuple is accepted | 2026-10-30 |
| CHK-M9-010 | CODE | W | r1 | PASS | `max_parallel_plugins` 0, −1, 9 and 100 raise `ValueError`; 1 and 8 are accepted; `[]` and `()` raise. **Recorded, not asserted:** `True` is taken as 1 (+630 s); timeouts 0 and −5 are accepted (+600 s, +598 s). The inputs come from the validated payload (`ComplianceJob` timeout 1–600) and the 1–8 setting | 2026-10-30 |
| CHK-M9-011 | CODE | W | r1 | PASS | For each accepting state: `D`, `D+7d−1µs` and `D+7d` accepted; `D+7d+1µs` and `D+7d+1s` refused. `queued`/`expired`/`cancelled` refused at D, D+1 s and D+1 d. `inventory` refused in all 8 states. Kind `bogus` and `dispatched_at=None` refused. **Recorded:** `now` before `dispatched_at` is accepted | 2026-10-30 |
| CHK-M9-012 | CODE | W | r1 | PASS | `LATE_WINDOW` 7 d, `DEADLINE_SLACK` 10 min, `NEVER_STARTED_AFTER` 24 h, `MAX_PARALLEL_MIN/MAX` (1, 8) | 2026-10-30 |
| CHK-M9-013 | CODE | W | r1 | PASS | AST import closure of each of the 7 W1 pure modules (explicit imports and their parent package inits) reaches no `db`, `repositories`, `api`, `app`, `cli`, `runtime`, `psycopg`, `fastapi`, `re`, `logging`, `socket` or `subprocess`. No system-clock call (`datetime.now`, `time.time` …; the idempotency store reads only its injected clock) and no `open`/`print`/`eval`. See note 1 | 2026-10-30 |
| CHK-M9-014 | CODE | W | r1 | PASS | Under a `sys.addaudithook` probe, 20 × (64 transition checks, acceptance, all batch shapes, deadline outcomes, `deadline_at`) see no `open`, socket, `subprocess.Popen` or `os.system` event | 2026-10-30 |
| CHK-M9-080 | CODE | W | r1 | PASS | 5,000 hypothesis walks of up to 20 events over 1–6 plugin jobs. No event leaves a final state. `failed`/`partial` reach only completed/partial. `running` is never re-entered. Every move is allowed. `start` comes only from dispatched and only once | 2026-10-30 |
| CHK-M9-081 | CODE | W | r1 | PASS | 3,000 cases (1–5,000 timeouts of 1–600, mpp 1–8): deadline − start − 600 s = `(Σ + mpp − 1) // mpp` exactly | 2026-10-30 |
| CHK-M9-325 | CODE | W | plant: `cancelled` added to `ACCEPTING` | PASS (red) | 9 failed: `test_final_and_accepting_sets`, the 6 cancelled × batch table rows, `test_non_accepting_states_are_refused_at_any_time[cancelled]`, `test_state_functions_do_no_io` | 2026-10-30 |
| CHK-M9-326 | CODE | W | plant: `now < dispatched_at + LATE_WINDOW` | PASS (red) | 5 failed: `test_acceptance_window_boundary[*]` (the +7 d exactly row) | 2026-10-30 |
| CHK-M9-334 | CODE | W | plant: `start = True` | PASS (red) | 8 failed: `test_running_never_restarts`, `test_running_outcomes`, the 6 running × batch table rows | 2026-10-30 |
| CHK-M9-335 | CODE | W | plants: (a) `sum // mpp` (floor); (b) `mpp` ignored (`// 1`) | PASS (red) | (a) 8 failed and (b) 10 failed: `test_deadline_rows` (Σ95/2, Σ5/2, Σ1/8 …), `test_deadline_keeps_the_start_microseconds_and_instant`, `test_deadline_accepts_a_tuple` | 2026-10-30 |
| CHK-M9-336 | CODE | W | plant: `DEADLINE_SLACK = timedelta(seconds=10)` | PASS (red) | 14 failed: every deadline row, `test_deadline_is_exact_for_large_sums`, `test_window_and_slack_constants` | 2026-10-30 |
| CHK-M9-337 | CODE | W | plant: `partial` on any batch with plugins missing | PASS (red) | 6 failed: `test_dispatched_batch_starts_the_job`, `test_running_outcomes`, 4 table rows | 2026-10-30 |
| CHK-M9-338 | CODE | W | plant: the `completed` branch returns `partial` | PASS (red) | 8 failed: `test_completed_job_never_changes`, the 6 completed × batch table rows and the G67 walk `test_state_machine_walks` | 2026-10-30 |
| CHK-M9-390 | CODE | W | plant: `accepts_results` ignores `kind` | PASS (red) | 6 failed: `test_inventory_jobs_are_never_accepted[5 accepting states]`, `test_unknown_kind_and_missing_dispatch_are_refused` | 2026-10-30 |
| CHK-M9-383 | CODE | L | plant: `import re` in each pure module | PASS (red) | ruff TID251 "`re` is banned" × 7 (G1); CHK-M9-013 also lists `re` in `FORBIDDEN_EXACT` | 2026-10-30 |

#### Acceptance (TASK-186 row: "REQ-206 (1)–(5) hold")

- (1) table of every (state, event) pair, with the pairs the table does not allow refused → CHK-M9-002, -003 (and -004 to -008).
- (2) deadline rows, exact integer arithmetic, `ValueError` → CHK-M9-009, -010, -081.
- (3) property: final states are kept, failed/partial reach only completed/partial, running is not re-entered → CHK-M9-080.
- (4) acceptance window, exactly 7 d accepted, + 1 µs refused, queued/expired/cancelled/inventory refused, completed accepted → CHK-M9-011.
- (5) import graph → CHK-M9-013.

#### Notes

1. **For the reviewer (not a TASK-186 defect).** `states.py` itself imports only the stdlib. But TASK-204's in-progress `services/jobs/__init__.py` now imports `services/jobs/intake.py`, so `import bitscan_manager.services.jobs.states` in a fresh interpreter also loads `repositories.job_intake`, `repositories.settings`, `repositories.audit_log` and psycopg. `test_package_init_effect_is_recorded` records this. The impl report's line "`pull.py`, which is pure" no longer describes the package init. The pure modules stay pure as source, but they are not import-light. Whether the package init should re-export the intake service is TASK-204's call.
2. The mutation row CHK-M9-338 names G66 and G67; both are red.

### TASK-187


Tester: tester-m9, 2026-10-30. Full rigor (scan state derivation, high risk). REQ-207 (and REQ-219's derivation rule); TS §4.4 L579–L580; #22, #127 (d), (e); #3. Code under test: `bm/services/jobs/scan_state.py` (impl-manager-m9, `work/reports/TASK-187-impl.md`; sha256 `6d78e8235b72af8e…`). Test files (new): `manager/tests/test_scan_state.py`, and `test_derivation_properties` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-015 to -021, -082. Written from #127 (d) before the code was read; the interface matched the plan (TASK-202 §2) unchanged.

#### Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_state.py tests/test_jobs_property.py::test_derivation_properties` | **53/53 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 3 plants in `/root/bstest-m9-mut-<id>` (removed after each) | 3/3 red |
| static (L) | ruff, ruff format, mypy --strict on `scan_state.py` and the test files | clean |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-015 | CODE | W | r1 | PASS | REQ-207 (1): 10 rows. A test helper builds each unit's facts from the job states of the original and its retry, and from the plugins with results. All queued → (queued, F); one dispatched → running (#22); expired + queued → running; all complete → (completed, T); original partial + retry completing it → completed; complete + failed with no results → partial; no results + cancelled → cancelled; expired + failed → failed; cancelled after results → partial; cancelled after every unit was complete → completed | 2026-10-30 |
| CHK-M9-016 | CODE | W | r1 | PASS | Unit rule: an original partial plus a completed retry is one complete unit (completed, not partial). failed + queued retry, and partial + running retry, are open (running, not finished). partial + partial still missing → partial; failed + failed → failed | 2026-10-30 |
| CHK-M9-017 | CODE | W | r1 | PASS | `queued` only when every unit is all-queued; one closed unit (expired, completed) makes it running; an ended original with a queued retry → running | 2026-10-30 |
| CHK-M9-018 | CODE | W | r1 | PASS | No results: a cancelled unit (alone, with expired, or as the retry of a failed original) → cancelled; nothing cancelled → failed. Results anywhere beat cancelled → partial | 2026-10-30 |
| CHK-M9-019 | CODE | W | r1 | PASS | `derive([])` and `derive(())` raise `ValueError` (#3); a list and a tuple of the same units agree | 2026-10-30 |
| CHK-M9-020 | CODE | W | r1 | PASS | Exhaustive: all 32 one-unit fact combinations and all 1,024 two-unit pairs give one of the 6 scan states (never dispatched or expired), finished exactly when no unit is open. Over every consistent closed pair the order completed > partial > cancelled > failed holds | 2026-10-30 |
| CHK-M9-021 | CODE | W | r1 | PASS | `Unit` is frozen; `derive` leaves its input unchanged | 2026-10-30 |
| CHK-M9-082 | CODE | W | r1 | PASS | 5,000 hypothesis sets of 1–20 consistent units (complete ⇒ has_results; all_queued ⇒ open ∧ no results ∧ not cancelled). Finished ⇔ no unit open; never dispatched/expired; independent of unit order. Adding a result to one unit never turns partial/completed into failed/cancelled, and an unfinished scan stays queued/running | 2026-10-30 |
| CHK-M9-360 | CODE | W | plant: the `any_cancelled` check moved above `has_results` | PASS (red) | 3 failed: `test_req_207_table` (cancelled after some results), `test_cancelled_failed_overlap`, `test_closed_scan_states_follow_the_order_of_the_rule` | 2026-10-30 |
| CHK-M9-362 | CODE | W | plant: the open branch returns `dispatched` instead of `running` | PASS (red) | 14 failed, in G66 (`test_req_207_table`, `test_one_unit_any_facts`, `test_two_units_any_facts`, `test_queued_only_when_every_job_is_queued`, `test_failed_original_with_a_queued_retry_is_open`) and G67 (`test_derivation_properties`) | 2026-10-30 |
| CHK-M9-391 | CODE | W | plant: `all(u.open …)` instead of `any` (finished too early) | PASS (red) | 4 failed: `test_req_207_table` (expired + queued), `test_queued_only_when_every_job_is_queued`, `test_two_units_any_facts`, `test_derivation_properties` | 2026-10-30 |
| CHK-M9-361 | CODE | W | plant: "derivation per job, not per unit" | NOT RUN here (reason) | `derive()` receives `Unit` facts, so a per-job derivation cannot be planted in this module alone. The per-unit grouping lives in TASK-194's `unit_facts` (`COALESCE(retry_of, job_id)`). The plant there is "group by `job_id`", which must turn CHK-M9-114/-212 red. **Handed to tester-m9b.** At this level CHK-M9-016 pins the unit rule (an original `partial` + completing retry = complete) | 2026-10-30 |

#### Acceptance (TASK-187 row: "REQ-207 (1)–(3) hold")

- (1) the table → CHK-M9-015 to -018.
- (2) property over random unit sets → CHK-M9-082 (and the exhaustive CHK-M9-020).
- (3) empty unit list raises `ValueError` → CHK-M9-019.

#### Notes

- `derive()` reads only the five facts and does not check that they are consistent (for example `all_queued` without `open`). CHK-M9-020 shows that for every combination, consistent or not, it still never returns dispatched/expired and finished ⇔ no unit open. Whether the facts are consistent is TASK-194's SQL (CHK-M9-114).

### TASK-188


Tester: tester-m9, 2026-10-30. Full rigor (scan targets, high risk). REQ-208 (1), (2), (4); TS §4.4 L555, §5.2 L865, §6.4 L1151; #122 (b)–(d), #68; decisions 2026-10-30 "M9 early rulings" (1) (tag constants copied) and (3) (a case variant of one UUID is a duplicate). Code under test: `bm/services/jobs/targets.py` (impl-manager-m9, `work/reports/TASK-188-impl.md`; sha256 `d3c1180cef98390d…`). Test files (new): `manager/tests/test_scan_targets.py`, and `test_parse_target_never_raises_anything_else` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-025 to -032, -086.

#### Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_scan_targets.py` (first run) | 71/72 passed, 1 failed (`test_every_allowed_tag_character`: **test bug**, my tag of all 66 allowed characters is over the 64 limit) |
| r1 | `pytest tests/test_scan_targets.py tests/test_jobs_property.py::test_parse_target_never_raises_anything_else` (test fixed: two tags of 64 + 2 characters) | **73/73 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 3 plants in `/root/bstest-m9-mut-<id>` | 3/3 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-025 | CODE | W | r1 | PASS | `{"agents": [u1, u2]}` → kind agents, `UUID`s in input order; uppercase input is stored lowercase; `{"tags": ["a","b"]}` → kind tags; `{"all": true}` → `Target("all")` with no agents and no tags | 2026-10-30 |
| CHK-M9-026 | CODE | W | r1 | PASS | 1 and 10,000 agents accepted, 10,001 refused; 32 tags accepted, 33 refused; tags of 1 and 64 characters accepted, 65 and `""` refused; each of the 66 `[A-Za-z0-9._:-]` characters accepted; `a b`, `a/b`, `a,b`, `é`, NUL, tab, `*`, newline, `+`, `@` and a lone surrogate refused | 2026-10-30 |
| CHK-M9-027 | CODE | W | r1 | PASS | 37 refusals, each `InvalidTarget` (a `ValueError`): no key, two keys, an unknown key, `ALL`; `all` false, 1, 1.0, "true", null, [true]; empty lists; duplicate agent and duplicate tag; non-UUIDs (`x`, 32-hex, braced, `urn:uuid:`, hyphen moved, `1234567_-…` (accepted by `int()`), a leading space, `g`); non-lists (string, object, tuple); non-string items; non-dict values (null, [], "all", 1, true) | 2026-10-30 |
| CHK-M9-028 | CODE | W | r1 | PASS | Six canary inputs (in a tag, an agent id, a key, `all`'s value, a duplicate tag): `str()`, `repr()` and `args` name `target` and hold no input. Over all 37 refusals the messages are at most 4 fixed strings, each starting `Invalid request: target` | 2026-10-30 |
| CHK-M9-029 | CODE | W | r1 | PASS | `stored_target`: the agents form → lowercase ids in request order plus `resolved_agents` sorted; the tags form → the tags plus sorted resolved; all → `{"all": true, "resolved_agents": …}`; resolved ids are lowercase, distinct and sorted, and the duplicates in the input are dropped; JSON round trip is equal; one form key only; the dict does not alias the `Target` | 2026-10-30 |
| CHK-M9-030 | CODE | W | r1 | PASS | Ruling (3): `[u, U]` and `[U-prefix, u]` (one UUID in two letter cases) → `InvalidTarget`. Tags stay case-sensitive (`Prod`, `prod` are two tags, the M3 rule) | 2026-10-30 |
| CHK-M9-031 | CODE | W | r1 | PASS | Covered by CHK-M9-013 (TASK-186 report): `targets.py` imports only `string`, `collections.abc`, `dataclasses`, `typing`, `uuid` | 2026-10-30 |
| CHK-M9-032 | CODE | W | r1 | PASS | Ruling (1): `targets.TAGS_MAX == admin.MAX_TAGS == 32`, `MAX_TAG_LENGTH == admin.MAX_TAG_LENGTH == 64`, `TAG_CHARACTERS == admin.TAG_CHARACTERS`, `AGENTS_MAX == 10_000`. For every single character U+0000 to U+02FF, `parse_target` accepts it as a tag exactly when it is in `admin.TAG_CHARACTERS` | 2026-10-30 |
| CHK-M9-086 | CODE | W | r1 | PASS | 5,000 random JSON values: only `InvalidTarget` is ever raised; each accepted value gives a `stored_target` with exactly one form key that round-trips through JSON | 2026-10-30 |
| CHK-M9-392 | CODE | W | plant: `if not inner:` instead of `inner is not True` | PASS (red) | 6 failed: `test_refused` for `{"all": 1}`, `1.0`, `"true"`, `[true]`, plus `test_messages_name_target_and_quote_no_input[all=canary]` and `test_message_set_is_small_and_fixed` | 2026-10-30 |
| CHK-M9-392a | CODE | W | plant: duplicates compared as strings, not by UUID value | PASS (red) | 1 failed: `test_case_variant_of_one_uuid_is_a_duplicate` (ruling (3)) | 2026-10-30 |
| CHK-M9-392b | CODE | W | plant: the hex-digit check dropped (hyphen positions only) | PASS (red) | 4 failed: `test_refused` for `1234567_-…` (accepted by `int()`), a leading space and a `g`, which escape as a plain `ValueError`, plus `test_message_set_is_small_and_fixed` | 2026-10-30 |

#### Acceptance (TASK-188 row: "REQ-208 (1), (2) and (4) hold")

- (1) three forms, lowercase storage → CHK-M9-025, -029.
- (2) every listed refusal, message names `target` and holds no input → CHK-M9-026 to -028, -030.
- (4) `scan.target` = the request plus sorted `resolved_agents` → CHK-M9-029.
- (3), resolution on PostgreSQL, is TASK-193 (tester-m9b, CHK-M9-110).

#### Notes

- No mutation-table row targets TASK-188; the three plants come from the impl report's suggestions and the plan (CHK-M9-392, -392a, -392b).
- `InvalidTarget.field` is one of `target`, `target.agents`, `target.tags`, `target.all`, for TASK-205's problem detail. It is not asserted per case; the spec asks only that the message names `target`.

### TASK-189


Tester: tester-m9, 2026-10-30. Full rigor (job and retry builder; second look, PD-39). REQ-209 (1)–(4), (6) and REQ-210 (1)–(4) for plugins given as values; REQ-212 at builder level; TS §3.5 L248, §6.5 L1165–L1182, §4.4 L566, L577, §4.1 L530; SR §1.1; #117, #125 (a)–(c), (g), #126 (a), (b). Code under test: `bm/services/jobs/build.py` (impl-manager-m9, `work/reports/TASK-189-impl.md`, including the later `PICKUP_WINDOW as PICKUP_WINDOW` re-export; sha256 `fd339fbcf84aac92…`). Test file (new): `manager/tests/test_job_build.py`. Plan rows: CHK-M9-037 to -050.

#### Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_job_build.py` (first run) | 61/62 passed, 1 failed (`test_no_payload_holds_evaluation_data`: **test bug**, my fixture gave plugin *n* `timeout_s = 10 + n`, which goes over 600 for the 5,000-plugin case) |
| r1 | same, fixture `timeout_s = 10 + n % 590` | **62/62 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 9 plants in `/root/bstest-m9-mut-<id>` | 9/9 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-037 | CODE | W | r1 | PASS | `payload()` has exactly the six keys; `job_id` and `agent_id` are the lowercase strings (an uppercase-built `UUID` too); `kind` compliance. It validates as `ComplianceJob`, as `JobsResponse`, and against `JobsResponse.model_json_schema()` with the contract suite's Draft 2020-12 validator and its uuid/date-time format checks | 2026-10-30 |
| CHK-M9-038 | CODE | W | r1 | PASS | Plugin order = input order (5, 1, 4, 2, 3), and the same in `eval_spec`; items are exactly `{plugin_uuid, execute, timeout_s}`; `plugin_uuid` lowercase. `execute` is byte-identical (also after a JSON round trip) for the SR §1.1 command, awk with `$3`, a grep with `\s`, newlines, tabs, backslashes, non-ASCII, an emoji and 16,384 characters. `timeout_s` 1 and 600 are copied | 2026-10-30 |
| CHK-M9-039 | CODE | W | r1 | PASS | `pickup_by`: 12:00:00Z → next day 12:00:00Z; `.999999` → `…12:00:00Z` (truncated, never rounded up); 2026-12-31 23:59:59.5 → `2027-01-01T23:59:59Z`; 2028-02-28 → 02-29 (leap); `+08:00` and `−05:00` creation times → UTC text. Each text matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` and lies in (column − 1 s, column]. `build.PICKUP_WINDOW` = 24 h. A naive `created_at` → `ValueError` | 2026-10-30 |
| CHK-M9-040 | CODE | W | r1 | PASS | Recursive walk of three payloads (5,000 plugins with a canary pattern, a 5-plugin one, a retry): no `operator`, `expected`, `expected_result`, `eval_spec` or `name` key, and no string that is an expected value or a display name (the canary carries both). Each validates as `ComplianceJob` | 2026-10-30 |
| CHK-M9-041 | CODE | W | r1 | PASS | `parse_eval_spec(eval_spec_json)` succeeds; its uuids equal the payload's in order (3, 1, 2); `name` = display name, `operator`, `expected` copied; each entry has exactly the four #117 keys and the top level only `plugins` | 2026-10-30 |
| CHK-M9-042 | CODE | W | r1 | PASS | 0, 1 and 50 patterns are copied in order (each payload validates). Mutating the caller's list, or a built payload, does not change the next `payload()` from the same `BuiltPlugins`. **Recorded:** 51 patterns are accepted by the builder; the setting caps at 50 (`MAX_REDACTION_PATTERNS`, `services/settings/store.py`) | 2026-10-30 |
| CHK-M9-043 | CODE | W | r1 | PASS | 16 cases (U+0000, `\ud800`, `\udfff`, a reversed pair `\udc00\ud800` in `execute`, `display_name`, `expected` and a pattern) → `UnstorableText` (a `ValueError`) with one fixed message holding no canary. An emoji, U+FFFD, `é`, U+0001 and a tab are accepted. The text check runs before the operator check | 2026-10-30 |
| CHK-M9-044 | CODE | W | r1 | PASS | 1 and 5,000 plugins build; 0 and 5,001 → `ValueError`; a duplicate uuid, the operator `EQUALS` and an empty name → `ValueError` | 2026-10-30 |
| CHK-M9-045 | CODE | W | r1 | PASS | The SR §1.1 plugin gives `eval_spec` `{"plugins": [{"plugin_uuid": "3f6c2a9e-…", "name": "CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed", "operator": "equals", "expected": "install ok installed"}]}`, and the payload carries its `Execute` and timeout 30 | 2026-10-30 |
| CHK-M9-046 | CODE | W | r1 | PASS | REQ-210 (1)–(3): from a 5-plugin original, missing {5, 1, 3} given as a set → plugins exactly the original items 1, 3, 5 (equal dicts); the original's patterns; `job_id` = the new id; `agent_id` the original's; `pickup_by` = the new creation + 24 h; `eval_spec` = the original's entries 1, 3, 5, which parse; the keys match the original's six. All five missing → the whole original | 2026-10-30 |
| CHK-M9-047 | CODE | W | r1 | PASS | `retry`'s parameters are exactly `original_payload, original_eval_spec, missing, job_id, created_at, original_is_retry`. There is no catalog input, so the retry carries `original command 3`, not anything else | 2026-10-30 |
| CHK-M9-048 | CODE | W | r1 | PASS | `original_is_retry=True`, `missing` empty (set, list, tuple) and `missing` naming a uuid outside the payload → `ValueError`. An `eval_spec` in another order → `ValueError`; an empty one → `EvalSpecError` | 2026-10-30 |
| CHK-M9-049 | CODE | W | r1 | PASS | Retry payloads validate as `ComplianceJob` (CHK-M9-040 walk). Mutating the returned payload or `eval_spec` leaves the original unchanged | 2026-10-30 |
| CHK-M9-050 | CODE | W | r1 | PASS | `CatalogPlugin` and `BuiltPlugins` are frozen; `UnstorableText` ⊂ `ValueError`. The strict `ComplianceJob` refuses an extra `operator` key (the backstop for CHK-M9-347 at the contract) | 2026-10-30 |
| CHK-M9-343 | CODE | W | plant: retry keeps every plugin (`if True`) | PASS (red) | 5 failed: `test_retry_holds_only_the_missing_plugins_in_original_order`, `test_retry_keeps_original_values_not_any_catalog`, `test_retry_with_a_mismatched_eval_spec_is_refused`, `test_retry_does_not_alias_the_original`, `test_no_payload_holds_evaluation_data` | 2026-10-30 |
| CHK-M9-347 | CODE | W | plant: `"operator": p.operator` added to each payload item | PASS (red) | 10 failed: the exact-shape, schema, SR §1.1, pattern, timeout, retry and no-evaluation-data tests (the strict model refuses the extra key) | 2026-10-30 |
| CHK-M9-348 | CODE | W | plant: `eval_spec` built from `reversed(plugins)` | PASS (red) | 6 failed: `test_eval_spec_parses_and_matches_payload_order`, `test_plugin_order_is_the_given_order`, the retry tests (their uuid order no longer matches), `test_no_payload_holds_evaluation_data` | 2026-10-30 |
| CHK-M9-349 | CODE | W | plant: the U+0000 check removed | PASS (red) | 5 failed: `test_unstorable_text_is_refused[*-a\x00b]` (4 fields), `test_unstorable_text_is_checked_before_anything_else`. The lone-surrogate rows stay green, because the separate encode check still catches them | 2026-10-30 |
| CHK-M9-350 | CODE | W | plants: (a) 25 h instead of 24 h; (b) the format without `Z` | PASS (red) | (a) 8 failed (`test_pickup_by_text[*]`, the exact-shape and retry tests). (b) 14 failed (also every schema validation: `Timestamp` refuses a naive time) | 2026-10-30 |
| CHK-M9-351 | CODE | W | plant: `patterns=[]` | PASS (red) | 5 failed: `test_payload_is_exactly_the_ts_6_5_job`, `test_redaction_patterns_copied_in_order[1]`, `[50]`, `test_built_payload_does_not_alias_inputs`, the retry test | 2026-10-30 |
| CHK-M9-393 | CODE | W | plant: `pickup_by` rounded up to the next second | PASS (red) | 2 failed: `test_pickup_by_text[.999999]`, `[23:59:59.5]` | 2026-10-30 |
| CHK-M9-344 | CODE | W | plant: "retry rebuilt from the current catalog" | NOT RUN here (reason) | `retry()` takes no catalog input, so the plant cannot be made in `build.py`. CHK-M9-047 pins the signature. The end-to-end row is CHK-M9-209: an import changes plugin 3's `Execute` and the setting changes, and the retry must keep the original's. That row belongs to TASK-202 (tester-m9b) | 2026-10-30 |

#### Acceptance (TASK-189 row: "REQ-209 (1)–(4) and (6) and REQ-210 (1)–(4) hold for plugins given as values")

- REQ-209 (1) shape, lowercase, `pickup_by` → CHK-M9-037 to -039; (2) no evaluation data at any depth → CHK-M9-040; (3) `eval_spec` parses and matches one to one → CHK-M9-041; (4) unstorable text → CHK-M9-043; (6) SR §1.1 → CHK-M9-045.
- REQ-210 (1)–(3) → CHK-M9-046, -047; (4) → CHK-M9-048.
- REQ-209 (5) (M8's `host_counts` on an M9-queued scan) is TASK-198 on PostgreSQL (CHK-M9-159, tester-m9b).

#### Notes for the second look (PD-39)

- `payload()` copies the lists, so a built payload cannot alias the shared `BuiltPlugins` (CHK-M9-042).
- `retry()` has an extra guard: an `eval_spec` whose kept uuids differ from the payload's in order is refused (CHK-M9-048). It also re-derives `agent_id` through `UUID()`, so the result is always lowercase.
- `payload()` does not re-check text itself. It is safe only because `BuiltPlugins` comes from `plugins_and_spec`. A caller that builds `BuiltPlugins` by hand skips the unstorable-text check. Today the only callers are TASK-193/198 (tester-m9b, CHK-M9-112).

### TASK-190


Tester: tester-m9, 2026-10-30. Full rigor (intake plan; TS §8.2 second approval, PD-39). REQ-214, REQ-215, REQ-216 at plan level; TS §6.1 L1071, §4.4 L578, §4.5 L587, L596, L599, L603; #12, #116 (d), #121, #124 (a), (b). Code under test: `bm/services/jobs/intake_plan.py` (impl-manager-m9, `work/reports/TASK-190-impl.md`; sha256 `89a13f83aef30f8b…`). Test files (new): `manager/tests/test_intake_plan.py`, and `test_plan_accounting`, `test_storable_properties`, `test_plan_rows_always_encode` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-053 to -066, -083, -084. Items are the M3 `ResultItem`, built with `json.loads` + `model_validate` as the route does (lone surrogates and U+0000 survive both, checked first); every expected verdict is computed by the test from M8's `result_verdict` / `classify`.

#### The recompute departure (impl report §"Departure")

The plan said: recompute through `result_verdict` with a proxy holding the replaced text. The code instead recomputes with `classify()` on the stored stdout, only when stdout changed, no runner error was sent and the verdict was not `oversize`. Checked against #121 and found consistent: (b) the caps are measured once, on the received text (CHK-M9-058, and plant CHK-M9-331c shows the proxy reading goes red); (c) the stored text is the evaluated text (CHK-M9-059); a runner error or `timed out` keeps its verdict (CHK-M9-059 rows). No ruling needed. The departure is also what makes a stdout of 65,000 bytes with 300 NULs stay under the cap (CHK-M9-058).

#### Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_intake_plan.py` (first run) | 106/107 passed, 1 failed (`test_storable[…]`, **test bug**: my file-writing tool turned the two-surrogate escape (U+D83D then U+DE00, written as escapes) into one emoji character, so the "two lone surrogates" row was testing U+1F600; restored as escapes, and every other decoded literal in my M9 files was restored to `\uXXXX` too) |
| r1 | `pytest tests/test_intake_plan.py tests/test_jobs_property.py::test_plan_accounting ::test_storable_properties ::test_plan_rows_always_encode` | **110/110 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 9 plants in `/root/bstest-m9-mut-<id>` | 9/9 red |
| static (L) | ruff, ruff format, mypy --strict | clean |
| r2, after review (W) | the same as r1, after `test_caps` was given short explicit `ids=` (reviewer-m9 should-fix 1: a 65 KB id breaks `PYTEST_CURRENT_TEST` on Windows) | **110/110 passed**, 0 failed, 0 errors, 0 skipped |
| r2-L (Windows, worktree venv, `CI=true`, `-n 0`) | `pytest tests/test_intake_plan.py tests/test_job_build.py` (the 16,384-character `execute` param in `test_job_build.py` was given short ids too) | **169/169 passed**, 0 errors (before the fix: 10 errors at setup/teardown, per the review). The whole M9 unit set on Windows: 675/676, the one failure being TASK-191's `utc ` zone row (see the TASK-191 report) |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-053 | CODE | W | r1 | PASS | A 50-item batch whose 50th (and, separately, whose 1st) item names a foreign plugin → `PluginNotInJob`, nothing returned. A uuid in the payload but not in `eval_spec`, or the reverse → refused. A foreign uuid also listed in `existing` → refused (membership before duplicates). The message is fixed (no canary, no uuid) | 2026-10-30 |
| CHK-M9-054 | CODE | W | r1 | PASS | uuids in `existing` (the caller's job + sibling set) → duplicates; two items for one plugin → the first (told apart by stdout) is the row, 1 duplicate; three → 1 row, 2 duplicates | 2026-10-30 |
| CHK-M9-055 | CODE | W | r1 | PASS | 50 items in reverse order → 50 rows in batch order; an empty batch → `Plan((), 0)` | 2026-10-30 |
| CHK-M9-056 | CODE | W | r1 | PASS | 54 cases: each of the 14 operators with a passing, a failing and an exit-1 input; exits 126, 127, 137, None and −1; `timed_out`; `truncated`; both runner errors; non-numeric stdout for `eq`; a refused regex. Each row's `(eval_code, eval_detail)` = `result_verdict(entry, item)` (`detail.value` or None). The codes seen are {0, 1, 2}, and detail is None exactly for PASS/FAIL | 2026-10-30 |
| CHK-M9-057 | CODE | W | r1 | PASS | stdout 65,537 B → ERROR `oversize` with `""`/`""`; 65,536 B → as sent; stderr 16,385 → oversize with both streams `""`; 16,384 → as sent; `€` × 21,846 (65,538 B) → oversize; `€` × 21,845 + `a` (65,536 B) → as sent. Oversize beats `runner_unavailable`, `truncated` and `timed_out` | 2026-10-30 |
| CHK-M9-058 | CODE | W | r1 | PASS | #121 (b): `"a" × 65,535 + NUL` (65,536 B received) is **not** oversize; stored `… + U+FFFD` (65,538 B). 65,000 B + 300 NULs → stored with 300 U+FFFD, `contains U+FFFD` PASS. 65,537 NULs → oversize with `""` streams | 2026-10-30 |
| CHK-M9-059 | CODE | W | r1 | PASS | #121 (c): `equals "a�b"` with stdout `a\x00b` → PASS (the raw text gives FAIL, checked); `equals "�"` with `json.loads('"\\ud800"')` → PASS; `regex ^x$` on `"\ud800\nx"` → PASS (raw gives M8's ERROR). stderr-only replacement → stderr replaced, verdict unchanged. `spool_overflow` + NUL → ERROR `spool_overflow`, text replaced; `timed_out` + NUL → ERROR `timed out` | 2026-10-30 |
| CHK-M9-060 | CODE | W | r1 | PASS | REQ-215 (4): the shared fixture `results/request_valid_nul_in_stdout_and_stderr.json` → every row has U+FFFD where U+0000 was, in stdout and stderr; every row encodes as strict UTF-8; the verdict equals `classify` on the stored stdout; the fixture does hold NULs | 2026-10-30 |
| CHK-M9-061 | CODE | W | r1 | PASS | `storable`: 13 rows. Identity on clean text, U+FFFD, the emoji and U+0001/U+007F/U+0085; NUL, `\ud800`, `\udbff`, `\udc00`, `\udfff` → U+FFFD; two surrogate code points → two U+FFFD; mixed → one-for-one; the length is kept. `json.loads('"\\ud83d\\ude00"')` (= the emoji) is unchanged | 2026-10-30 |
| CHK-M9-062 | CODE | W | r1 | PASS | `plugin_name_snap`, `operator_snap`, `expected_snap` from the entry; `execute_snap` = the payload command; `exit_code` 3, flags, `started_at` (with .250 s), `finished_at` and stderr as sent | 2026-10-30 |
| CHK-M9-063 | CODE | W | r1 | PASS | `runner_unavailable` and `spool_overflow` → ERROR with that detail, stdout stored as sent | 2026-10-30 |
| CHK-M9-064 | CODE | W | r1 | PASS | SR §1.1: `install ok installed` exit 0 → (0, None); `""` exit 1 → (1, None) | 2026-10-30 |
| CHK-M9-065 | CODE | W | r1 | PASS | `caplog` at DEBUG over an accepted plan and a refused one, with a canary in stdout, stderr and the expected value: no record holds it | 2026-10-30 |
| CHK-M9-066 | CODE | W | r1 | PASS | `Plan`, `ResultRow` frozen; `rows` a tuple; `existing` not mutated; `existing` may be a list, tuple, frozenset or dict view | 2026-10-30 |
| CHK-M9-083 | CODE | W | r1 | PASS | 2,000 hypothesis batches (0–50 items, jobs of 1–60 plugins, random repeats and `existing`): `rows + duplicates = items`; row uuids distinct and disjoint from `existing`; each row is the first item of its uuid; the row set = picked − existing; any foreign uuid → `PluginNotInJob` | 2026-10-30 |
| CHK-M9-084 | CODE | W | r1 | PASS | 5,000 random texts (all code points plus NUL, surrogates, U+FFFD, emoji): `storable` output encodes, holds no NUL, keeps the length, changes exactly the NUL/surrogate positions; 1,000 random stdout/stderr pairs through `plan` → rows always encode, code ∈ {0, 1, 2} | 2026-10-30 |
| CHK-M9-323 | CODE | W | plant: `seen.add` removed | PASS (red) | 3 failed: `test_two_items_for_one_plugin_first_wins`, `test_three_items_for_one_plugin`, `test_plan_accounting` (G66, G67) | 2026-10-30 |
| CHK-M9-324 | CODE | W | plant: foreign items skipped instead of refusing the batch | PASS (red) | 7 failed: the four membership tests, `test_plugin_not_in_job_message_is_fixed`, `test_no_output_in_logs`, `test_plan_accounting` | 2026-10-30 |
| CHK-M9-330 | CODE | W | plant: `oversize` stored with its streams | PASS (red) | 6 failed: `test_caps` (4 oversize rows), `test_oversize_wins_over_flags_and_runner_error`, `test_oversize_with_nuls_stores_empty_streams` | 2026-10-30 |
| CHK-M9-331 | CODE | W | plants: (a) `storable()` skipped (NUL stored raw); (c) the caps measured after replacement (#121 order reversed) | PASS (red) | (a) 9 failed: `test_caps_are_measured_on_the_received_text`, `test_many_nuls_under_the_cap_stay_under_it`, `test_verdict_is_on_the_replaced_nul_text`, `test_verdict_is_on_the_replaced_surrogate_text`, `test_regex_on_replaced_surrogate_text`, `test_stderr_replacement_does_not_change_the_verdict`, `test_runner_error_with_nul_keeps_its_verdict_and_replaces_text`, `test_nul_fixture_is_stored_with_replacement_characters`, `test_plan_rows_always_encode` (G67). The first run's summary was swallowed because the output held NUL bytes and `grep` treated it as binary; it was re-run with `grep -a`. (c) 2 failed: `test_caps_are_measured_on_the_received_text`, `test_many_nuls_under_the_cap_stay_under_it` | 2026-10-30 |
| CHK-M9-332 | CODE | W | plant: `execute_snap` from the entry instead of the payload | PASS (red) | 1 failed: `test_snapshots_and_sent_values` | 2026-10-30 |
| CHK-M9-384 | CODE | W | plant: `storable` replaces only U+0000 | PASS (red) | 10 failed: `test_storable` (surrogate rows), `test_verdict_is_on_the_replaced_surrogate_text`, `test_regex_on_replaced_surrogate_text`, `test_stderr_replacement_does_not_change_the_verdict`, `test_storable_properties` | 2026-10-30 |
| CHK-M9-385 | CODE | W | plant: no recompute after replacement (evaluate the received text, store the replaced one) | PASS (red) | 5 failed: `test_verdict_is_on_the_replaced_nul_text`, `…_surrogate_text`, `test_regex_on_replaced_surrogate_text`, `test_many_nuls_under_the_cap_stay_under_it`, `test_nul_fixture_is_stored_with_replacement_characters` | 2026-10-30 |

#### Acceptance (TASK-190 row)

"For a given `eval_spec`, payload, set of existing result uuids and batch, the plan lists exactly the rows to insert with their verdicts and snapshots and the duplicates count (CHK-M9-054 to -057, -062, -083), or refuses a batch naming a plugin outside the job (CHK-M9-053); REQ-215 (2) (CHK-M9-057), (4) (CHK-M9-058 to -061), (6) (CHK-M9-064) hold at plan level." REQ-216 (5) (two items in one batch) → CHK-M9-054.

#### Notes

- CHK-M9-322 (the sibling ignored) cannot be planted here: `plan()` takes the unit's existing uuids from its caller. At plan level, a sibling's uuid passed in `existing` is a duplicate (`test_sibling_results_passed_as_existing_are_duplicates`). The plant belongs to TASK-195/199 (tester-m9b).
- `storable()` treats every surrogate code point as unstorable, including two adjacent ones built in Python. `json.loads` already joins an escaped pair, so from the route only lone ones reach it (CHK-M9-061).

### TASK-191


**Revision 2 (2026-10-30).** `_zone()` now also requires an exact, case-sensitive match in a cached `zoneinfo.available_timezones()` set (`cron.py` sha256 `69735ddd45ff1887…`; impl report "Revision 2"). Re-runs: the failing test alone on L, `test_refused_zones['utc ']`: **1/1 passed**. Then the shared code's tests (`test_cron.py` + the `next_fire` property), with three refusal rows added (`utc`, `UTC `, `europe/london`): **L 110/110, W 110/110**, 0 failed, 0 errors, 0 skipped. Plant CHK-M9-073a (the known-zones check removed, on L): red, 3 failed (`test_refused_zones['utc ']`, `['utc']`, `['UTC ']`). r2 changes only `_zone()`, so the r1 DST and weekday plants below still stand. CHK-M9-073 is now PASS on L and W. The r1 text below is kept as the record.

---

#### Record of revision 1: FAIL (1 Windows-only row; the DST rows pass)

Tester: tester-m9, 2026-10-30. Full rigor (cron and time zone, high risk). REQ-223; TS §4.4 L557, §5.2 L851–L852, §2.1 L103; #128 (a)–(c); DST per the **user decision** (decisions 2026-10-30, "DST behaviour for scheduled scans", relayed by `main`): shift the gap and run the repeat once (at the first occurrence), as standard cron does. Code under test: `bm/services/scheduler/cron.py` **revision 1** (impl-manager-m9, `work/reports/TASK-191-impl.md` "Revision 1"; sha256 `4e6eb1d67c9d4a8d…`), on APScheduler 3.11.3 (locked). Test files (new): `manager/tests/test_cron.py`, and `test_next_fire_strictly_increasing` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-067 to -074, -085. Every expected fire time was worked out by hand from crontab(5) and the IANA rules (Europe/London 2026-03-29 and 2026-10-25; America/New_York 2026-11-01).

#### Failing test (expected vs actual)

| Test | Where | Expected | Actual |
| --- | --- | --- | --- |
| `tests/test_cron.py::test_refused_zones['utc ']` | **L (Windows) only**; W passes | `InvalidSchedule`, `field == "timezone"`: `utc ` is not an IANA name (#128 (b): unknown names 400) | accepted. On Windows `ZoneInfo('utc ')`, `ZoneInfo('utc')` and `ZoneInfo('UTC ')` all load, while `ZoneInfo('europe/london')` is refused (checked directly) |

**Diagnosis:** a product gap on the local platform. `_zone()` accepts any name `ZoneInfo()` can open. On Windows, the locked `tzdata` resources sit on a case-insensitive file system that ignores trailing spaces, so non-IANA spellings resolve. G66 runs "local; WSL; CI", so the row cannot be dropped. Sent to impl-manager-m9 with a suggested fix: require an exact `name in zoneinfo.available_timezones()`, or compare with `str(ZoneInfo(name))`. Waiting for r2, after which only this test is re-run on L and W.

#### DST history

- **r0** (APScheduler as is) against ruling (2) "skip the gap, the repeat once": 2 rows red. Spring: fired 03-29 01:30Z (shifted). Autumn: fired twice (00:30Z and 01:30Z). Reported to `main`, and the test was not adjusted.
- **User decision**: shift the gap and run the repeat once. The two rows were changed to it, as `main` instructed (spring: once at 01:30Z = 02:30 BST; autumn: once at 00:30Z, the first occurrence).
- **r1**: `next_fire()` drops a fire whose local time is the second occurrence (fold 1 with a different offset). All DST rows pass. The plant "dedupe dropped" fires twice and goes red (CHK-M9-386a).

#### Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | `pytest tests/test_cron.py tests/test_jobs_property.py::test_next_fire_strictly_increasing`, code r0 | 100/102 passed, 2 failed (the r0 DST rows), 0 errors, 0 skipped |
| r1 (W) | same, code r1, DST rows per the user decision, plus 5 new DST rows | **107/107 passed**, 0 failed, 0 errors, 0 skipped |
| r1-L (Windows, worktree venv, `CI=true`, `-n 0`) | the 8 M9 unit and property files | 675/676 passed, **1 failed** (`test_refused_zones['utc ']`), 0 errors, 0 skipped |
| plants (W, on r1) | 7 plants in `/root/bstest-m9-mut-<id>` (removed after each) | 7/7 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-067 | CODE | W, L | r1 | PASS | `0 3 * * 0`, `7`, `sun`, `SUN` in UTC → the Sundays 2026-11-01 … 11-29 at 03:00Z. In Asia/Kolkata → Saturdays 21:30Z (Sunday 03:00 IST). `0 3 * * 1` → Mondays | 2026-10-30 |
| CHK-M9-068 | CODE | W, L | r1 | PASS | Weekday sets over 21 days for 18 fields: `1-5`/`mon-fri`; `5-7` = Fri–Sun; `0-5` = Sun–Fri; `0-3` = Sun–Wed; `0,6`, `6,7`, `sat,sun`; `*/2` = Sun, Tue, Thu, Sat; `1-5/2` = Mon, Wed, Fri; `0-6`, `0-7`, `*` = all; `7` and `0` = Sun; `3`, `6`, `2,4` | 2026-10-30 |
| CHK-M9-069 | CODE | W, L | r1 | PASS | `*/15`; `jan`/`1`/`JAN` → 2027-01-01, 2028-01-01; the 31st only in 31-day months; `0 0 29 2 *` → 2028-02-29, 2032-02-29 (accepted: fires within 5 years); `0 9-17/4`; `30 6 1,15`; New York noon 16:00Z → 17:00Z after 2026-11-01 | 2026-10-30 |
| CHK-M9-070 | CODE | W, L | r1 | PASS | `0 9 * * *` Asia/Kolkata → 03:30Z daily; UTC, Etc/UTC → 09:00Z | 2026-10-30 |
| CHK-M9-071 | CODE | W, L | r1 | PASS | Europe/London: `30 2` spring 03-29 → once at 01:30Z, autumn 10-25 → once at 02:30Z. `30 1` spring → [03-28 01:30Z, **03-29 01:30Z** (shifted), 03-30 00:30Z]. `30 1` autumn → [**10-25 00:30Z** (once), 10-26 01:30Z, 10-27 01:30Z]. Asked from 00:30Z or 00:45Z on 10-25 → 10-26 01:30Z (the GMT repeat is not a fire). `*/15 1` → 00:00, 00:15, 00:30, 00:45Z then 10-26 01:00Z. `*/30 *` from 10-24 23:50Z → 00:00, 00:30, 02:00, 02:30Z. Spring `*/30 *`: distinct, strictly increasing, includes 01:00Z (02:00 BST). A UTC schedule is unchanged on those days | 2026-10-30 |
| CHK-M9-072 | CODE | W, L | r1 | PASS | 37 refusals, all with `field == "cron"` (six/four fields, empty, `@daily`, `@reboot`, both day fields ×3, never fires ×3, out of range ×8, `?`, `L`, `#`, `W`, `5L`, `last`, `*/0`, `5/10`, `5-1`, `sat-sun`, bad names, an Arabic-Indic digit, `1,,2`, `1-`). 64 characters accepted, 65 refused | 2026-10-30 |
| CHK-M9-073 | CODE | W: PASS; **L: FAIL** | r1, r1-L | **FAIL (L)** | W: all 11 bad zones refused with `field == "timezone"`, the 5 good ones accepted, messages fixed. L: `utc ` accepted (see "Failing test") | 2026-10-30 |
| CHK-M9-074 | CODE | W, L | r1 | PASS | At a fire time exactly → the next; −1 µs and −1 s → the fire; +1 µs → the next; aware UTC; independent of the `after` zone; `* * * * *` steps by one minute; a naive `after` → `ValueError` | 2026-10-30 |
| CHK-M9-085 | CODE | W, L | r1 | PASS | 400 random crons × 6 zones (incl. Lord_Howe 30-minute DST, Kathmandu +05:45) × instants 2026–2030: 10 successive fires strictly increasing, UTC | 2026-10-30 |
| CHK-M9-368 | CODE | W | plant on r1: weekday field passed raw | PASS (red) | 20 failed: the Sunday rows (`0` → Monday, `7` refused), Kolkata Sunday, `test_monday`, 14 `test_weekday_field` rows, one refused-cron row | 2026-10-30 |
| CHK-M9-369 | CODE | W | plant on r1: both day fields accepted | PASS (red) | 4 failed: `test_refused_crons` for the three both-day-field crons, `test_messages_are_fixed` | 2026-10-30 |
| CHK-M9-370 | CODE | W | plant on r1: `CronTrigger(timezone=UTC)` | PASS (red) | 10 failed: Kolkata ×4, New York, the London `30 2` and `30 1` rows, the `*/15` repeat row | 2026-10-30 |
| CHK-M9-386 | CODE | W | plant on r1: per-number weekday rename (the plan's wording) | PASS (red) | 9 failed: `test_weekday_field` for `0-5`, `0-3`, `*/2`, `1-5/2`, `0-6`, `0-7`, and 3 refused-cron rows. This confirms the impl's set expansion is needed | 2026-10-30 |
| CHK-M9-386a | CODE | W | plant on r1: the repeat dedupe dropped (`if not _repeated(...)` → `if True`) | PASS (red) | 4 failed: `test_london_0130_autumn_repeat_fires_once`, `…_repeat_seen_from_inside_the_repeated_hour`, `…_every_15_minutes_through_the_repeat`, `…_every_30_minutes_across_the_repeated_hour` (fires twice) | 2026-10-30 |
| CHK-M9-387 | CODE | W | plant on r1: `next_fire` may return the instant itself | PASS (red) | 47 failed, including `test_next_fire_is_strictly_after`, `test_every_minute_moves_forward` and the G67 property. The fire helpers now assert progress, so the plant fails fast (the r0 attempt hung in an unbounded helper loop: a test robustness gap, fixed) | 2026-10-30 |
| CHK-M9-383 | CODE | L | plant: `import re` | PASS (red) | ruff TID251 (see the TASK-186 report) | 2026-10-30 |

#### Acceptance (TASK-191 row: "REQ-223 (1)–(4) hold, the DST rows recording APScheduler 3.11's answer")

- (1) → CHK-M9-067, -068. (2) Kolkata → CHK-M9-070; DST → CHK-M9-071 (r1 meets the user decision; APScheduler's raw answer is recorded under "DST history"). (3) → CHK-M9-072 and CHK-M9-073 (**red on Windows**). (4) → CHK-M9-074, -085.

#### Recorded, not asserted

- Any run of blanks separates fields (crontab(5)).
- `5/10` (a step on one value) is refused; crontab(5) defines steps only on ranges and `*`.
- With "repeat once", a sub-hourly schedule has no run during the repeated GMT hour (for `*/30`, 01:00Z and 01:30Z are skipped). This follows from the decision; the README is TASK-208's to update (DST is not described there yet).

### TASK-192


Tester: tester-m9, 2026-10-30. Full rigor (idempotency store, high risk). REQ-222 (1)–(3); TS §6.3 L1135, §6.4 L1149, §2.1 L103; #123. Code under test: `bm/api/user/idempotency.py` (impl-manager-m9, `work/reports/TASK-192-impl.md`; sha256 `157f93abee143589…`). Its interface (`IdempotencyStore[T](clock).run(user_id, key, body, call)`, `check_key`, `body_digest`, `InvalidKey`, `KeyReused`) is new; no plan fixed one. Test file (new): `manager/tests/test_idempotency.py`. Plan rows: CHK-M9-075 to -079. A fake clock is used, and threads are ordered only by `Barrier` and `Event`, each wait bounded at 10 s; there are no sleeps.

#### Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_idempotency.py` | **34/34 passed**, 0 failed, 0 errors, 0 skipped |
| r1-L | same on Windows (part of the M9 unit set run) | 34/34 passed |
| plants | 4 plants in `/root/bstest-m9-mut-<id>` | 4/4 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-075 | CODE | W, L | r1 | PASS | Same user, key and body → the first answer, `call` run once. Another user with the same key → a new answer, which is then remembered for that user. Same key with another body → `KeyReused` with exactly "Idempotency-Key was used with a different request.", and the first answer is still remembered. Bodies are compared after parsing: key order is ignored, but list order matters, and `1`, `1.0` and `true` stay distinct. The digest is 32 bytes | 2026-10-30 |
| CHK-M9-076 | CODE | W, L | r1 | PASS | At first + 24 h − 1 s: remembered. At first + 24 h + 1 s: `call` runs again. Once expired, the key takes another body. `TTL` 24 h, `MAX_ENTRIES` 100,000, `KEY_MAX` 255. **Recorded:** exactly 24 h is still remembered (`>` TTL expires) | 2026-10-30 |
| CHK-M9-077 | CODE | W, L | r1 | PASS | A first refusal (raised from `call`) is not remembered; the same key and body then run `call`. Three raising calls in a row leave the per-key lock free (a second thread completes within the bound). A refused body does not block another body on the same key | 2026-10-30 |
| CHK-M9-078 | CODE | W, L | r1 | PASS | REQ-222 (2): two threads at a barrier, the same user, key and body, `call` held on an event → `call` runs once and both threads get the same answer object. The lock is per key: while user 1's key A is held, user 1's key B and user 2's key A both complete. A repeat with another body that waits behind the first gets `KeyReused` once the first commits | 2026-10-30 |
| CHK-M9-079 | CODE | W, L | r1 | PASS | Accepted keys: `a`, 255 × `x`, `abc-123_~!`, `~`, `!`. Refused (`InvalidKey`, before `call` runs): `""`, 256 characters, NUL, U+001F, U+007F, LF, TAB, CR, `é`, an emoji. The message is fixed. Capacity: 100,000 entries are kept; the 100,001st drops the oldest stored (k0), while k1 and k99,999 are still remembered (a hit stores nothing); with `max_entries=3` the 4th drops the 1st. **Recorded:** a space inside a key, and a key that is a single space, are accepted (0x20 is printable ASCII) | 2026-10-30 |
| CHK-M9-367 | CODE | W | plants: (a) the body digest not compared; (b) the per-key lock replaced by a fresh lock per call | PASS (red) | (a) 3 failed: `test_same_key_other_body_is_a_conflict`, `test_bodies_are_compared_after_parsing`, `test_a_waiting_repeat_with_another_body_gets_the_conflict`. (b) 2 failed: `test_two_concurrent_identical_requests_run_once` (`call` runs twice), `test_a_waiting_repeat_with_another_body_gets_the_conflict` | 2026-10-30 |
| CHK-M9-388 | CODE | W | plant: entries never expire | PASS (red) | 2 failed: `test_kept_for_24_hours_then_forgotten`, `test_expired_key_can_take_another_body` | 2026-10-30 |
| CHK-M9-389 | CODE | W | plant: a refused first request is remembered and replayed | PASS (red) | 3 failed: `test_a_refused_first_request_is_not_remembered`, `test_a_failing_call_releases_the_key_lock`, `test_a_refused_body_does_not_block_another_body` | 2026-10-30 |

#### Acceptance (TASK-192 row: "Unit with a fake clock and two threads: REQ-222 (1)–(3) hold")

- (1) → CHK-M9-075 to -077. (2) → CHK-M9-078. (3) → CHK-M9-079 (and through the API: CHK-M9-245, tester-m9b).

#### Notes for TASK-205 (tester-m9b) and the reviewer

- **`body_digest` raises `ValueError` on a NaN body** (`allow_nan=False`; recorded by `test_body_digest_nan_is_recorded`). Python's `json.loads` accepts `NaN`. If the route calls `store.run()` before its strict body model has refused the body, `{"policy_id": 1, "target": {"agents": [NaN]}}` with an `Idempotency-Key` could answer 500 instead of 400. Please check the order in `api/user/scans.py`.
- The store remembers whatever `call()` returns. Only a 202 should be remembered, so the route must raise for every refusal and return only after its transaction commits (as the impl report says).
- `check_key` accepts spaces. A header value with leading or trailing spaces is trimmed by HTTP parsers, so a key of only spaces may arrive as `""` and be refused.

### TASK-193


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-208 (3), REQ-211, REQ-230; TS §4.4 L555, L558–L560, L566, §4.1 L530, §4.3 L550, §6.5 L1165–L1182, §5.2 L1011–L1012; #122 (c), #125 (a)–(f). Code under test: `bm/repositories/scan_queue.py` (impl-manager-m9b, `work/reports/TASK-193-impl.md`). Test files: `manager/tests/test_scan_queue_repo_pg.py` (new); the TP-M9-01 builder `manager/tests/scan_pg_fixtures.py` and its self-test `manager/tests/test_m9_fixtures_pg.py`. Plan rows: CHK-M9-100 to -104, -110 to -113, -123.

#### Runs

| Run | Command (W: `/root/bstest-m9b-base`, venv `/root/venv-m9b`, `PYTHONPATH` pinned, `CI=true`, PG16 by Testcontainers, `-n 0`, a database of the module's own) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_m9_fixtures_pg.py tests/test_scan_queue_repo_pg.py` (W1 batch) | **15/15 passed** (5 + 10), 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 9 (8 pytest, 1 ruff), throwaway copies | 9/9 red |
| static (L) | whole-tree `ruff check manager`, `ruff format --check manager`; `mypy --strict` on the test files | clean |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-100 to -104 | PASS | Builder self-test 5/5. Catalog through M7's real upload/delete: document order → `sort_order`, `v_plugin` name `CIS Ubuntu 24.04 - 1.3.1.1 - Ensure AppArmor is installed`, version bumps on re-import, disabled upload, soft delete. The six statuses exactly as the `agent_status` enum, with tags and real `bsa_` tokens (hash stored only). Owner-written jobs validate as `ComplianceJob`, `eval_spec` parses (#117), the trigger accepts the job's `created_at` and refuses +1 s, jobs in two months land in two partitions (none in default), the `scan_job` CHECK refuses a compliance job without a scan. The clock moves only when told; the canary is unique; a checksum changes on a one-byte change. The simulated agent pulls through the real route with its token (another agent's path → 403); fixture mapping keeps every other field |
| CHK-M9-110 | PASS | With every earlier agent decommissioned: `all` = exactly the enrolled, online, stale and offline agents (+ the other eligible ones), sorted, in **one** statement; `tags [a, b]` = eligible holders of a **or** b, an agent holding both once; `tags [c]` → the stale holder; an unused tag → `[]`; `agents [offline x, unknown, decommissioned, awaiting]` → `[x]`; input order does not matter (sorted); an unknown kind → `ValueError` |
| CHK-M9-111 | PASS | After the `FOR SHARE`, version, status, deleted flag and the active plugins come from **one** statement (spy: exactly 2 statements, the first `FOR SHARE`). A re-import that reverses document order reverses the snapshot (SR §2.3). A listed plugin made `retired` is left out. Display name, execute, `timeout_s`, operator and expected are each correct. Disabled, deleted (M7 delete), unknown (None) and "no active plugin" (`[]`) are reported. A second session's `UPDATE policy` waits on the share lock until commit (pg_locks probe). The advisory queue lock makes a second scan of the same policy wait; another policy does not |
| CHK-M9-112 | PASS | 3 jobs in **one** INSERT. Each SQL-composed payload equals the test's own TS §6.5 body (six keys, `job_id` = row id, lowercase ids, `pickup_by` text, plugins in order, patterns) and the pure builder's `payload()` for the same ids; it validates as `ComplianceJob`. `eval_spec` is stored as given; every job has the scan's `created_at` (with µs); state `queued`. The scan row has version, trigger, `requested_by`, target and `queued`. 10,000 jobs are still one INSERT, each payload `job_id` = its row id. Mismatched or empty id lists → `ValueError`, nothing written |
| CHK-M9-113 | PASS | `cancel_older_queued(policy P, [a1, a3], new scan)` cancels exactly scan 1's queued job for a1 and an older scan's queued **retry** for a1 (`finished_at` = now). Byte-identical: the original of that retry, a2's queued job (not listed), a3's dispatched job, another policy's queued job, both agents' queued inventory jobs, the new scan's own jobs, every `scan` row. A repeat → `[]` |
| CHK-M9-272 (part) | PASS | as `bitscan_app`, UPDATE of `scan_job.agent_id/scan_id/payload/eval_spec/retry_of` and of `scan.policy_id/policy_version/target` → `InsufficientPrivilege` |
| CHK-M9-352 | PASS (red) | plant: `v.state = 'active'` dropped → 2 failed |
| CHK-M9-353 | PASS (red) | plant: `FOR SHARE` dropped → 2 failed (the lock probe; the queue race rows) |
| CHK-M9-354 / -355 / -356 | PASS (red) | plants: status filter dropped / offline excluded / tags all-of → 1 failed each (resolution row) |
| CHK-M9-358 | PASS (red) | plants: dispatched jobs included / policy filter dropped → 1 failed each |
| CHK-M9-381 | PASS (red) | plant (rewritten, see note): join `OR j.scan_id IS NULL`, kind filter dropped, `IS DISTINCT FROM` the new scan → 2 failed (repo row and the TASK-198 queue row: inventory jobs cancelled) |
| CHK-M9-376 / -123 | PASS (red) | f-string query in `scan_queue.py` → ruff `S608` |

#### Acceptance (TASK-193 row)

REQ-208 (3) → CHK-M9-110. The snapshot is one statement, and a concurrent policy delete waits for the scan's commit → CHK-M9-111 (the full delete race is TASK-198's, CHK-M9-150). N jobs in one INSERT → CHK-M9-112. The older-queued cancel touches only queued compliance jobs of that policy for the listed agents → CHK-M9-113. G1 red on a planted f-string → CHK-M9-376.

#### Notes (no defect)

- CHK-M9-381 plant: the impl report's suggested plant (`OR j.scan_id IS NULL` without the kind filter) stays green, because `j.scan_id <> new` is NULL for an inventory job. The query has three independent guards against inventory jobs. The plant that turns red removes all three.

### TASK-194


Tester: tester-m9b, 2026-10-30. Full rigor (high risk). REQ-219, REQ-220, REQ-230; TS §4.4 L573, L579–L581, §5.2 L1012; #127 (d)–(f). Code under test: `bm/repositories/scan_progress.py` (impl-manager-m9b, `work/reports/TASK-194-impl.md`). Test files: `manager/tests/test_scan_progress_repo_pg.py` (new), on the TP-M9-01 builder `manager/tests/scan_pg_fixtures.py` (self-test `test_m9_fixtures_pg.py`, 5/5). Plan rows: CHK-M9-114 to -116.

#### Runs

| Run | Command (W: `/root/bstest-m9b-base`, venv `/root/venv-m9b`, `PYTHONPATH` pinned, `CI=true`, PostgreSQL 16 by Testcontainers, `-n 0`, a database of the module's own) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_progress_repo_pg.py` (in the W1 batch) | **6/6 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 4 (3 pytest, 1 ruff), each in a throwaway copy `/root/bstest-m9b-mut-<id>` | 4/4 red |
| static (L) | `ruff check manager`, `ruff format --check manager`, `mypy --strict` on the test files | clean |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-114 | PASS | `unit_facts` over 3 scans is **one** statement (spy); the 6 units of scan A match the hand-written `Unit`s: a completed original; a partial original whose retry stored the 2 missing plugins (one complete, closed unit); a failed original with a queued retry (open, not all-queued); cancelled; expired; a partial + failed retry with p3 missing (has results, not complete). Scan B (two queued jobs) is all-queued; scan C (running, 1 result) is open with results. Unknown id absent, `[]` → `{}`. A result only in the retry makes the unit `has_results` |
| CHK-M9-115 | PASS | Candidates include a 30-day-old scan with `finished_at` NULL, finished `partial`/`failed`/`cancelled` scans created within 8 days, and a queued scan; they exclude a `completed` scan and a finished `partial` scan created 9 days ago |
| CHK-M9-116 | PASS | `cancel_open_jobs` of a scan with one job per state plus a queued retry cancels exactly queued, dispatched, running and the retry (sorted ids, `finished_at` = now); the 5 other jobs, another scan's queued job, the inventory job and every `scan` row are byte-identical; a repeat returns `[]`. `set_scan_state`: unchanged state → False (no write); `finished_at` is set once and kept through later state changes (`None` never clears it); `dispatched`, `expired`, `bogus` → `ValueError`; the other `scan` columns never change. `scan_row(lock=True)` makes a second session's `set_scan_state` wait (lock probe) until commit |
| CHK-M9-359 | PASS (red) | plant `state IN ('queued')` → 1 failed (cancel row) |
| CHK-M9-363 | PASS (red) | plant: candidates `finished_at IS NULL` only → 1 failed (refresh row) |
| CHK-M9-361 (repo) | PASS (red) | plant: group by `job_id` instead of the root → 2 failed (unit rows) |
| CHK-M9-376 | PASS (red) | f-string query added → ruff `S608`, exit 1 |

#### Acceptance (TASK-194 row)

Unit facts match owner-written fixtures (originals with retries, results, every state) → CHK-M9-114. Candidates exclude `completed` scans and finished scans older than 8 days → CHK-M9-115. Cancel moves only queued, dispatched and running jobs of that scan; only `state` and `finished_at` of `scan` are updated → CHK-M9-116 (and CHK-M9-272: the app cannot update `scan.policy_id`, `policy_version` or `target`; `test_scan_queue_repo_pg.py::test_repository_runs_with_app_grants_only`).

#### Notes (no defect)

- The 8-day boundary itself (`created_at > now − 8 days`, strict) is recorded, not asserted: #127 (f) says "created in the last 8 days" without naming the boundary instant.
- Probe fix in my builder: `pg_stat_activity` hides other roles' wait events from a non-superuser, so the lock probe reads `pg_locks` (`granted = false`), which every role can read.

### TASK-195


Tester: tester-m9b, 2026-10-30. Full rigor; TS §8.2 second approval task (PD-39). REQ-215, REQ-216, REQ-217, REQ-230; TS §4.4 L568–L570, L575, L577, L578, L582, §4.5 L587, §5.2 L892–L913, L1011; #124 (c), #127 (a), (f). Code under test: `bm/repositories/job_intake.py` (impl-manager-m9b, `work/reports/TASK-195-impl.md`, incl. r1). Test file: `manager/tests/test_job_intake_repo_pg.py` (new). Plan rows: CHK-M9-117 to -119.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 (round 1) | `pytest tests/test_job_intake_repo_pg.py` | **18/20 passed, 2 failed**, 0 errors, 0 skipped |
| r1 service | `pytest tests/test_intake_pg.py` (TASK-199, same defect end to end) | 26/27 passed, 1 failed |
| re-run after r1 | the 3 failing node ids (below) | **3/3 passed** |
| r2 (r1 tree) | `pytest tests/test_job_intake_repo_pg.py` in the W1 batch | **20/20 passed**, 0 skipped; 0 containers left |
| plants | 7 (6 pytest, 1 ruff) in throwaway copies | 7/7 red |

#### Round 1 failure (fixed in r1)

- `test_sibling_is_the_other_job_of_the_unit[completed-running-orig-retry]` and `[completed-completed-orig-retry]`: expected `(retry_id, retry_created_at)`, got `None`.
- End to end: `test_intake_pg.py::test_a_completed_original_still_sees_its_retrys_results`. The original failed and got a retry; the retry stored p2; a late batch to the original stored p1, so the original became `completed`. p2 posted again to the original was then **stored a second time** (`count == 2` in the unit). It should have been a duplicate.
- Diagnosis: `sibling()` searched `retry_of` only for `failed`/`partial` originals. But a late batch can move such an original to `completed` while its retry exists (TS §4.4 L577, L582), so TS §4.4 L578 ("skipping plugins that already have a result in the original job or its retry") broke. r1 searches for every original in `failed`, `partial` or `completed` (decisions "First result wins includes completed originals").

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-117 | PASS | `lock_unit(retry)` returns the posted job with payload, `eval_spec`, ids, state and times; unknown → None. For each of (orig, retry), (retry, orig), (retry, retry), (orig, orig), a second session locking a job of the same unit **waits** (pg_locks probe) until the first ends; a job of another unit does not wait |
| CHK-M9-118 | PASS | 3 rows in **one** INSERT (statement spy); stored exactly as given (verdict fields, streams, flags, the four snapshots, item times), `job_created_at` = the job's, `received_at` = the argument, `result` generated (PASS/FAIL/ERROR); `[]` → 0 with no SQL. An `IntakeJob` with `created_at` shifted by 1 µs is refused by the TS §5.2 trigger and stores nothing. `result_uuids` covers exactly the given (job, created_at) pairs |
| CHK-M9-119 | PASS | `start`: dispatched → running with `started_at`/`deadline_at`; a second call → False, unchanged; a failed (never-started) job is not started. `set_state`: running → completed, failed → partial, partial → completed (with `finished_at`); completed/expired/cancelled → False and unchanged; `failed`, `queued`, `cancelled`, `expired`, `dispatched` → `ValueError`; only progress columns change. `sibling`: 10 rows, incl. the two completed-original rows above (r1) |
| CHK-M9-320 | PASS (red) | plant: no `FOR UPDATE` on the job and the root → 5 failed (4 serialise rows + the 200-round race) |
| CHK-M9-321 | PASS (red) | plant: the root lock skipped for a retry → 3 failed (the serialise rows that post to the retry; the race) |
| CHK-M9-322 (repo) | PASS (red) | plant: `sibling` always None → 10 failed (sibling rows + intake first-result rows) |
| extra 322-fp | PASS (red) | plant: lookup restricted back to failed/partial (lead's ask) → 3 failed (2 sibling rows + the end-to-end row) |
| CHK-M9-334 (repo) | PASS (red) | plant: `start` guards dropped → 1 failed (start row) |
| CHK-M9-376 | PASS (red) | f-string query → ruff `S608` |

#### Acceptance (TASK-195 row)

A second session locking the same root waits → CHK-M9-117. N rows insert in one statement with `job_created_at` accepted by the trigger → CHK-M9-118. `started_at` and `deadline_at` are written only while NULL → CHK-M9-119. G1 red on a planted f-string → CHK-M9-376. The race suite (TASK-199) finishes with no deadlock.

#### Notes

- The r1 docstring now states the right reason (a completed original can have a retry).

### TASK-196


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-218, REQ-230; TS §4.4 L575, L577, §3.3 L218, §5.2 L1011; #126, #127 (b), #124 (c). Code under test: `bm/repositories/job_sweep.py` (impl-manager-m9b, `work/reports/TASK-196-impl.md`). Test file: `manager/tests/test_job_sweep_repo_pg.py` (new). Plan rows: CHK-M9-120, -121.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_job_sweep_repo_pg.py` (W1 batch) | **9/9 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 5 (4 pytest, 1 ruff) | 5/5 red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-120 | PASS | Deadline candidates: `deadline_at = now` is not, `now − 1 µs` is; a dispatched job past its deadline is; `now + 1 µs`, completed/partial/failed jobs and an inventory job are not. Never-started: `dispatched_at = now − 24 h` is not, `− 24 h − 1 s` is; a job created 5 days ago but dispatched 1 h ago is not (from `dispatched_at`); a started, a running and an inventory job are not |
| CHK-M9-121 | PASS | `lock_for_sweep(retry)` reads job, root, `retry_of`, scan, agent, payload, `eval_spec`, state, times, and the flags (policy deleted through M7's delete; agent decommissioned); unknown → None; `unit_result_uuids` of a retry covers the retry and its original. With the root or the job held by another session (`FOR UPDATE`), it returns None **at once** (the session has `lock_timeout = 2s`, so a wait would raise), and the lock after release succeeds. `end_job`: first call True (state and `finished_at` only), second False and unchanged; queued/ended/inventory jobs untouched; a non-ending state → `ValueError`; two sessions racing `end_job` give `[True, False]` (the second waits, then re-checks). `insert_retry` writes the given payload/`eval_spec` (job_id = row id), the original's scan and agent, `retry_of`, `queued`, the given times; the original's row is unchanged; a retry of a retry and a payload whose `job_id` differs from the row → `ValueError` before SQL. `UPDATE scan_job SET payload` as `bitscan_app` → `InsufficientPrivilege` |
| CHK-M9-339 | PASS (red) | plant `deadline_at <= %s` → 1 failed |
| CHK-M9-340 | PASS (red) | plant `created_at < %s` → 1 failed |
| CHK-M9-346 | PASS (red) | plant: `end_job` state guard dropped → 2 failed (end-once rows) |
| CHK-M9-377 | PASS (red) | plant: `UPDATE scan_job SET payload` in `end_job` → 2 failed, the grant refusal surfaces (`InsufficientPrivilege`) |
| CHK-M9-376 | PASS (red) | f-string query → ruff `S608` |

#### Acceptance (TASK-196 row)

Candidates follow the strict boundaries → CHK-M9-120. A root held by another session is skipped; the retry row has the given payload, `eval_spec` and `retry_of`; only progress columns of the original change → CHK-M9-121.

#### Notes (no defect)

- `unit_result_uuids` reads the sibling only for a retry. For a sweep candidate that is an original, no retry can exist yet, because a retry is made only when its original leaves dispatched/running. Unlike TASK-195's completed-original case, this holds for the sweep: its candidates are always dispatched or running.

### TASK-197


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-224, REQ-225, REQ-230; TS §5.2 L846–L857, L864, L1013, §4.4 L557; #122 (h), #128 (d), (e); decisions "M9 builder rulings" (FOR SHARE on schedule create/enable; the tick never waits for a policy). Code under test: `bm/repositories/schedules.py` (impl-manager-m9b, `work/reports/TASK-197-impl.md` and its r1 note). Test file: `manager/tests/test_schedules_repo_pg.py` (new). Plan row: CHK-M9-122.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_schedules_repo_pg.py` (W1 batch, r1 tree) | **9/9 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| plants | 4 (3 pytest, 1 ruff) | 4/4 red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-122 | PASS | CRUD round trip: insert returns the full row (name stored as given, incl. spaces and `é`); `update` changes name, target, cron, timezone, enabled, `next_run_at` and never `policy_id`/`created_by`. `policy_id`, `created_by`, `last_run_at`, `{}` and a mixed change → `ValueError`, with the row unchanged. Unknown id → None; delete True once, then False. Page by `schedule_id` after a cursor, in order. DELETE leaves the schedule's scans with `schedule_id` NULL (TS §5.2 L864). `due`: enabled and `next_run_at ≤ now` (exactly now is due, +1 µs not, NULL never, disabled never), oldest first, `limit` honoured; a second session gets `[]` for the rows the first holds, then both after release. `previous_unfinished`: the latest scan by `created_at` decides (no scan → False). `mark_run` keeps `last_run_at` on a skip. `get(lock=True)` holds the row (`LockNotAvailable` for a second session with a 300 ms lock timeout) |
| r1 FOR SHARE | PASS | `policy_state(lock=True)` makes a policy `UPDATE` (what M7's delete does first) in a second session wait (pg_locks probe) until the schedule transaction commits |
| r1 SKIP LOCKED | PASS | `try_share_policy` returns False **at once** while another session holds the policy row (an `UPDATE`), and True once released; another session's plain `FOR SHARE` does not block it |
| CHK-M9-373 | PASS (red) | plant: `due` without `SKIP LOCKED` → 1 failed (the second session waits and hits its 2 s lock timeout) |
| 197r1-share | PASS (red) | plant: `policy_state(lock=True)` without `FOR SHARE` → 1 failed |
| 197r1-skip | PASS (red) | plant: `try_share_policy` without `SKIP LOCKED` → 1 failed |
| CHK-M9-376 | PASS (red) | f-string query → ruff `S608` |

#### Acceptance (TASK-197 row)

CRUD round trip; due selection skips rows another session holds; DELETE leaves that schedule's scans with `schedule_id` NULL → CHK-M9-122. The r1 rows back TASK-201 r1 and TASK-203 r1 (their races are in those reports).

#### Notes (no defect)

- `try_share_policy` on an unknown policy returns False. That can't happen: the FK holds, and policies are only soft-deleted.

### TASK-198


Tester: tester-m9b, 2026-10-30. Full rigor; lead's second look (PD-39). REQ-209, REQ-211, REQ-212, REQ-227, REQ-229 (2); TS §2.3 L133, §3.3 L213, §3.5 L248, §4.4 L555, L558–L560, L566, §4.1 L530, §4.3 L547, L550, §6.5 L1165–L1182, §8.4 L1290; #3, #18, #122 (c)–(f), #125 (a)–(h), #129 (a), (b); SR §1.1. Code under test: `bm/services/jobs/queue.py`, `bm/services/audit/alerts.py` (`M9_ALERT_KINDS`) (impl-manager-m9, `work/reports/TASK-198-impl.md`), on TASK-188/189 (tester-m9) and TASK-193. Test files: `manager/tests/test_queue_scan_pg.py`, `manager/tests/test_queue_scan_race_pg.py` (new); `manager/tests/test_alerts.py` (the alert-kind oracle gains the TS §8.4 L1290 kind: old CHK-M7 "34 kinds" → **CHK-M9-232** "35 kinds", every other assertion unchanged). Plan rows: CHK-M9-150 to -161.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own databases) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_queue_scan_pg.py tests/test_queue_scan_race_pg.py` (8-file batch) | **8/8** and **5/5 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| r1 | `pytest tests/test_alerts.py` (with the M3 batch) | passed (inside 346/347; the one failure there was a metrics oracle, TASK-204) |
| plants | 8 service plants + 353/381 repo plants run on these files | all red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-150 | PASS | The scan parks after its snapshot (gate). M7's delete, started then, **waits** (pg_locks probe); after the scan commits, the delete cancels all 3 of the scan's queued jobs. A delete committed first → `PolicyDeleted`, counts unchanged. 20 unforced rounds at a barrier: the scan either refused (`PolicyDeleted`) or its jobs were cancelled; never a queued job of a deleted policy |
| CHK-M9-151 | PASS | An import (Execute and ExpectedResult changed, version +1) started while the scan is parked waits. The scan's recorded version, its job's command and its `eval_spec` expected are all the old version's. A scan after the import has the new ones |
| CHK-M9-152 | PASS | 20 rounds of two concurrent scans of one policy and agent: both succeed, `["cancelled", "queued"]` |
| CHK-M9-153 | PASS | version 3 (two re-imports); tag target over decommissioned, awaiting, offline, online → `("queued", 3, 2)`; scan row: version, `manual`, no schedule, `requested_by` 11, target `{tags, resolved_agents}` sorted, `queued`, `created_at` = now (µs); jobs for the offline and online agents with the scan's `created_at`; counts +1 scan, +2 jobs, +1 audit |
| CHK-M9-154 | PASS | `PolicyDisabled`, `PolicyDeleted`, `PolicyNotFound`, `NoTargetAgents` (decommissioned-only list; an unused tag), `PolicyHasNoPlugins` (its only plugin retired): scan, job, result and audit counts unchanged |
| CHK-M9-155 | PASS | scan 2 for {a, b} cancels scan 1's queued job for a and an older scan's queued retry for b (`finished_at` = now); byte-identical: scan 1's dispatched job (c) and its job for d, another policy's queued job for a, the original of b's retry, both inventory jobs; `cancelled_older: 2` in the entry; scan 2's two jobs queued |
| CHK-M9-156 | PASS | queued before an import → the old Execute; after → the new one and version +1; disabling the policy afterwards leaves both queued (#18) |
| CHK-M9-157 | PASS | the six keys; `ComplianceJob`; equals the test's TS §6.5 body (agent id given upper case, stored lowercase; `pickup_by` `YYYY-MM-DDTHH:MM:SSZ` without the µs; patterns = the setting at queue time, in order; plugins in sort order with `timeout_s` 600 kept); no `operator`/`expected`/`expected_result`/`eval_spec`/`name` at any depth; `eval_spec` parses, matches the payload in order, SR §1.1 name/operator/expected |
| CHK-M9-158 | PASS | a snapshot with U+0000 in execute, a lone surrogate in the name, U+0000 in expected → `build.UnstorableText` (fixed message, no input), counts unchanged |
| CHK-M9-159 / -160 | PASS | M8 `host_counts` on an M9 scan of 4 plugins and 3 agents → `(0, 0, 0, 4)` each; every `execute` of every job = an active plugin's execute of that policy |
| CHK-M9-161 | PASS | all + API token → the `scan.create` entry is the alert (`alert` true, `alert_kind` `all_hosts_scan_api_token`), `bitscan_alerts_total{kind}` +1; session, tags + token and a scheduled all-hosts scan by `system` → no alert, exactly the 7 #129 (a) detail keys; a queue rolled back by its caller leaves no entry and no count |
| CHK-M9-351 | PASS (red) | patterns `()` → the payload row |
| CHK-M9-352 | PASS (red) | disabled not refused → the refusal row (and repo plant: retired included) |
| CHK-M9-353 | PASS (red) | (repo) no `FOR SHARE` → the delete race row |
| CHK-M9-357 | PASS (red) | zero agents not refused → the refusal row |
| CHK-M9-366 | PASS (red) | alert for a session (`kind == all`) / for tags with a token (`via_api_token` only) → the alert row, each |
| CHK-M9-381 | PASS (red) | (repo plant, all three guards) → this file's newer-scan row too |

#### Acceptance (TASK-198 row)

REQ-211 (1)–(6) → CHK-M9-150 to -156; REQ-209 (5) → -159; REQ-212 (2) → -160; REQ-227 (1), (2) → -161 (the sink half through the route: TASK-205, CHK-M9-242).

### TASK-199


Tester: tester-m9b, 2026-10-30. Full rigor; TS §8.2 second approval task (PD-39). REQ-214 to REQ-217, REQ-226, REQ-227; TS §6.1 L1071, §4.4 L568–L570, L575, L577, L578, L581, L582, §4.5 L587, L596, L599, L603, §3.3 L222, §8.4 L1288, §8.3 Security (first result wins under concurrent retries); #12, #116 (d), #121, #124, #127 (a)–(c), #129 (c); SR §1.1. Code under test: `bm/services/jobs/intake.py`, `bm/services/audit/metrics.py` (impl-manager-m9b, `work/reports/TASK-199-impl.md`), on `intake_plan.py`, `states.py` (TASK-186/190, tester-m9) and `job_intake.py` (TASK-195 r1). Test files: `manager/tests/test_intake_pg.py`, `manager/tests/test_first_result_wins_race_pg.py` (new). Plan rows: CHK-M9-163 to -175.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own databases) | Count |
| --- | --- | --- |
| r1 (round 1) | `pytest tests/test_intake_pg.py` | 26/27 passed, **1 failed** (`test_a_completed_original_still_sees_its_retrys_results`: p2 stored twice in the unit). Cause: TASK-195 `sibling()`; see `TASK-195-test.md` |
| re-run after TASK-195 r1 | that node id | **1/1 passed** |
| r2 | `pytest tests/test_intake_pg.py tests/test_first_result_wins_race_pg.py` (with the 8-file batch; +1 commit-failure test) | **28/28** and **1/1** passed (200 race rounds), 0 errors, 0 skipped; 0 containers left |
| plants | 17 (service and plan side, plus 320/321/322 run on the race and intake files) | 17/17 red (two variants dropped, see notes) |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-163 | PASS | 12 refusals → `Refused("job_not_acceptable", own)`, no row, job byte-identical: another agent; queued; expired; cancelled while dispatched and while running (`own_cancelled` True only for the agent's own job, False for another agent posting to it); 7 d + 1 s and 7 d + 1 µs; 49 + 1 foreign uuid (the 49 not stored); a plugin of the policy that is not in the job; an unknown job; an inventory job. An unreadable `eval_spec` → `Refused("eval_spec_invalid", False)` |
| CHK-M9-164 | PASS | dispatched, running, failed, partial, completed → `Accepted(1, 1)` (accepted + duplicates = items); `dispatched_at + 7 d` exactly accepted; a job created 10 days ago but dispatched 6 days ago accepted (window from dispatch) |
| CHK-M9-165 | PASS | a fault in `set_state` or `start` after the INSERT: the exception propagates; no row, the job unchanged, no counter move. A transaction that fails after the body (as a failed COMMIT): no row, no counter move |
| CHK-M9-166 | PASS | **one** INSERT per batch (spy); each row's verdict = `result_verdict(entry, item)` and the hand verdict (PASS for `yes\r\n` vs `yes` with exit 3; FAIL; ERROR truncated); `plugin_name_snap`/`operator_snap`/`expected_snap` from the job's `eval_spec` and `execute_snap` from its payload, both deliberately different from the catalog; `job_created_at` = the job's; `received_at` = the manager's now, not the item's `finished_at`; exit code, flags and item times as sent |
| CHK-M9-167 | PASS | stdout 65,536 UTF-8 bytes (32,768 × é) stored as sent; 65,537 → ERROR `oversize` with stdout and stderr `''`; stderr 16,384 kept, 16,385 → `oversize`. The `error_cases` fixture → ERROR, details "timed out", `spool_overflow`, `runner_unavailable`. The NUL fixture → stdout `a�b`, stderr `�`, PASS against expected `a�b` (the stored text is evaluated); a lone surrogate from `json.loads` → `x�y`, PASS. SR §1.1: `install ok installed`/exit 0 → PASS, `""`/exit 1 → FAIL, SR name and snapshots |
| CHK-M9-168 | PASS | queued with expected `before`; an import changes Execute and ExpectedResult (the catalog row shows the new values); `before` posted → PASS, snapshots `before` and the queued Execute |
| CHK-M9-169 | PASS | same plugin twice to one job → `{1, 0}` then `{0, 1}`, first row unchanged; two items in one batch → first stored; original then retry and the reverse → stored once, from the first post; **a completed original still sees its retry's results** (round-1 bug) |
| CHK-M9-170 | PASS | 200 rounds, barrier, two pooled sessions posting one plugin to the original and to its retry: every round exactly one row, answers `{1,0}` and `{0,1}`, M8 `host_counts` (1 PASS, 1 not run), no deadlock or error |
| CHK-M9-171 | PASS | posting to a retry: both `FOR UPDATE` statements (root, then job) precede the INSERT (spy) |
| CHK-M9-172 | PASS | canary in stdout, stderr, execute and expected through accepted, duplicate, oversize, refused and unreadable-spec batches: in no log record (DEBUG) and no audit `detail`; the `eval_spec` refusal is logged by exception type only |
| CHK-M9-173 | PASS | empty batch on dispatched → running, `started_at` = now, `deadline_at` = now + 648 s (Σ 95 s, `max_parallel_plugins` 2 set for that call); a second notice with the setting at 8 changes nothing; a first non-empty batch also starts (12 + 600 s with 8). Non-final with plugins missing → running; final → partial (`finished_at`); all → completed |
| CHK-M9-174 | PASS | failed + non-final 1 of 3 → partial (`finished_at` t1); the other 2 → completed (`finished_at` moves to t2); empty batch on failed → unchanged; completed takes only duplicates; expired and cancelled refused and unchanged |
| CHK-M9-175 | PASS | the family exports exactly `result` ∈ {PASS, FAIL, ERROR}; 2 PASS + 1 FAIL + 3 ERROR add exactly those; a duplicate batch and a refused batch add nothing |
| CHK-M9-320 / -321 | PASS (red) | root lock removed / posted job locked instead → the race goes red (double rows, M8 double count) together with the repo rows |
| CHK-M9-322 | PASS (red) | sibling always None → 10 failed incl. the original↔retry rows |
| CHK-M9-324 | PASS (red) | members of a mixed batch stored → 2 failed |
| CHK-M9-325 | PASS (red) | `cancelled` accepted → 3 failed (intake refusals, cancel rows) |
| CHK-M9-327 | PASS (red) | window from `created_at` → 1 failed |
| CHK-M9-328 | PASS (red) | the kind ignored → 2 failed (inventory job: wrong reason) |
| CHK-M9-329 | PASS (red) | verdict from the current catalog → 2 failed (catalog-change and snapshot rows) |
| CHK-M9-330 / -331 / -332 / -333 | PASS (red) | streams kept on oversize / NUL replaced after evaluation / execute from the catalog / `received_at` from `finished_at` → 1, 1, 2, 1 failed |
| CHK-M9-374 | PASS (red) | counter before commit → the commit-failure row; duplicates counted → the counter row |
| CHK-M9-375 | PASS (red) | stdout logged at DEBUG → the canary row |

#### Acceptance (TASK-199 row)

REQ-214 (1)–(3), (5) (flood: TASK-204), (6); REQ-215 (1)–(6); REQ-216 (1)–(5); REQ-217 (1)–(6); REQ-226 (1)–(3) → the rows above.

#### Notes

- Two plant variants were dropped as not defects. 334s (relax `start`'s guard; the service still calls it only for a dispatched job, so behaviour is unchanged) is covered at the repository level, `TASK-195` 334r red. 374a (the counter before commit, with my first fault test) stayed green because the faults ran before the counting. The commit-failure test added for it is red as expected.

### TASK-200


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-219, REQ-220, REQ-227; TS §4.4 L573, L579–L581, §6.2 L1122; #122 (g), #127 (d), (e), #129 (a); decisions "M9 builder rulings" (one `scan.cancel` entry per call, including `cancelled_jobs: 0`). Code under test: `bm/services/jobs/cancel.py` (impl-manager-m9, `work/reports/TASK-200-impl.md`). Test file: `manager/tests/test_cancel_pg.py` (new). Plan rows: CHK-M9-182 to -185.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_cancel_pg.py` | 6/7 passed, 1 failed: **test bug** (the race used a 1-plugin policy, so a stored result completed the job before the cancel) |
| re-run | the file after the fix (2-plugin policy) | **7/7 passed**, 0 skipped; 0 containers left |
| plants | 4 | 4/4 red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-182 | PASS | one job per state plus a queued retry: queued, dispatched, running and the retry → `cancelled`, `finished_at` = now; answer `cancelled_jobs: 4`; the 5 ended jobs, another scan's queued job and 3 inventory jobs byte-identical |
| CHK-M9-183 | PASS | no result → scan `cancelled` with `finished_at` = now in the cancel's own transaction; a completed unit + a running unit with a result → `partial` (never `cancelled`, #127 (d)); an original completed by late results with its retry still queued → `completed` |
| CHK-M9-184 | PASS | repeat → `cancelled_jobs: 0`, same state, `finished_at` not moved; two `scan.cancel` entries (`user:41` `{1}`, `user:42` `{0}`), target `scan:<id>`; unknown scan → `ScanNotFound`, no entry; `verify_chain` ok |
| CHK-M9-185 / REQ-220 (2) | PASS | after the cancel a pull returns only the agent's inventory job (state unchanged by the cancel); posts for the cancelled dispatched and running jobs → `Refused("job_not_acceptable", own_cancelled=True)`, nothing stored |
| race | PASS | 20 rounds, cancel and a post to one running job at a barrier: no error or deadlock; the job ends cancelled; the result is stored iff the post was accepted |
| CHK-M9-359 | PASS (red) | (repo plant) dispatched/running left → cancel rows red |
| CHK-M9-360 | PASS (red) | through `derive()` (tester-m9, G66) |
| derive step dropped | PASS (red) | 3 failed (the scan stays running/queued) |
| detail leaks job ids | PASS (red) | 1 failed (exact detail `{cancelled_jobs}`) |

#### Acceptance (TASK-200 row)

REQ-220 (1), (3)–(5) → CHK-M9-182 to -184. REQ-220 (2) is checked through the routes in TASK-205 too.

### TASK-201


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-224, REQ-227; TS §6.2 L1124, §4.4 L557, §4.3 L550, §5.2 L846–L857, L864; #122 (h), (i), #128 (d), (i), #129 (a); decisions "M9 builder rulings" (FOR SHARE on schedule create and enable). Code under test: `bm/services/scheduler/schedules_admin.py` (impl-manager-m9b, `work/reports/TASK-201-impl.md` incl. r1). Test file: `manager/tests/test_schedules_admin_pg.py` (new). Plan rows: CHK-M9-188, -189.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_schedules_admin_pg.py` | 8/26 passed, 18 failed: **test bug** (my checksum helper lacked `scan_schedule`) |
| re-run | the file after the helper fix | **26/26 passed**, 0 skipped; 0 containers left |
| plants | 5 | 5/5 red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-188 | PASS | create: defaults UTC and enabled; `next_run_at` = 16th 03:00 UTC from the 15th 12:00 (worked out by hand); agent ids stored lowercase; one `scan_schedule.create` by `user:7`, target `scan_schedule:<id>`. `0 9 * * *` Asia/Kolkata → 03:30 UTC; `0 3 * * 0` and `* * 7` → the next Sunday 03:00. PATCH cron → 04:30 UTC; timezone → 23:00 UTC (04:30 IST); `enabled: false` keeps `next_run_at`; `enabled: true` two days later recomputes from then; `policy_id` and `{}` → `InvalidField`; four `scan_schedule.update` entries by `user:8` naming the changed fields. Deleted policy: create and enable → `ScheduleConflict`, nothing written; a disabled policy is accepted; an unknown policy → `PolicyNotFound`; renaming a deleted policy's (disabled) schedule is allowed |
| CHK-M9-189 | PASS | delete: one `scan_schedule.delete` entry; its scan keeps its row with `schedule_id` NULL; delete/get/update afterwards → `ScheduleNotFound`. 18 bad fields (name `""`, 129 chars, U+0000, lone surrogate, non-string; cron `61 * * * *`, `@daily`, `0 0 1 * 1`, `0 0 30 2 *`, six fields, non-string; zone `Mars/Base`, `localtime`, `../etc/passwd`; target `{all:false}`, `{tags:[]}`, bad uuid; enabled `"yes"`) are refused on create **and** PATCH, with counts and the `scan_schedule` checksum unchanged and no input in the message. A 128-character name with outer spaces is kept as given. Another operator may change the schedule (`created_by` kept) |
| r1 race | PASS | for create and for enable: the schedule transaction is held open after its write; M7's policy delete started then **waits** (pg_locks probe) and, after the commit, disables the schedule. The schedule ends `enabled = false`, the policy deleted |
| plants | PASS (red) | FOR SHARE dropped (`lock=False`) → the race row; `next_run_at` not recomputed on enable → the PATCH row; NUL allowed in name → its row; the deleted check dropped → the conflict row; (CHK-M9-370 zone ignored, TASK-203 list) → the Kolkata rows |

#### Acceptance (TASK-201 row)

REQ-224 (1)–(4), (6), (7) at service level → CHK-M9-188, -189. Through the API (incl. (5), RBAC) → TASK-206.

### TASK-202


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-218, REQ-219, REQ-228, REQ-229, REQ-210 (end to end); TS §3.3 L218, §4.4 L575, L577, L579–L582, §4.1 L530, §3.4 L244, §8.4 L1291; #18, #66, #126, #127 (a)–(f); REQ-078 (5). Code under test: `bm/services/scheduler/sweep.py` (impl-manager-m9, `work/reports/TASK-202-impl.md`), on TASK-186/187/189 (tester-m9), 194, 196. Test files: `manager/tests/test_sweep_compliance_pg.py` (new); `manager/tests/test_sweep.py` updated under decisions "M9 builder rulings" (PD-40's rule): old **CHK-M3-185** "4 commits / 3 + 1" → new **CHK-M9-217** "7 commits / 6 + 1". A fake `ComplianceRepos` with no candidates records the three new steps' calls (24 h never-started window asked); every other assertion is unchanged. Plan rows: CHK-M9-204 to -214, -216, -217.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_sweep_compliance_pg.py tests/test_sweep.py` | 14/15 + 10/10. 1 failed: **test bug** (my expired-count assertion counted only my job; earlier tests' retries expire too) |
| re-run | that node id after the fix | **1/1 passed** |
| r2 | both files in the 8-file batch | **15/15** and **10/10 passed**, 0 skipped; 0 containers left |
| M3 | `tests/test_sweep_pg.py`, `tests/test_metrics_api_pg.py` (with the M3 batch) | green (G33) |
| plants | 11 | 11/11 red |
| r1 | `pytest tests/test_sweep_compliance_pg.py tests/test_sweep.py tests/test_queue_scan_race_pg.py` on the r1 tree (per-job savepoints) | **33/33 passed** (sweep 18 incl. the 3 new rows, `test_sweep.py` 10, queue race 5), 0 skipped; 0 containers left |
| r1 plant | per-job savepoint dropped | red: 2 failed (the poison `eval_spec` row: the bad job ended `failed` without a retry; the fault row) |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-204 | PASS | at the deadline exactly: nothing. 1 µs later: 2 of 5 results → `partial` (`finished_at` now) + one retry with plugins 1, 3, 5. No result → `failed` + a retry with all 5. Each retry is the TS §6.5 body (job_id = row, original commands and patterns, `pickup_by` now + 24 h), with the matching `eval_spec` entries, `retry_of`, `queued`. A second sweep makes none. Every result by the deadline → `completed`, no retry |
| CHK-M9-205 | PASS | dispatched at D, never started: at D + 24 h nothing; D + 24 h + 1 s → `failed` (`started_at` NULL) + a retry with all plugins |
| CHK-M9-206 | PASS | a retry past its deadline → `failed` (or `partial` with a result), no retry of it; a dispatched retry that never started → `failed`, none; an original `partial` by a final batch is not a candidate (no retry) |
| CHK-M9-207 | PASS | two sweeps at one barrier over 10 jobs → exactly 10 retries in total, one per job, no failed step; 20 rounds of a sweep and a post to one retry: no error, no failed step, each result stored once, no retry of the retry, the retry `completed` |
| CHK-M9-208 | PASS | deleted policy, decommissioned agent → `failed`, no retry; a disabled policy → retry made (#18) |
| CHK-M9-209 | PASS | REQ-210 (1), (2) end to end: after an import changed plugin 3's Execute (timeout 99) and the redaction setting changed, the retry holds 1, 3, 5 with the original command, timeout and patterns and the original's three `eval_spec` entries |
| CHK-M9-210 | PASS | a fault in `insert_retry` rolls back that job's ending too (r1: its savepoint): the job stays `running` with no retry, never `failed` without one; the next sweep → `failed` + 1 retry |
| r1 poison row | PASS | one past-deadline job with an unreadable `eval_spec`, or with a payload that has no `plugins` (written as owner), next to a normal past-deadline job and a never-started job. The sweep raises nothing, `failed_steps == []`. The bad job is byte-identical (still running, no retry) and logged once as `sweep job failed` with exactly `{step, job_id, exc_type}`. The two normal jobs end `failed` and get their retries in the same sweep |
| REQ-228 (2) | PASS | with compliance jobs and results present for 10 eligible agents (1 offline): `agents_offline` once with `offline` 1, `eligible` 10. `inventory_stale` names exactly the online agent whose `last_inventory_at` is older than twice the inventory interval. Compliance results do not count as inventory |
| CHK-M9-211 | PASS | an inventory job 31 min after dispatch → `failed`, never retried; a queued compliance job past `pickup_by` → `expired`; `bitscan_jobs_expired_total` grows by exactly the step's count; with the deadline step failing, `failed_steps == ["compliance_deadline"]` and the other steps and the scan refresh still apply (the all-expired scan → `failed`) |
| CHK-M9-212 | PASS | all completed → `completed` + `finished_at`; completed + expired → `partial`; all expired → `failed`; completed + failed → `partial`, then the failed job's late result → `completed` at the next sweep with `finished_at` unchanged; M7's delete cancelling the last queued jobs → `cancelled` (no results) / `partial` (some), with `finished_at`; no scan `dispatched`/`expired` |
| CHK-M9-213 | PASS | the refresh step reads `scan_job` in **one** statement (spy) with one `unit_facts` call; a completed scan and a finished scan created 9 days ago are not among its ids; an unchanged scan is not written; `scans_refreshed` = UPDATEs = written scans |
| CHK-M9-214 | PASS | REQ-228 (1): a compliance job queued 2 h for an offline agent → no `job_queue_age`; for an online agent → one alert in the hour (second run 10 min later: none) |
| CHK-M9-216 | PASS | across a sweep that ends, retries and refreshes, every earlier job's payload, `eval_spec`, agent, scan and `retry_of` are byte-identical |
| CHK-M9-217 | PASS | `test_sweep.py` 10/10 (seven steps; each of the 7 failing alone rolls back alone) |
| CHK-M9-341 | PASS (red) | retry of a retry allowed → 7 failed (the step errors) |
| CHK-M9-342 | PASS (red) | partial jobs as candidates, the re-check widened, `end_job`'s answer ignored → 5 failed |
| CHK-M9-343 | PASS (red) | retry holds every plugin → 2 failed |
| CHK-M9-344 | PASS (red) | retry commands from the current catalog → the CHK-M9-209 row |
| CHK-M9-345 | PASS (red) | retry failure swallowed (as if a separate transaction) → the fault row |
| CHK-M9-339 / -340 / -346 / -363 / -377 | PASS (red) | repo plants also run on this file |
| extras | PASS (red) | retry for a deleted policy / decommissioned agent; unchanged scans written → 1 failed each |

#### Acceptance (TASK-202 row)

REQ-218 (1)–(8) → CHK-M9-204 to -211; REQ-219 (1)–(5) → -212, -213; REQ-228 (1) → -214; REQ-228 (2) → the compliance-present row (added at the reviewer's request); REQ-229 (1), (2) → -211 and the M3 G33 suites green (scan-cancel effect on inventory: TASK-198/200).

### TASK-203


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-225, REQ-227; TS §4.4 L557, §4.3 L550, §2.1 L103; #3, #128 (d)–(g); decisions "M9 builder rulings" (the tick never waits for a policy while it holds its schedule row). Code under test: `bm/services/scheduler/scan_schedules.py`, `bm/services/scheduler/runner.py` (impl-manager-m9b, `work/reports/TASK-203-impl.md`, incl. r1). Test files: `manager/tests/test_scan_schedules_pg.py` (new). Under the ruling's PD-40 rule: `manager/tests/test_scheduler_runner.py` job-set checks, old **CHK-M3-230** `{inventory, offline_sweep}` → new **CHK-M9-218** `{inventory, offline_sweep, scan_schedules}` (30 s, run at start, one instance), plus the failing-run row for `scan_schedules`; and `manager/tests/test_serve_scheduler_linux.py` stop records, old **CHK-M3-233-r1** jobs `(offline_sweep, inventory)` → new **CHK-M9-219** (plus `scan_schedules`). Every other assertion in both files is unchanged. Plan rows: CHK-M9-195 to -202.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_schedules_pg.py tests/test_scheduler_runner.py` (8-file batch) | **11/11** and **16/16 passed**, 0 skipped; 0 containers left |
| serve | `pytest tests/test_serve_scheduler_linux.py` | run at the gate (G18); the change is one allowed job name |
| plants | 5 (370 also on TASK-201's file) | 5/5 red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-195 / -202 | PASS | at 03:00 one scan: `scheduled`, the schedule's id, `requested_by` NULL, `queued`, `created_at` = now, the policy version; one `scan.create` by `system` with `trigger` `scheduled` and the `schedule_id`, no alert (even for `{"all": true}`), the alert counter unchanged; `last_run_at` = now, `next_run_at` = the next day 03:00; a tick 30 s later queues nothing |
| CHK-M9-196 | PASS | previous scan unfinished → `previous_unfinished`; disabled policy → `policy_disabled`; tag with no agent → `no_target_agents`; no scan, no audit entry (counts equal); each: `last_run_at` kept (NULL), `next_run_at` → next day 03:00; the skip line carries exactly `{schedule_id, reason}` and no canary from the policy's command or the schedule name |
| CHK-M9-197 | PASS | hourly schedule due 01:00, the clock jumps to 03:00:10 → no scan, `missed`, `next_run_at` 04:00 (future), `last_run_at` NULL; a tick 1 min 59 s late runs; 2 min 1 s late → `missed` |
| CHK-M9-198 | PASS | a disabled schedule never runs over five ticks; two ticks at one barrier (10 rounds, one due schedule each) → exactly one scan per round, no error |
| CHK-M9-199 | PASS | `0 9 * * *` Asia/Kolkata: `next_run_at` 03:30 UTC; nothing at 03:29:59; one scan at 03:30; next 03:30 the day after; nothing at 09:00 UTC |
| CHK-M9-200 | PASS | a row whose run raises → `failed` 1, one record `scheduled run failed` with exactly `{schedule_id, exc_type: ValueError}` and no canary, the row still due; the next tick runs it. `SchedulerRunner` (real BackgroundScheduler, fake tick): job `scan_schedules`, `max_instances` 1; a raising tick is logged by job name and type only; `stop()` returns only after the running 1.5 s tick ended and no tick starts after |
| CHK-M9-201 | PASS | an owner-written row with cron `61 * * * *` → `invalid`, still enabled, `next_run_at` + 1 day, no scan |
| r1 deadlock race | PASS | the tick parks holding its due schedule row; M7's policy delete, started then, locks the policy and waits for that row (probe); released, the tick finds the policy held → `busy` 1, nothing written; the delete completes and disables the schedule; later ticks (30 s, a day) run nothing (no back-fill) |
| CHK-M9-370 | PASS (red) | time zone ignored (UTC) → 5 failed (Kolkata rows here and in TASK-201's file) |
| CHK-M9-371 | PASS (red) | missed check removed (back-fill) → the missed row |
| CHK-M9-372 | PASS (red) | unfinished-previous skip removed → the skip row |
| CHK-M9-373 | PASS (red) | (repo) `SKIP LOCKED` removed → the repo row. At service level two ticks still make one scan: the waiting tick re-checks the updated row (READ COMMITTED), so the repo row is the one that shows it |
| 203r1 | PASS (red) | `try_share_policy` replaced by a plain `FOR SHARE` → the deadlock race row fails (see note) |

#### Acceptance (TASK-203 row)

REQ-225 (1)–(8) → CHK-M9-195 to -200. `SchedulerRunner` starts the 30 s tick and still waits for a running job on `stop()` → CHK-M9-200, -218.

#### Notes

- 203r1 plant: with the plain `FOR SHARE`, the tick and the delete each wait on the other's row. The race test fails on that run (details in the M9 gate record).

### TASK-204


Tester: tester-m9b, 2026-10-30. Full rigor; TS §8.2 second approval task (PD-39). REQ-213 to REQ-216, REQ-229 (3), REQ-066, REQ-226 (metrics oracle); TS §6.1 L1064, L1065, L1071, L1072, §3.3 L203, L214, L222, L224, §6.5 L1165–L1190, §4.4 L567, L578, L581, §8.4 L1287, L1291; #54 (c), #121, #124 (a)–(h); PD-40. Code under test: `bm/repositories/jobs.py`, `bm/services/jobs/pull.py`, `bm/services/jobs/__init__.py` (r1: back to its M3 content), `bm/api/agent/jobs.py` (impl-manager-m9b, `work/reports/TASK-204-impl.md`); `manager/openapi.json` unchanged. Test files: `manager/tests/test_agent_jobs_api_pg.py` (new, the simulated agent end to end); `manager/tests/test_jobs_api_pg.py` (PD-40 rewrite, below); `manager/tests/test_metrics_api_pg.py` and `manager/tests/test_alerts.py` (REQ-226's counter added to two M3/M7 oracles, below). Plan rows: CHK-M9-220 to -231.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_agent_jobs_api_pg.py tests/test_jobs_api_pg.py tests/test_alerts.py tests/test_inventory_api_pg.py tests/test_sweep_pg.py tests/test_metrics_api_pg.py` (+1 sweep row) | 345/347 passed. 2 failed, both **test bugs**: pull equality ignored the ruling-2026-10-23 `pickup_by` re-serialisation; the accept-line check read a `data` key that the JSON formatter flattens. Then 1 failed after the fixes: the metrics label oracle (the `_created` sample) |
| re-runs | each failing node id after its fix | 1/1 passed each |
| r2 | `tests/test_agent_jobs_api_pg.py` in the W4 plant control | **20/20 passed** (19 + the planted row green on the clean tree) |
| security | `pytest tests/test_security_m9.py tests/test_invariants_m3.py tests/test_openapi.py tests/test_contract_agent.py` | **622/622 passed** (r1: pure modules load no psycopg/repository, CHK-M9-271) |
| plants | 6 route plants + 325/328 at route level | 8/8 red |

#### PD-40 (a) rewrite (TP-M9-19, CHK-M9-231): old → new

| Old check | Old assertion | New check | New assertion |
| --- | --- | --- | --- |
| CHK-M3-247 (compliance half; plant CHK-M3-351) `test_a_compliance_job_is_never_returned_in_m3` | REQ-072 (4): a queued compliance job is not returned | **CHK-M9-221** `test_a_compliance_job_is_returned_with_the_inventory_job` | REQ-213 (1), (2): returned with the inventory job, oldest first, equal to its stored payload (`pickup_by` the same instant), dispatched at the clock; still no `eval_spec`/`operator`/`expected` (CHK-M3-346 kept) |
| CHK-M3-249 own-compliance case (plant CHK-M3-359) `test_every_well_formed_batch_is_409_with_one_entry_and_nothing_stored` | REQ-073 (1): every well-formed batch is 409 | **CHK-M9-225** `test_well_formed_batches_for_jobs_that_cannot_take_them_are_409` | REQ-214 (2): the agent's own dispatched compliance job answers 200 `{1, 0}` with one stored row and no refusal entry. The inventory (dispatched, queued), unknown, foreign and start-notice cases keep their 409 and entry assertions **unchanged** |

Every other M3 assertion in `test_jobs_api_pg.py` (refusal entry, flood alert, 400, 413, gzip, no stdout in logs, the token matrix, rate limits) is unchanged and green.

REQ-226 also changes two oracles: the registry family set (`test_alerts.py`: + `bitscan_plugin_results`, **CHK-M9-233**) and the bounded-label oracle (`test_metrics_api_pg.py`: + `result` ∈ {PASS, FAIL, ERROR} on that family only, **CHK-M9-234**).

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-220 / -221 | PASS | 6 inventory + 6 compliance queued at interleaved times: the first pull returns the 10 oldest in creation order (mixed kinds), the second the other 2. Each job is dispatched once, at the clock. The answer validates against `JobsResponse` and the pull schema in `manager/openapi.json`. Each compliance job equals its stored payload (six keys, `ComplianceJob`). No answer contains `"eval_spec"`, `"operator"`, `"expected"` or `"expected_result"`. A third pull is `{"jobs": []}` |
| CHK-M9-222 | PASS | cancelled, expired, past-`pickup_by` and another agent's jobs are never returned (the other agent's stays queued); 1 µs before `pickup_by` is returned. Four concurrent pulls over 12 compliance jobs → each once, all 12 |
| CHK-M9-223 | PASS | the M3 pull checks for inventory (REQ-072 (1), (3), (5), (6)) green in `test_jobs_api_pg.py` |
| CHK-M9-224 | PASS | 10 refusals through the route: unknown, foreign, inventory, queued, expired, cancelled (dispatched, running), dispatched + 7 d + 1 s, 49 + 1 foreign, unreadable `eval_spec`. Each is 409 `job_not_acceptable` (problem keys only, no canary in the answer) with exactly one `agent.result_refused` entry (`agent:<id>`, `job:<id>`, reason `job_not_acceptable` or `eval_spec_invalid`, `results`, `final`, no canary) and no stored row; the `scan_job` checksum is unchanged |
| CHK-M9-225 | PASS | dispatched, running, failed, partial, completed → 200 `{1, 1}` validating `ResultsResponse`; dispatched + 7 d exactly → 200 |
| CHK-M9-226 | PASS | malformed → 400, no entry; 1.5 MiB + 1 as sent → 413 with one `too_large` entry; gzip → 200, stored; gzip inflating past the cap → 413 |
| CHK-M9-227 | PASS | 21 409s for agent B's own cancelled job → no flood alert (21 refusal entries); 21 counted 409s for agent A within 10 min → one `result_409_flood` for A, `bitscan_alerts_total` +1 |
| CHK-M9-228 | PASS | end to end with the SR §1.1 plugin: pull → the start-notice fixture (running, `started_at` = clock, `deadline_at` = + 615 s with `max_parallel_plugins` 2) → the one-final fixture (PASS, snapshots, `received_at` = clock) → completed; the repeat → `{0, 1}`; `host_counts` (1, 0, 0, 0). A 0.1.0 agent's `error_cases` fixture → three ERROR rows (`spool_overflow`, `runner_unavailable`). The NUL fixture bytes, plain and gzip → `a�b` / `�`, PASS. Catalog change after queue → the pulled command is the queued one; PASS on the queued expected. First result wins across original and retry, both orders |
| CHK-M9-229 | PASS | the results route refuses an inventory job id (409); the inventory route refuses a compliance job id (409); both jobs unchanged |
| CHK-M9-230 | PASS | `bsu_` and `bsk_` tokens on both routes → 401; another agent's `bsa_` on this agent's path → 403; nothing dispatched or stored |
| logs | PASS | a canary in stdout/stderr (plain, gzip, duplicate, refused) is in no log line; the accept line carries `agent_id`, `job_id`, `accepted`, `duplicates` only |
| CHK-M9-378 | PASS (red) | pull inventory-only → 9 failed |
| CHK-M9-379 | PASS (red) | `eval_spec` added to pulled payloads → 10 failed |
| CHK-M9-380 | PASS (red) | own cancelled counted / no 409 counted → 1 failed each (the flood row) |
| CHK-M9-325 / -328 (G70) | PASS (red) | cancelled accepted / kind ignored → 2 / 1 failed through the route |

#### Acceptance (TASK-204 row)

REQ-213 (1)–(5), REQ-214 (1)–(6) (6: TASK-199), REQ-215 (3)–(5), REQ-216 (1)–(3) end to end, gzip/400/413 as REQ-066, REQ-229 (3) → the rows above. `manager/openapi.json` byte-identical (G6 green in the security run).

### TASK-205


Tester: tester-m9b, 2026-10-30. Full rigor; lead's second look (PD-39). REQ-212 (1), REQ-220 (2), REQ-221, REQ-222 (3), (4), REQ-227 (2); TS §6.2 L1119, L1122, L1084, §6.3 L1133–L1138, §6.4 L1146–L1155, §8.4 L1290, §3.3 L213; #3, #48, #122 (a)–(g), #123, #129 (b). Code under test: `bm/api/user/scans.py`, `bm/api/user/__init__.py`, `manager/openapi.json` (impl-manager-m9, `work/reports/TASK-205-impl.md`, incl. r1: the target is parsed before the idempotency digest). Test file: `manager/tests/test_scans_api_pg.py` (new). Plan rows: CHK-M9-240 to -246.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scans_api_pg.py` (8-file batch, r1 tree) | **12/12 passed**, 0 failed, 0 errors, 0 skipped; 0 containers left |
| security | `tests/test_security_m9.py tests/test_invariants_m3.py tests/test_openapi.py tests/test_contract_agent.py` | 622/622 passed (G6, G34 with the seven operations) |
| plants | 4 | 4/4 red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-240 | PASS | operator and admin, each with a session and with an API token → 202 with exactly `{scan_id, state: "queued", policy_version, jobs}`; the scan row is `requested_by` the caller, `manual`. A viewer → 403 `forbidden`; a `bsa_` token, no token and a revoked token → 401; nothing written |
| CHK-M9-241 | PASS | unknown policy → 404 `not_found`; disabled → 409 `conflict` "The policy is disabled."; deleted → 409 "The policy is deleted."; only a decommissioned agent → 422 `about:blank` "The target resolves to no host."; `{all: false}`, two keys, `policy_id` as a string, no `policy_id`, an extra `plugins`/`execute`/`command`/`payload`/`eval_spec` key, and `execute` inside the target → 400 `invalid_request` (no input echoed); 1 MiB + 1 → 413 `too_large`; scan, job, result and audit counts unchanged. Exactly 1 MiB → 202 |
| CHK-M9-242 | PASS | `{all: true}` + `bsk_` → 202, the `scan.create` entry carries `alert` true and `alert_kind` `all_hosts_scan_api_token`, the counter +1, the fake sink receives it after one shipper cycle; a session and tags + `bsk_` → 202, no alert |
| CHK-M9-243 | PASS | cancel: viewer 403; `bsa_` 401; operator 200 `{scan_id, state: "cancelled", cancelled_jobs: 3}` (queued, dispatched, and running after a start notice); a repeat → `cancelled_jobs: 0`; unknown 404; `x`, `123`, short and long ids → 400. The cancelled queued job is never pulled; posts for the cancelled dispatched and running jobs → 409, nothing stored |
| CHK-M9-244 | PASS | `api/user/scans.py` imports no repository and no psycopg (AST; also `test_security_m9.py`) |
| CHK-M9-245 | PASS | a repeat with the same key and body → the same 202 body, no second scan row and no second `scan.create` entry; the same key with another body → 409 `conflict` "Idempotency-Key was used with a different request."; another user's same key → its own scan. Keys of 256 characters, with `\x01`, with a tab, and empty → 400; 255 characters → 202. **r1:** `{"agents": [NaN]}` with a key → 400, not 500 |
| CHK-M9-246 | PASS | a snapshot with U+0000 in `execute` → 500 `about:blank`, fixed detail with no input, nothing written |
| CHK-M9-364 | PASS (red) | operator → viewer in the dependency → 2 failed |
| CHK-M9-365 | PASS (red) | the token check removed (any caller, incl. `bsa_` and none) → 7 failed |
| CHK-M9-382 | PASS (red) | `extra="ignore"` → 1 failed (the refusal row: an `execute` key accepted) |
| CHK-M9-367 (route) | PASS (red) | the store bypassed → 1 failed (a second scan on repeat) |

#### Acceptance (TASK-205 row)

REQ-221 (1)–(5), REQ-222 (4), REQ-212 (1), REQ-220 (2) → the rows above. `manager/openapi.json` re-export byte-identical (G6 green).

#### Notes (no defect)

- `POST /scans` validates its declared body before the token check, as the existing user routes do, so a malformed body with a bad token gets 400, not 401. With a valid body, each token case is 401. The impl report mentions this. No 401 from this suite depends on body order.

### TASK-206


Tester: tester-m9b, 2026-10-30. Full rigor. REQ-212 (1), REQ-224; TS §6.2 L1124, L1084, §6.3 L1133–L1138, §4.4 L557, §4.3 L550, §5.2 L846–L857, L864; #122 (h), (i), #128 (d), #129 (a). Code under test: `bm/api/user/scan_schedules.py`, `bm/api/user/__init__.py`, `manager/openapi.json` (impl-manager-m9b, `work/reports/TASK-206-impl.md`), on TASK-201 r1. Test file: `manager/tests/test_scan_schedules_api_pg.py` (new). Plan rows: CHK-M9-255 to -257.

#### Runs

| Run | Command (W, own copy and venv, `CI=true`, PG16, `-n 0`, own database) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_scan_schedules_api_pg.py` | 21/22 passed, 1 failed: **test bug** (after moving the clock a day, my session token had idled out → 401; the test now opens a new session for the later call) |
| re-run | the file | **22/22 passed**, 0 skipped; 0 containers left |
| plants | 2 | 2/2 red |

#### Checks (rows for `tests/m9/report.md`)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-M9-255 | PASS | POST → 201 with exactly the 10 item keys, `UTC`, enabled, `created_by` = the caller (API token), `last_run_at` null, `next_run_at` RFC 3339 Z = the next 03:00 UTC; list `{items, next_cursor}` paged by `schedule_id` in order; get → the item; unknown → 404 `not_found`; ids `x`, `1.0`, `+1`, `-1` and a bad cursor → 400 |
| CHK-M9-256 | PASS | PATCH cron → 04:30 next day; timezone Asia/Kolkata → 23:00 UTC; `enabled: false` → off; a day later `enabled: true` → recomputed from then; `{"policy_id": …}`, `{}`, `{"name": null}`, `{"enabled": "yes"}` → 400; a disabled policy's schedule → 201; a deleted policy → create 409 "The policy is deleted.", enable 409; unknown policy → 404 |
| CHK-M9-257 | PASS | DELETE → 204, empty body; second DELETE → 404; the schedule's scan keeps its row with `schedule_id` NULL; create, update and delete → exactly three entries by the caller with target `scan_schedule:<id>` (update detail `{"name": "renamed"}`). A viewer → 403 on all five operations, a `bsa_` token and no token → 401, nothing written; another operator (API token) and an admin may change and delete the schedule. 17 bad bodies (cron `61 * * * *`, `@daily`, both day fields; zone `Mars/Base`, `localtime`; target `{all:false}`, bad uuid; name empty, 129 characters, U+0000; extra `execute`, `plugins`, `command`, `payload`, `eval_spec`; `policy_id` "1"; `enabled` 1) → 400 `invalid_request` on create (and on PATCH for the patchable fields), counts and the `scan_schedule` checksum unchanged, no input echoed. A body over 1 MiB → 413 |
| role plant | PASS (red) | operator → viewer → 1 failed |
| extra-keys plant | PASS (red) | `extra="ignore"` on both bodies → 5 failed (the command-text keys and `policy_id` in PATCH accepted) |

#### Acceptance (TASK-206 row)

REQ-224 (1)–(7) and REQ-212 (1) for the schedule bodies → the rows above. `manager/openapi.json` byte-identical after the re-export (G6 green in the security run).

### TASK-207


Tester: tester-m9, 2026-10-30. Low risk (batched with TASK-208). REQ-232; TS §6 L1056, §8.2 L1266; PD-20. Code under test: `web/src/api/schema.d.ts` regenerated by impl-manager-m9 (`work/reports/TASK-207-impl.md`; sha256 `e08b7eb309cc68e2…`), from `manager/openapi.json` (sha256 `74182d35538d1d99…`, as re-exported by TASK-205/206). Plan rows: CHK-M9-280 to -284. Everything ran in a throwaway copy (`$TEMP/m9t-207`, holding `web/` without `node_modules` plus `manager/openapi.json`; `npm ci --ignore-scripts` from the lockfile; removed afterwards). Nothing in the worktree was regenerated.

#### Runs

| Run | Command (L, Windows, Node 24.22, npm 11.19, in the copy) | Result |
| --- | --- | --- |
| r1 | `npm ci --ignore-scripts`, then `npm run gen:api` | `schema.d.ts` sha256 unchanged, and `cmp` with the worktree file is identical (G16) |
| r2 | `npm run typecheck`; `npm run lint` | exit 0; exit 0 (`--max-warnings 0`) |
| r3 | `oa.py` (JSON compare of `git show d09c537:manager/openapi.json` with the current one) and `git diff --numstat d09c537 -- web/src/api/schema.d.ts` | see CHK-M9-281, -284 |
| r4 (W) | `pytest tests/test_openapi.py` in a fresh copy of the current tree (G6) | **6/6 passed**, 0 failed, 0 errors, 0 skipped |
| plant | a hand-written comment line inserted in `schema.d.ts`, then `npm run gen:api` | red: the regenerated file differs from the hand-edited one (`621d620 < // hand edit (plant)`) |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-280 | CODE | L | r1 | PASS | Regeneration from the M9 `openapi.json` leaves `schema.d.ts` byte-identical (sha256 check and `cmp` with the worktree file) | 2026-10-30 |
| CHK-M9-281 | CODE | L | r3 | PASS | Exactly 7 operations are added since `d09c537`: `POST /api/v1/scans`, `POST /api/v1/scans/{id}/cancel`, `GET`/`POST /api/v1/scan-schedules`, `GET`/`PATCH`/`DELETE /api/v1/scan-schedules/{id}`. All start with `/api/v1/`. None was removed, no earlier path changed, and there is no read view, reevaluate or `run` route. `schema.d.ts`: +813/−0, adding exactly those 4 paths. The new request schemas `ScanRequest`, `CreateSchedule` and `PatchSchedule` have `additionalProperties: false` and no `execute`, `plugins`, `payload` or `eval_spec` property (REQ-212 (1) at contract level) | 2026-10-30 |
| CHK-M9-282 | CODE | L | r2 | PASS | `tsc --noEmit -p tsconfig.json` exit 0; `eslint --max-warnings 0 .` exit 0 | 2026-10-30 |
| CHK-M9-283 | CODE | L | plant | PASS (red) | A hand edit to `schema.d.ts` gives a regeneration diff (G16 red) | 2026-10-30 |
| CHK-M9-284 | CODE | L | r3 | PASS | REQ-232 (3): the component schemas `ComplianceJob`, `ResultsRequest`, `ResultsResponse`, `ResultItem`, `PluginSpec`, `JobsResponse` and `InventoryJob` are identical to `d09c537` (JSON-equal). No schema was removed or changed; added: `CreateSchedule`, `Page_ScheduleItem_`, `PatchSchedule`, `ScanCancelledItem`, `ScanQueuedItem`, `ScanRequest`, `ScheduleItem` | 2026-10-30 |
| CHK-M9-303 | CODE | W | r4 | PASS (for this tree) | G6: `test_openapi.py` 6/6, so the committed export matches the app. The gate row itself stays tester-m9b's at the M9 gate | 2026-10-30 |

#### Acceptance (TASK-207 row: "G16 shows no diff, every new path starts with `/api/v1/`, and `npm run typecheck` passes")

→ CHK-M9-280, -281, -282 (and the plant CHK-M9-283).

#### Note

The result holds for `openapi.json` sha256 `74182d35…`. If TASK-205 or TASK-206 re-export again (for example after a review round), G16 must be re-run; at the gate this is G16 in CI.

### TASK-208


Tester: tester-m9, 2026-10-30. Low risk (docs; batched with TASK-207). REQ-233; TS §4.4, §6.2 L1119, L1122, L1124, §6.4. Under test: `README.md` (impl-manager-m9b, `work/reports/TASK-208-impl.md`: the new "## Scans" and "### Schedules" sections, the Agent API results row and the "Compliance jobs and results" bullets, the metrics list and the Scheduler section), against the M9 tree at the time of the run (TASK-205 r1 included). Test file (new): `manager/tests/test_readme_m9_walk_linux.py`. Plan rows: CHK-M9-285 to -287.

#### How it was walked

A real `bitscan-manager serve` over HTTPS on its own migrated PostgreSQL 16, with the fake OpenBao and audit sink and a temporary bits folder (the M5/M7 walk harness), on the **real clock**: the scheduler ticks every 30 s and `offline_sweep` runs every 60 s. The walk sets up:
- the admin through `users create-admin`, then a TOTP session and an API token;
- an operator and a viewer through `POST /users`, and an operator `bsk_` token;
- three folder policies (enabled, disabled, another one) and one uploaded and then deleted policy;
- four agents enrolled through `POST /agent/enroll` (three auto-approved, one held), tagged through `PUT /agents/{id}/tags`;
- agent pulls and result posts with their own `bsa_` tokens.

Every expected value is the README's text. The database is only read, as owner, to observe job, scan, result and audit state. Each documented step is one row; the test fails if any row differs.

#### Runs

| Run | Command (W, copy `/root/bstest-m9-walk` of the current tree + README, venv `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_readme_m9_walk_linux.py` | 1 failed in 10 s: `SSLEOFError` sending the over-1 MiB body. **Test bug**: the server answers 413 from the declared length and closes while `http.client` is still sending. A `post_big()` helper now sends like curl, tolerates the early close and reads the answer |
| r1 | same | 1 failed (190 s), 87/88 rows matched. **Test bug** in the row "a job keeps the commands it was built with": A1's pull also returned the other profile's queued job, which the walk had queued on purpose, so there were 2 compliance jobs. The pulled jobs are now filtered to the main profile's checks |
| r2 | same | **1/1 passed** (188 s), 0 failed, 0 errors, 0 skipped. **88/88 README rows** as written |
| static (L) | ruff check, ruff format --check, mypy --strict on the test file | clean |

#### Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-285 | APP | W | r2 | PASS | 88/88 rows. **Starting:** the 202 body has exactly `jobs, policy_version, scan_id, state`, queued, at the profile's version, `jobs` = hosts; tags match any (the held host is left out); unknown agent ids are left out; `all` = every host not awaiting approval; the scan records the request, `resolved_agents` and the version. **Idempotency-Key:** a repeat returns the same 202 with no second scan and no second `scan.create`; another body → 409; 256 characters → 400. **Alert:** an API-token all-hosts scan carries `all_hosts_scan_api_token` on its `scan.create` entry, and a session scan does not; one `scan.create` per scan. **Refusals, nothing written:** an empty or two-form target 400 (detail `Invalid request: target…`), another key (`execute`) 400, unknown 404, disabled 409, deleted 409, no eligible host 422, a body over 1 MiB 413; a viewer 403. **One job per host:** the earlier scan's queued jobs are cancelled with `finished_at`; another profile's queued job and every inventory job are untouched; a handed-out job keeps running. **Commands fixed when queued:** a job queued before a re-import keeps `cat /etc/hostname`; a scan after it has version + 1 and the new command. **Agent side:** a pull returns inventory and compliance jobs together, with exactly the six job keys and `{plugin_uuid, execute, timeout_s}`, and no expected value or operator; an empty batch is the start notice (running, `started_at` and `deadline_at` set), and a second changes nothing; `{1, 0}`, then `{0, 1}` for a repeat; a batch naming a foreign check → 409 `job_not_acceptable`, nothing stored; U+0000 stored as U+FFFD; 65,537 bytes stored as ERROR `oversize` with `''` texts; job completed; `bitscan_plugin_results_total` exports PASS/FAIL/ERROR (ERROR ≥ 1); the scan becomes completed and finished within the documented lag. **Cancel:** 200 with exactly `{scan_id, state, cancelled_jobs}`, 2 cancelled, state cancelled; the handed-out job's results → 409; cancelled queued jobs are not pulled; again → 0; one `scan.cancel` per cancel (2); unknown 404; unhyphenated id 400; viewer 403. **Schedules:** the README example → 201 with exactly the ten item keys, enabled, `next_run_at` in the future; `timezone` defaults to UTC; weekday 0 and 7 give the same Sunday 03:00Z; a disabled profile is accepted; a viewer gets 403 on list and get; the list is ordered and paged by `limit`/`cursor`; get one; PATCH `cron` recomputes `next_run_at` (Monday 04:00 London); `policy_id` → 400; `{}` → 400; another operator's `{enabled: false}` → 200; 11 refusals (both day fields, `@daily`, a seconds field, never fires, 65+ characters, an unknown or too long zone, an empty or 129-character name, a bad target, `execute`) → 400; a 128-character name accepted; DELETE 204 then 404; deleting a profile disables its schedule; a deleted profile's schedule can be neither created nor enabled (409); one `scan_schedule.*` entry per create/change/delete (5/3/1). **Runs (real clock):** an every-minute `{all: true}` schedule created with an API token queued a `scheduled` scan with `requested_by` NULL, actor `system`, no alert, and set `last_run_at`. Skips were logged `scheduled run skipped` with the schedule id and `policy_disabled`, `no_target_agents` and `previous_unfinished`; they queued nothing. The scan of a deleted schedule is kept with `schedule_id` NULL | 2026-10-30 |
| CHK-M9-286 | CODE | W, L | r2; `git diff README.md` scan | PASS | The Scans + Schedules text has no `bs?_` token shape, no "password", no TASK/REQ/CHK id, no tester/impl/planner name and no milestone name. The whole README diff has no token, no host path and no process note (the only "password" is the existing `/auth/password` route name) | 2026-10-30 |
| CHK-M9-287 | CODE | W | r2 | PASS | The README says the results routes are "not part of this version yet"; Idempotency-Key entries are kept "in memory, for 24 hours" and "forgotten when the manager restarts"; the scan state can lag (`offline_sweep`); `### Schedules` sits inside `## Scans`. Each matches the spec values (#123 (c), #127 (f)) | 2026-10-30 |

#### Not walked (reason), covered elsewhere

- Deadlines, the single retry, the 24 h never-started rule, the 7-day late window and "no back-fill" need hours of real time. They are tested with clock control on PostgreSQL (TP-M9-14, -15: CHK-M9-197, -204 to -210, tester-m9b).
- A decommissioned host's exclusion needs `decommission_after_days` of real time (CHK-M9-110, tester-m9b).
- The skip reasons `policy_has_no_plugins` and `invalid` cannot be produced through the API (they need an owner write).

#### Observations for the README owner (not failures)

- "A job past its deadline ends `partial` or `failed`": by #127 (b) a job whose every check already has a result ends `completed` at the deadline. This edge cannot follow from a final batch, so the wording is fine for users. Noted only.
- DST is not described. The user's decision (shift the gap, run the repeat once; TASK-191 r1) could be added in one line, and it also means a sub-hourly schedule has no run in the repeated hour. That is for impl-manager-m9b and `main` to decide; it is not required by REQ-233.
- The awaiting-approval host's `PUT /agents/{id}/tags` was recorded only (the README makes no claim about it).

#### Round 2 (TASK-208 r1, 2026-10-30): PASS

impl-manager-m9b's r1 adds two README lines (README sha256 `9fe42ce43caff550…`): the DST sentence in the `### Schedules` `timezone` bullet (L488), and "(or `completed` if every check already has a result)" in the deadline bullet of "How a scan proceeds" (L466). The walk gains two rows for them; the earlier 88 rows are unchanged.
- **DST row:** the three statements are in the Schedules text (a time skipped in spring runs just after the jump; a time in the repeated hour runs once, at its first occurrence; a sub-hourly schedule makes no runs in the repeated hour). Each is checked against the manager's `next_fire` on the Europe/London 2026 transition days, the user decision as pinned by TASK-191 CHK-M9-071: `30 1 * * *` → 03-29 01:30Z, then 03-30 00:30Z; → 10-25 00:30Z only, then 10-26 01:30Z; `*/30 * * * *` → 00:00, 00:30, 02:00, 02:30Z on 10-25 (no 01:00Z or 01:30Z). PASS.
- **Deadline row:** the text says a job past its deadline ends `partial` or `failed` "(or `completed` if every check already has a result)", and that only "a `partial` or `failed` one gets **one** retry" (#127 (b), #126 (c)). PASS.

| Run | Command (W, a fresh copy of the current tree + the r1 README, `/root/venv-m9`, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| r3 | `pytest tests/test_readme_m9_walk_linux.py` (the walk is one test, so it was run whole) | **1/1 passed** (190 s), 0 failed, 0 errors, 0 skipped; **90/90 rows** as written |
| static (L) | ruff check, ruff format --check, mypy --strict on the test file | clean |

Remaining note (not a failure): the **Scheduler** section bullet (README L612) still reads "Compliance jobs past their deadline end `partial` or `failed`". It is a short summary that points to Scans, where the full rule is now stated. Noted for impl-manager-m9b only.

#### Type fix (2026-10-30, before the M9 gate)

`mypy --strict --config-file manager/pyproject.toml --platform linux` found 7 errors in `manager/tests/test_readme_m9_walk_linux.py`. On Windows the module-level `pytest.skip` makes mypy skip the body, so the default local run had looked clean. They were fixed test-side only, keeping every assertion:
- `ans` is checked for `None` before `.get`;
- the skip-poll lambda is now `functools.partial(skipped, sched, reason)`;
- the final failed-row list is renamed `failed_rows`, because `bad` was already the loop variable of the PATCH refusals.

| Run | Command | Count |
| --- | --- | --- |
| mypy (L) | `mypy --strict --config-file manager/pyproject.toml --platform linux manager`, and the default form | this file clean in both. Re-check after tester-m9b's current `test_sweep_compliance_pg.py`: **whole tree clean, 385 files, both forms** (the earlier 2 errors there came from an older copy of that file) |
| ruff (L) | `ruff check`, `ruff format --check` on the file | clean |
| r4 (W) | `pytest tests/test_readme_m9_walk_linux.py` in a fresh copy of the current tree | **1/1 passed** (189 s), 0 failed, 0 errors, 0 skipped; 90/90 rows |

### M9-gate


Tester: tester-m9b, 2026-10-30. Tree: worktree `Bitscan-m9`, branch `m9-scan-engine` = main `d09c537` plus the uncommitted M9 files (all 23 tasks APPROVED). W runs: copy `/root/bstest-m9b-g18` (G18) and `/root/bstest-m9b-base` (plants and re-runs). Venv `/root/venv-m9b` was built with `pip install --require-hashes -r manager/requirements-dev.txt`, then `-e` of the copy. `PYTHONPATH` was pinned to the copy, with `CI=true` and PostgreSQL 16 by Testcontainers. Free memory was checked before each run (≥ 3,000 MB for `-n 2`). The web UI was built from a temp copy of `web/` (`npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`) and copied into the WSL copy only, never into the worktree. All my containers were removed after each run.

#### Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| G1 | `ruff check manager` (whole tree, L) | PASS | "All checks passed!" after one fix: an E501 in my `test_queue_scan_race_pg.py` that reviewer-m9 found. Plants CHK-M9-376: an f-string query in each of the 5 new repositories → `S608`, exit 1 (5/5 red) |
| G2 | `ruff format --check manager` (L) | PASS | 385 files already formatted |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager`, and the same with `--platform linux` (L) | PASS | "Success: no issues found in 385 source files", both forms. Plant: an untyped `def _untyped(x)` in `services/jobs/intake.py` → `no-untyped-def`, exit 1 (W) |
| G4 | the venv built with `--require-hashes` (W); `git diff --stat d09c537 -- manager/requirements.txt manager/requirements-dev.txt manager/pyproject.toml manager/bitscan_manager/db/migrations agent deploy bits/samples .github` | PASS | install ok; the diff is empty (no dependency, no migration, no agent/unit/package/workflow change) |
| G5 | services coverage in the G18 run | PASS (plant red: 83.99 %, exit 1) | **98.53 %** (5,692/5,777) of `bm/services`. `services/jobs/*` 100 % each; scheduler `cron` 94.55 %, `runner` 98.86 %, `scan_schedules` 98.80 %, `schedules_admin` 98.13 %, `sweep` 98.22 %. Plant: 920 untested statements in `intake.py` (sized from the clean report: 5,692 / 6,697 = 84.99 %); result in "G5 plant" below |
| G6 | `tests/test_openapi.py` in G18; `git diff d09c537 -- manager/openapi.json` | PASS | green. The added operations are exactly the seven M9 ones: `POST /scans`, `POST /scans/{id}/cancel`, `POST`/`GET /scan-schedules`, and `GET`/`PATCH`/`DELETE /scan-schedules/{id}`. Plant: a `GET /scans/{id}/planted` route without re-export → 2 failed (byte check, module command) |
| G16 | in a temp copy (`web/` + `manager/openapi.json`): `npm run gen:api`, then `cmp` with the worktree `web/src/api/schema.d.ts` (L) | PASS | byte-identical. Every M9 path starts with `/api/v1/` (`/scans`, `/scans/{id}/cancel`, `/scan-schedules`, `/scan-schedules/{id}`). Plant: a hand edit to `schema.d.ts` makes the regenerated file differ (red); regeneration restores the committed bytes |
| G18 | full manager suite, `pytest -n 2 -rfEs --cov` (W, web build present, `CI=true`) | PASS after test-only fixes | First run: **11,160 passed, 6 failed, 0 errors, 0 skipped of 11,166** (25 min 13 s). All 6 were M3/M2 oracles that an M9 requirement supersedes and that I had not yet updated (below). After the fixes, the 6 node ids re-ran **6/6 passed**. Final: **11,166/11,166**, 0 skipped |
| G19 | `tests/test_schema_diff.py` in G18 | PASS | green with no migration. Plant: a throwaway `m0006` creating `ix_job_scan ON scan_job(scan_id)` → `test_migrated_schema_equals_the_spec` red (1 failed) |
| G30 | `tests/test_contract_agent.py`, `test_contract_fixtures.py` in G18; component schemas against `git show d09c537:manager/openapi.json` | PASS | green. `ComplianceJob`, `ResultsRequest`, `ResultsResponse`, `ResultItem`, `InventoryJob`, `JobsResponse` and `PluginSpec` are identical to `d09c537`. Plants: `operator` added to `ComplianceJob` → 2 failed; the NUL fixture made invalid (stdout pattern refusing U+0000) → 2 failed |
| G31, G33 | M3 agent-auth, sweep and inventory suites in G18 | PASS | green (`test_agent_auth_pg`, `test_security_m3`, `test_sweep_pg`, `test_inventory_*`, `test_jobs_api_pg` with the PD-40 rewrite). CHK-M9-365 (the scan route accepting any caller, incl. `bsa_`) → 7 failed in G70 |
| G34 | `tests/test_invariants_m3.py` in G18 | PASS | green with the seven M9 operations. Plant: `POST /scans/{id}/run` taking an `execute` body → 2 failed (the M3 route walk, and the M9 route-set and command-property check in `test_security_m9.py`) |
| G66 | M9 unit suite (7 files) | PASS | **674/674** in G18 (job_states 238, scan_state 52, scan_targets 72, job_build 62, intake_plan 107, cron 109, idempotency 34; tester-m9) |
| G67 | `test_jobs_property.py` | PASS | **8/8** in G18 (tester-m9) |
| G68 | M9 integration on PostgreSQL (12 files) | PASS | **157/157** in G18 (fixtures 5, scan_queue 10, scan_progress 6, job_intake 20, job_sweep 9, schedules repo 9, queue 8, intake 28, cancel 7, schedules admin 26, scheduled runs 11, sweep 18) |
| G69 | races and security | PASS | **20/20** in G18 (first-result-wins race 1, 200 rounds; queue races 5; `test_security_m9.py` 14) |
| G70 | API suites | PASS | **54/54** in G18 (agent job routes 20, scan routes 12, schedule routes 22) |

#### G18 findings (all test-only; no product change)

Each failure was a pre-M9 oracle whose expected value an approved M9 requirement changes. Each was updated under PD-40's rule (decisions "M9 builder rulings"): every other assertion is kept, and old → new is listed here and in the TASK reports.

| Test (first run) | Was | Now | Requirement |
| --- | --- | --- | --- |
| `test_jobs_repo_pg.py::test_pull_ten_oldest_then_the_rest` | REQ-072 (4): the planted compliance job not pulled (CHK-M3-081 kind half, plant CHK-M3-351) | **CHK-M9-235**: the compliance job (oldest) is pulled first as its stored payload and dispatched; the 12 inventory jobs follow 9 + 3; every other assertion unchanged | REQ-213 (PD-40 (a)) |
| `test_jobs_repo_pg.py::test_pull_never_returns_eval_spec_or_compliance` → `test_pull_returns_compliance_but_never_eval_spec` | pull returns `[]` | **CHK-M9-236**: returns `[stored payload]`; still no `eval_spec`/`operator`/`expected` | REQ-213 (2) (PD-40 (a)) |
| `test_login.py::test_openapi_error_contract[committed]`, `[fresh]` | the only operation listing 422 is the inventory upload | **CHK-M9-237**: inventory upload and `POST /scans` (422 `about:blank` for a target with no host), compared as a set; still problem+json | REQ-221 (2), #3, #122 (f) |
| `test_thresholds.py::test_metric_families_and_labels` | six families | **CHK-M9-238**: + `bitscan_plugin_results` (counter, label `result`) | REQ-226 |
| `test_thresholds.py::test_no_unbounded_label_names_anywhere` | label names kind/status/le/mode | **CHK-M9-239**: + `result` ∈ {PASS, FAIL, ERROR} | REQ-226 (3) |

Re-run by node id after the fixes: **6/6 passed** (`test_login` counts twice, from its parametrization).

Earlier during the tasks, the same kind of oracle updates (listed in their TASK reports):
- CHK-M3-247 → CHK-M9-221 and CHK-M3-249 → CHK-M9-225 (PD-40 (a), `test_jobs_api_pg.py`);
- CHK-M3-185 → CHK-M9-217 (`test_sweep.py`, 7 steps);
- CHK-M3-230 → CHK-M9-218 (`test_scheduler_runner.py`);
- CHK-M3-233-r1 → CHK-M9-219 (`test_serve_scheduler_linux.py`);
- CHK-M9-232 (35 alert kinds);
- CHK-M9-233 and -234 (`test_alerts.py`, `test_metrics_api_pg.py`).

#### G2: inventory cannot be disabled (REQ-229)

- **Diff:** `git diff --stat d09c537` over `services/settings`, `auth`, `services/scheduler/inventory.py`, `services/inventory` and `api/agent/inventory.py` is empty. M9 adds no setting, role, schedule kind or inventory code path. In `repositories/jobs.py`, the only change is that the pull no longer filters `kind`.
- **Route checks:** the route walk (G34) and `test_security_m9.py::test_no_m9_route_takes_command_text_or_names_inventory` find no M9 path, parameter or body property naming inventory, disable or skip. Every M9 body is closed.
- **Behaviour:**
  - a compliance scan, a newer scan and a cancel leave each agent's inventory job state unchanged (CHK-M9-155, -185);
  - inventory jobs still fail after 30 min and are never retried (CHK-M9-211);
  - the results route refuses an inventory job id, and the inventory route refuses a compliance job id (CHK-M9-229);
  - the M3 inventory suites (G33) are green.

#### REQ-228 (2), compliance-present run

`test_sweep_compliance_pg.py::test_offline_share_and_stale_inventory_with_compliance_rows_present` (in G68, green; added at the reviewer's request): 10 eligible agents with compliance jobs and results, 1 offline. `agents_offline` fires once with offline 1, eligible 10. `inventory_stale` names exactly the online agent whose `last_inventory_at` is older than twice the interval. Compliance results do not count as inventory.

#### M9 mutation table (CHK-M9-320 to -382)

Each row was planted in a throwaway copy and went red on its gate. Evidence is in the TASK report named; rows run at the gate are marked **gate**. tm9 = tester-m9 (pure modules, G66/G67).

| CHK | Red in | Source |
| --- | --- | --- |
| 320 S, 321 S | G68 repo lock probes, G69 race (double rows, M8 double count) | TASK-195, 199 |
| 322 S | G68 (sibling rows, original↔retry rows; also the restriction-to-failed/partial variant) | TASK-195, 199 |
| 323 | G66 | tm9 TASK-190 |
| 324 S | G66 (tm9), G68 | TASK-190, 199 |
| 325 S | G66 (tm9), G68, G70 | TASK-186, 199, 204 |
| 326 | G66 | tm9 TASK-186 |
| 327 | G68 | TASK-199 |
| 328 S | G68, G70 | TASK-199, 204 |
| 329 S | G68 (catalog-change and snapshot rows) | TASK-199 |
| 330 S | G66 (tm9), G68 | TASK-190, 199 |
| 331, 332 | G66 (tm9), G68 | TASK-190, 199 |
| 333 | G68 | TASK-199 |
| 334 | G66 (tm9), G68 (repo `start` guard) | TASK-186, 195 |
| 335, 336, 337 | G66 | tm9 TASK-186 |
| 338 | G66, G67 | tm9 TASK-186 |
| 339, 340 | G68 (repo and sweep) | TASK-196, 202 |
| 341 S, 342, 345 | G68 | TASK-202 |
| 343 | G66 (tm9), G68 | TASK-189, 202 |
| 344 S | G68 (CHK-M9-209 end to end; the tm9 hand-over) | TASK-202 |
| 346 | G68 (repo and two-sweep race) | TASK-196, 202 |
| 347 S | G66 (tm9); **gate**: operator/expected added to the built plugins → 10 failed (G70 agent routes, G68 queue); G30 `operator` in `ComplianceJob` → 2 failed | TASK-189; gate |
| 348, 349 S, 350 | G66 | tm9 TASK-189 |
| 351 S | G66 (tm9), G68 | TASK-189, 198 |
| 352 S, 353 S | G68, G69 (delete race) | TASK-193, 198 |
| 354, 355, 356 | G68 | TASK-193 |
| 357 | G68 | TASK-198 |
| 358 | G68 | TASK-193 |
| 359 | G68 | TASK-194, 200 |
| 360 | G66 (tm9), G68 (cancel derive) | TASK-187, 200 |
| 361 | G68 (repo grouped by `job_id`; the tm9 hand-over) | TASK-194 |
| 362 | G66, G67 | tm9 TASK-187 |
| 363 | G68 | TASK-194, 202 |
| 364 S, 365 S | G70 | TASK-205 |
| 366 S | G68, G70 | TASK-198, 205 |
| 367 | G66 (tm9), G70 (store bypassed) | TASK-192, 205 |
| 368, 369 | G66 | tm9 TASK-191 |
| 370 | G66 (tm9), G68 (5 Kolkata rows) | TASK-191, 201, 203 |
| 371, 372 | G68 | TASK-203 |
| 373 | G68 (repo `SKIP LOCKED` row) | TASK-197, 203 |
| 374 | G68 (commit-failure row; duplicates-counted variant) | TASK-199 |
| 375 S | G68 canary row | TASK-199 |
| 376 S | G1 (5 repositories) | TASK-193 to 197 |
| 377 S | G68 (`InsufficientPrivilege` surfaces) | TASK-196 |
| 378, 379 S, 380 | G70 | TASK-204 |
| 381 S | G68 (all three guards dropped) | TASK-193, 198 |
| 382 S | G70; **gate**: G69 (the route-schema check sees an open body) → 2 failed | TASK-205; gate |

**63/63 rows red** (the 24 security rows included), plus the tester extras CHK-M9-383 to -393 (tm9) and my per-task extras. The extras include, for example:
- 322-fp;
- 197r1 share/skip;
- 201 share/enable/nul/deleted;
- 202 deleted/decommissioned/unchanged/per-job savepoint;
- 203r1 (`DeadlockDetected` with a plain `FOR SHARE`);
- 206 role/extra keys.

All red.

Plants that stayed green, and why (no defect):
- 334s: the service only calls `start` for a dispatched job, so the guard is defence in depth; the repo plant is red.
- 374, first try: my fault test raised before the counter step, so the commit-failure test was added and went red.
- 381 as first written: a third guard, `scan_id <>`, still held.
- 373 at service level: the waiting tick re-checks the row, so the repo row shows it.

#### G5 plant

Throwaway copy `/root/bstest-m9b-mut-G5` (removed after the run), web build present, `CI=true`, `-n 2`, `pytest --cov --cov-report=term --cov-fail-under=85` (the CI command's floor):

| Run | Plant | Result |
| --- | --- | --- |
| p1 | 920 never-called statements in `services/jobs/intake.py` (`_untested_g5_plant`) | 11,166/11,166 passed. `intake.py` 1,002 statements, 920 missed (8.18 %). **TOTAL 6,698 / 1,005 missed = 85.00 % as printed**: the raw value is 5,693 / 6,698 = 84.99 %. pytest-cov printed "FAIL Required test coverage of 85% not reached. Total coverage: 85.00%", but **the process exited 0** |
| control | `--cov-fail-under=85` on one file (1.07 %) | exit 1 with `-n 0` and `-n 2`: the floor does fail the run normally |
| p2 | 1,000 never-called statements in `intake.py` (5,692 / 6,777 = 83.99 %), clear of the rounding boundary | **RED**: 11,166/11,166 passed. `intake.py` 1,082 statements, 1,000 missed (7.58 %); **TOTAL 6,778 / 1,085 missed = 83.99 %**; "FAIL Required test coverage of 85% not reached. Total coverage: 83.99%"; **exit 1** (25 min 57 s). The copy was removed and no containers were left |

**Observation for `main`** (tooling, not M9 code; no gate lowered): at a coverage of 84.99 %, which prints as 85.00 % at two decimals, pytest-cov 7.1.0 prints FAIL but exits 0. So the CI floor (`.github/workflows/manager.yml` L140) passes a run that is under 85 % by less than 0.005 points. p1 was sized at the boundary on purpose; it found this. The M9 tree itself is at 98.53 %, far from it.

#### NOT RUN at the M9 gate (by design)

- A real runner executing plugins and redacting: **M10**.
- The nightly end-to-end scan → results on VMs, the read views, CSV, the re-evaluation route and scan retention: **M11**.
- Load tests: deferred by the user. CI (GitHub Actions): not run here (no push).
- G7 to G15, G17, G35 to G41: not re-run; M9 changes no agent, unit, package or web source file other than the generated `schema.d.ts`, which G16 covers.
- `tests/m9/report.md`: the harness refused my write of a file named `report.md`. Its content (the per-task table, the old → new list, the security rows) is in this file and the TASK reports, for `main` to fold.
