# TASK-055 REVIEW: runtime settings (repository, typed read, patch validation)

Reviewer: reviewer. Date: 2026-10-23. REQ-083, REQ-088. Spec: TS §8.6 L1317–L1339 (seven keys, defaults, ranges, RE2 patterns, at most 50), §5.2 L827–L840 (`system_schedule` with no `enabled` column, the inventory CHECK, `setting`), §3.4 L237 and §6.2 L1129 (inventory cannot be turned off); #42 (seed JSON shapes), #68 (one object, non-empty partial patch); `.claude/rules/manager/config-and-cli.md` ("Validate every redaction pattern with RE2 before saving"). Inputs:
- `work/reports/TASK-055-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-090 to -095, `manager/tests/test_settings_service.py` and `test_settings_pg.py`; rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/bitscan_manager/repositories/settings.py` (new, 53 lines);
- `manager/bitscan_manager/services/settings/store.py` (new, 122 lines);
- `manager/bitscan_manager/services/settings/__init__.py` (re-exports);
- the tester's two test files.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Spec conformance.**
  - The seven keys and their inclusive ranges match TS §8.6 exactly:
    - `agent_token_ttl_days`: 60–730;
    - `job_pull_seconds`: 60–3,600;
    - `decommission_after_days`: 0–365;
    - `max_parallel_plugins`: 1–8;
    - `enrolment_alert_per_hour`: 1–10,000;
    - `inventory_interval_s`: 3,600–86,400.
  - `inventory_interval_s` is read from `system_schedule`, never from `setting`. A stray `setting` row is ignored, and the tester covers that.
  - `validate_patch` checks the whole patch before anything is returned, so one bad key refuses all of it. It refuses an empty patch, unknown keys (`inventory_enabled` included), booleans, floats (`300.0` too), strings and null for the integer keys, and anything but a list of at most 50 RE2-compilable strings for `redaction_patterns`.
  - An unknown key is reported as `key=None`, so the client's text is never echoed (REQ-038 rule, decisions 2026-10-21).
- **Security invariants and REQ-088.**
  - No key, field or constant names an inventory switch; the tester's AST scan covers both packages.
  - The repository only UPDATEs existing rows (`write_value` cannot insert a new key), and it has no DELETE.
  - The database CHECK still bounds the inventory interval underneath the service check.
  - RE2 is used for pattern validation, with `log_errors = False`, so a refused pattern's text is not printed to stderr by the C++ library (tested with a canary).
- **Scope.** Three files, as the task row lists. The RE2 compile was planned for TASK-069. Doing it here is required by the config rule as soon as TASK-062 can save patterns (W2, before TASK-069 in W4), so it is the binding rule applied early, not scope creep. TASK-069 keeps the `redaction_default_removed` alert and the M3 test plan items for it.
- **Tests (my run, Windows).** `test_settings_service.py`, `test_settings_pg.py` and `test_lock_files.py`: 128 passed, 15 skipped (PostgreSQL; run in WSL by the tester). ruff, format and `mypy --strict` are clean on the five files. The tests read the default patterns from the spec text itself and check them byte for byte. Each integer key is tested at both bounds and one beyond, mixed patches are refused as a whole, and the grants are probed (no DELETE or TRUNCATE on either table). These would turn red for CHK-M3-352 and CHK-M3-354.

## Findings

None block approval.

1. **nit**, `manager/bitscan_manager/services/settings/store.py:86`. `read_settings` coerces stored values with `int(...)`, so a non-integer JSON number in `setting` (only possible through a hand-written owner UPDATE) would be truncated silently rather than reported. Optional fix: treat a stored value that is not an `int` (or a bool) as `SettingsUnavailable`, the same as a missing row.

## Note for `main` and the planner

TASK-069's row says "RE2 compile of each pattern"; that part now exists in `services/settings/store.py`. TASK-069 can reuse it or move it into `redaction.py`. Either is fine, as long as only one compile check remains.
