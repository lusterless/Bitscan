# TASK-165 REVIEW: import history route `GET /api/v1/imports`

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-28. REQ-173, REQ-174. Low risk: one review round.

Scope reviewed, per `work/reports/TASK-165-impl.md`:
- `manager/bitscan_manager/api/user/imports.py`: new, 65 non-blank lines.
- `manager/bitscan_manager/api/user/__init__.py`: +2 lines.
- `manager/openapi.json`: +270 lines, additions only (`git diff --stat` shows 0 deletions).

Three files, within the row.

TEST: PASS (`work/reports/TASK-165-test.md`, tester-m7). r0 ran 142/142 on WSL with 0 skipped. All 5 security plants went red: RBAC lowered, auth removed, cursor shape check removed, scope fallback, HMAC check removed.

My checks:
- `ruff check` and `mypy --strict` (CI config) are clean on the new module.
- A fresh `python -m bitscan_manager.app` export is byte-identical to `manager/openapi.json` (G6).

Spec read:
- TS §6.2 L1107 (`GET /imports`, admin).
- TS §6.3 L1134 (cursor, limit up to 500) and L1139 (catalog keys are integers).
- TS §6 L1056 (route groups).
- SR §3.5.
- #98 (h), (i); #48.
- Decisions 2026-10-28, "TASK-154 and TASK-165 rulings": the direct repository read follows the `GET /audit-log` precedent, so it isn't flagged.

## Checks
1. **RBAC and route group.** The route uses `require_role("admin")`, which accepts an admin session or API token and requires TOTP enrolment, like the approved admin reads. It isn't a sensitive action in TS §6.2, so an API token is correct. It is mounted in the user router, so only `bsu_` and `bsk_` tokens are accepted: `bsa_` and `bse_` get 401 (CHK-M7-282, with a plant).
2. **Shape (#98 (h), (i)).** The response holds all twelve `bit_import` columns in table order, with `import_id` as a JSON integer and `imported_at` in RFC 3339 UTC. `errors` holds the four-key findings (#110). There are no filters, and `limit` and `cursor` come from the shared `page_params`.
3. **Cursor.** It is HMAC-checked and scoped `imports`. The decoded key is shape-checked (`type(key) is int`, 1 to 2^63 − 1) before the parameterised keyset query, so a bad cursor gets 400, never 500 (builder checklist 1). The Problem text is fixed and never echoes input (checklist 12).
4. **Data handling.** The route only reads, through the TASK-149 parameterised query in one transaction, and writes nothing. Stored text comes back unchanged as JSON strings, and rendering it as plain text is the UI's job (TS §6.3 L1141, TASK-172).
5. **Scope.** The route adds no route that runs or queues anything, changes no agent route, and has no dead code.

## Findings
None blocking or should-fix.

1. nit, `imports.py:72`: `principal` is bound only to enforce the dependency. That matches the other admin reads, so no change is needed.
