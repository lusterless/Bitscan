# TASK-260 REVIEW: results CSV memory documented as a known v1 limit (#155)

Reviewer: reviewer-m11, 2026-11-09. Round 1. Low risk (docs), one approval.

Verdict: APPROVED

**Scope reviewed:** against HEAD `c090303`:
- `README.md` (+1 bullet under Scan results → CSV export)
- `deploy/runbooks/manager-operations.md` (+6 lines, a new §8 Known limits)

**Checked against:** the user's #155 decision (decisions 2026-11-09 (1), option (a): no code change, document the limit), #146 (e), (f), TS §4.5 L601 (output caps), TS §6.2 L1123.

**Reports:** `work/reports/TASK-260-impl.md`, `work/reports/TASK-260-test.md` (PASS: facts checked against the code, `check_runbook_text.py` 0 new findings, README walks 4/4).

## Checks

- **The decision is applied as recorded:** it is documented only. No code, cap or setting changed.
- **The facts match the code and spec:**
  - The full in-memory build matches `results_read.results_csv`, which builds the text before the response.
  - The 100,000-row cap matches `CSV_MAX_ROWS`.
  - The output caps of 64 KiB and 16 KiB match `STDOUT_CAP` and `STDERR_CAP` and TS §4.5 L601.
  - The figure of about 8 GB is 100,000 × 80 KiB. The runbook's "and more while the file is written" covers the text and byte copies, as the #155 note said.
  - A viewer's export has no output columns, which matches `include_output` and TASK-244 CHK-M11-222.
  - The advice to narrow the export works, because the two filters, `status` and `agent_id`, exist on `results.csv`.
- **The two notes agree.** KiB in the README is exact for the byte caps, and KB in the runbook follows the spec's wording. Both are accurate.
- **§8 is appended after §7.** §1 to §7 and their shell blocks are unchanged, so the harnesses that index them by position are unaffected.
- **No secret, token, DSN or process note:** the checker agrees.

## Findings

None.
