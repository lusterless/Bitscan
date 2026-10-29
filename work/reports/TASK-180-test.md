# TASK-180 TEST: PASS

Tester: tester-m8, 2026-10-29. Full rigor (evaluator, high risk). REQ-195 (1)–(4); TS §4.5 L587, L603; §5.2 L880, L888; §3.5 L248; #117. Code under test: `bm/services/evaluator/eval_spec.py` (impl-manager-m8b, `work/reports/TASK-180-impl.md`). New test file: `manager/tests/test_eval_spec.py`. Plan rows: CHK-M8-110 to -116.

## Runs

| Run | Command (W, `/root/bstest-m8-base`, venv `/root/venv-m8`, `CI=true`, `PYTHONPATH` pinned) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_evaluator_verdict.py tests/test_eval_spec.py tests/test_evaluator_score.py` | 205/205 passed, 0 failed, 0 errors, 0 skipped |
| plants p1 | 12 plants (four files, 210 tests each) | 11/12 red; **x180-quote stayed green** (a test gap, mine; see below) |
| r2 (test strengthened) | `pytest tests/test_eval_spec.py` | **101/101 passed**, 0 failed, 0 errors, 0 skipped |
| plants p2 | x180-quote again, plus a second quote plant on the uuid message | 2/2 red |
| static (L) | `ruff check`, `ruff format --check`, `mypy --strict` on the test file | clean |

## Test gap found and closed (no product defect)

Plant x180-quote (`EvalSpecError("eval_spec values must be strings: " + repr(value))`) passed all of r1. My canary inputs had no non-string value holding the canary, and the "small fixed set of messages" bound was too loose. Added (r2): canary inputs as list, dict and nested values, and `test_one_fixed_message_per_refusal`, where different inputs refused for the same reason must give one identical message (six groups: name type, expected type, uuid, operator, name length, expected length). Both quote plants are now red. The product's messages are fixed and quote nothing.

## Report rows (tests/m8/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M8-110 | CODE | W | r2 | PASS | REQ-195 (1): round trip through `json.dumps(allow_nan=False)` / `json.loads` for 1, 2, 14 and 5,000 plugins (non-ASCII names), plus 500 hypothesis specs of 1–50 entries; order kept; `build` output is exactly the #117 shape (only `plugins`; each entry exactly the four string keys; lowercase uuid). `parse` doesn't mutate its input | 2026-10-29 |
| CHK-M8-111 | CODE | W | r2 | PASS | REQ-195 (2): 52 refusals, each `EvalSpecError` (a `ValueError`): not an object (list, str, int, None, bytes); `{}`; missing `plugins`; extra top keys; `plugins` dict/tuple; empty; 5,001 entries; entry not an object; each of the four keys missing; `execute`/`timeout_s`/other extra; duplicate uuid; uppercase, braced, urn, 32-hex, short, padded, int, None and `UUID`-object uuids; operator `EQUALS`/`""`/`equal`/padded; name `""` and 401 chars; expected 4,001; int/None/list/bool/float values. Accepted: 5,000 entries, name 1 and 400 (also non-ASCII), expected 0 and 4,000 (also `€`), each of the 14 operators. `EvalSpec(...)` refuses the same seven cases itself | 2026-10-29 |
| CHK-M8-112 | CODE | W | r2 | PASS | 18 canary inputs: the canary is in no `str`/`repr`/`args`/`__cause__`/`__context__`. Six refusal groups each give one identical message | 2026-10-29 |
| CHK-M8-113 | CODE | W | r2 | PASS | REQ-195 (3): `get` returns each listed entry and None for an unknown uuid | 2026-10-29 |
| CHK-M8-114 | CODE | W | r2 | PASS | REQ-195 (4): the SR §1.1 entry holds the name, `equals` and `install ok installed`; a recursive key walk finds only `plugins, plugin_uuid, name, operator, expected` (no `execute`, no `timeout_s`) | 2026-10-29 |
| CHK-M8-115 | CODE | W | r2 | PASS | Lengths count characters (`€`×400 accepted); a lone-surrogate name never crashes the parser | 2026-10-29 |
| CHK-M8-116 | CODE | W | r2 | PASS | 2,000 hypothesis JSON-like values (nested dicts/lists, NaN floats, uuids, operator names): `parse` raises only `EvalSpecError`, and anything accepted builds back to the same value | 2026-10-29 |
| CHK-M8-344 | CODE | W | plants: entry keys ⊇ (extras accepted); duplicate check off; top key `"plugins" in` | PASS (red) | 4 / 2 / 2 failed: the extra-key, duplicate and extra-top-key rows | 2026-10-29 |
| CHK-M8-345 | CODE | W | plant: `build` writes `"execute": ""` | PASS (red) | 16 failed: round trips, the shape row, the SR §1.1 key walk, the boundaries, the generated round trip | 2026-10-29 |
| extra x180-upper | CODE | W | plant: lowercase check off | PASS (red) | 1 failed: uppercase uuid | 2026-10-29 |
| extra x180-5001 / name401 / name0 / exp4001 | CODE | W | plants: each bound off by one | PASS (red) | 2 failed each: the parse row and the constructor row | 2026-10-29 |
| extra x180-types | CODE | W | plant: int accepted as a value | PASS (red) | 5 failed (`TypeError` escapes: totality) | 2026-10-29 |
| extra x180-op | CODE | W | plant: operator check off | PASS (red) | 6 failed | 2026-10-29 |
| extra x180-quote, x180-quote-uuid | CODE | W | plants: message quotes `repr(value)` | PASS (red, p2) | 3 / 2 failed: the fixed-message groups and the canary row | 2026-10-29 |

## Notes for M9 (no defect here)

- `parse_eval_spec` accepts a lone surrogate in `name` or `expected` (a valid Python `str`). PostgreSQL JSONB refuses `\ud800`, so M9's job builder can't store such a value anyway. Worth a line in M9's builder tests.
- The `<family name> - <plugin name>` composition is the caller's (M9). `build_eval_spec` stores `name` as given; the SR §1.1 row passes the composed name.
