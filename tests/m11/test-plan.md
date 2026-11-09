# M11 test plan (results and end to end)

Owners: **tester-m11** (manager: pure modules, PostgreSQL, routes, security suite, retention, wiring, docs walks and the manager gate rows; TP-M11-00 to -13, -15, -16, -21 to -24), **tester-m11e** (end to end and N / N−1: TP-M11-17 to -20, the harness plants CHK-M11-370 to -374) and the web tester for the batched UI waves (TP-M11-07, -14; CHK-M11-260 to -289, plants -360 to -366). Written 2026-11-08 by tester-m11 from `work/tasks.md` "M11 results and end-to-end" (TASK-232 to TASK-254 acceptance tests, design notes D1 to D4, TP-M11-00 to -24, the gate G1 to G87, the mutation table CHK-M11-320 to -374, the coverage matrix), `work/requirements.md` REQ-264 to REQ-292, the plans `work/plans/TASK-232.md`, `TASK-235.md`, `TASK-242.md`, the approved answers in `work/open-questions.md` "M11" (#144 to #154, PD-46 to PD-51; #3, #9, #12, #28, #39, #44, #74, #84, #89, #118 to #120, #122, #127 (f) reused) as approved by the user on 2026-11-08 (`work/decisions.md`: every recommended answer, N / N−1 both ways, #151 no index in v1, #148 no alert, #152 (b) standing VM approval), the lead's two plan corrections of 2026-11-08 for TASK-237 and TASK-242 (the tokens step's future-row probe reads `user_token.created_at`; `scan_chunk` takes no row lock), and the spec (TS §2.1 L101–L105, §2.2 L114, §2.3 L138, §4.3 L552–L553, §4.4 L557–L585, §4.5 L589–L605, §5.2 DDL and grants, §5.3 L1045–L1054, §6 L1058–L1066, §6.2 L1083–L1131, §6.3 L1133–L1144, §8.1, §8.3 L1277–L1285, §8.4, §8.6 L1309, §8.7 L1348–L1350; SR §1.1). Written **before any M11 product code was read**. Names below are the interfaces of the plans' §2 to §5; where the code names something differently the row keeps its expected value and the task report says which name it bound to. Results go to [report.md](report.md) (folded from `work/reports/TASK-###-test.md`).

`bm/` means `manager/bitscan_manager/`; `mt/` means `manager/tests/`; `wb/` means `web/src/`.

## Conventions

- Type: **CODE** = static gate, unit or property test on the tree (no database). **APP** = the real code against a real PostgreSQL 16 through the Testcontainers harness (M1 bootstrap from TS §5.2, then `bitscan-manager db migrate`), or through the real routes of `create_app`.
- Where: **L** = Windows 11 + Git Bash, worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m11` (ruff, `ruff format`, `mypy --strict`, web lint and typecheck only). **W** = WSL2 Ubuntu 24.04 (`wsl -d Ubuntu-24.04 -u root`); tester-m11 works in `/root/m11t` (`tree/` copied without `.venv`, `node_modules`, caches; `venv/` installed with `pip install --require-hashes -r manager/requirements-dev.txt`, then `pip install --no-deps -e tree/manager`), `CI=true` (nothing skipped), pytest-xdist with one PostgreSQL container per worker, every run under `timeout`. **Python tests run on W only.** **CI** = GitHub Actions only.
- PostgreSQL rows connect as `bitscan_app` for the read path and `bitscan_retention` for retention. Scans, jobs, results, re-evaluations, inventory, enrolment, token and audit rows the code under test reads but does not write are written by the test as **owner** (`bitscan_migrate` + `SET ROLE bitscan_owner`), never as a superuser, through the TP-M11-01 builder (`mt/m11_pg_fixtures.py`).
- **Row checksum** = `md5(string_agg(t::text, '|' ORDER BY <pk>))` per table, read as owner. "Unchanged" = equal checksums.
- **Canaries** (four, so a legitimate appearance is never confused with a leak): `OUT` in stdout and `ERR` in stderr (must reach operator and admin results only), `EXEC` in `execute` and `EXP` in an expected value (catalog content: allowed in every role's results items and CSV rows, #144 (a); never in a scan list or detail item, a log record, an exception, a problem detail or an audit detail), plus the callers' tokens. "Leaves no trace" = absent from every `caplog` record (message, args, every attribute), `capsys` out/err, every raised exception's chain (`canary.sweep`), every audit `detail` and every answer it is not allowed in.
- **Time** is never waited out (decisions 2026-10-26): pure functions take the instant; services take `now` or the clock double; the sink outage is moved by the clock. **Races** use two sessions at a held lock or a `threading.Barrier`, with a lock-wait probe on `pg_locks` polled at 20 ms with a 10 s bound; never a sleep for ordering.
- Retention rows use the **real current instant** as `now` (the clock check compares the manager clock with the database's `now()`), and every aged row is placed relative to that same `now`.
- **Planted violations** are made in a throwaway copy (`/root/m11t/mut-<chk>` on W; `$TEMP/m11t-mut-<chk>` on L for ruff and mypy rows), never in the worktree. The unmodified copy is green first. "Red" = non-zero exit **and** the named test fails for the planted reason. A copy is deleted after its row is recorded.
- **Results are totals**: `passed/total`, plus failed, errors, skipped. A failing test is re-run alone by node id after the fix, as its own row (`1/1 passed`).
- Every expected value comes from the spec or an approved answer, never from the implementation. A behaviour the spec leaves open is **recorded, not asserted**, and goes to `main` under "Questions".
- Secrets: no token, password or DSN is printed or saved; `bs[uaek]_` strings are masked in every row.

## Expected values (spec and approved answers)

| Item | Expected | Source |
| --- | --- | --- |
| Scan item keys | exactly `scan_id, policy_id, policy_name, policy_version, trigger, schedule_id, requested_by, state, target_kind, resolved_count, created_at, finished_at`; `state` = `scan.state` as stored; `target_kind` ∈ `agents`, `tags`, `all`; `resolved_count` = length of the stored `resolved_agents` | #145 (a); plan TASK-232 §4 |
| Scan list | newest first (`created_at` desc, then `scan_id` desc); `limit` 1–500, default 50; cursor holds `scan_id` only; filters AND: `policy_id`, `agent_id` (stored `resolved_agents` holds it), `state` (the six scan states), `created_after` (≥, inclusive), `created_before` (<, exclusive), RFC 3339 with an offset | REQ-264; TS §6.3 L1136; #89, #145 (a), (d) |
| Scan states (filter) | `queued`, `running`, `completed`, `partial`, `failed`, `cancelled` (M9 `ScanState`); anything else 400 | REQ-264; TS §4.4 L582 |
| Scan detail | the item + `target` (as requested, no `resolved_agents`) + `hosts`: one per agent with an original job, ordered by hostname then `agent_id`; host keys exactly `agent_id, hostname, jobs, passed, failed, errors, not_run, score`; job keys exactly `job_id, state, retry_of, dispatched_at, started_at, finished_at`, original first then its retry | #145 (b); REQ-265 |
| Score | passed ÷ (passed + failed), unrounded, in [0, 1]; null when passed + failed = 0; ERROR and Not run excluded; counts use the effective verdict (latest `reeval_id`, else the original) over the unit (original + retry, once) | TS §4.5 L604, L603; #119, #120 (a); M8 `score.host_score` |
| Result item keys (viewer) | exactly `agent_id, hostname, job_id, retry, plugin_uuid, plugin_name, result, eval_detail, original_result, original_eval_detail, reeval_policy_version, reevaluated_by, reevaluated_at, operator, expected, execute, exit_code, timed_out, truncated, started_at, finished_at, received_at` (22); **no** `stdout` / `stderr` key | #144 (a), (b); plan TASK-232 §4 |
| Result item keys (operator, admin) | the 22 + `stdout`, `stderr` (24), for a session or an API token alike; the role is the caller's current role | #144 (b); TS §6.2 L1083, L1123 |
| Result items | one per plugin of each host's **original** job payload, in payload order; the unit's stored result if any (from the original or the retry: `retry` true iff it came from the retry), else Not run (`result`, `job_id`, `original_*`, `exit_code`, flags and times null; `plugin_name`, `operator`, `expected` from the original job's `eval_spec`, `execute` from the payload); `result` = effective, `original_result` = stored; `reeval_*` null when never re-evaluated; ordered by `agent_id`, then payload position; cursor `[agent_id, position]`; filters `status` ∈ `PASS`, `FAIL`, `ERROR`, `NOT_RUN` (on the effective result) and `agent_id`, AND | #144 (a), (c)–(e); REQ-267; TS §4.4 L585 |
| Results CSV | header, in order: `hostname, agent_id, plugin_uuid, plugin_name, result, eval_detail, original_result, original_eval_detail, reevaluated_at, reeval_policy_version, exit_code, timed_out, truncated, started_at, finished_at, job_id, retry`, then `stdout, stderr` for operator and admin only; null → empty cell; booleans `true` / `false`; times RFC 3339 UTC; every cell (header too) through M5 `escape_cell`, then RFC 4180 quoting; UTF-8, no BOM, CRLF; `Content-Disposition: attachment; filename="scan-<scan_id>-results.csv"`; ≤ 100,000 rows, else 400 `invalid_request` "Invalid request: more than 100000 rows; narrow the filters" before any CSV byte | #146; #84; TS §6.3 L1144 |
| Formula triggers | a cell starting with `=`, `+`, `-`, `@`, a tab, a CR, or whitespace followed by one of these gets a leading `'` | TS §6.3 L1144; security invariants |
| Re-evaluate | `POST /api/v1/scans/{id}/reevaluate`, no body read, `require_totp_session()` (admin, TOTP-verified session, sink gate); 200 exactly `{scan_id, policy_id, scan_policy_version, policy_version, rows_added, not_in_version}`; 404 `not_found` unknown; 409 `conflict` "The policy is deleted."; 400 malformed id; one `scan.reevaluate` audit entry, no alert | REQ-270; #147, #148; TS §6.2 L1086, L1125 |
| Auth refusals | no token, revoked token, `bsa_` or `bse_` on a user route → 401 `unauthorized`; viewer or operator on an admin route → 403 `forbidden`; admin API token on a TOTP-session route → 403 `totp_session_required`; admin session without TOTP (restricted) → 403 `totp_enrolment_required`; sink outage ≥ 15 min on a sensitive route → 503 `audit_sink_unavailable` (14 min 59 s still accepted; accepted again after the drain) | TS §6, §6.2 L1083–L1093, §5.3 L1053; M2 |
| Path ids | `/scans/{id}…`: hyphenated UUID (any letter case), else 400; `/agents/{id}/scans`: unknown or not a UUID → 404 `not_found` | plan TASK-232 §3, §7; REQ-265 (3), REQ-266 (2) |
| Retention cutoffs | scans `created_at < now − 400 d`; snapshots `collected_at < now − 180 d`; requests `decision IS NOT NULL AND decided_at < now − 90 d`; tokens `expires_at < now − 90 d` (revoked or not); audit `at < now − 3 calendar years` (Feb 29 → Feb 28); inventory jobs `kind = 'inventory' AND finished_at < now − 30 d`; packages: no `agent_package` reference. Strict `<`: a row exactly at the cutoff stays | REQ-274; #150 (a)–(e) |
| Audit prefix | the highest id N such that every entry with id ≤ N has `at` < cutoff; N ≤ the shipper's cursor and N is a stored id; none when the cursor is None or nothing qualifies; at most 10,000 per chunk, each chunk with its own checkpoint | #150 (d); REQ-274 (2), REQ-276 |
| Checkpoint | one `audit.checkpoint` entry via `append_entry` (chain lock), actor `system`, target null, detail exactly `{last_deleted_id, last_deleted_row_hash, deleted}`, written **before** the delete in the **same** transaction; `verify_chain()` OK afterwards | TS §5.3 L1053; #39, #150 (d) |
| Chunks | scans 100, inventory jobs 1,000, snapshots / requests / tokens / packages 10,000, audit 10,000; one transaction per chunk | #150 (g) |
| Clock guards | no delete at all when the manager clock and the database `now()` differ by **more than** 5 min (5 min exactly: runs); a step is skipped when its table holds a row dated **more than** 1 day after `now` (probe columns: `scan.created_at`, `inventory_snapshot.collected_at`, `enrollment_request.decided_at`, `user_token.created_at` (lead correction 2026-11-08), inventory `scan_job.finished_at`) | #150 (j); REQ-278 |
| Re-evaluation lock | M8 `reeval.lock_scan`'s key (`hashtext('scan_reeval')`, `hashtext(scan_id::text)`) tried per scan; a held lock skips that scan until the next run; no row lock (`FOR UPDATE` needs UPDATE, which `bitscan_retention` lacks; lead correction 2026-11-08) | #150 (k) |
| Retention grants | `bitscan_retention`: SELECT on every table; DELETE on exactly `scan, scan_job, scan_result, scan_result_reeval, inventory_snapshot, enrollment_request, user_token, audit_log, package`; INSERT on `audit_log` only; USAGE on `audit_log_audit_id_seq`; no UPDATE anywhere | TS §5.2 L1003–L1006, §5.3 L1051 |
| Never deleted by retention | pending requests, compliance jobs of younger scans, `agent`, `os_info`, `agent_package`, `enrollment_token`, catalog (`family`, `policy`, `plugin`, `policy_plugin`, `bit_import`), `scan_schedule`, `setting`, `system_schedule`, `task`, `app_user` | REQ-275; G2 |
| Scheduler | four jobs `inventory`, `offline_sweep`, `scan_schedules`, `retention`; retention first run start + 10 min, then every `system_schedule.retention.interval_s` read at start-up (86,400 s if unreadable), at most one at a time, on the retention pool behind the stop flag | REQ-277; #150 (h) |
| Logs | retention: step names, counts, exception types only; no line, exception, problem detail or audit detail with stdout, stderr, `execute`, an expected value or a token anywhere in M11 | REQ-272 (4), REQ-277 (4); TS §5.3 L1054, §8.4 |

## Gate map

| Gate | Checks |
| --- | --- |
| G1–G4 ruff (S608, `re` ban), ruff format, mypy --strict, hashed locks | CHK-M11-310; plants -344, -345, -390 |
| G5 services coverage ≥ 85 % (incl. `services/retention`, the new `services/jobs` modules), W | CHK-M11-311; plant -391 |
| G6 OpenAPI byte-identical | CHK-M11-312; plant -392 |
| G16 web client regenerated with no diff | CHK-M11-313 |
| G18 full W run, 0 skipped, `-n auto` | CHK-M11-314 |
| G19 schema diff (no migration) | CHK-M11-315; plant -393 |
| G30, G33 agent contract suite; M3 sweep and inventory suites | CHK-M11-316 |
| G34 route walk with the six M11 operations | CHK-M11-317 |
| G37–G40 lintian, maintainer scripts, reproducible build, SBOM | CHK-M11-318 |
| G41 inventory chain against the real manager in W | CHK-M11-319 |
| G80 M11 unit suite | CHK-M11-001 to -079 |
| G81 M11 PostgreSQL integration | CHK-M11-080 to -199 (property rows on PostgreSQL included) |
| G82 M11 API suites | CHK-M11-200 to -239 |
| G83 M11 security suite | CHK-M11-240 to -259 |
| G84 M11 web suites | CHK-M11-260 to -289 |
| G85, G86, G87 nightly, N / N−1, workflow | CHK-M11-290 to -309 (tester-m11e) |

## TP-M11-01: PostgreSQL fixtures — `mt/m11_pg_fixtures.py`, self-test `mt/test_m11_fixtures_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-100 | APP | Owner-written catalog (family, policy, active plugins in `policy_plugin.sort_order`; re-import as a new version; soft delete) and scans in the stored M9 shape (`target` = request + sorted `resolved_agents`), jobs in **every** job state, originals and retries (`retry_of`), results with `job_created_at = scan_job.created_at` (the trigger accepts them) in **two** monthly partitions, re-evaluation rows with chosen `reeval_id` and `reevaluated_at`, intake ERRORs (`runner_unavailable`, `oversize` with empty streams), not-run plugins; the default partition stays empty | W |
| CHK-M11-101 | APP | Hosts with `<script>` hostnames; users of every role with a session and an API token, a restricted admin (no TOTP, unverified session), a revoked token, a demotable operator; `bsa_` and `bse_` tokens for the wrong-group rows | W |
| CHK-M11-102 | APP | The four canaries placed in stdout, stderr, `execute` (payload and snapshot) and an expected value (`eval_spec` and snapshot); the clock double; a statement spy recording the login role of every statement; a lock helper that holds M8's re-evaluation lock on a scan through M8's own `lock_scan` | W |
| CHK-M11-103 | APP | Aged retention rows on both sides of every cutoff relative to one `now` (exactly at, 1 µs past, well inside), including partitions created for the old months, inventory (`os_info`, `agent_package`, referenced and unreferenced `package`, snapshots), decided and pending requests, tokens (expired 91 d, 89 d, revoked not expired, live API token expiring in 300 d) | W |
| CHK-M11-104 | APP | An old audit chain written through M1's `append_entry` with chosen `at` values (ages old, old, new, old …) that `verify_chain()` accepts; a row-checksum helper sensitive to a one-byte change; grant probe helper (SQLSTATE `42501` or none) | W |

## TP-M11-02: results view and CSV units (TASK-233; REQ-267 to -269 at view level) — `mt/test_results_view.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-001 | CODE | `include_output(role)`: True for `operator` and `admin` only; False for `viewer`, `""`, `"Admin"`, `"root"`, any unknown string (fails closed) | W |
| CHK-M11-002 | CODE | `item(row, with_output=False)` has exactly the 22 viewer keys and **no** `stdout` / `stderr` key (not null: absent); `with_output=True` has exactly the 24 keys; values equal the row's (effective `result`, stored `original_result`, both equal when never re-evaluated) | W |
| CHK-M11-003 | CODE | A Not-run row maps to `result`, `job_id`, `original_result`, `original_eval_detail`, `exit_code`, `timed_out`, `truncated`, `started_at`, `finished_at`, `received_at`, `reeval_*` null, with `plugin_name`, `operator`, `expected`, `execute` from the row's planned values; `retry` false | W |
| CHK-M11-004 | CODE | `retry` true only for a result stored in the retry job | W |
| CHK-M11-005 | CODE | Each item validates against the TASK-232 response model chosen by the same flag (`ResultItem` / `ResultItemWithOutput`); a viewer item fed to the output model fails (keys absent) | W |
| CHK-M11-006 | CODE | `CSV_HEADER` equals the #146 (b) 17 names in order; `OUTPUT_COLUMNS` = (`stdout`, `stderr`); `CSV_MAX_ROWS` = 100,000 | W |
| CHK-M11-007 | CODE | `csv_text(rows, with_output=False)`: header line = the 17 names; no `stdout` / `stderr` column; the OUT and ERR canaries absent from the text; `with_output=True`: 19 columns and the canaries present | W |
| CHK-M11-008 | CODE | CSV cell forms: null → empty cell; booleans `true` / `false`; times RFC 3339 UTC parseable and equal to the instant; verdicts `PASS` / `FAIL` / `ERROR`; Not run `result` empty; UTF-8 text with no BOM; every line ends CRLF; parsed back with a strict RFC 4180 reader the rows equal the items | W |
| CHK-M11-009 | CODE | Formula escaping in **every** column (each of the 19 in turn): `=`, `+`, `-`, `@`, `\t`, `\r`, `" ="`, `"  +x"`, `"\t-1"`, `" \r@"` get a leading `'`; `a=b`, `1-2` with no leading trigger, an empty cell do not | W |
| CHK-M11-010 | CODE | RFC 4180 quoting of stdout holding commas, double quotes, LF and CRLF: quoted, quotes doubled, round-trips exactly | W |
| CHK-M11-011 | CODE | Every cell goes through M5's `escape_cell`: with `escape_cell` replaced by a recording double (monkeypatched on `csv_export`), it is called once per cell of the header and of every row; Python's `csv` module is not imported by `results_view` (AST) | W |
| CHK-M11-012 | CODE | Status parse: `PASS`, `FAIL`, `ERROR`, `NOT_RUN` accepted; `pass`, `Pass`, `NOTRUN`, `""`, `OK`, `ERROR ` raise `InvalidResultQuery`; its message names the parameter only (no value echo of a canary) | W |
| CHK-M11-013 | CODE | `<script>`, `<img src=x onerror=alert(1)>`, U+202E, U+FFFD in hostname, plugin name and stdout are returned verbatim in items and CSV (no HTML escaping server-side; plain text is the UI's job) | W |
| CHK-M11-014 | CODE | Purity: `results_view` imports only `csv_export`, the row type and the standard library (no `psycopg`, no repository, no `logging` calls); no `re` | W, L |

## TP-M11-05: retention rules (TASK-236; REQ-274, REQ-278 rule level) — `mt/test_retention_rules.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-040 | CODE | Constants: 400, 180, 90, 90, 30 days; 3 years; 5 min; 1 day; chunks 100, 1,000, 10,000, 10,000 | W |
| CHK-M11-041 | CODE | `cutoffs(now)` for each rule: the cutoff equals `now − age`; a timestamp exactly at the cutoff is **not** selected (`t < cutoff` false), 1 µs older is selected (REQ-274 (1)); checked for several `now` values incl. a DST-irrelevant UTC instant and a non-UTC aware `now` (same instant) | W |
| CHK-M11-042 | CODE | Calendar years: `now` 2029-03-01T00:00Z → audit cutoff 2026-03-01T00:00Z; 2028-02-29T12:00Z → 2025-02-28T12:00Z; 2028-02-28 → 2025-02-28; 2027-12-31T23:59:59.999999Z → 2024-12-31T23:59:59.999999Z; an aware non-UTC `now` gives the same instant as its UTC form (REQ-274 (3)) | W |
| CHK-M11-043 | CODE | Naive datetime raises `ValueError` in `cutoffs`, `minus_years`, `clock_doubt`, `future_rows` (REQ-274 (4)) | W |
| CHK-M11-044 | CODE | `audit_prefix`: ids 1–4 aged old, old, new, old → 2; all new → None; all old with shipped ≥ 4 → 4; gaps in ids (1, 5, 9 all old) → 9; shipped 1 → 1; shipped None → None; shipped between stored ids (ids 5, 8, shipped 7) → 5; shipped below the first id → None; empty input → None; `limit` 2 over four old → 2 (REQ-274 (2)) | W |
| CHK-M11-045 | CODE | `audit_prefix` boundary: an entry exactly at the cutoff stops the prefix; 1 µs older continues | W |
| CHK-M11-046 | CODE | `clock_doubt`: skew 5 min → False; 5 min + 1 µs → True; 5 min 1 s → True (REQ acceptance of TASK-236); both directions (manager ahead and behind); 0 → False | W |
| CHK-M11-047 | CODE | `future_rows`: newest None → False; `now + 1 d` → False; `now + 1 d + 1 µs` → True; `now + 2 d` → True; past rows → False | W |
| CHK-M11-048 | CODE | Purity: no I/O, no clock read (`datetime.now` / `time` not called: monkeypatched to raise), no logging; no `re` | W, L |
| CHK-M11-080 | CODE | Property (hypothesis): for random id-ordered sequences of (id, at) with gaps, random cutoff and cursor, `audit_prefix` returns the largest stored id N ≤ cursor with every entry ≤ N older than the cutoff, or None; never an id above the cursor, never an id after a not-old entry | W |

## TP-M11-03: scan reads repository (TASK-234; REQ-264 to -266, REQ-272) — `mt/test_scan_reads_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-105 | APP | World: two policies, scans in three states over two days with overlapping resolved targets (as bitscan_app reading owner-written rows). No filter: every scan, `created_at` desc then `scan_id` desc (two scans with equal `created_at` ordered by `scan_id` desc) | W |
| CHK-M11-106 | APP | Each filter alone (`policy_id`, `agent_id`, `state`, `created_after`, `created_before`) and all together return exactly the expected scans in order; `created_after` = a scan's `created_at` includes it, `created_before` = it excludes it | W |
| CHK-M11-107 | APP | Keyset: `limit` 2 visits every scan exactly once in order, under each filter set; the anchor is read by `scan_id` only | W |
| CHK-M11-108 | APP | `agent_id` filter uses a parameter in a JSONB containment test: an agent id embedded in a string elsewhere in `target` (e.g. a tag equal to the uuid text) does not match; a quote or `%` in a tag does not break the statement | W |
| CHK-M11-109 | APP | A deleted anchor (scan removed as owner after the first page) raises `AnchorGone` | W |
| CHK-M11-110 | APP | One scan by id: policy name and target (as stored) returned; a scan of a soft-deleted policy still returned; unknown id → None / not found | W |
| CHK-M11-111 | APP | A scan's jobs with hostnames: originals and retries, every job state, ordered as the detail needs (hostname, `agent_id`, original before retry) | W |
| CHK-M11-112 | APP | An agent's scans: exactly the scans whose stored `resolved_agents` holds it (3 of 5), newest first, `limit` 1 keyset visits each once; a decommissioned agent's history returned | W |
| CHK-M11-113 | APP | Statement spy: only SELECT statements (and the transaction control the pool issues); no write | W |
| CHK-M11-114 | APP | As bitscan_app: every function works with SELECT only (grants unchanged) | W |

## TP-M11-04: result reads repository (TASK-235; REQ-267, REQ-269, REQ-272, PD-46) — `mt/test_result_reads_pg.py`, `mt/test_results_property_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-118 | APP | REQ-267 (1): a scan with host A (original + retry; PASS, FAIL re-evaluated twice, ERROR `runner_unavailable`, a plugin answered only in the retry, a not-run plugin), host B (job queued: every plugin Not run), host C (all PASS): exactly the expected rows, `result` from the highest `reeval_id` (even when its `reevaluated_at` is earlier), `original_result` unchanged, both equal when never re-evaluated | W |
| CHK-M11-119 | APP | Results in two monthly partitions (retry created next month) both read; partition pruning not required for correctness | W |
| CHK-M11-120 | APP | Not run: name, operator, expected from the original job's `eval_spec`, execute from its payload, even after the catalog changed (plugin renamed, re-imported, retired) — never from the current catalog | W |
| CHK-M11-121 | APP | A plugin dropped from the current version and re-evaluated before it was dropped shows that earlier re-evaluation; an `oversize` intake ERROR with empty streams shows ERROR with its detail | W |
| CHK-M11-122 | APP | Filters alone and together: `status` PASS / FAIL / ERROR / NOT_RUN on the **effective** code (a FAIL re-evaluated to PASS is in PASS, not FAIL), `agent_id`; NOT_RUN gives only planned plugins without a result; `NOT_RUN` + an agent with nothing missing → empty | W |
| CHK-M11-123 | APP | Keyset `(agent_id, position)`: `limit` 2 visits every item once, in order, under each filter set | W |
| CHK-M11-124 | APP | Another scan's rows never appear: two scans sharing hosts, plugins and a job created in the same microsecond partition; a second scan's job with the same `(plugin_uuid)` and results | W |
| CHK-M11-125 | APP | Output variant: with `with_output=False` the statement returns no stdout / stderr content (NULL or absent) — the OUT and ERR canaries never leave the database for a viewer | W |
| CHK-M11-126 | APP | CSV read: same rows as the pages concatenated, no keyset; `LIMIT CSV_MAX_ROWS + 1` (100,001 planned rows give 100,001 back, 100,000 give 100,000) | W |
| CHK-M11-127 | APP | `read_only_snapshot()` is the first statement of the transaction; a write after it fails (`25006` read-only transaction); repeatable read: a result inserted by another session after the first page is not seen within the same snapshot | W |
| CHK-M11-128 | APP | `exists(scan_id)`: true / false; unknown scan distinguishable from an empty page | W |
| CHK-M11-129 | APP | PD-46: `repositories/results.py` byte-identical to `6efe0fb`; the page statement's text begins with `results._EFFECTIVE`'s text (composed, not copied) | W |
| CHK-M11-130 | APP | `EXPLAIN` of the page statement: `scan_result_reeval` scanned once (no SubPlan / correlated subquery over it) | W |
| CHK-M11-131 | APP | Spy: SELECT only; as bitscan_app | W |
| CHK-M11-082 | APP | Property, 200 random scans (seeded; originals, retries with only the missing plugins, random results, random re-evaluations incl. out-of-order `reevaluated_at`): every item's `result` equals M8 `score.effective()` for that unit and plugin, every `original_result` equals the stored code, and per-host counts of the items (PASS, FAIL, ERROR, Not run) equal `results.host_counts` | W |

## TP-M11-06 and TP-M11-22: retention repositories and grant probes (TASK-237, 238; REQ-275, -276, -278) — `mt/test_retention_repo_pg.py`, `mt/test_retention_grants_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-135 | APP | As bitscan_retention, each delete given a cutoff removes exactly the rows past it (strict `<`; the row at the cutoff stays) and at most one chunk (`n`) per call, returning its row count: inventory jobs (only `kind = 'inventory'`; a compliance job finished long ago stays; an unfinished inventory job stays), snapshots, decided requests (pending stay whatever `requested_at`), tokens (`expires_at`; revoked-not-expired stays; live API token stays), packages (only unreferenced) | W |
| CHK-M11-136 | APP | `scan_chunk(cutoff, n)`: ids of scans with `created_at < cutoff`, oldest first, at most `n`; takes **no** row lock (works as bitscan_retention; lead correction) | W |
| CHK-M11-137 | APP | `delete_scans(ids)`: one statement removes the scans, their originals **and** retries (self-reference), results in every partition, re-evaluation rows; a scan whose results partition was already dropped still goes; other scans untouched | W |
| CHK-M11-138 | APP | `try_reeval_lock`: true when free; false while another session holds M8's lock (through `reeval.lock_scan`); refuses autocommit (`RuntimeError`) | W |
| CHK-M11-139 | APP | `newest(table)` per probe column (scan `created_at`, snapshot `collected_at`, request `decided_at`, token **`created_at`**, inventory job `finished_at`); None on an empty table; the table / column come from a fixed mapping (an unknown name raises before SQL) | W |
| CHK-M11-140 | APP | `db_now()` equals the server's `now()` of the transaction | W |
| CHK-M11-141 | APP | Audit repo: `oldest(n)` returns `(audit_id, at)` in id order, at most `n`; `row_hash(id)` equals the stored hash; `delete_through(N)` removes exactly ids ≤ N; refuses autocommit | W |
| CHK-M11-142 | APP | As bitscan_app, every retention delete is refused by the grants (`42501`), incl. `delete_through` | W |
| CHK-M11-143 | APP | Token rows (lead correction (a)): with a live API token expiring in 300 days present, a token expired 91 days ago is deleted, one expired 89 days ago kept (repository level, given the cutoff) | W |
| CHK-M11-144 | APP | SQL shape: every statement parameterised (spy sees no literal cutoff, id or table name from input); no DDL | W |
| CHK-M11-150 | APP | Grant probes on a freshly migrated database (TS §8.3 L1280): bitscan_retention may DELETE from the nine tables (probed in a rolled-back transaction) and nowhere else: DELETE on `agent`, `policy`, `agent_package`, `os_info`, `enrollment_token`, `setting`, `family`, `plugin`, `policy_plugin`, `scan_schedule`, `system_schedule`, `app_user`, `task`, `bit_import`, `agent_tag`, `agent_ip_seen` refused (`42501`) | W |
| CHK-M11-151 | APP | bitscan_retention: INSERT only on `audit_log` (INSERT on `scan`, `scan_result`, `package` refused); no UPDATE on any table (`UPDATE scan`, `UPDATE audit_log` refused); USAGE on `audit_log_audit_id_seq` | W |
| CHK-M11-152 | APP | Lead correction (a) of the second note: as bitscan_retention, `SELECT scan_id FROM scan … FOR UPDATE` (and `FOR UPDATE SKIP LOCKED`) fails with permission denied (`42501`) | W |
| CHK-M11-153 | APP | A newly created `scan_result` partition (as owner, after the migration): bitscan_retention can delete its rows through the parent, can SELECT it; bitscan_app cannot delete through the parent, the default partition or the new partition | W |
| CHK-M11-154 | APP | DDL refused: bitscan_retention cannot `DROP TABLE` a partition or `TRUNCATE` a retention table | W |

## TP-M11-08: scan views service (TASK-240; REQ-264 to -266) — `mt/test_scan_views_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-155 | APP | REQ-265 (1): a host with PASS, FAIL, ERROR and not-run plugins gets `score` = passed ÷ (passed + failed) exactly, `errors` and `not_run` beside; an all-ERROR host → null; a queued host → null with `not_run` = every plugin; a FAIL re-evaluated to PASS counts PASS; a retry's results count once with the original's | W |
| CHK-M11-156 | APP | REQ-265 (2): for 50 random scans every host's counts and score equal M8 `scores.scan_host_scores()` | W |
| CHK-M11-157 | APP | Hosts ordered by hostname then `agent_id` (two hosts with the same hostname); each host's jobs: original first, then its retry; job fields as stored | W |
| CHK-M11-158 | APP | The returned state equals `scan.state` even when a derivation from the jobs would differ (stored `running` with every job completed) | W |
| CHK-M11-159 | APP | REQ-265 (4): a scan of a soft-deleted policy is returned; REQ-265 (5): a late result, then a re-evaluation, each change the next answer | W |
| CHK-M11-160 | APP | One read-only snapshot: a result committed by another session between the jobs read and the counts read is not half-seen (barrier inside the service's transaction) | W |
| CHK-M11-161 | APP | `ScanNotFound` for an unknown scan; `agent_scans` raises `AgentNotFound` for an unknown agent; a decommissioned agent's scans returned (REQ-266 (3)) | W |
| CHK-M11-162 | APP | `list_scans` with every filter, keyset and `AnchorGone` passed through; the `target` returned without `resolved_agents` | W |

## TP-M11-09: results service (TASK-241; REQ-267 to -269) — `mt/test_results_read_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-165 | APP | `results_page(role=viewer)`: items without `stdout` / `stderr` keys, the OUT and ERR canaries absent from every page and filter; `role=operator` / `admin`: present; the role argument alone decides (no token kind parameter) | W |
| CHK-M11-166 | APP | Paging: `limit + 1` read, `next_cursor` only when a further item exists; last page's cursor None; REQ-267 (1)–(4) hold through the service | W |
| CHK-M11-167 | APP | `results_csv`: rows equal the JSON items for the same filters (both verdicts); a viewer's CSV has no stdout / stderr column; operator's has them with the canaries | W |
| CHK-M11-168 | APP | Cap: 100,000 rows export; 100,001 raise `TooManyRows` before any text is built (`csv_text` not called: spy) | W |
| CHK-M11-169 | APP | Unknown scan → `ScanNotFound` for both; read-only snapshot used for both (spy: the first statement of each transaction) | W |
| CHK-M11-170 | APP | Canary: no log record, exception text or return value other than the allowed item fields holds a canary; caplog at DEBUG | W |

## TP-M11-10: retention service with clock control (TASK-242; REQ-274 to -278) — `mt/test_retention_pg.py`, `mt/test_retention_race_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-175 | APP | REQ-275 (1): one run over the aged world deletes exactly the expired rows of every rule; a deleted scan leaves none of its jobs, results (any partition) or re-evaluation rows; a 399-day scan and a scan exactly 400 days old are whole | W |
| CHK-M11-176 | APP | REQ-275 (2): every retention statement runs with login role bitscan_retention (spy on the retention pool); the app pool is not used (its `transaction()` not entered); `current_user` read inside the run is `bitscan_retention` | W |
| CHK-M11-177 | APP | REQ-275 (3): a fault injected in one chunk (the second scans chunk) rolls back only that chunk; the first chunk's deletes stay; the step is logged as failed (step, exception type) and the later steps run; the next run finishes the work | W |
| CHK-M11-178 | APP | REQ-275 (4): a pending request, a token expired 89 days ago and a revoked token not yet expired remain; lead correction (a): with a live API token expiring in 300 days, a token expired 91 days ago is deleted and one expired 89 days ago kept | W |
| CHK-M11-179 | APP | REQ-275 (5): an unreferenced package deleted, a referenced one kept; an inventory upload (M3 `ingest`) after the prune stores the package again | W |
| CHK-M11-180 | APP | REQ-275 (6), G2: every agent's `os_info` and `agent_package` rows unchanged; checksums of `agent`, `enrollment_token`, catalog tables, `scan_schedule`, `setting`, `system_schedule`, `app_user`, `task` unchanged | W |
| CHK-M11-181 | APP | Chunking: 250 expired scans take three chunks (100, 100, 50) in three transactions; 2,500 inventory jobs three chunks (1,000, 1,000, 500); `StepResult` counts and chunks equal | W |
| CHK-M11-182 | APP | REQ-276 (1): 10 expired and 5 recent entries: 10 deleted, one checkpoint naming id 10 and its `row_hash`, `deleted` = 10, actor `system`, target null; `verify_chain()` OK; a second run deletes nothing and writes no checkpoint | W |
| CHK-M11-183 | APP | REQ-276 (2): an expired entry with an id above a recent one stays (prefix only) | W |
| CHK-M11-184 | APP | REQ-276 (4): a fault after the checkpoint insert (in the delete) leaves every entry in place and no checkpoint; the chain verifies | W |
| CHK-M11-185 | APP | REQ-276 (5): an expired entry above the shipper's cursor stays until the cursor passes it; cursor None → no audit delete | W |
| CHK-M11-186 | APP | REQ-276 (6): 25,000 expired entries take three chunks and three checkpoints (10,000, 10,000, 5,000); the chain verifies after the run; each checkpoint's `last_deleted_id` is the last id of its chunk | W |
| CHK-M11-187 | APP | Checkpoint before the delete in the same transaction: the checkpoint's `audit_id` is greater than every deleted id and committed with the delete (no checkpoint without delete, no delete without checkpoint); the shipper's wake is called after commit (on_commit) | W |
| CHK-M11-188 | APP | REQ-278 (1): the manager clock 1 h ahead of the database → nothing deleted in any step and exactly one `clock_doubt` log line; 5 min ahead → runs | W |
| CHK-M11-189 | APP | REQ-278 (1): a scan dated 2 days ahead → the scans step skipped, the other steps run; lead correction (b): a token whose `created_at` is 2 days ahead → the tokens step skipped while the other steps run; likewise snapshots, requests, inventory jobs | W |
| CHK-M11-190 | APP | REQ-278 (4): statement spy over a run: no DDL (`CREATE`, `DROP`, `ALTER`, `TRUNCATE`), no INSERT other than the checkpoint into `audit_log`, no UPDATE; audit entries written = checkpoints only | W |
| CHK-M11-191 | APP | REQ-277 (4) / REQ-272 (4): retention log lines hold step names, counts and exception types only; no hostname, id, stdout, `execute`, expected value or token (canaries planted in the deleted rows) | W |
| CHK-M11-192 | APP | Lead correction (b) of the second note: the scans step runs as bitscan_retention without error (no row lock) and deletes the expired scans | W |
| CHK-M11-193 | APP | Race (REQ-278 (2)): a session holding M8's re-evaluation lock on an expired scan → that scan skipped (the others deleted); after release the next run deletes it; a re-evaluation started after the delete gets `ScanNotFound` | W |
| CHK-M11-194 | APP | Race (REQ-276 (3)): app writers appending audit entries during the audit step (barrier: writer parked on the chain lock while the step holds it) never fork the chain; `verify_chain()` OK; no entry lost | W |
| CHK-M11-195 | APP | Race (#150 (f)): an inventory upload racing the package prune (barrier) fails once, and the retried upload stores the package; nothing is lost | W |

## TP-M11-13: retention wiring (TASK-245; REQ-277, REQ-275) — `mt/test_retention_wiring.py`, `mt/test_serve_retention_linux.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-196 | APP | Clock-controlled `SchedulerRunner`: job set exactly `inventory`, `offline_sweep`, `scan_schedules`, `retention`; retention first run at start + 10 min, then every `interval_s` of the `retention` row (a changed row value used at start-up; 86,400 when the row cannot be read); `max_instances` 1; an exception in one step leaves the later steps run | W |
| CHK-M11-197 | APP | `stop()` during a run: it gives up at its next transaction (`SchedulerStopping`) and `stop()` returns; the retention pool is wrapped by the stop flag | W |
| CHK-M11-198 | APP | Real `serve` in W: opens a pool named `bitscan_retention` from `BITSCAN_RETENTION_DSN_FILE` (connections log in as bitscan_retention), closes it at stop; a missing file still fails start-up with the M2 message (no DSN content in output) | W |
| CHK-M11-199 | APP | `shipper.shipped_through()`: None before the first save; then the id of the last entry written to the disk queue; read-only (calling it changes no state); used as the retention cap | W |

## TASK-232: API contract (REQ-264 to -270, REQ-273; PD-48) — `mt/test_m11_contract.py`, `mt/test_m11_contract_api_pg.py`

Lead-approved naming (TASK-232 IMPL, 2026-11-08): the results models are `ScanResultItem` and `ScanResultItemWithOutput` (the plan's `ResultItem` is already the agent-route component); their fields are the plan's.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-230 | CODE | `openapi.json` holds exactly the six M11 operations of plan TASK-232 §3 (methods, paths under `/api/v1/`), each with exactly the planned query parameters and constraints (`limit` 1–500, `cursor`, `policy_id` ≥ 1, `agent_id` uuid, `state` the six scan states, `created_after` / `created_before` date-time, `status` the four values), path-id patterns, 200 schemas (`Page[ScanItem]`, `ScanDetailItem`, results page of either item model, `text/csv` string, `ReevalItem`) and declared refusals (400, 401, 403, 429, 503, + 404, + 409) | W, L |
| CHK-M11-231 | CODE | Component schemas: `ScanItem`, `HostJob`, `HostSummary`, `ScanDetailItem`, `ScanResultItem`, `ScanResultItemWithOutput`, `ReevalItem` have exactly the plan §4 properties and required sets; only `ScanResultItemWithOutput` has `stdout` / `stderr`; no `resolved_agents`, `execute` or `expected` outside the results items | W, L |
| CHK-M11-232 | CODE | REQ-273 (3): every component schema present at `6efe0fb` is byte-identical (agent-route schemas included, `ResultItem` among them); M11 adds only | W, L |
| CHK-M11-233 | APP | PD-48: each handler answers 501 `about:blank` only after its auth dependency ran: viewer session on each read → 501; viewer and operator sessions on re-evaluate → 403 `forbidden`; admin API token → 403 `totp_session_required`; restricted admin → 403 `totp_enrolment_required`; no token and `bsa_` → 401 `unauthorized`; admin TOTP session → 501; nothing written | W |
| CHK-M11-234 | APP | Path ids at the contract level: `/scans/not-a-uuid` and an unhyphenated hex id → 400; `/agents/not-a-uuid/scans` → 404 `not_found`; `/scans/{id}/results.csv` routed to the CSV operation (not to `/results`) | W |
| CHK-M11-235 | CODE | G6 export byte-identical; G34 route walk passes with the six operations and the auth markers of REQ-273 (4) | W, L |

## TP-M11-11: re-evaluate route (TASK-243; REQ-270, REQ-271) — `mt/test_reevaluate_api_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-200 | APP | REQ-270 (1): an admin TOTP session gets 200 with exactly the six keys; `rows_added` equals the new `scan_result_reeval` rows, `not_in_version` the plugins left out; one `scan.reevaluate` audit entry; it reaches the recording sink immediately (the shipper's wake, without a further cycle) | W |
| CHK-M11-201 | APP | REQ-270 (2) refusals, each writing no `scan_result_reeval` row and no audit entry (checksums): admin `bsk_` → 403 `totp_session_required`; operator and viewer sessions → 403 `forbidden`; operator and viewer API tokens → 403; restricted admin session → 403 `totp_enrolment_required`; no token, revoked token, `bsa_`, `bse_` → 401 `unauthorized` | W |
| CHK-M11-202 | APP | REQ-270 (2): sink outage under clock control: 14 min 59 s → 200; 15 min → 503 `audit_sink_unavailable` with no row and no entry; after the drain → 200 | W |
| CHK-M11-203 | APP | REQ-270 (3): unknown id 404 `not_found`; malformed id (`not-a-uuid`, unhyphenated hex, too long) 400 `invalid_request`; upper-case hyphenated id accepted; deleted policy 409 `conflict` "The policy is deleted."; none writes a row | W |
| CHK-M11-204 | APP | No body read: a body of garbage, of `{"execute": …}`, or 2 MiB of JSON does not change the answer (200, same rows) — or is refused by the M2 body cap before any work; never acted on | W |
| CHK-M11-205 | APP | REQ-270 (4): two concurrent calls on one scan (barrier) both answer 200, and the latest rows (highest `reeval_id` per job and plugin) come from the second | W |
| CHK-M11-206 | APP | REQ-271 (3): after a re-evaluation no audit entry has `detail.alert = true`; the alert metric for every kind unchanged | W |
| CHK-M11-207 | APP | Auth before work: a viewer, an API token and the restricted admin each read no `scan_result` / `scan_result_reeval` (spy sees no statement on them) | W |
| CHK-M11-208 | APP | Canary: the EXEC, EXP, OUT and ERR canaries in the scan's rows appear in no answer, log record or audit detail of the route | W |
| CHK-M11-209 | CODE | REQ-270 (5): `bm/api/user/reevaluate.py` imports no `bm.repositories` module (AST, transitive through `bm.api` only) | W, L |

## TP-M11-12: read routes (TASK-244; REQ-264 to -269, REQ-272) — `mt/test_scan_views_api_pg.py`, `mt/test_results_api_pg.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-213 | APP | REQ-264 (1): `GET /scans` filters alone and together, newest first; `limit=2` paging visits every scan once; default limit 50 (51 scans → 50 + cursor) | W |
| CHK-M11-214 | APP | REQ-264 (2) / REQ-266 (4): viewer, operator, admin with a session and with an API token → 200 on all five reads; no token, revoked token, `bsa_`, `bse_` → 401 | W |
| CHK-M11-215 | APP | REQ-264 (3): 400 `invalid_request` for unknown `state`, malformed `agent_id`, `created_after` without an offset, `limit` 0 and 501 (500 accepted), a tampered cursor, a cursor from other filters, a cursor whose scan was deleted (`AnchorGone`), a cursor from `/agents/{id}/scans` or from results | W |
| CHK-M11-216 | APP | REQ-264 (4): no scan item (list, detail, host history) holds `resolved_agents`, stdout, stderr, `execute` or an expected value (key walk and the four canaries) | W |
| CHK-M11-217 | APP | REQ-264 (5): statement spy over the read routes sees SELECT only (plus transaction control); no UPDATE / DELETE on `scan_result` or `scan_result_reeval` (REQ-271 (2)) | W |
| CHK-M11-218 | APP | REQ-265 (3), (6): `GET /scans/{id}` unknown 404 `not_found`, non-hyphenated id 400; the detail body keys exactly as expected, `target` without `resolved_agents` | W |
| CHK-M11-219 | APP | REQ-266 (1), (2): an agent in 3 of 5 scans gets exactly those 3, newest first; `limit=1` visits each once; unknown and malformed ids 404 `not_found`; decommissioned agent returned | W |
| CHK-M11-220 | APP | REQ-267 (3): results `limit=2` visits every item once; a cursor from another scan or another filter set → 400 | W |
| CHK-M11-221 | APP | REQ-267 (5): unknown scan 404, malformed id 400, unknown `status` 400, malformed `agent_id` 400 | W |
| CHK-M11-222 | APP | REQ-268 (1): with the OUT / ERR canaries, every viewer response (session and API token; JSON and CSV; every page and every filter) holds no canary byte and no `stdout` / `stderr` key or column; operator and admin responses hold them | W |
| CHK-M11-223 | APP | REQ-268 (2): an operator demoted to viewer gets no stdout on the next call with the same API token; promoted back gets it again | W |
| CHK-M11-224 | APP | REQ-268 (4): no canary (any of the four) and no token in any log record of these requests (caplog DEBUG) or problem detail | W |
| CHK-M11-225 | APP | REQ-269 (2), (4): CSV rows equal the JSON items for the same filters; `Content-Type` `text/csv` (UTF-8 if a charset is named), `Content-Disposition: attachment; filename="scan-<scan_id>-results.csv"` (the canonical lower-case id), no BOM, CRLF; unknown scan 404 (problem JSON, not CSV) | W |
| CHK-M11-226 | APP | REQ-269 (3): 100,000 rows export; 100,001 → 400 `invalid_request` with detail "Invalid request: more than 100000 rows; narrow the filters" and a problem body (no CSV byte, no `Content-Disposition`) | W |
| CHK-M11-227 | APP | `/scans/{id}/results.csv` and `/scans/{id}/results` are separate (the id never swallows `.csv`); `/scans/{id}.csv` is 400 / 404, never a CSV | W |
| CHK-M11-228 | APP | Every M11 response carries the TS §6.3 L1142 security headers (HSTS, CSP, nosniff, no-referrer); problem bodies are RFC 9457 | W |
| CHK-M11-229 | APP | G6: `openapi.json` exported from the tree equals the committed file byte for byte after TASK-244 | W, L |

## TP-M11-15: security suite (G83; REQ-268, REQ-271 to -273, REQ-275, REQ-278) — `mt/test_security_m11.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-240 | CODE | Route walk: the six M11 operations exist, all under `/api/v1/`, in TS §6.2; markers: `role` viewer for the five reads, `totp_session` with the sink gate for re-evaluate; no route runs an ad-hoc command or disables inventory (G34) | W, L |
| CHK-M11-241 | CODE | Response-model walk: no M11 response model other than `ResultItemWithOutput` has a `stdout` or `stderr` field (REQ-268 (3)); scan models have no `execute` / `expected` / `resolved_agents` | W, L |
| CHK-M11-242 | CODE | REQ-271 (1): `scan_result_reeval` appears in an INSERT only in `bm/repositories/reeval.py`; `reevaluate_scan` is called only from `bm/api/user/reevaluate.py`; no M11 module has UPDATE on `scan_result` / `scan_result_reeval`; only `bm/repositories/retention.py` deletes from `scan` | W, L |
| CHK-M11-243 | CODE | REQ-272 (2): `bm/api/user/scan_views.py` and `reevaluate.py` import no `bm.repositories` module | W, L |
| CHK-M11-244 | CODE | REQ-272 (3): `git diff 6efe0fb` over the frozen files (`services/evaluator/{score,scores,reevaluate}.py`, `repositories/{results,reeval,scan_progress}.py`, `services/jobs/*` except the three new M11 modules, `api/user/{scans,scan_schedules}.py`, `services/packages/csv_export.py`, `services/audit/{chain,verify}.py`, `auth/*`) is empty | W, L |
| CHK-M11-245 | CODE | REQ-272 (5): `bm/db/migrations/versions/` unchanged since `6efe0fb`; G19 green | W |
| CHK-M11-246 | CODE | REQ-273 (3): the agent-route component schemas in `openapi.json` byte-identical to `6efe0fb` | W, L |
| CHK-M11-247 | APP | Token groups: `bsa_` and `bse_` on every M11 route → 401; `bsu_` / `bsk_` on agent routes still 401 (unchanged) | W |
| CHK-M11-248 | APP | Canary across the M11 suites: a session-wide log handler collects every record of the M11 API and retention suites; no canary or token in any of them | W |
| CHK-M11-249 | CODE | Retention role limits: `bm/services/retention/` and `bm/repositories/retention*.py` contain no UPDATE, no DDL keyword, no INSERT other than through `append_entry`; the retention service is imported only by the scheduler runner | W, L |
| CHK-M11-250 | CODE | S608 and `re`: ruff S608 red on a planted f-string query in each new repository (CHK-M11-344, -345); `re` import red in each new module (CHK-M11-390) | W, L |

Written at the gate by tester-m11g (2026-11-09) as one file, bound to these test names: CHK-M11-240 `test_the_scan_operations_are_exactly_the_spec_routes_with_their_markers`, `test_no_operation_of_the_app_takes_command_text`; -241 `test_only_the_operator_results_model_carries_output`; -242 `test_reevaluate_scan_is_the_one_writer_of_reevaluations` and the read-route spy in `test_viewers_never_receive_output_and_reads_write_nothing`; -243 `test_the_m11_routes_reach_no_repository[*]`, `test_the_m11_layers_point_down_only[*]`; -244, -245 `test_the_frozen_files_are_byte_unchanged` (sha256 pins of 38 files at `6efe0fb`), `test_no_file_was_added_to_a_frozen_folder[*]`; -246 stays in `test_m11_contract.py` (`test_earlier_components_are_byte_identical`); -247 `test_tokens_are_refused_outside_their_route_group` (also a `bsa_`/`bse_` hash stored in `user_token`, and a `bsk_`/`bsu_` hash stored in `agent`); -248 `test_no_canary_or_token_leaves_through_logs_problems_or_audit`; -249 `test_retention_code_cannot_update_alter_or_insert`, `test_only_the_scheduler_runs_retention`, `test_serve_gives_retention_its_own_bitscan_retention_pool`, `test_retention_runs_as_bitscan_retention_within_its_role` (a `SchedulerRunner` with both pools); -250 `test_s608_is_green_as_is_and_red_on_an_f_string_query[*]`, `test_the_re_ban_is_green_as_is_and_red_on_an_re_import[*]` (ruff on stdin with the tree's configuration). Re-evaluate refusals at gate level: `test_reevaluate_refuses_everyone_but_a_totp_admin_session`, `test_reevaluate_is_refused_from_15_minutes_of_sink_outage_until_the_drain`. Results: `work/reports/M11-gate-test.md`.

## TP-M11-07 and TP-M11-14: web (web tester; REQ-273, REQ-279 to -284) — `wb/**/*.test.ts(x)`

Owner of this section: **tester-m11w** (from 2026-11-08; the rows were drafted by tester-m11 from the criteria and are kept, refined here by tester-m11w without reading the M11 web code). Web runs: `npm run lint`, `npm run typecheck`, `npx vitest run <files>` from `web/` on L (worktree `node_modules` installed with `npm ci --offline` from the identical lock). Plants for the web security rows are made in a throwaway copy of `web/` under `$TEMP/m11w-mut-<chk>` (with its own `node_modules` junction), never in the worktree.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-260 | CODE | `schema.d.ts` regenerated from the TASK-232 document with no diff (G16); `npm run typecheck` passes | L, CI |
| CHK-M11-261 | CODE | `Score`: 0.75 with 5 errors → "75.0 %" and "5 errors"; null → "n/a" (never "0.0 %"); 0.9996 → "99.9 %" (rounded down); 1.0 → "100.0 %"; 1 error → "1 error"; 0 errors → "0 errors"; the error count is shown beside "n/a" too (REQ-280 (1), #149). Boundaries of "rounded down": 2/3 → "66.6 %" (not 66.7), 0.0004 → "0.0 %", 0 → "0.0 %"; exact one-decimal scores are not under-rounded by float error: 29/100 → "29.0 %", 57/100 → "57.0 %", 58/100 → "58.0 %", 23/40 → "57.5 %" (a `floor(s*100*10)` formatter shows 28.9, 56.9, 57.9, 57.4) | L |
| CHK-M11-262 | CODE | `ResultBadge`: PASS, FAIL, ERROR each named; null → "Not run" (not FAIL, not empty); a re-evaluated result shows the current verdict and the original beside it (web-ui rule: "both … when a result has been re-evaluated"), a never re-evaluated one shows one verdict (REQ-281 (1)) | L |
| CHK-M11-263 | CODE | Generic CSV download: one GET through the generated client with the bearer and exactly the given query, `parseAs: "blob"` (body saved byte for byte, CRLF and non-ASCII kept), saved under the given name, object URL revoked after the click; the M5 packages export still behaves as CHK-M5-274 to -276 | L |
| CHK-M11-264 | CODE | Generic CSV download refusals: a 400 returns the problem detail and saves nothing; a 401 ends the session | L |
| CHK-M11-265 | CODE | Scans screen: filters build the expected query, paging forward and back, a viewer sees no Run scan (REQ-279 (1)) | L |
| CHK-M11-266 | CODE | Run scan: operator submission sends `{policy_id, target}` with one `Idempotency-Key`; a double click sends one request; a retried submission keeps its key, the next gets a new one; 409 and 422 show their detail (REQ-279 (1), (2); #154) | L |
| CHK-M11-267 | CODE | Scan detail: summary and per-host table with `Score`; viewer no buttons, operator Cancel only, admin both; confirm before each; re-evaluate 200 shows `rows_added` and reloads; 403 `totp_session_required` and 503 show the prompt and send no other request; never an API-token fallback (REQ-280 (2), (3)) | L |
| CHK-M11-268 | CODE | Results screen: both verdicts for a re-evaluated row, Not run for null; no output column when items lack `stdout`; with it, text in a `<pre>` text node; `<img src=x onerror=alert(1)>` renders as text; Export CSV calls `/api/v1/scans/{id}/results.csv` with the current filters, saved as `scan-<id>-results.csv` (REQ-281) | L |
| CHK-M11-269 | CODE | Schedules: create sends the #122 (h) body, edit only changed fields, delete confirms; 400 and 409 show their detail; a viewer is not offered the route and the screen never mounts (REQ-282) | L |
| CHK-M11-270 | CODE | Host scans: rows, links to the scan detail, empty state, error banner; existing HostDetail tests pass (REQ-283) | L |
| CHK-M11-271 | CODE | Router: every new hash parses and formats; malformed ids fall back to the host list; viewer offered neither schedules nor run scan; the profile page links to Run scan with the profile chosen | L |
| CHK-M11-272 | CODE | REQ-284 (2): a `<script>` hostname, plugin name, eval detail and stdout render as text in every new screen; no `dangerouslySetInnerHTML`, `innerHTML`, `fetch(`; session in memory only (no `localStorage` / `sessionStorage`) | L |
| CHK-M11-273 | CODE | TASK-256 `TargetPicker` (#154 (a), #122 (b), #68): the three forms "All hosts", "Hosts with any of these tags", "These hosts" (chosen from `GET /agents`, paged through the client); the tag check runs before anything is sent: 1–32 distinct tags, each 1–64 characters from `[A-Za-z0-9._:-]` (64 accepted, 65 refused; 32 accepted, 33 refused; `/`, `<`, a non-ASCII letter and an empty list refused; a space or comma separates; a repeated tag is sent once, so the body holds distinct tags); a refused form sends no request and names the problem; no host chosen is refused; `<script>` hostnames in the host list render as text | L |
| CHK-M11-274 | CODE | TASK-256 `toTarget` / `fromTarget` / `describeTarget`: each form gives exactly one key (`{all: true}`, `{tags: [...]}`, `{agents: [...]}`, #122 (b)); `fromTarget(toTarget(x))` returns `x` for each form, and `toTarget(fromTarget(t))` returns `t` for each stored target (the detail's `target`, without `resolved_agents`); `describeTarget` names each form in plain text (a `<script>` tag value stays text) | L |
| CHK-M11-275 | CODE | TASK-256 `ScanTable` / `ScanStateBadge`: one row per scan with policy name, version, trigger, state, target kind, host count and times; each of the six scan states has its own label; a row links to that scan's detail through the `ScanLinks` prop (mocked in the screen tests until TASK-251 wires the router); a `<script>` policy name renders as text; an empty list has no body rows (the empty-state text is each screen's: "No scans.", "No scans of this host yet.") | L |

Web plants (throwaway copy; the unmodified copy green first; "red" = the named web test fails for the planted reason, or the lint exits non-zero on the planted line):

| Plant | Planted in | Must turn red | Batch |
| --- | --- | --- | --- |
| CHK-M11-360 `dangerouslySetInnerHTML` for stdout | `ScanResults.tsx` | G12 (lint) and the CHK-M11-268 `onerror` row | W3 |
| CHK-M11-361 a `fetch(` call | `ScanDetail.tsx` | G12 (lint) | W3 |
| CHK-M11-362 re-evaluate falls back to an API token / token saved in `sessionStorage` | `ScanDetail.tsx` | G12 (storage ban) and the CHK-M11-267 403 row | W3 |
| CHK-M11-363 null score shown as "0.0 %" | `Score.tsx` | CHK-M11-261 null row | W2 |
| CHK-M11-364 round to nearest (0.9996 → "100.0 %") | `Score.tsx` / `format.ts` | CHK-M11-261 0.9996 row | W2 |
| CHK-M11-365 `original_result` hidden | `ScanResults.tsx` (and `ResultBadge.tsx` in W2) | CHK-M11-268 / CHK-M11-262 both-verdicts row | W2, W3 |
| CHK-M11-366 a viewer offered Run scan or Schedules | `routes.tsx` / `Scans.tsx` | CHK-M11-265 viewer row, CHK-M11-271 | W3, W4 |
| CHK-M11-375 (tester extra, S) a `<script>` hostname rendered as HTML (`innerHTML`) | `ScanDetail.tsx`, `Scans.tsx` / `HostScans.tsx`, `ScanTable.tsx`, `TargetPicker.tsx` (TASK-256) | CHK-M11-272, -273, -275 for that file | W3 |
| CHK-M11-379 (tester extra) the tag check relaxed (65 characters, or `<` / space allowed) | `TargetPicker.tsx` (TASK-256) | CHK-M11-273 tag rows | W3 |
| CHK-M11-430 (tester extra, S) a scan hash with any non-empty id accepted | `router.ts` (TASK-251) | CHK-M11-271 fallback rows | W4 |
| CHK-M11-431 (tester extra) a Run scan hash with any profile id accepted | `router.ts` (TASK-251) | CHK-M11-271 fallback rows | W4 |
| CHK-M11-432 (tester extra) the in-flight guard removed (double click) | `RunScan.tsx` | CHK-M11-266 double-click row | W3 |
| CHK-M11-433 (tester extra) a new Idempotency-Key on every send (retry gets a new key) | `RunScan.tsx` | CHK-M11-266 retry row | W3 |
| CHK-M11-434 (tester extra, S) Cancel offered to viewers | `ScanDetail.tsx` | CHK-M11-267 viewer row | W3 |
| CHK-M11-435 (tester extra) an edit always sends `cron` | `ScheduleForm.tsx` | CHK-M11-269 changed-fields rows | W3 |
| CHK-M11-436 (tester extra, S) a reload after a refused re-evaluate or cancel | `ScanDetail.tsx` | CHK-M11-267 "no other request" rows | W3 |
| CHK-M11-437 (tester extra) the CSV export drops the current filters | `ScanResults.tsx` | CHK-M11-268 export row | W3 |
| CHK-M11-438 (tester extra) the host-id filter sent untrimmed and in its typed case | `Scans.tsx` | CHK-M11-265 filter row | W3 |
| CHK-M11-439 (main's plant, TASK-258) `fromTarget` returns All hosts for an unrecognised stored target | `TargetPicker.tsx` | the TASK-258 "edit sends no target" row (CHK-M11-269, -274 extended) | W3 follow-up |
| CHK-M11-440 (tester extra, TASK-258) the edit form passes an unknown target to `toTarget` | `ScheduleForm.tsx` | the TASK-258 edit rows | W3 follow-up |
| CHK-M11-376 (tester extra, S) the output column shown with an empty cell for viewer items (keys absent) | `ScanResults.tsx` | CHK-M11-268 no-output row | W3 |
| CHK-M11-377 (tester extra) score formatter `floor(s*100*10)` | `format.ts` | CHK-M11-261 29/100 row | W2 |
| CHK-M11-378 (tester extra) CSV download without `parseAs: "blob"` (text parse) | `download.ts` | CHK-M11-263 byte-for-byte row | W2 |

## TP-M11-17 to -20: end to end and N / N−1 (tester-m11e) — `e2e/m6/manager_walk.py`, `e2e/m11/`

Ids agreed with tester-m11e 2026-11-08; that tester writes the rows of this section. Results: `work/reports/M11-e2e-test.md` (linked from [report.md](report.md)). W = WSL2 with Docker and QEMU/KVM guests of the official cloud images (development runs; no Hyper-V VM). CI = the hosted `ubuntu-24.04` runner through `e2e.yml` (TASK-254); the user's standing approval for the local Hyper-V VMs (decisions 2026-11-08 (4)) covers only that workflow's fallback, never a development run.

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-290 | APP | `manager_walk.py` green against the current `deploy/runbooks/manager-install.md`: every fenced block found by section and anchor (none by position), each walked or NOT RUN with its reason, a new or changed block stops the walk (REQ-291 (1)) | W |
| CHK-M11-291 | APP | `BITSCAN_BITS_DIR` set in `manager.env`; the folder and `uploaded/` exist with the runbook's owners and modes (`root:bitscan-manager 750`, `bitscan-manager:bitscan-manager 750`) before the manager starts; the catalog starts without the M10 G79 `FileNotFoundError` | W |
| CHK-M11-292 | APP | The start check stops the walk with a clear message when the folder or `uploaded/` is missing (REQ-291 (2)). Plant: a runbook copy without §4's `uploaded/` line turns -291 and -292 red and nothing starts | W |
| CHK-M11-293 | APP | Walk secret sweep: no password, token, DSN or key line in the rows, the walk log or the host journal | W |
| CHK-M11-294 | APP | Nightly pre-check: `/dev/kvm` usable, QEMU, the cloud images and the `.deb` checked against their published SHA-256, memory, the manager port free; a failed pre-check makes every later row NOT RUN, never a silent skip (#152 (a)) | CI; W |
| CHK-M11-295 | APP | The manager host installed by `manager-install.md` (the CHK-M11-290 walk, 0 FAIL), port published for the guests | CI; W |
| CHK-M11-296 | APP | Per host (22.04, 24.04): the `.deb` installs with `install.env` (24.04 also the SPKI pin) and the enrolment is held, kind new, this host's name and version | CI; W |
| CHK-M11-297 | APP | Per host: approve through the API with the admin TOTP session (200) | CI; W |
| CHK-M11-298 | APP | Per host: online after approval, with the package version | CI; W |
| CHK-M11-299 | APP | Per host: first inventory, `os_info` of the host and a snapshot holding every `dpkg-query -W` package | CI; W |
| CHK-M11-300 | APP | Import of the SR §1.1 canonical example, extracted verbatim from the spec, by upload: `success`, the policy name, one plugin `3f6c2a9e-…` | CI; W |
| CHK-M11-301 | APP | A scan of both hosts queued (202), and per host the compliance job `completed` | CI; W |
| CHK-M11-302 | APP | Per host: scan `completed`, `score` 1.0, `errors` 0, the plugin PASS with exit 0 and its stdout (admin); `results.csv` parsed (one PASS row per host, `Content-Disposition`); a viewer's JSON and CSV hold no `stdout` or `stderr` | CI; W |
| CHK-M11-303 | APP | Token and password sweep over the report, the harness and walk logs, the manager host's and both guests' journals (REQ-285 (3)) | CI; W |
| CHK-M11-304 | APP | N / N−1 pre-check: the v0.1.0 `.deb` and manager wheel checked against the release's published SHA-256 (#153 (a)) | CI; W |
| CHK-M11-305 | APP | Manager N with agent 0.1.0: enrol, approve, heartbeat, inventory (REQ-287) | CI; W |
| CHK-M11-306 | APP | Manager N with agent 0.1.0: a scan stores every plugin as ERROR `runner_unavailable`, `score` null, `errors` = plugins, shown so in the results (#74, #28; REQ-287) | CI; W |
| CHK-M11-307 | APP | Upgrade walk once at the gate (#153 (d)): manager 0.1.0 with agent 0.1.0 → migrate and manager N → heartbeat and inventory go on → agent upgraded to N → a scan completes | CI; W |
| CHK-M11-308 | APP | Agent N with manager 0.1.0: enrol, approve, heartbeat, inventory (REQ-288) | CI; W |
| CHK-M11-309 | APP | Agent N with manager 0.1.0: no compliance job is ever sent; token sweep over the N / N−1 runs | CI; W |
| CHK-M11-370 | APP (plant) | An agent `.deb` whose runner returns no results (throwaway copy: `emit(res)` dropped in `agent/internal/runner/job.go`) → CHK-M11-302 FAIL | W; CI |
| CHK-M11-371 | APP (plant) | A manager tree whose results route leaves out a host → CHK-M11-302 FAIL (after TASK-244) | W; CI |
| CHK-M11-372 | APP (plant) | A manager tree that refuses the 0.1.0 heartbeat body → CHK-M11-305 FAIL | W; CI |
| CHK-M11-373, -374 | APP (plant) | `e2e.yml`: a FAIL row, and a removed expected row (`nightly.py --check-report`), each turn the job red (TASK-254 TEST; tester-m11e if assigned) | CI |

## TP-M11-16 and TP-M11-21: docs walks and replaced checks (TASK-252, 253, 245; REQ-289, -290, PD-51)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-380 | APP | Each new README section (scan list, detail and score, results and CSV, re-evaluation, retention, nightly) followed against a W manager: every step behaves as written (REQ-289 (1)) | W |
| CHK-M11-381 | CODE | The Scheduler line reads "partial, failed or completed"; the "not part of this version" lines are gone (REQ-289 (2)) | L |
| CHK-M11-382 | CODE | No token, password, internal id or process note in README or the runbook (REQ-289 (3), REQ-290 (2)) | L |
| CHK-M11-383 | APP | Runbook: retention operations, upgrade order with agents N−1 and the release checklist followed against a W manager | W |
| CHK-M11-384 | CODE | `dpkg-parsechangelog` gives `0.2.0~pre2-1`; CHK-M10-318 and -319 stay green (`release.yml` refuses `~`) (REQ-290 (1)) | W |
| CHK-M11-385 | APP | PD-51: the scheduler job-set and stop-record checks of `test_scheduler_runner.py` and `test_serve_scheduler_linux.py` rewritten for four jobs; old CHK ids listed with their replacements in `report.md`; every other assertion kept | W |
| CHK-M11-386 | APP | PD-51: the README walk checks of "results views arrive with M11" rewritten; old → new ids listed | W |

## TP-M11-23 and TP-M11-24: gate rows

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M11-310 | CODE | G1–G4: `ruff check manager`, `ruff format --check manager`, `mypy --strict manager`, `pip install --require-hashes` | L, W |
| CHK-M11-311 | APP | G5: services line coverage ≥ 85 % on the full W run (report the exact figure, two decimals, not rounded up) | W |
| CHK-M11-312 | CODE | G6: OpenAPI export byte-identical | W, L |
| CHK-M11-313 | CODE | G16: web client regenerated with no diff (after TASK-239) | L |
| CHK-M11-314 | APP | G18: full manager suite, `CI=true`, `-n auto`, 0 skipped; totals | W |
| CHK-M11-315 | APP | G19: schema diff green (no migration) | W |
| CHK-M11-316 | APP | G30, G33: agent contract suite and M3 sweep / inventory suites green | W |
| CHK-M11-317 | CODE | G34: route walk green with the six operations | W |
| CHK-M11-318 | APP | G37–G40 re-run for the changelog change | W |
| CHK-M11-319 | APP | G41: `e2e/agent_manager.sh` inventory chain against the real W manager (the `serve` wiring changed) | W |
| CHK-M11-387 | APP | #151 measurement for the owner: time per 1,000 inventory-job deletes and per 100 scans on a realistic table size, recorded (not a gate) | W |

## Mutation table (CHK-M11-320 to -374, `work/tasks.md`; plus tester extras)

Every row of `work/tasks.md` "M11 mutation table" is planted by the tester of its target task and must turn the named gate red; the check expected to go red is named in the task report. Manager rows (tester-m11): -320 to -359, -367 to -369. Web rows (web tester): -360 to -366. Harness and workflow rows (tester-m11e): -370 to -374. Each high-risk task (233, 235, 236, 237, 238, 241, 242, 243, 244, 245) also gets a plant for every boundary and race its checks name. Extra tester plants:

| CHK | Plant | Red in | Target |
| --- | --- | --- | --- |
| CHK-M11-390 | `import re` added to a new M11 module | G1 | TASK-233 to 245 |
| CHK-M11-391 | an untested function added to `bm/services/retention/task.py` sized from the clean report | G5 | TASK-242 |
| CHK-M11-392 | a route parameter added without re-export | G6 | TASK-244 |
| CHK-M11-393 | a throwaway migration adding `ix_reeval_job` | G19 | gate |
| CHK-M11-394 | the tokens probe switched back to `expires_at` (lead correction (a)) | G81 (CHK-M11-143 at service level: CHK-M11-178) | TASK-237, 242 |
| CHK-M11-395 | `FOR UPDATE SKIP LOCKED` put back into `scan_chunk` (lead correction (b)) | G81 (CHK-M11-136, -192) | TASK-237 |
| CHK-M11-396 | a cutoff compared with `<=` instead of `<` (each rule in turn) | G80 (CHK-M11-041), G81 (CHK-M11-135) | TASK-236, 237 |
| CHK-M11-397 | `clock_doubt` with `>=` 5 min | G80 (CHK-M11-046) | TASK-236 |
| CHK-M11-398 | `future_rows` with `>=` 1 day | G80 (CHK-M11-047) | TASK-236 |
| CHK-M11-399 | `audit_prefix` not capped at the cursor; capped but returning the cursor itself when not stored | G80 (CHK-M11-044) | TASK-236 |
| CHK-M11-400 | `minus_years` by 365-day steps | G80 (CHK-M11-042) | TASK-236 |
| CHK-M11-401 | `delete_requests` without `decision IS NOT NULL` | G81 (CHK-M11-135) | TASK-237 |
| CHK-M11-402 | `delete_inventory_jobs` without `kind = 'inventory'` | G81 (CHK-M11-135) | TASK-237 |
| CHK-M11-403 | `delete_through` with `<` instead of `<=` | G81 (CHK-M11-141) | TASK-238 |
| CHK-M11-404 | `include_output` true for an unknown role | G80 (CHK-M11-001) | TASK-233 |
| CHK-M11-405 | results keyset `>=` instead of `>` (an item repeated across pages) | G81 (CHK-M11-123) | TASK-235 |
| CHK-M11-406 | scan list ordered by `scan_id` only (ties ignored) / `created_after` exclusive | G81 (CHK-M11-105, -106) | TASK-234 |

## Questions

None at drafting. Anything the spec leaves open that a check meets is recorded, not asserted, and sent to `main`.

## Not run in M11 (with the milestone)

Load tests (deferred by the user); Debian 12 and arm64 rows of TS §8.3 (not supported, decisions 2026-10-24). A row refused by a safety check is NOT RUN with its reason and its lower-level cover, and goes to the user (PD-49).
