# TASK-069 IMPL report: redaction-pattern setting

REQ: REQ-084. Spec: TS §8.6 L1324 and L1329–L1339, §8.4 L1290; security invariants (RE2); #42; PD-23 (a). Depends on TASK-062, which is approved. Lead ruling 2026-10-23: the RE2 compile stays in `store.py` (TASK-055), no second compile is added, and `log_errors = False` is kept.

## Files (2)

- `manager/bitscan_manager/services/settings/redaction.py`: new, 27 lines.
  - `DEFAULT_PATTERNS` holds the five TS §8.6 lines verbatim (raw strings, spec order). The probe checked them equal to the m0005 seeds; the service does not import the frozen migration.
  - `removed_defaults(before, after) -> list[str]` returns the defaults that were present before and are missing after, in spec order. A default removed by an earlier patch is not reported again.
- `manager/bitscan_manager/services/settings/store.py`: 12 lines added to `apply_patch`. When the patch contains `redaction_patterns` and `removed_defaults` is not empty, it writes a second alert in the same transaction: kind `redaction_default_removed`, action `settings.redaction_default_removed`, actor `user:<id>`, target `settings`, detail `{"removed": [the removed default patterns]}`.

`manager/openapi.json` is unchanged; the route already takes `redaction_patterns` (TASK-062).

## Behaviour (REQ-084)

- At most 50 patterns. Each is compiled with RE2 by `validate_patch` before anything is written; a refused pattern is never written to stderr, because `log_errors` is false. 51 patterns, an invalid pattern (for example a backreference `(a)\1`) or a non-string item refuse the whole patch with 400 and change nothing.
- **Removing a default** writes two alert entries: the usual `settings_changed` (old and new values), and `redaction_default_removed`. This follows REQ-084 (2), "one `redaction_default_removed` alert entry plus the settings alert". The patch already needs an admin TOTP session (TS §8.6 "removing a default needs a TOTP session").
- Restoring or adding patterns writes only `settings_changed`.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: pass (164 files).
- `pytest -q`: 2131 passed, 725 skipped, 0 failed.
- OpenAPI export: unchanged.
- **Scratch probe**: `apply_patch` with a fake repository seeded from m0005.

  | Patch | Result |
  | --- | --- |
  | (check) | defaults equal the seeds |
  | remove default 3 | `settings_changed` plus `redaction_default_removed` naming exactly pattern 3 |
  | add one with 3 already gone | only `settings_changed` |
  | restore the five defaults | only `settings_changed` |
  | read back | the five patterns round-trip byte for byte |
  | 50 non-default patterns | stored; a `redaction_default_removed` alert listing all five defaults |
  | 51 patterns | refused with key `redaction_patterns`; nothing changed, no alert |
  | `(a)\1` | refused the same way; no RE2 output on stderr |
  | `[1]` | refused the same way |

- PostgreSQL round trip (TP-M3-23): **NOT RUN locally**; WSL.

## Deviations

None.

## Revision 1 (tester-b FAIL round 1: two 500s instead of 400)

1. **`nul-in-pattern`:** RE2 compiles a pattern holding U+0000, but PostgreSQL jsonb refuses `\u0000` when the value is written, so the request answered 500.
2. **Lone surrogate (`"a\ud800b"`):** `re2.compile` raises `UnicodeEncodeError`, not `re2.error`, which `_compiles` did not catch, so the request answered 500.

**Fix:** `services/settings/store.py` `_compiles` only. This is still the one RE2 compile, with `log_errors` off.
- A pattern containing U+0000 is refused first.
- `pattern.encode("utf-8")` and the compile now run in one `try`, which catches both `UnicodeEncodeError` and `re2.error`.
- Either refusal raises `SettingsInvalid("redaction_patterns")`. The request gets 400 and nothing changes. The NUL is written in the source as the escape `"\x00"`; the file holds no NUL byte.

**Probe:** with the five defaults plus one extra pattern:

| Extra pattern | Result |
| --- | --- |
| `a\x00b` | refused |
| `a\ud800b` | refused |
| `(a)\1` | refused |
| `ok+` | accepted |
| `café` | accepted |

**Gates (Windows):** ruff, ruff format and `mypy --strict` pass (172 files). `tests/test_settings_service.py` plus `tests/test_redaction_setting.py`: 115 passed.
