# TASK-069 REVIEW: redaction-pattern setting

Reviewer: reviewer. Date: 2026-10-23. REQ-084. Spec: TS §8.6 L1324 (RE2 patterns, at most 50; removing a default needs a TOTP session and alerts), L1329–L1339 (the five defaults, exactly as written), §8.4 L1290 ("settings or redaction list changed", "a default redaction pattern removed"); security invariants "Data handling" (RE2 for every untrusted pattern); #42; PD-23 (a). Lead ruling 2026-10-23: the RE2 compile stays in `store.py` (TASK-055), with no second compile, and `log_errors = False` is kept. Inputs:
- `work/reports/TASK-069-impl.md`, including "Revision 1";
- `work/reports/TASK-069-test.md`: round 1 FAIL (a NUL and a lone-surrogate pattern each gave 500), then PASS on revision 1 (33 PostgreSQL tests plus 4 unit tests; 232 passed in WSL; 12 of 12 plants red).

Files reviewed:
- `manager/bitscan_manager/services/settings/redaction.py` (new, 27 lines);
- `manager/bitscan_manager/services/settings/store.py` (the `apply_patch` alert; `_compiles` in revision 1);
- the tester-b tests.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Spec conformance.**
  - `DEFAULT_PATTERNS` holds the five TS §8.6 lines verbatim as raw strings, in spec order. The tester checks them against the spec text and the m0005 seeds, and they round-trip byte for byte through GET and PATCH.
  - A patch with `redaction_patterns` is limited to 50 strings, each compiled once with RE2 by `validate_patch`. That covers 51 patterns, a backreference, a lookaround, a non-string item and a bare string.
  - Revision 1 also refuses U+0000 (`jsonb` cannot store it) and a lone surrogate (RE2 cannot encode it). Each answers 400 `Invalid request: body.redaction_patterns`, the whole patch is refused, and nothing changes, where round 1 gave 500.
- **Alerts.**
  - Removing any default that was present writes one `redaction_default_removed` alert, with detail `{"removed": [the removed defaults]}`, in addition to the `settings_changed` alert, in the same transaction. That is REQ-084 (2), which names both entries.
  - An edited default counts as removed. Reordering removes nothing. A patch without the key, or one restoring defaults, never alerts a removal. A default removed earlier is not reported again.
  - The PATCH already requires an admin TOTP session with the sink gate (TASK-062), which covers "removing a default needs a TOTP session".
- **Security invariants.**
  - RE2 only: a G1 plant (`import re` in `redaction.py`) is red, and `grep` finds no stdlib `re` in `bitscan_manager`.
  - Refused pattern text never reaches stderr (`log_errors` off) or the error message.
  - Patterns are not secrets, so the alert detail may name them. No other change.
- **Scope.** Two files. `store.py` was listed for this task. `manager/openapi.json` is unchanged, since the route already took the key.
- **Tests (my run, Windows).** `test_redaction_setting.py`, `test_settings_redaction_pg.py`, `test_settings_service.py` and `test_settings_api_pg.py`: 115 passed, 102 skipped (PostgreSQL; run in WSL by tester-b). ruff and format are clean, and `mypy --strict` is clean on the whole tree (174 files). `store.py` contains no NUL byte; the check uses the `"\x00"` escape.

## Findings

None.

## Note

M10 (the runner's redaction) must apply these patterns exactly as stored, with RE2, before truncation (TS §3.5). The agent receives them in the compliance Job's `redaction_patterns` (TASK-048), so no further manager change is needed for M3.
