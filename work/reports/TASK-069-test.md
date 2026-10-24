# TASK-069 TEST report: redaction-pattern setting

**Verdict: PASS** (2026-10-23, tester-b), on revision 1. REQ-084 (1) to (4). Plan checks: CHK-M3-215 to -218. Code tested: `bm/services/settings/redaction.py`, `bm/services/settings/store.py` (`work/reports/TASK-069-impl.md`).

## Tests added
- `manager/tests/test_settings_redaction_pg.py`: 33 tests (marker `pg`) through `PATCH`/`GET /api/v1/settings` on PostgreSQL, with the TASK-062 environment and its row restore.
- `manager/tests/test_redaction_setting.py`: 4 unit tests (spec defaults, `removed_defaults`, one RE2 compile, the G1 plant on a temporary copy).

## Commands
- W (`CI=true`): 232 passed, 0 skipped (with the TASK-055 and TASK-062 suites), no container left.
- L: 4 passed; ruff, format, mypy clean (172 files).
- Plants (WSL copies, control 142 passed): 12 of 12 red (tests/m3/report.md CHK-M3-215-mut).

## Acceptance criteria
- 50 valid patterns stored; 51, an invalid RE2 pattern and a non-string refused with no change: CHK-M3-215 PASS.
- Removing default 3 writes one `redaction_default_removed` alert plus the settings alert: CHK-M3-216 PASS.
- G1 finds no stdlib `re`: CHK-M3-218 PASS.
- The five defaults read back byte for byte after GET and PATCH round trips: CHK-M3-217 PASS.

## Carry-overs
- RE2 `log_errors` off (the fd-level stderr test passes; planting it on is red); one RE2 compile only, in `store.py`; the `redaction_default_removed` alert: all PASS.

## Round history
- Round 1 FAIL: `PATCH` with a pattern containing U+0000 → 500 (jsonb refuses it), and a lone-surrogate pattern → 500 (`re2.compile` raised `UnicodeEncodeError`). Fixed in r1 inside `_compiles`, still the single compile.
