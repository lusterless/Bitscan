# TASK-109 TEST: package search query parsing

Verdict: **PASS**. Tester: tester-m5. REQ-113 (1). Plan: tests/m5/test-plan.md TP-M5-02 (CHK-M5-010 to -025).

Commands (W, CI=true, /root/venv-m5): `pytest -q -n 4 -rfE tests/test_package_query.py tests/test_csv_export.py tests/test_package_repo_pg.py` -> 359/360 passed, 1 failed (test bug in TASK-110's file, see TASK-110-test), 0 errors, 0 skipped; tests/test_package_query.py 171/171. `tests/test_module_imports.py` 104/104. Plants (CHK-M5-321..324, 330 half, 353 half): all red; control 360/360. L: ruff `import re` plant red (TID251).

AC coverage: q<3 refused, q=abc accepted; q with name; version_op w/o version; ne/removed/name refused; os forms (#83 (c)); agent_id not-a-uuid; each #83 (h) limit at and one over; empty and U+0000 refused (#88); every corpus version accepted -> report rows CHK-M5-010..025. Detail names parameters only (canary never in the exception): CHK-M5-022; the route half of REQ-113 (2) is TASK-113.

Notes: installed statuses asserted as the user rulings ({install, hold, deinstall} ok installed). parse_search also refuses lone surrogates (implementer addition, harmless). `~1`/`.1` are refused (plan rule: upstream starts with a digit; dpkg itself only warns).
