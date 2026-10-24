# TASK-055 TEST report: runtime settings (repository, typed read, patch validation)

**Verdict: PASS** (2026-10-23, tester). REQ-083 (1), (2), (3) at the service and repository level, and REQ-088 (2). Plan checks: CHK-M3-090 to -095. Code tested: `bm/repositories/settings.py`, `bm/services/settings/{__init__,store}.py` (`work/reports/TASK-055-impl.md`).

## Tests added
- `manager/tests/test_settings_service.py`: 111 tests (L). The TS §8.6 defaults and redaction patterns are read from the spec file as the oracle.
- `manager/tests/test_settings_pg.py`: 15 tests (marker `pg`, W). They run as `bitscan_app` and restore every changed row as owner.

## Commands
- L: `PY -m pytest tests/test_settings_service.py` → 111 passed; ruff, format and mypy clean.
- W (`CI=true`): `tests/test_settings_pg.py tests/test_settings_service.py tests/test_seeds_partitions.py` → 134 passed, 0 skipped, no container left.
- Plants, each in a throwaway copy. Control green, every plant red:
  - L, 10 plants:
    - CHK-M3-354 (range widened);
    - CHK-M3-352 (`inventory_enabled` accepted);
    - bound off by one;
    - bool as int;
    - RE2 compile skipped;
    - RE2 logging on;
    - 51 patterns;
    - interval read from a setting row first;
    - empty patch accepted;
    - unknown key echoed.
  - W, 3 plants: upsert in `write_value`; missing key filter (first planted with an untyped parameter, which failed for a typing reason, then re-planted typed and red for the planted reason); wrong schedule kind.

## Acceptance criteria
- "On a migrated database the read returns the seeded defaults with `inventory_interval_s` from `system_schedule`": CHK-M3-090 PASS.
- "every key at its minimum and maximum validates, one beyond … fails": CHK-M3-091 PASS.
- "a wrong type and an unknown key (including `inventory_enabled`) fail": CHK-M3-091, CHK-M3-094 PASS.
- "a patch with one bad key fails as a whole": CHK-M3-092 PASS.
- REQ-083 (3) at the service: CHK-M3-093 PASS. The 400/500 distinction through the route (CHK-M3-354 as worded in the mutation table) is re-checked in TASK-062 TEST.

## Notes
- The RE2 compile already lives in TASK-055 (the impl report explains why). TASK-069 TEST will re-run these cases through `PATCH /settings`.
- RE2's default C++ logging writes a refused pattern to stderr. The test guards against that at file-descriptor level, so moving the check into `redaction.py` (TASK-069) must keep `log_errors = False`.
