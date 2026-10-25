# TASK-113 REVIEW: package search service and `GET /api/v1/packages/search`

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (package search). Not a two-approval task.

Scope reviewed:
- `manager/bitscan_manager/services/packages/search.py`: `search()` and the `SearchStore` Protocol;
- `manager/bitscan_manager/api/user/packages.py`: `search_params`, the item models, `_anchor`/`_key` and `search_packages`;
- `manager/bitscan_manager/api/user/__init__.py`;
- the re-exported `manager/openapi.json` (`work/reports/TASK-113-impl.md`).

The `/search.csv` route and `export_csv` in the same files belong to TASK-114 and are not covered here. Sources: TS §6.2 L1117, §6.3 L1133–L1136, §7.1, REQ-113..115, #83 and #89, and the approved TASK-110 query and repository.

TEST: PASS (`work/reports/TASK-113-test.md`, CHK-M5-120..134). Plants CHK-M5-328, -330 (route), -335, -352 and -353 (route) are red.

## Checks
1. Spec:
   - The eleven TS §7.1 parameters are present, with their lengths and the `version_op`, `status` and `group_by` enums. `status` defaults to `installed`.
   - The three row shapes have exactly the TS §7.1 keys, in that order, with no `package_id`.
   - Every response is `{items, next_cursor}`, and an empty result is `next_cursor: null`.
   - `limit` is 1–500 through the shared `page_params`.
   - `parse_search` re-checks every rule, including q ≥ 3, q with name, and version_op without version.
2. Order and auth:
   - `require_role("viewer")` is the first dependency and raises before the query dependency is solved. A bad token is therefore 401 and counted, even with bad parameters.
   - Only `bsu_`/`bsk_` tokens are accepted, and the 600/min limit applies (CHK-M5-126, -129).
   - There is no request body.
3. Cursors:
   - Each cursor is HMAC-bound to `cursor_scope()`, that is, the shape plus every filter (#83 (b)). Its key holds only ids, so its length never depends on stored text (#89).
   - `_anchor` refuses a bool used as an int, a wrong arity, a shape mismatch and a non-UUID string. `AnchorGone` gives 400 `query.cursor`.
4. Error text: every `detail` is built from parameter names only and never from a client value (checklist 12).
5. Data handling:
   - The SQL is in the approved `PackageSearchRepo`, parameterised, with `::debversion` comparisons (checklist 2, reviewed in TASK-110).
   - NUL, wildcard and invalid-version inputs never give a 500 (CHK-M5-130..132, checklist 1).
   - The route writes and audits nothing.
6. Re-run by the reviewer:
   - `ruff check` and `ruff format --check` pass.
   - `mypy --strict` passes (110 files).
   - A fresh OpenAPI export is byte-identical to `manager/openapi.json` (checklist 13). The document has no 422 on this operation.
7. Scope: within the plan. Layering is api → services → repositories, and the route holds no business logic.

## Findings
None. `web/src/api/schema.d.ts` stays behind until TASK-124 regenerates it.
