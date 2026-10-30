# TASK-208 TEST: PASS

Tester: tester-m9, 2026-10-30. Low risk (docs; batched with TASK-207). REQ-233; TS §4.4, §6.2 L1119, L1122, L1124, §6.4. Under test: `README.md` (impl-manager-m9b, `work/reports/TASK-208-impl.md`: the new "## Scans" and "### Schedules" sections, the Agent API results row and the "Compliance jobs and results" bullets, the metrics list and the Scheduler section), against the M9 tree at the time of the run (TASK-205 r1 included). Test file (new): `manager/tests/test_readme_m9_walk_linux.py`. Plan rows: CHK-M9-285 to -287.

## How it was walked

A real `bitscan-manager serve` over HTTPS on its own migrated PostgreSQL 16, with the fake OpenBao and audit sink and a temporary bits folder (the M5/M7 walk harness), on the **real clock**: the scheduler ticks every 30 s and `offline_sweep` runs every 60 s. The walk sets up:
- the admin through `users create-admin`, then a TOTP session and an API token;
- an operator and a viewer through `POST /users`, and an operator `bsk_` token;
- three folder policies (enabled, disabled, another one) and one uploaded and then deleted policy;
- four agents enrolled through `POST /agent/enroll` (three auto-approved, one held), tagged through `PUT /agents/{id}/tags`;
- agent pulls and result posts with their own `bsa_` tokens.

Every expected value is the README's text. The database is only read, as owner, to observe job, scan, result and audit state. Each documented step is one row; the test fails if any row differs.

## Runs

| Run | Command (W, copy `/root/bstest-m9-walk` of the current tree + README, venv `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_readme_m9_walk_linux.py` | 1 failed in 10 s: `SSLEOFError` sending the over-1 MiB body. **Test bug**: the server answers 413 from the declared length and closes while `http.client` is still sending. A `post_big()` helper now sends like curl, tolerates the early close and reads the answer |
| r1 | same | 1 failed (190 s), 87/88 rows matched. **Test bug** in the row "a job keeps the commands it was built with": A1's pull also returned the other profile's queued job, which the walk had queued on purpose, so there were 2 compliance jobs. The pulled jobs are now filtered to the main profile's checks |
| r2 | same | **1/1 passed** (188 s), 0 failed, 0 errors, 0 skipped. **88/88 README rows** as written |
| static (L) | ruff check, ruff format --check, mypy --strict on the test file | clean |

## Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-285 | APP | W | r2 | PASS | 88/88 rows. **Starting:** the 202 body has exactly `jobs, policy_version, scan_id, state`, queued, at the profile's version, `jobs` = hosts; tags match any (the held host is left out); unknown agent ids are left out; `all` = every host not awaiting approval; the scan records the request, `resolved_agents` and the version. **Idempotency-Key:** a repeat returns the same 202 with no second scan and no second `scan.create`; another body → 409; 256 characters → 400. **Alert:** an API-token all-hosts scan carries `all_hosts_scan_api_token` on its `scan.create` entry, and a session scan does not; one `scan.create` per scan. **Refusals, nothing written:** an empty or two-form target 400 (detail `Invalid request: target…`), another key (`execute`) 400, unknown 404, disabled 409, deleted 409, no eligible host 422, a body over 1 MiB 413; a viewer 403. **One job per host:** the earlier scan's queued jobs are cancelled with `finished_at`; another profile's queued job and every inventory job are untouched; a handed-out job keeps running. **Commands fixed when queued:** a job queued before a re-import keeps `cat /etc/hostname`; a scan after it has version + 1 and the new command. **Agent side:** a pull returns inventory and compliance jobs together, with exactly the six job keys and `{plugin_uuid, execute, timeout_s}`, and no expected value or operator; an empty batch is the start notice (running, `started_at` and `deadline_at` set), and a second changes nothing; `{1, 0}`, then `{0, 1}` for a repeat; a batch naming a foreign check → 409 `job_not_acceptable`, nothing stored; U+0000 stored as U+FFFD; 65,537 bytes stored as ERROR `oversize` with `''` texts; job completed; `bitscan_plugin_results_total` exports PASS/FAIL/ERROR (ERROR ≥ 1); the scan becomes completed and finished within the documented lag. **Cancel:** 200 with exactly `{scan_id, state, cancelled_jobs}`, 2 cancelled, state cancelled; the handed-out job's results → 409; cancelled queued jobs are not pulled; again → 0; one `scan.cancel` per cancel (2); unknown 404; unhyphenated id 400; viewer 403. **Schedules:** the README example → 201 with exactly the ten item keys, enabled, `next_run_at` in the future; `timezone` defaults to UTC; weekday 0 and 7 give the same Sunday 03:00Z; a disabled profile is accepted; a viewer gets 403 on list and get; the list is ordered and paged by `limit`/`cursor`; get one; PATCH `cron` recomputes `next_run_at` (Monday 04:00 London); `policy_id` → 400; `{}` → 400; another operator's `{enabled: false}` → 200; 11 refusals (both day fields, `@daily`, a seconds field, never fires, 65+ characters, an unknown or too long zone, an empty or 129-character name, a bad target, `execute`) → 400; a 128-character name accepted; DELETE 204 then 404; deleting a profile disables its schedule; a deleted profile's schedule can be neither created nor enabled (409); one `scan_schedule.*` entry per create/change/delete (5/3/1). **Runs (real clock):** an every-minute `{all: true}` schedule created with an API token queued a `scheduled` scan with `requested_by` NULL, actor `system`, no alert, and set `last_run_at`. Skips were logged `scheduled run skipped` with the schedule id and `policy_disabled`, `no_target_agents` and `previous_unfinished`; they queued nothing. The scan of a deleted schedule is kept with `schedule_id` NULL | 2026-10-30 |
| CHK-M9-286 | CODE | W, L | r2; `git diff README.md` scan | PASS | The Scans + Schedules text has no `bs?_` token shape, no "password", no TASK/REQ/CHK id, no tester/impl/planner name and no milestone name. The whole README diff has no token, no host path and no process note (the only "password" is the existing `/auth/password` route name) | 2026-10-30 |
| CHK-M9-287 | CODE | W | r2 | PASS | The README says the results routes are "not part of this version yet"; Idempotency-Key entries are kept "in memory, for 24 hours" and "forgotten when the manager restarts"; the scan state can lag (`offline_sweep`); `### Schedules` sits inside `## Scans`. Each matches the spec values (#123 (c), #127 (f)) | 2026-10-30 |

## Not walked (reason), covered elsewhere

- Deadlines, the single retry, the 24 h never-started rule, the 7-day late window and "no back-fill" need hours of real time. They are tested with clock control on PostgreSQL (TP-M9-14, -15: CHK-M9-197, -204 to -210, tester-m9b).
- A decommissioned host's exclusion needs `decommission_after_days` of real time (CHK-M9-110, tester-m9b).
- The skip reasons `policy_has_no_plugins` and `invalid` cannot be produced through the API (they need an owner write).

## Observations for the README owner (not failures)

- "A job past its deadline ends `partial` or `failed`": by #127 (b) a job whose every check already has a result ends `completed` at the deadline. This edge cannot follow from a final batch, so the wording is fine for users. Noted only.
- DST is not described. The user's decision (shift the gap, run the repeat once; TASK-191 r1) could be added in one line, and it also means a sub-hourly schedule has no run in the repeated hour. That is for impl-manager-m9b and `main` to decide; it is not required by REQ-233.
- The awaiting-approval host's `PUT /agents/{id}/tags` was recorded only (the README makes no claim about it).

## Round 2 (TASK-208 r1, 2026-10-30): PASS

impl-manager-m9b's r1 adds two README lines (README sha256 `9fe42ce43caff550…`): the DST sentence in the `### Schedules` `timezone` bullet (L488), and "(or `completed` if every check already has a result)" in the deadline bullet of "How a scan proceeds" (L466). The walk gains two rows for them; the earlier 88 rows are unchanged.
- **DST row:** the three statements are in the Schedules text (a time skipped in spring runs just after the jump; a time in the repeated hour runs once, at its first occurrence; a sub-hourly schedule makes no runs in the repeated hour). Each is checked against the manager's `next_fire` on the Europe/London 2026 transition days, the user decision as pinned by TASK-191 CHK-M9-071: `30 1 * * *` → 03-29 01:30Z, then 03-30 00:30Z; → 10-25 00:30Z only, then 10-26 01:30Z; `*/30 * * * *` → 00:00, 00:30, 02:00, 02:30Z on 10-25 (no 01:00Z or 01:30Z). PASS.
- **Deadline row:** the text says a job past its deadline ends `partial` or `failed` "(or `completed` if every check already has a result)", and that only "a `partial` or `failed` one gets **one** retry" (#127 (b), #126 (c)). PASS.

| Run | Command (W, a fresh copy of the current tree + the r1 README, `/root/venv-m9`, `CI=true`, `-n 0`) | Count |
| --- | --- | --- |
| r3 | `pytest tests/test_readme_m9_walk_linux.py` (the walk is one test, so it was run whole) | **1/1 passed** (190 s), 0 failed, 0 errors, 0 skipped; **90/90 rows** as written |
| static (L) | ruff check, ruff format --check, mypy --strict on the test file | clean |

Remaining note (not a failure): the **Scheduler** section bullet (README L612) still reads "Compliance jobs past their deadline end `partial` or `failed`". It is a short summary that points to Scans, where the full rule is now stated. Noted for impl-manager-m9b only.

## Type fix (2026-10-30, before the M9 gate)

`mypy --strict --config-file manager/pyproject.toml --platform linux` found 7 errors in `manager/tests/test_readme_m9_walk_linux.py`. On Windows the module-level `pytest.skip` makes mypy skip the body, so the default local run had looked clean. They were fixed test-side only, keeping every assertion:
- `ans` is checked for `None` before `.get`;
- the skip-poll lambda is now `functools.partial(skipped, sched, reason)`;
- the final failed-row list is renamed `failed_rows`, because `bad` was already the loop variable of the PATCH refusals.

| Run | Command | Count |
| --- | --- | --- |
| mypy (L) | `mypy --strict --config-file manager/pyproject.toml --platform linux manager`, and the default form | this file clean in both. Re-check after tester-m9b's current `test_sweep_compliance_pg.py`: **whole tree clean, 385 files, both forms** (the earlier 2 errors there came from an older copy of that file) |
| ruff (L) | `ruff check`, `ruff format --check` on the file | clean |
| r4 (W) | `pytest tests/test_readme_m9_walk_linux.py` in a fresh copy of the current tree | **1/1 passed** (189 s), 0 failed, 0 errors, 0 skipped; 90/90 rows |
