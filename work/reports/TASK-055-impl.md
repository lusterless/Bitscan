# TASK-055 IMPL report: runtime settings (repository, typed read, patch validation)

REQ: REQ-083, REQ-088. Spec: TS §8.6 L1317–L1339, §5.2 L827–L840, §3.4 L237, §6.2 L1129; #42, #68.

## Files (3)

- `manager/bitscan_manager/repositories/settings.py`: new, 53 lines.
- `manager/bitscan_manager/services/settings/store.py`: new, 122 lines.
- `manager/bitscan_manager/services/settings/__init__.py`: new, 27 lines (re-exports).

## Repository (`SettingsRepo(conn)`, inside the caller's transaction)

- `read_values() -> dict[str, Any]`: every `setting` row, with the JSONB value decoded.
- `schedule_interval(job_kind) -> int | None`: reads `system_schedule`. TASK-071 also uses it for `offline_sweep`.
- `lock_settings()`: `SELECT … FOR UPDATE` over every setting row, in key order. It is for TASK-062's atomic apply.
- `write_value(key, value, updated_by, now) -> bool`: an UPDATE only. It never inserts, so no new key can appear.
- `write_schedule_interval(job_kind, interval_s) -> bool`: also an UPDATE only. `system_schedule` has no `enabled` column, and the database CHECK still bounds the inventory interval to 3,600–86,400.

## Service (`services/settings`)

- `KEYS` lists the seven TS §8.6 keys in table order. `INT_RANGES` holds the six integer keys with their inclusive ranges, `inventory_interval_s` 3,600–86,400 included.
- `Settings` is a frozen dataclass with the seven typed fields. `as_dict()` returns the GET body (#68: one object, all seven keys).
- `read_settings(repo) -> Settings` takes the six `setting` rows plus `inventory_interval_s` from `system_schedule`. A missing row raises `SettingsUnavailable`.
- `validate_patch(patch) -> dict` is pure and checks the **whole** patch before anything is written. It raises `SettingsInvalid(key)` when:
  - the patch is empty, or holds any unknown key. `inventory_enabled` is one such key, and `key` is then None, so the client's key is never echoed (REQ-038).
  - an integer key is not an `int`, or is a `bool` or a float such as `300.0`, or is outside its range.
  - `redaction_patterns` is not a list of at most 50 strings, or any one pattern fails to compile with **RE2**.
- **RE2 now, not in TASK-069:** I compile each pattern here, because the config rule says "Validate every redaction pattern with RE2 before saving". Without it, `PATCH /settings` (TASK-062, W2) could store an uncompiled pattern before TASK-069 (W4) arrives. TASK-069 still adds the `redaction_default_removed` alert, and may move the check into `redaction.py`.
- RE2 is compiled with `log_errors = False`. By default the RE2 C++ library writes a refused pattern's text to stderr, outside the JSON logs.

## Local gates (Windows)

- `ruff check manager` and `ruff format --check manager`: pass. `mypy --strict`: pass for `bitscan_manager`.
- `pytest -q`: 1198 passed, 451 skipped. The 2 failures are the expected `test_alerts.py` ones from TASK-056.
- Scratch probe with a fake repository holding the m0005 seeds: `read_settings` returns the seven defaults. Each integer key validated at its minimum and maximum. One below, one above, `True`, `float(min)` and `str(min)` were each refused, naming the key. 50 patterns were accepted; 51, `(a)\1` (a backreference), a non-string item and a bare string were refused. An unknown key (`inventory_enabled`) and an empty patch were refused with `key=None`. A mixed patch was refused as a whole, naming the bad key.
- PostgreSQL read of the seeds: **NOT RUN locally** (Docker unavailable); this is part of TP-M3-09.

## Deviations

None. The RE2 compile is the binding rule applied early, as explained above.
