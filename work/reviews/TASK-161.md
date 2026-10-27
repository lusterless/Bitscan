# TASK-161 REVIEW: profiles service and routes

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-168, REQ-169, REQ-174, REQ-178. main rated it high risk, and it gets the user's second look (PD-35: `PATCH` re-enables profiles).

Scope reviewed: per `work/reports/TASK-161-impl.md`, these files:
- `manager/bitscan_manager/services/importer/profiles.py` (new, 87 lines);
- `manager/bitscan_manager/api/user/policies.py` (new, 170 lines);
- `manager/bitscan_manager/api/user/__init__.py` (+2);
- `manager/openapi.json` (+674; `git diff` shows 0 removed lines).

The size was kept as one task by the lead and is not a finding.

TEST: PASS (`work/reports/TASK-161-test.md`; 59 new tests, affected suites 154/154). These plants turned it red:
- PATCH role lowered to operator;
- CHK-M7-353, the re-enable not alerted;
- CHK-M7-361, `execute` in the PATCH body (red in G6 and G34).

The tester changed one pin, `test_invariants_m3.py`. `GET /policies` is now pinned to exactly `{limit, cursor, status}`, and the general query-name set is unchanged, so no parameter can switch inventory off.

Re-run by me on Windows:
- `tests/test_openapi.py` and `tests/test_invariants_m3.py`: 39 passed;
- ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager`: clean (271 files).

Spec read: TS §6.2 L1100–L1102 (route table), L1084 (sensitive actions); §4.3 L546–L548; §6.3 (errors, pagination, plain text, ids); §8.4 L1290; #9, #98 (a)–(c), (i), (k), #101, #104 (d).

## Checks
1. **RBAC (TS §6.2).**
   - Both GETs need viewer; PATCH needs admin, by session or API token. PATCH is not in the L1084 sensitive list, so it has no TOTP-session or sink gate, which is correct.
   - `bsa_`, `bse_`, no token and a garbage token get 401 on all three operations (user router).
   - A restricted admin session gets 403, as on the other admin routes.
2. **PATCH body (REQ-168 (1)).** Only `{"policy_status": "enabled"|"disabled"}` or `{"status_overridden": false}` is accepted. `extra="forbid"`, `StrictBool` and the `model_fields_set` check refuse every other body, including `execute`, both keys, `true` and `null`, with fixed 400 text. No route edits plugins or commands.
3. **Decision under the row lock (checklist 9).**
   - `change_status` locks the row, refuses unknown (404) and deleted (409 `conflict`), and applies the TASK-150 update.
   - It writes one `policy.status_change` entry in the same transaction, even for a no-op (REQ-168: every change is audit-logged).
   - The `policy_reenabled` alert fires only for locked `disabled` → new `enabled`, by an override or by clearing one onto an enabled file (TS §8.4 L1290, #101).
   - The sink is woken on commit.
   - A concurrent import keeps the override (TASK-148 D3; covered by the race tests in TASK-150 and TASK-151).
4. **Cursor before the casts (my TASK-150 carry, checklist 1).**
   - The cursor is HMAC-checked by `decode_cursor`, then shape-checked before any cast: a name of 1–128 characters without U+0000, and an `int` id (not `bool`) in 1..2^63−1.
   - Garbage, another list's cursor, and out-of-range values give 400, never 500.
5. **Ids (REQ-169 (3), #98 (i)).**
   - The path takes ASCII digits only (`+1`, `1.0`, `1_0`, `١` → 400).
   - `0` and values above the bigint range give 404, never a 500.
   - Body ids stay JSON integers.
6. **Shapes (#98 (a), (b); #9).**
   - The list holds non-deleted policies only, with `?status=deleted` → 400, in `(policy_name, policy_id)` order as `{items, next_cursor}`.
   - The detail adds `deleted_at` and the plugins in `sort_order`, with `display_name` from `v_plugin`.
   - Text comes back byte-identical as JSON strings.
   - `execute` is visible to viewers as catalog content (#98 (b)); no stdout or stderr appears.
7. **Audit target.** It is always `policy:<id>`, well within `VARCHAR(255)` (checklist 16).
8. **Layering and OpenAPI.**
   - The handler only parses and validates the id, cursor and body, and maps exceptions to fixed-text problems; the service holds the logic.
   - The export is byte-stable (G6), additions only, with no component clash and no 422.

## Findings
None blocking or should-fix.

1. nit, `policies.py:164`: PATCH declares its body, so a malformed body gets 400 before the token check. That matches the approved `users` and `settings` PATCH routes. A bad body gives 400 whatever the token, so it is not an oracle; the per-IP failed-check count simply sees only well-formed requests. No change for consistency's sake. A route-class change would apply to all user PATCH routes alike and is not this task's.
2. nit, `profiles.py:67` (`_status`): a guard that cannot fire, because the enum has only two values. Harmless.

## For the user's second look (PD-35)
- `PATCH /policies/{id}` lets an admin (session or API token) set a profile's effective status with an override, or clear the override back to the file's status.
- Every PATCH is audit-logged. A change from disabled to enabled raises the `policy_reenabled` alert.
- It cannot touch plugins, commands, scans or files.
