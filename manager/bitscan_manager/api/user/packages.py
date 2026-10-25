"""GET /api/v1/packages/search and /search.csv (TS §6.2 L1117, §7.1, §7.3;
viewer, bsu_ or bsk_).

The routes parse, call the service and map its exceptions; the rules live in
services/packages. Cursors are bound to the shape and every filter
(SearchQuery.cursor_scope) and hold ids only (work/plans/TASK-110.md).
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from bitscan_manager.api.pagination import (
    CursorKey,
    Page,
    PageParams,
    decode_cursor,
    encode_cursor,
    page_params,
)
from bitscan_manager.api.problems import Problem
from bitscan_manager.api.user import problem_responses
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.repositories.packages import (
    AnchorGone,
    HostGroup,
    PackageGroup,
    PackageRow,
    PackageSearchRepo,
)
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.packages import (
    MAX_LEN,
    InvalidSearch,
    SearchQuery,
    parse_search,
)
from bitscan_manager.services.packages import search as service

router = APIRouter(prefix="/packages", tags=["packages"])
VIEWER = Annotated[Principal, Depends(require_role("viewer"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
PAGE = Annotated[PageParams, Depends(page_params)]
_BASE = (401, 403, 429, 503)
_BAD_CURSOR = "Invalid request: query.cursor"


def search_params(
    q: Annotated[str | None, Query(max_length=MAX_LEN["q"])] = None,
    name: Annotated[str | None, Query(max_length=MAX_LEN["name"])] = None,
    version: Annotated[str | None, Query(max_length=MAX_LEN["version"])] = None,
    version_op: Literal["lt", "le", "eq", "ge", "gt"] | None = None,
    arch: Annotated[str | None, Query(max_length=MAX_LEN["arch"])] = None,
    status: Literal["installed", "any"] = "installed",
    os_: Annotated[str | None, Query(alias="os", max_length=MAX_LEN["os"])] = None,
    tag: Annotated[str | None, Query(max_length=MAX_LEN["tag"])] = None,
    host: Annotated[str | None, Query(max_length=MAX_LEN["host"])] = None,
    agent_id: Annotated[str | None, Query(max_length=36)] = None,
    group_by: Literal["package", "host"] | None = None,
) -> SearchQuery:
    """The TS §7.1 parameters, declared so the document carries them;
    parse_search re-checks every rule. The 400 names parameters only."""
    raw = {
        "q": q,
        "name": name,
        "version": version,
        "version_op": version_op,
        "arch": arch,
        "status": status,
        "os": os_,
        "tag": tag,
        "host": host,
        "agent_id": agent_id,
        "group_by": group_by,
    }
    try:
        return parse_search(raw)
    except InvalidSearch as exc:
        names = ", ".join(f"query.{p}" for p in exc.params)
        raise Problem(400, "invalid_request", f"Invalid request: {names}") from None


QUERY = Annotated[SearchQuery, Depends(search_params)]


class PackageRowItem(BaseModel):
    name: str
    version: str
    architecture: str
    status: str
    agent_id: UUID
    hostname: str


class PackageGroupItem(BaseModel):
    name: str
    version: str
    architecture: str
    host_count: int


class HostGroupItem(BaseModel):
    agent_id: UUID
    hostname: str
    package_count: int


Item = PackageRowItem | PackageGroupItem | HostGroupItem
Found = PackageRow | PackageGroup | HostGroup


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise Problem(400, "invalid_request", _BAD_CURSOR) from None


def _anchor(shape: str, key: CursorKey) -> service.Anchor:
    """The ids _key wrote for this shape; anything else is a bad cursor."""
    match shape, key:
        case "rows", [int() as package_id, str() as agent] if type(package_id) is int:
            return (package_id, _uuid(agent))
        case "package", [int() as package_id] if type(package_id) is int:
            return package_id
        case "host", [str() as agent]:
            return _uuid(agent)
    raise Problem(400, "invalid_request", _BAD_CURSOR)


def _key(found: Found) -> CursorKey:
    if isinstance(found, PackageRow):
        return [found.package_id, str(found.agent_id)]
    if isinstance(found, PackageGroup):
        return [found.package_id]
    return [str(found.agent_id)]


def _item(found: Found) -> Item:
    if isinstance(found, PackageRow):
        return PackageRowItem(
            name=found.name,
            version=found.version,
            architecture=found.architecture,
            status=found.status,
            agent_id=found.agent_id,
            hostname=found.hostname,
        )
    if isinstance(found, PackageGroup):
        return PackageGroupItem(
            name=found.name,
            version=found.version,
            architecture=found.architecture,
            host_count=found.host_count,
        )
    return HostGroupItem(
        agent_id=found.agent_id,
        hostname=found.hostname,
        package_count=found.package_count,
    )


@router.get("/search", responses=problem_responses(_BASE))
def search_packages(
    principal: VIEWER, runtime: RUNTIME, page: PAGE, query: QUERY
) -> Page[PackageRowItem] | Page[PackageGroupItem] | Page[HostGroupItem]:
    scope = query.cursor_scope()
    after = None
    if page.cursor is not None:  # another filter or group_by fails here (#83 (b))
        after = _anchor(query.shape(), decode_cursor(scope, page.cursor))
    try:
        with runtime.db.transaction() as tx:
            found = service.search(
                PackageSearchRepo(tx.conn), query, page.limit + 1, after
            )
    except AnchorGone:
        raise Problem(400, "invalid_request", _BAD_CURSOR) from None
    rows: list[Found] = list(found[: page.limit])
    more = len(found) > page.limit
    next_cursor = encode_cursor(scope, _key(rows[-1])) if more else None
    items = [_item(r) for r in rows]
    if query.shape() == "package":
        return Page[PackageGroupItem](items=items, next_cursor=next_cursor)
    if query.shape() == "host":
        return Page[HostGroupItem](items=items, next_cursor=next_cursor)
    return Page[PackageRowItem](items=items, next_cursor=next_cursor)


class CsvResponse(Response):
    media_type = "text/csv"  # Starlette adds "; charset=utf-8" (#84 (c))


# Fixed text: names the cap, never a client value.
_TOO_MANY = (
    f"Invalid request: more than {service.CSV_MAX_ROWS} rows; narrow the filters"
)
_CSV_CONTENT = {"text/csv": {"schema": {"type": "string"}}}


@router.get(
    "/search.csv",
    response_class=CsvResponse,
    responses={
        200: {"description": "Successful Response", "content": _CSV_CONTENT},
        **problem_responses(_BASE),
    },
)
def search_packages_csv(principal: VIEWER, runtime: RUNTIME, query: QUERY) -> Response:
    """The whole result set (#84 (a)): no limit or cursor. The body is built
    in full inside one read-only snapshot before the response starts, so an
    over-cap or failing export never sends a CSV byte."""
    try:
        with runtime.db.transaction() as tx:
            repo = PackageSearchRepo(tx.conn)
            repo.read_only_snapshot()
            body = service.export_csv(repo, query)
    except service.TooManyRows:
        raise Problem(400, "invalid_request", _TOO_MANY) from None
    return CsvResponse(
        body.encode("utf-8"),
        headers={"Content-Disposition": 'attachment; filename="packages.csv"'},
    )
