# TASK-109 REVIEW: package search query parsing

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (package search). Not a two-approval task.

Scope reviewed: `manager/bitscan_manager/services/packages/__init__.py` and `manager/bitscan_manager/services/packages/query.py` (`work/reports/TASK-109-impl.md`). Sources: TS §7.1, §6.3, REQ-113, #83 (b), (c), (g), (h), #88 and REQ-038 (2).

TEST: PASS (`work/reports/TASK-109-test.md`). `test_package_query.py` is 171/171 and `test_module_imports.py` 104/104. Plants CHK-M5-321 to -324 are red, and so is the `import re` (TID251) plant.

## Checks
1. Spec:
   - These are the eleven TS §7.1 names. `version_op`, `status` and `group_by` take only their enums.
   - `q` must be at least 3 characters and cannot be combined with `name`. `version_op` needs `version`.
   - Each #83 (h) length is counted in code points, as `VARCHAR` counts. Empty values and U+0000 are refused (#88).
   - `os` must be `<id>` or `<id>:<version>`, at most 32 and 16 characters (#83 (c)).
   - `agent_id` must be the hyphenated form only (M3 ruling).
   - `version` must be dpkg syntax (#83 (g)): a numeric epoch that fits an int32, an upstream part starting with a digit, a colon only after an epoch, and the revision character set. The whole M1 dpkg corpus is accepted.
2. Security:
   - `InvalidSearch` carries only parameter names, never values (canary test CHK-M5-022).
   - No regular expression: plain ASCII sets, so the RE2 rule is not triggered.
   - `cursor_scope` binds the shape and every filter field through a SHA-256 of canonical JSON. The M2 HMAC cursor machinery then authenticates it, so a cursor reused with other filters is refused (#83 (b)). `status=installed` and an omitted `status` share a scope, which is correct because they are the same filter.
3. Scope: 2 files, about 190 lines.
4. Re-run by the reviewer (Windows): ruff and format are clean, and `mypy --strict` is clean. `pytest tests/test_package_query.py tests/test_csv_export.py` gave 302 passed; this is a sanity check only, and the WSL run is the evidence.

## Findings
1. nit, `query.py:111`. Versions such as `~1` or `.1` are refused because the upstream part must start with a digit. dpkg only warns on those and still installs them, so an agent can report one, and then no exact `version=` search can find it. The plan's rule is followed, and real archive packages never have such versions. No change; the tester already recorded it.
