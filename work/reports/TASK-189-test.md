# TASK-189 TEST: PASS

Tester: tester-m9, 2026-10-30. Full rigor (job and retry builder; second look, PD-39). REQ-209 (1)–(4), (6) and REQ-210 (1)–(4) for plugins given as values; REQ-212 at builder level; TS §3.5 L248, §6.5 L1165–L1182, §4.4 L566, L577, §4.1 L530; SR §1.1; #117, #125 (a)–(c), (g), #126 (a), (b). Code under test: `bm/services/jobs/build.py` (impl-manager-m9, `work/reports/TASK-189-impl.md`, including the later `PICKUP_WINDOW as PICKUP_WINDOW` re-export; sha256 `fd339fbcf84aac92…`). Test file (new): `manager/tests/test_job_build.py`. Plan rows: CHK-M9-037 to -050.

## Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_job_build.py` (first run) | 61/62 passed, 1 failed (`test_no_payload_holds_evaluation_data`: **test bug**, my fixture gave plugin *n* `timeout_s = 10 + n`, which goes over 600 for the 5,000-plugin case) |
| r1 | same, fixture `timeout_s = 10 + n % 590` | **62/62 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 9 plants in `/root/bstest-m9-mut-<id>` | 9/9 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

## Report rows (for tests/m9/report.md)

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

## Acceptance (TASK-189 row: "REQ-209 (1)–(4) and (6) and REQ-210 (1)–(4) hold for plugins given as values")

- REQ-209 (1) shape, lowercase, `pickup_by` → CHK-M9-037 to -039; (2) no evaluation data at any depth → CHK-M9-040; (3) `eval_spec` parses and matches one to one → CHK-M9-041; (4) unstorable text → CHK-M9-043; (6) SR §1.1 → CHK-M9-045.
- REQ-210 (1)–(3) → CHK-M9-046, -047; (4) → CHK-M9-048.
- REQ-209 (5) (M8's `host_counts` on an M9-queued scan) is TASK-198 on PostgreSQL (CHK-M9-159, tester-m9b).

## Notes for the second look (PD-39)

- `payload()` copies the lists, so a built payload cannot alias the shared `BuiltPlugins` (CHK-M9-042).
- `retry()` has an extra guard: an `eval_spec` whose kept uuids differ from the payload's in order is refused (CHK-M9-048). It also re-derives `agent_id` through `UUID()`, so the result is always lowercase.
- `payload()` does not re-check text itself. It is safe only because `BuiltPlugins` comes from `plugins_and_spec`. A caller that builds `BuiltPlugins` by hand skips the unstorable-text check. Today the only callers are TASK-193/198 (tester-m9b, CHK-M9-112).
