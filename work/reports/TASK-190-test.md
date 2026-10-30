# TASK-190 TEST: PASS

Tester: tester-m9, 2026-10-30. Full rigor (intake plan; TS §8.2 second approval, PD-39). REQ-214, REQ-215, REQ-216 at plan level; TS §6.1 L1071, §4.4 L578, §4.5 L587, L596, L599, L603; #12, #116 (d), #121, #124 (a), (b). Code under test: `bm/services/jobs/intake_plan.py` (impl-manager-m9, `work/reports/TASK-190-impl.md`; sha256 `89a13f83aef30f8b…`). Test files (new): `manager/tests/test_intake_plan.py`, and `test_plan_accounting`, `test_storable_properties`, `test_plan_rows_always_encode` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-053 to -066, -083, -084. Items are the M3 `ResultItem`, built with `json.loads` + `model_validate` as the route does (lone surrogates and U+0000 survive both, checked first); every expected verdict is computed by the test from M8's `result_verdict` / `classify`.

## The recompute departure (impl report §"Departure")

The plan said: recompute through `result_verdict` with a proxy holding the replaced text. The code instead recomputes with `classify()` on the stored stdout, only when stdout changed, no runner error was sent and the verdict was not `oversize`. Checked against #121 and found consistent: (b) the caps are measured once, on the received text (CHK-M9-058, and plant CHK-M9-331c shows the proxy reading goes red); (c) the stored text is the evaluated text (CHK-M9-059); a runner error or `timed out` keeps its verdict (CHK-M9-059 rows). No ruling needed. The departure is also what makes a stdout of 65,000 bytes with 300 NULs stay under the cap (CHK-M9-058).

## Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_intake_plan.py` (first run) | 106/107 passed, 1 failed (`test_storable[…]`, **test bug**: my file-writing tool turned the two-surrogate escape (U+D83D then U+DE00, written as escapes) into one emoji character, so the "two lone surrogates" row was testing U+1F600; restored as escapes, and every other decoded literal in my M9 files was restored to `\uXXXX` too) |
| r1 | `pytest tests/test_intake_plan.py tests/test_jobs_property.py::test_plan_accounting ::test_storable_properties ::test_plan_rows_always_encode` | **110/110 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 9 plants in `/root/bstest-m9-mut-<id>` | 9/9 red |
| static (L) | ruff, ruff format, mypy --strict | clean |
| r2, after review (W) | the same as r1, after `test_caps` was given short explicit `ids=` (reviewer-m9 should-fix 1: a 65 KB id breaks `PYTEST_CURRENT_TEST` on Windows) | **110/110 passed**, 0 failed, 0 errors, 0 skipped |
| r2-L (Windows, worktree venv, `CI=true`, `-n 0`) | `pytest tests/test_intake_plan.py tests/test_job_build.py` (the 16,384-character `execute` param in `test_job_build.py` was given short ids too) | **169/169 passed**, 0 errors (before the fix: 10 errors at setup/teardown, per the review). The whole M9 unit set on Windows: 675/676, the one failure being TASK-191's `utc ` zone row (see the TASK-191 report) |

## Report rows (for tests/m9/report.md)

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

## Acceptance (TASK-190 row)

"For a given `eval_spec`, payload, set of existing result uuids and batch, the plan lists exactly the rows to insert with their verdicts and snapshots and the duplicates count (CHK-M9-054 to -057, -062, -083), or refuses a batch naming a plugin outside the job (CHK-M9-053); REQ-215 (2) (CHK-M9-057), (4) (CHK-M9-058 to -061), (6) (CHK-M9-064) hold at plan level." REQ-216 (5) (two items in one batch) → CHK-M9-054.

## Notes

- CHK-M9-322 (the sibling ignored) cannot be planted here: `plan()` takes the unit's existing uuids from its caller. At plan level, a sibling's uuid passed in `existing` is a duplicate (`test_sibling_results_passed_as_existing_are_duplicates`). The plant belongs to TASK-195/199 (tester-m9b).
- `storable()` treats every surrogate code point as unstorable, including two adjacent ones built in Python. `json.loads` already joins an escaped pair, so from the route only lone ones reach it (CHK-M9-061).
