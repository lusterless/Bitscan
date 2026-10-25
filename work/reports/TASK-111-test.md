# TASK-111 TEST: CSV writer with formula escaping

Verdict: **PASS**. Tester: tester-m5. REQ-116 (1), (2), (4). Plan: TP-M5-04 (CHK-M5-080 to -086).

Commands: same W run; tests/test_csv_export.py 131/131. Plants CHK-M5-331, 332 and escape-after-quoting: all red.

AC coverage: every trigger and every #84 (d) whitespace-then-trigger form gets exactly one `'`; `a=b`, `1-2`, `'=x`, empty, plain unchanged; RFC 4180 quoting after the prefix; `=HYPERLINK("http://x")` -> `"'=HYPERLINK(""http://x"")"`; header escaped; CRLF, no BOM.

Note (#84 (d) as approved): ` \t1` and LF-first cells are not prefixed (tab/CR count only as the first character).

## Revision 1: PASS
Oracle updated to the lead's ruling (leading whitespace run holding tab or CR is prefixed). tests/test_csv_export.py 142/142 (run m5-t113b, 150/150 total). Plant of the old condition red on ` \tabc` (8 failed). Rows CHK-M5-080..086 (r1), -360.
