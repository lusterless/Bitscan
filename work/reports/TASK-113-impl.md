# TASK-113 IMPL: package search service and `GET /api/v1/packages/search`

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-113, REQ-114, REQ-115. Plan: `work/plans/TASK-113.md`. TS §6.2 L1117, §6.3 L1133–L1136, §7.1.

## Files

- `manager/bitscan_manager/services/packages/search.py` (new): `SearchStore` Protocol, `Anchor`, `Found`, `search(store, query, limit, after)`. It dispatches on `group_by`, and an anchor of the wrong type for the shape is a `TypeError`, a programming error the route cannot produce. `AnchorGone` passes through.
- `manager/bitscan_manager/api/user/packages.py` (new):
  - `search_params` declares the eleven TS §7.1 parameters with the `MAX_LEN` lengths and the three `Literal` enums. `os` is declared as `os_` with `alias="os"`, and `agent_id` as a string of at most 36 characters.
  - It calls `parse_search`. `InvalidSearch` becomes 400 `invalid_request` with detail `Invalid request: query.<p>[, query.<p>]`, built from parameter names only.
  - Item models `PackageRowItem`, `PackageGroupItem`, `HostGroupItem`, with exactly the TS §7.1 keys in that order and no `package_id`.
  - Route `search_packages`.
- `manager/bitscan_manager/api/user/__init__.py`: one import and one `include_router(packages.router)`, after `agents`.
- `manager/openapi.json`: **re-exported**. 513 lines were added and none removed: the operation, its 13 query parameters with lengths and enums, the 200 `anyOf` of `Page_PackageRowItem_`, `Page_PackageGroupItem_` and `Page_HostGroupItem_`, the three item components, and 400/401/403/429/503 as problem+json. Two exports compared byte-identical.

## Route steps

1. `require_role("viewer")` comes first (`bsu_`/`bsk_` only; 600/min). Then the parameters: FastAPI's own checks (lengths, enums, limit 1–500) give the M2 validation 400, and `parse_search` re-checks every rule.
2. A cursor is decoded with `decode_cursor(query.cursor_scope(), cursor)`, so a cursor from other filters or another `group_by` fails the scope check (CHK-M5-328). Its key must be the shape's id form: `[int, uuid-str]`, `[int]` or `[uuid-str]`, with bool rejected as an int. Anything else is 400 `query.cursor`.
3. One READ COMMITTED transaction runs `service.search(PackageSearchRepo(tx.conn), query, limit + 1, after)`. `AnchorGone` becomes 400 `Invalid request: query.cursor`.
4. `next_cursor` holds the ids of the last item on the page, or null when there is no extra row. Cursor length never depends on stored text (#89, CHK-M5-352).
5. The response is the shape's `Page`; an empty result is `{"items": [], "next_cursor": null}`. Text is returned verbatim. Nothing is written and nothing is audited.

## Ad-hoc sanity (not a test file)

- `_key` and `_anchor` round-trip for all three shapes.
- `_anchor` refuses `[True, uuid]`, a short key, a shape mismatch, a non-UUID string and a bare int.
- `search_params(q="ab")`, `(q="abc", name="x")` and `(name="")` give 400 with `query.q`, `query.name, query.q` and `query.name`.
- Without a runtime the route answers 503, like every user route (`get_runtime`). Token-group and data behaviour need the PostgreSQL harness (TP-M5-06).

## Checks run (from `Bitscan-m5/manager`, M3 venv)

`ruff check`, `ruff format --check` and `mypy --strict` on `bitscan_manager` all pass (110 files). No tests run.

## For the tester

- `web/src/api/schema.d.ts` is behind the document until TASK-124.
- The route walk (G34) gains `GET /api/v1/packages/search`, a TS §6.2 route.
- One OpenAPI export run hung once on this Windows machine and passed on the rerun (about 12 s). I did not reproduce it and saw no code cause; mention it if CI sees it.
