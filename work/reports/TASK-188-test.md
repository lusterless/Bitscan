# TASK-188 TEST: PASS

Tester: tester-m9, 2026-10-30. Full rigor (scan targets, high risk). REQ-208 (1), (2), (4); TS §4.4 L555, §5.2 L865, §6.4 L1151; #122 (b)–(d), #68; decisions 2026-10-30 "M9 early rulings" (1) (tag constants copied) and (3) (a case variant of one UUID is a duplicate). Code under test: `bm/services/jobs/targets.py` (impl-manager-m9, `work/reports/TASK-188-impl.md`; sha256 `d3c1180cef98390d…`). Test files (new): `manager/tests/test_scan_targets.py`, and `test_parse_target_never_raises_anything_else` in `manager/tests/test_jobs_property.py`. Plan rows: CHK-M9-025 to -032, -086.

## Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r0 | `pytest tests/test_scan_targets.py` (first run) | 71/72 passed, 1 failed (`test_every_allowed_tag_character`: **test bug**, my tag of all 66 allowed characters is over the 64 limit) |
| r1 | `pytest tests/test_scan_targets.py tests/test_jobs_property.py::test_parse_target_never_raises_anything_else` (test fixed: two tags of 64 + 2 characters) | **73/73 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 3 plants in `/root/bstest-m9-mut-<id>` | 3/3 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

## Report rows (for tests/m9/report.md)

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

## Acceptance (TASK-188 row: "REQ-208 (1), (2) and (4) hold")

- (1) three forms, lowercase storage → CHK-M9-025, -029.
- (2) every listed refusal, message names `target` and holds no input → CHK-M9-026 to -028, -030.
- (4) `scan.target` = the request plus sorted `resolved_agents` → CHK-M9-029.
- (3), resolution on PostgreSQL, is TASK-193 (tester-m9b, CHK-M9-110).

## Notes

- No mutation-table row targets TASK-188; the three plants come from the impl report's suggestions and the plan (CHK-M9-392, -392a, -392b).
- `InvalidTarget.field` is one of `target`, `target.agents`, `target.tags`, `target.all`, for TASK-205's problem detail. It is not asserted per case; the spec asks only that the message names `target`.
