# TASK-165 REVIEW: import history route `GET /api/v1/imports`

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-173, REQ-174; #98 (h), (i), #110. Low risk; one round.

Scope reviewed: frozen worktree at `0d16604`. The product code came in with `7456345` and is unchanged since; I ignored the TASK-154 pipeline files. Per `work/reports/TASK-165-impl.md`:
- `manager/bitscan_manager/api/user/imports.py` (new, 70 lines);
- `api/user/__init__.py` (+2);
- `manager/openapi.json` (+228, 0 removed).

That is within the row's budget of about 70 lines plus the generated file.

TEST: PASS (`work/reports/TASK-165-test.md`; 79/79, 8/8 plants red). The test file in the worktree has the sha256 the tester gave (`627d7690…cb70`).

Re-run by me:
- `test_imports_api_pg.py`, `test_openapi.py` and `test_invariants_m3.py` on PostgreSQL: 118 passed.
- `ruff check`: clean. `ruff format --check`: 283 files formatted. `mypy --strict` on `api/`: clean.

## Checks
1. **Spec.**
   - TS §6.2 L1107: admin by session or API token, and no TOTP-session gate, since this is not a sensitive action.
   - The 403s for operator and viewer come from `require_role`.
   - The route is on the user router, so `bsa_`, `bse_` and no token get 401. The test of an agent prefix whose hash matches an admin token is a good addition.
   - Every `bit_import` column is returned in DDL order. `import_id` is an integer (#98 (i)), and `mode`/`outcome` are the CHECK literals.
   - `errors` is passed through as stored, warnings included (#110).
   - Rows come newest first by `import_id`, with no filters (#98 (h)).
2. **Cursor (checklist 1).**
   - It is HMAC- and scope-checked, then must be an `int` (not `bool`) in 1..2^63−1 before the cast.
   - A tampered cursor, another list's cursor, a bad key, or a dict key gives 400, never 500.
3. **Safety.**
   - It only reads: one transaction, no write, and no audit entry or alert.
   - The SQL is TASK-149's parameterised `_PAGE`.
   - A hostile `file_name` comes back as the same bytes.
   - No other method exists on the path, and the 600-per-minute limit applies.
4. **OpenAPI (G6).** The diff only adds: the path and the `ImportItem` and `Page_ImportItem_` components. There is no component clash and no 422; `limit` has `maximum: 500`.

## Findings
None blocking or should-fix.

1. nit, `imports.py:24` and `:68`, layering (CLAUDE.md "api → services → repositories"). The handler calls `repositories.imports.imports_newest_first` directly, with no service in between.
   - **Why it is acceptable here.** It holds no business logic: it only checks the cursor as input and maps rows to the model. It follows the approved `GET /audit-log` (`api/user/audit_log.py:28`, `:57`). A pass-through service would add a file and no behaviour.
   - **For main.** This is now the second route built this way. Please record in `work/decisions.md` that a plain paginated read with no rules may call its repository read directly, so the next reviewer doesn't reopen the question. Anything that applies rules still goes through a service.
