# TASK-110 TEST: package search repository

Verdict: **PASS** (r1 included). Tester: tester-m5. REQ-114, REQ-115 (2), (3), (5). Plan: TP-M5-03 (CHK-M5-040 to -059).

Commands: same W run; tests/test_package_repo_pg.py 57/58 then 58/58 after the re-run of `test_five_filter_combination` (1/1; my expectation omitted the awaiting_approval host, a test bug). Plants CHK-M5-320, 325, 326, 327 (both shapes), 329, extra SQL-text interpolation and literal-only statuses: all red. L: ruff S608 plant red.

AC coverage: each filter alone, every pair, five-filter combination, all three shapes vs independent oracles (CHK-M5-041..043); 120 corpus pairs, five operators (CHK-M5-044, -045); paging N+1 incl. 1.0/1.0-0 and long non-ASCII boundaries (CHK-M5-053, -054); `q=%_\'";--`, `host=_` literal (CHK-M5-049); S608 (CHK-M5-057); read-only (CHK-M5-056); #87 probe kept as regression (CHK-M5-059).

Fixture: manager/tests/package_fleet.py (24 hosts via the M3 ingest()).
