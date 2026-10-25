# TASK-113 plan: package search service and the two routes

Covers TASK-113 (`GET /api/v1/packages/search`) and TASK-114 (`GET /api/v1/packages/search.csv`). REQs: REQ-113 to REQ-116. Owner: impl-manager. One review round; the reviewer is asked for a second look at TASK-113 (new SQL reached by user input). Tests: TP-M5-06, TP-M5-07; mutation rows CHK-M5-328, -330, -333 to -336.

Uses the types of `work/plans/TASK-110.md` (`SearchFilter`, `SearchQuery`, `parse_search`, `PackageSearchRepo`, the row types) and the CSV function of TASK-111. **Blocked on #83** (semantics), **#84** (CSV format and cap), **#88** (empty values, U+0000). Both tasks edit M3 files (`bm/api/user/__init__.py`, `manager/openapi.json`) and start after the M3 gate verdict.

In this file `bm/` is `manager/bitscan_manager/`.

## Spec quotes

- TS §6.2 L1117: "`GET` | `/packages/search`, `/packages/search.csv` | Fleet-wide package search (§7), JSON or CSV | viewer".
- TS §6 and §2.3 L118: user routes accept only `bsu_` and `bsk_`; agent tokens are refused.
- TS §6.3 L1133–L1134: problem details; "Lists use cursor pagination: `?limit=50&cursor=<opaque>`, max limit 500." L1136: 600 requests per minute per user.
- TS §6.3 L1142: "**CSV exports:** any cell starting with `=`, `+`, `-`, `@`, a tab, a carriage return or whitespace followed by one of these is prefixed with `'` … This applies to every export."
- TS §7.1 L1213–L1215: the three item shapes and `{ "items": [ … ], "next_cursor": "…" | null }`.
- TS §7.3 L1224: "Export the current result set as CSV (`/packages/search.csv`), escaped as in §6.3."

## Files

| Task | Files |
| --- | --- |
| TASK-113 | `bm/services/packages/search.py` (new), `bm/api/user/packages.py` (new), `bm/api/user/__init__.py` (one import, one `include_router`), `manager/openapi.json` (re-export) |
| TASK-114 | `bm/api/user/packages.py`, `bm/services/packages/search.py`, `bm/repositories/packages.py` (adds three methods, below), `manager/openapi.json` |

TASK-114 now also edits `bm/repositories/packages.py` (TASK-110's file, W1; TASK-114 is W3, so no wave shares it). This keeps TASK-110 near 200 lines and puts the export SQL with its only consumer.

## Service (`bm/services/packages/search.py`)

```python
class SearchStore(Protocol):                    # PackageSearchRepo satisfies it
    def rows(self, f: SearchFilter, limit: int, after: RowAnchor | None) -> list[PackageRow]: ...
    def package_groups(self, f: SearchFilter, limit: int, after: int | None) -> list[PackageGroup]: ...
    def host_groups(self, f: SearchFilter, limit: int, after: UUID | None) -> list[HostGroup]: ...

Anchor = RowAnchor | int | UUID
Found = list[PackageRow] | list[PackageGroup] | list[HostGroup]

def search(store: SearchStore, query: SearchQuery, limit: int, after: Anchor | None) -> Found:
    """limit is what the store is asked for (the route passes page limit + 1).
    Dispatches on query.group_by; after must match the shape (the route
    decodes it). AnchorGone passes through."""

# TASK-114
CSV_MAX_ROWS: Final = 100_000                   # #84 (a), a planner proposal
CSV_HEADERS: Final[Mapping[str, tuple[str, ...]]] = {
    "rows": ("name", "version", "architecture", "status", "agent_id", "hostname"),
    "package": ("name", "version", "architecture", "host_count"),
    "host": ("agent_id", "hostname", "package_count"),
}

class ExportStore(Protocol):
    def count_capped(self, query_filter: SearchFilter, shape: str, cap: int) -> int: ...
    def stream(self, query_filter: SearchFilter, shape: str) -> Iterator[PackageRow | PackageGroup | HostGroup]: ...

class TooManyRows(Exception): ...

def export_csv(store: ExportStore, query: SearchQuery, cap: int = CSV_MAX_ROWS) -> str:
    """The whole result set as one CSV document (#84 (b), (c)): the header row
    of CSV_HEADERS[shape], then one row per item in the JSON order, through
    TASK-111's shared writer. Raises TooManyRows before writing anything when
    count_capped(...) > cap."""
```

Cells are the JSON values as text: `agent_id` as its lowercase hyphenated string, counts as decimal integers. Every cell, header included, goes through TASK-111's escaping (CHK-M5-333); the service never escapes on its own.

No business logic in the routes: they parse, call the service, map exceptions and build the response.

## Repository additions (TASK-114, `bm/repositories/packages.py`)

```python
def read_only_snapshot(self) -> None:
    """First statement of the transaction: SET TRANSACTION ISOLATION LEVEL
    REPEATABLE READ, READ ONLY, so the count and the read see one snapshot
    and nothing can be written (REQ-115 (5)). Raises if a statement already
    ran in the transaction."""

def count_capped(self, f: SearchFilter, shape: str, cap: int) -> int:
    """min(real count, cap + 1): SELECT count(*) FROM (SELECT 1 <the shape's
    FROM, WHERE and GROUP BY> LIMIT cap + 1) s. Never counts past cap + 1."""

def stream(self, f: SearchFilter, shape: str) -> Iterator[...]:
    """The shape's full ordered query (no keyset, no LIMIT) through a named
    server-side cursor, itersize 1000. Must be consumed inside the
    transaction."""
```

They reuse TASK-110's fragments and order, so the CSV rows are the JSON items of every page in the same order (REQ-116 (3)). The isolation check: `AppDatabase.transaction()` opens a READ COMMITTED transaction (`bm/runtime.py`); `SET TRANSACTION` is valid only before the transaction's first query, so `read_only_snapshot()` is called immediately after entering it (as `repositories/audit_log.iter_entries` does for its own read).

## Routes (`bm/api/user/packages.py`)

```python
router = APIRouter(prefix="/packages", tags=["packages"])
VIEWER = Annotated[Principal, Depends(require_role("viewer"))]   # bsu_ or bsk_, 600/min (M2)

def search_params(
    q: Annotated[str | None, Query(max_length=255)] = None,
    name: Annotated[str | None, Query(max_length=255)] = None,
    version: Annotated[str | None, Query(max_length=255)] = None,
    version_op: Annotated[Literal["lt", "le", "eq", "ge", "gt"] | None, Query()] = None,
    arch: Annotated[str | None, Query(max_length=16)] = None,
    status: Annotated[Literal["installed", "any"], Query()] = "installed",
    os: Annotated[str | None, Query(max_length=49)] = None,
    tag: Annotated[str | None, Query(max_length=64)] = None,
    host: Annotated[str | None, Query(max_length=255)] = None,
    agent_id: Annotated[str | None, Query(max_length=36)] = None,
    group_by: Annotated[Literal["package", "host"] | None, Query()] = None,
) -> SearchQuery:
    """Shared by both routes. The declarations put the parameters, their
    enums and lengths in the document (so the generated client types them);
    the lengths come from query.MAX_LEN, not new literals. parse_search
    re-checks everything; InvalidSearch -> 400 invalid_request naming the
    parameters only."""
```

`agent_id` is declared as a string (not `UUID`) so the hyphenated-UUID rule of `parse_search` is the only one that applies. `os` shadows the module name only inside the function; the implementer may use `alias="os"` on a differently named argument instead (the document must still say `os`).

### `GET /api/v1/packages/search` (TASK-113)

```python
class PackageRowItem(BaseModel):   name: str; version: str; architecture: str; status: str; agent_id: UUID; hostname: str
class PackageGroupItem(BaseModel): name: str; version: str; architecture: str; host_count: int
class HostGroupItem(BaseModel):    agent_id: UUID; hostname: str; package_count: int

@router.get("/search", responses=problem_responses((401, 403, 429, 503)))
def search_packages(
    principal: VIEWER, runtime: RUNTIME, page: PAGE,
    query: Annotated[SearchQuery, Depends(search_params)],
) -> Page[PackageRowItem] | Page[PackageGroupItem] | Page[HostGroupItem]: ...
```

Steps:
1. Decode the cursor, if any, with `decode_cursor(query.cursor_scope(), page.cursor)` (a cursor from another filter set or `group_by` fails here, CHK-M5-328). Check the key's shape for the query's shape (`[int, uuid-string]`, `[int]` or `[uuid-string]`); anything else is 400 `query.cursor`, as `api/user/agents._cursor` does.
2. One READ COMMITTED transaction: `service.search(PackageSearchRepo(tx.conn), query, page.limit + 1, after)`.
3. `AnchorGone` → 400 `invalid_request`, `Invalid request: query.cursor`.
4. If more than `page.limit` came back, `next_cursor = encode_cursor(scope, key(rows[page.limit - 1]))` with the ids of `work/plans/TASK-110.md` "Cursor keys"; else `null`. The first `page.limit` rows become items. (`page_of` is not used directly because its key function would see the response models, which carry no `package_id`.)
5. Return the Page of the shape. An empty result is `{"items": [], "next_cursor": null}`.

Item models list their fields in the TS §7.1 order and nothing else (no `package_id`, REQ-114 (4)). Text is returned verbatim (REQ-115 (4)).

Problem statuses: 400 (added for every operation with parameters by `_problem_openapi`), 401, 403 (`forbidden` for a role below viewer cannot happen, but `totp_enrolment_required` for a restricted admin can), 429, 503. No 404: an unknown `agent_id` is an empty result.

### `GET /api/v1/packages/search.csv` (TASK-114)

```python
class CsvResponse(Response):
    media_type = "text/csv"

@router.get(
    "/search.csv",
    response_class=CsvResponse,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}},
               **problem_responses((401, 403, 429, 503))},
)
def search_packages_csv(principal: VIEWER, runtime: RUNTIME,
                        query: Annotated[SearchQuery, Depends(search_params)]) -> Response: ...
```

Steps:
1. No `limit` or `cursor` (#84 (a)): the route does not declare them, so they are ignored like any unknown parameter.
2. One transaction: `repo = PackageSearchRepo(tx.conn)`, `repo.read_only_snapshot()`, `body = service.export_csv(repo, query)`. The whole body is built inside the transaction (the stream is consumed there), and the M3 pattern is kept: the failure is stored and raised after the `with` block.
3. `TooManyRows` → 400 `invalid_request`, fixed detail `Invalid request: more than 100000 rows; narrow the filters` (no value echoed). Because the body is complete before the response starts, an over-cap or failing export never sends a CSV byte (REQ-116 (5), CHK-M5-334).
4. Success: `CsvResponse(body.encode("utf-8"), headers={"Content-Disposition": 'attachment; filename="packages.csv"'})`, with `Content-Type: text/csv; charset=utf-8` (Starlette adds the charset to `text/*`; the test checks the exact header). UTF-8 without BOM, CRLF line ends, RFC 4180 quoting (#84 (c); TASK-111).

The document gives this operation's 200 `text/csv` content with a string schema and no `application/json` (the generated client then types `data` as `string`; the UI downloads with `parseAs: "blob"`, TASK-125).

## Router registration and the document

`bm/api/user/__init__.py`: `from bitscan_manager.api.user import packages` inside `build_user_router()` and `router.include_router(packages.router)`. Both tasks re-export `manager/openapi.json` with `python -m bitscan_manager.app manager/openapi.json` (G6). The response union becomes an `anyOf` of three `Page_…_` components; the generated TypeScript union is narrowed by the UI on the `group_by` it sent (TASK-124).

## Edge cases

- **Token groups:** `require_role("viewer")` accepts only `bsu_` and `bsk_`; no token, `bsa_` and `bse_` get 401 (REQ-115 (1), CHK-M5-335, -336). TP-M5-22 re-runs the wrong-group probes on both routes.
- **Restricted admin session** (no TOTP yet): the M2 dependency answers 403 `totp_enrolment_required` (the session may call only TOTP enrolment and logout, TS §6.2 L1089).
- **Rate limit:** the M2 dependency counts these routes in the 600-per-minute user limit (REQ-115 (6)); the CSV route counts as one request.
- **Memory:** the CSV body is held in memory once (100,000 rows of honest data is a few MB; hostile 255-character fields at most about 80 MB). There is no streaming response, because a stream could not be refused after its first byte. The cap is #84 (a)'s planner number; the owner may change it (one constant).
- **Consistency:** the count and the read share one REPEATABLE READ snapshot, so an inventory upload committed between them cannot push the export over the cap after the check or change its rows.
- `statement_timeout` (300 s, `serve`) bounds a pathological query; a timeout surfaces as the M2 unhandled-error 500 problem, never a partial body.
- The `.csv` route path is a literal; FastAPI matches `/search` and `/search.csv` separately (neither has a path parameter).
- Nothing in either route writes: no audit entry (reads are not audited in M2 or M3), no table change (REQ-115 (5)).
- The routes add no command, setting or parameter that queues a job or touches inventory collection (REQ-088); TP-M5-06 re-runs the route walk (G34).

## Tests the plan expects (tester owns them)

- TP-M5-06 (`manager/tests/test_package_search_pg.py`): every REQ-113 refusal as a 400 problem naming the parameter; the three shapes with exactly their keys on the fixture fleet; paging N + 1 for each shape; a cursor reused with one filter changed, with another `group_by`, tampered, and after its anchor is removed → 400; token groups; hostile names verbatim; tables and `audit_log` unchanged after 50 searches; the 601st request → 429.
- TP-M5-07 (`manager/tests/test_package_search_csv_pg.py`): CSV rows equal the concatenated JSON pages for all three shapes; header row; `=HYPERLINK("http://x")` as `"'=HYPERLINK(""http://x"")"`; cap + 1 rows → 400 with a problem body and no CSV (the cap is set low through the service's `cap` argument in a unit test with a fake `ExportStore`, and the 100,000 constant itself is asserted once); headers exact; token groups; `limit` and `cursor` ignored.
