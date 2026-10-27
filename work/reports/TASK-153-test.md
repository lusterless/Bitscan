# TASK-153 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-162, REQ-165 to REQ-168; TS §8.4 L1288 to L1291, §4.1 L530, §5.2 L699; #23, #100 (a) to (d), #101, #103. Files under test: `bm/services/audit/alerts.py`, `bm/services/audit/metrics.py`, `bm/services/importer/alerts.py`. Checks CHK-M7-185 to -188, mutation row CHK-M7-354 and extra plants. New test file `manager/tests/test_import_alerts.py` (51 tests). Updated tester-owned tests:
- `test_alerts.py`: the #101 kinds, 34 kinds, the `bitscan_import_failures` family. Its unknown-kind example `policy_imported` (now a real kind) is replaced by `Policy_Imported` and `policy_moved`.
- `test_thresholds.py`: the family, type counter, label `mode`, and the REQ-086 (3) label-name pin extended with `mode`, whose values must be exactly `auto`, `manual`, `rebuild`.
- `test_metrics_api_pg.py`: the same label pin with the mode values.

None of these updates weakens a check. Each adds the fixed set #101 approved and asserts its exact values.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| r0 (W, label m7t-t153, `CI=true`, `-n 0`) | `pytest tests/test_import_alerts.py tests/test_alerts.py tests/test_thresholds.py tests/test_alerts_pg.py tests/test_metrics_api_pg.py tests/test_metrics_scrape.py tests/test_fleet_alerts_pg.py` | 152/155 passed, 3 failed, 0 skipped. The 3 failures are existing tests that pin the pre-M7 sets (test updates, not product bugs) |
| r1 (W, label m7t-t153b) | the 3 failing node ids after the test updates: `test_alerts.py::test_unknown_kind_is_refused_and_nothing_is_written`, `test_thresholds.py::test_no_unbounded_label_names_anywhere`, `test_metrics_api_pg.py::test_no_label_holds_an_unbounded_value` | 7/7 passed |
| static (L) | ruff, ruff format, `mypy --strict --config-file manager/pyproject.toml manager` | clean (257 files) |

## Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7`, `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0`, leftover-own 0. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>`, imported first through `PYTHONPATH`.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-185 | CODE | W | r0 (`test_import_alerts.py`, `test_alerts.py`) | PASS | `M7_ALERT_KINDS` = the six #101 kinds, no move kind; union of 34; each M7 kind and each of the 3 modes exported at `0.0` in a fresh process, no other mode; `raise_alert` refuses `policy_moved`, `Policy_Imported`, `policy_imported ` with nothing written; every kind (M7 included) writes one entry with `alert = true` and its kind | 2026-10-27 |
| CHK-M7-186 | CODE | W | r0 | PASS | `policy_imported`: action `policy.import`, target `policy:<id>`, the full detail (incl. `renamed_from`, `revived`), every changed Execute in full and in order (a 16,000-character Execute whole), actor kept; the six words flagged case-insensitively, each alone (12 cases incl. `SHADOW`, `.SSH`, `A.PEM`, `.Key`, `Token`, `CREDENTIALS`); six plain CIS commands (incl. `/etc/ssh/sshd_config`, `ssh_host_ed25519_key`) unflagged; several words listed once in spec order; the count +1 only on commit, none on rollback; the Execute text never in a log record | 2026-10-27 |
| CHK-M7-187 | CODE | W | r0 | PASS | `rejected`: action, kind, target the file name, else `policy:<id>`, else null; distinct codes in first-seen order; finding messages not in the entry (canary); `deleted` with the 3 reasons; `moved` is a plain `policy.move` entry with no alert key and no counter hook; `status_change` alerts only disabled → enabled (8 cases, PATCH and file); `rebuilt` target `task:<uuid>`; `integrity_failed` lists the first 100 of 150 in order with the total, and an empty list is refused; U+0000 and lone surrogates in path fields become U+FFFD, so every entry is UTF-8-encodable JSON | 2026-10-27 |
| CHK-M7-188 | CODE | W | r0 + r1 (`test_thresholds.py`, `test_metrics_api_pg.py`) | PASS | `bitscan_import_failures_total{mode}` is a counter; +1 per mode only on commit and only for that mode; none on rollback; unknown mode (`Auto`, `watch`, ``, `rebuild `) refused with no hook; a rejected alert and its count land together; label names on the wire = {kind, status, le, mode}; mode values exactly the three; the scrape route's samples obey the same | 2026-10-27 |
| CHK-M7-185..188 static | CODE | L | ruff, format, mypy (CI form) | PASS | clean, 257 files | 2026-10-27 |
| CHK-M7-354 | CODE | W | plants: (a) `execute` cut to 64 characters; (b) `flags` always `[]` | PASS (red) | (a) 1 failed; (b) 12 failed | 2026-10-27 |
| CHK-M7-153-case | CODE | W | plant: flags without `casefold` | PASS (red) | 6 failed | 2026-10-27 |
| CHK-M7-153-word | CODE | W | plant: `token` dropped from `FLAG_WORDS` | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-153-reen | CODE | W | plant: re-enable alert on any status change | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-153-cnt | CODE | W | plant: failure counted before commit | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-153-cap | CODE | W | plant: integrity list capped at 10 | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-153-move | CODE | W | plant: move raised as an alert | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-153-nul | CODE | W | plant: no U+0000 / surrogate replacement | PASS (red) | 1 failed (`UnicodeEncodeError`) | 2026-10-27 |
| CHK-M7-153-msg | CODE | W | plant: finding messages copied into the rejected entry | PASS (red) | 1 failed | 2026-10-27 |
| CHK-M7-153-mode | CODE | W | plant: `rebuild` dropped from `IMPORT_MODES` | PASS (red) | 3 failed | 2026-10-27 |
| CHK-M7-153-kind | CODE | W | plant: `policy_reenabled` dropped from `M7_ALERT_KINDS` | PASS (red) | 8 failed | 2026-10-27 |

Not here (by design): REQ-162 (4) and (5) on PostgreSQL. That is the alert in the catalog transaction, no alert or count after a rollback, and the entry reaching the fake sink. They run at TASK-154 (G60, CHK-M7-286, -349, -350). The detail keys the implementer chose (rejected, deleted, status_change, rebuilt, integrity) are tested as written; they were sent to main as choices.

## Round 2 (reviewer-m7 should-fix: `rejected()` fallback target capped at 255 characters, `TARGET_MAX`)

New rows: `test_import_alerts.py::test_rejected_fallback_target_fits_the_column_and_detail_keeps_it_whole` (n = 250, 255, 300: target = the first 255 characters of `uploaded/aaa….bit`, and `detail.file_name` holds the whole name) and `::test_rejected_target_counts_characters_not_bytes` (`é` × 300). New PostgreSQL file `test_import_alerts_pg.py::test_long_name_rejected_alert_is_stored` (the 263-character `uploaded/` name and `é` × 300 + `.bit` are written through `emit` and `PgAuditRepo` into `audit_log`; the stored target is the first 255 characters and the stored detail holds the full name).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-187-r2 | CODE + APP | W | `pytest -q -n 0 tests/test_import_alerts.py tests/test_import_alerts_pg.py` (label m7t-t151, in one run with TASK-151) | PASS | 55/55 + 2/2 passed, 0 failed, 0 skipped | 2026-10-27 |
| CHK-M7-153-cut | CODE + APP | W | plant: cut removed (`name or None`) | PASS (red) | 6 failed: 4 unit (length) and both PostgreSQL rows (the insert into `audit_log.target` VARCHAR(255) fails) | 2026-10-27 |
| CHK-M7-153 static | CODE | L | ruff, ruff format, mypy (CI form) | PASS | clean | 2026-10-27 |

Verdict after round 2: **PASS**.

## Round 3 (#100 (a) widened: each `changed_executes` entry gains `reason`)

Updated: `test_imported_shape_carries_every_changed_execute_in_full` (each entry carries `reason`). New: `test_each_entry_carries_its_reason_in_the_101_key_order` (keys exactly `plugin_uuid, plugin_name, execute, execute_sha256, reason, flags`; reasons new, changed, reactivated in order; a reactivated `cat /etc/shadow` in full with its flag).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-186-r3 | CODE + APP | W | `pytest -n 2 tests/test_import_alerts.py tests/test_import_alerts_pg.py tests/test_alerts.py tests/test_thresholds.py` (with the TASK-151 r2 file, m7t-t151r2) | PASS | 56 + 2 + 51 + 22 = 131/131 passed (the run: 166/166) | 2026-10-27 |
| CHK-M7-153-rr | CODE | W | plant: `reason` dropped from the entry | PASS (red) | 2 failed | 2026-10-27 |

Verdict after round 3: **PASS**.

## Round 4 (crash-window ruling: `rebuilt(..., removed_leftovers)`)

Updated `test_rebuilt_shape`: two leftover paths are listed in the given order, not sorted. New rows:
- `test_rebuilt_with_no_leftovers_lists_an_empty_list` (`()` gives `[]`).
- `test_rebuilt_leftover_paths_are_storable` (U+0000 and a lone surrogate become U+FFFD; UTF-8-encodable JSON).
- `test_rebuilt_requires_the_leftovers_keyword` (omitting it is a `TypeError`).

Tester note: while editing, a failed edit script of mine truncated the untracked `test_import_alerts.py`. I restored it byte for byte from my WSL copy synced at the m7t-t151r2 run (583 lines) before adding these rows, and checked it. No test was lost.

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-187-r4 | CODE + APP | W | same run as TASK-151 r3 (m7t-t151r3) | PASS | 59/59 alerts + 2/2 PostgreSQL | 2026-10-27 |
| CHK-M7-153-lo | CODE | W | plant: leftovers always `[]` | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-153-lr | CODE | W | plant: leftovers sorted | PASS (red) | 2 failed | 2026-10-27 |
| CHK-M7-153-ls | CODE | W | plant: leftovers not through `_storable` | PASS (red) | 1 failed (`UnicodeEncodeError`) | 2026-10-27 |

Verdict after round 4: **PASS**.
