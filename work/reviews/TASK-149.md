# TASK-149 REVIEW: import record and task repository

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-160, REQ-166, REQ-173. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `manager/bitscan_manager/repositories/imports.py` (132 non-blank lines against an estimate of 110; the extra is row types), per `work/reports/TASK-149-impl.md`. One file.

TEST: PASS (`work/reports/TASK-149-test.md`; 22 tests plus the 25 M1 grant probes). These planted faults turned it red: CHK-M7-379, CHK-M7-380 (after the tester bounded the paging walk), `finish_task` without its condition, and the order reversed.

CHK-M7-378 is rightly left to TASK-154, because the repository takes the caller's connection. The D4 rows show a record surviving a rolled-back sibling, both on another connection and on one pinned connection.

Spec read: SR §3.5, §3.6; TS §4.1 L520, §4.2 L540, §5.2 (`bit_import`, `task` in `m0004_system.py`, grants); #20, #98 (g) and (h), #107 (d), #110.

## Checks
1. **`bit_import` is a log (TS §5.3 L1049).** INSERT and SELECT only, and the grant probe still refuses UPDATE and DELETE. Every column is written; `errors` is stored as jsonb, warnings included (#110); `imported_by` NULL means the system or the CLI.
2. **Paging (#98 (h)).** Newest first by `import_id`, with a strict keyset and `limit + 1`. This is the same pattern as `audit_log.page_newest_first` and the other list repositories.
3. **Task.**
   - `insert_task` starts a `rebuild` task as `running`, with `requested_by` NULL for the CLI (#107 (d)).
   - `finish_task` is a conditional UPDATE (`AND state = 'running'`, `rowcount == 1`; builder checklist 8), so a finish that races the start-up fail changes the row once.
   - `fail_running_tasks` changes only `running` rows and sets `finished_at`.
4. **SQL.** Constant strings with bound parameters; S608 is clean, and a planted f-string is red.
5. **Re-run by me:** ruff, ruff format and mypy (CI form) are clean.

## Findings
None blocking or should-fix.

1. nit, `imports.py:25` and `:31`: `_PAGE` and `_TASK` are wrapped in `sql.SQL` with nothing composed into them; a plain `str` would do. Cosmetic only.
