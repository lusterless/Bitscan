"""POST /api/v1/policies/import (TS §6.2 L1103, L1084; §6.3 L1137-L1138; §4.1
L522; REQ-170; open questions #57, #98 (d), (j), #99, #102 (d); design note
D5, work/plans/TASK-162.md). Admin, session or API token: upload is not a
sensitive action (L1084), so there is no TOTP-session check or sink gate.

The route declares no body, so the token and role check run before a byte is
read; the body is read through the `bit` cap and parsed in memory with
python-multipart's low-level parser (nothing is spooled to disk, L522). The
client's file name is only metadata (#99 (d)). Every 400 detail is fixed text
that never echoes the body, a header or the file name.
"""

import logging
from dataclasses import dataclass
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.concurrency import run_in_threadpool

from bitscan_manager.api.agent.bodies import TooLarge, read_capped
from bitscan_manager.api.problems import ABOUT_BLANK, Problem
from bitscan_manager.api.user import problem_responses
from bitscan_manager.api.user.imports import ImportFinding
from bitscan_manager.auth.dependencies import require_role
from bitscan_manager.auth.principal import Principal
from bitscan_manager.runtime import Runtime, get_runtime
from bitscan_manager.services.importer.model import MAX_BIT_BYTES
from bitscan_manager.services.importer.pipeline import Actor, ImportOutcome
from bitscan_manager.services.importer.service import (
    RETRY_AFTER_S,
    STARTING_DETAIL,
    CatalogStarting,
)
from bitscan_manager.services.importer.store import PolicyManagedOnServer
from bitscan_manager.services.importer.uploads import client_file_name

log = logging.getLogger(__name__)
router = APIRouter(tags=["policies"])
ADMIN = Annotated[Principal, Depends(require_role("admin"))]
RUNTIME = Annotated[Runtime, Depends(get_runtime)]
_FORM: Final = "The body must be multipart/form-data with one part named file."
_MANAGED: Final = "This policy is managed in the server folder; change its file there."
_NOT_RECORDED: Final = "The import was stored but its record could not be written."
_DISK: Final = "The policy file could not be stored; retry shortly."
_BOUNDARY_MAX: Final = 70  # RFC 2046
_HEADERS_MAX: Final = 16
_HEADER_VALUE_MAX: Final = 8 * 1024
_BODY: Final = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file"],
                "additionalProperties": False,
                "properties": {"file": {"type": "string", "format": "binary"}},
            }
        }
    },
}


class ImportResult(BaseModel):
    """#98 (d): both outcomes answer 200; the policy fields are null when
    rejected; `errors` as stored, warnings included (#110)."""

    model_config = ConfigDict(extra="forbid")
    import_id: int
    outcome: Literal["success", "rejected"]  # a manual import is never skipped
    policy_id: int | None
    policy_name: str | None
    policy_version: int | None
    plugins_added: int
    plugins_updated: int
    plugins_retired: int
    errors: list[ImportFinding]


@dataclass(frozen=True)
class UploadPart:
    data: bytes
    client_name: str  # the #99 (d) form


class _Collector:
    """MultipartParser callbacks: one part, at most 16 headers of at most
    8 KiB, at most 5 MiB of data (TS §6.3 L1138)."""

    def __init__(self) -> None:
        self.parts = 0
        self.headers: dict[bytes, bytes] = {}
        self.field, self.value, self.data = bytearray(), bytearray(), bytearray()
        self.done = False

    def part_begin(self) -> None:
        self.parts += 1
        if self.parts > 1:
            raise FormParserError("more than one part")

    def header_field(self, data: bytes, start: int, end: int) -> None:
        self.field += data[start:end]

    def header_value(self, data: bytes, start: int, end: int) -> None:
        self.value += data[start:end]
        if len(self.value) > _HEADER_VALUE_MAX:
            raise FormParserError("header too long")

    def header_end(self) -> None:
        self.headers[bytes(self.field).lower()] = bytes(self.value)
        self.field, self.value = bytearray(), bytearray()
        if len(self.headers) > _HEADERS_MAX:
            raise FormParserError("too many headers")

    def part_data(self, data: bytes, start: int, end: int) -> None:
        self.data += data[start:end]
        if len(self.data) > MAX_BIT_BYTES:
            raise TooLarge()  # 413, no bit_import row (#99 (b))

    def end(self) -> None:
        self.done = True


def parse_upload(content_type: str, body: bytes) -> UploadPart:
    """The one `file` part of a multipart/form-data body (#99 (c)); its own
    Content-Type is ignored, and an empty part is an import (BIT001)."""
    bad = Problem(400, "invalid_request", _FORM)
    kind, params = parse_options_header(content_type)
    boundary = params.get(b"boundary", b"")
    if kind.lower() != b"multipart/form-data" or not (
        1 <= len(boundary) <= _BOUNDARY_MAX
    ):
        raise bad
    got = _Collector()
    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": got.part_begin,
            "on_header_field": got.header_field,
            "on_header_value": got.header_value,
            "on_header_end": got.header_end,
            "on_part_data": got.part_data,
            "on_end": got.end,
        },
        max_header_count=_HEADERS_MAX,
        max_header_size=_HEADER_VALUE_MAX + 1024,  # the value check is exact
    )
    try:
        parser.write(body)
        parser.finalize()
    except FormParserError:
        raise bad from None
    disposition, fields = parse_options_header(got.headers.get(b"content-disposition"))
    if not (got.done and got.parts == 1 and disposition.lower() == b"form-data"):
        raise bad
    if fields.get(b"name") != b"file":
        raise bad
    return UploadPart(bytes(got.data), client_file_name(fields.get(b"filename")))


def _result(outcome: ImportOutcome) -> ImportResult:
    if outcome.import_id is None:  # the catalog committed, its record did not
        log.error("upload stored without its bit_import record")
        raise Problem(503, ABOUT_BLANK, _NOT_RECORDED)
    return ImportResult(
        import_id=outcome.import_id,
        outcome="success" if outcome.outcome == "success" else "rejected",
        policy_id=outcome.policy_id,
        policy_name=outcome.policy_name,
        policy_version=outcome.policy_version,
        plugins_added=outcome.plugins_added,
        plugins_updated=outcome.plugins_updated,
        plugins_retired=outcome.plugins_retired,
        errors=[ImportFinding(**f.to_json()) for f in outcome.findings],
    )


@router.post(
    "/policies/import",
    responses=problem_responses((401, 403, 409, 413, 503)),
    openapi_extra={"requestBody": _BODY},
)
async def import_policy(
    request: Request, principal: ADMIN, runtime: RUNTIME
) -> ImportResult:
    """Upload one `.bit` file; 200 for `success` and `rejected` (#98 (d))."""
    catalog = runtime.catalog
    if catalog is None:
        raise Problem(503, ABOUT_BLANK, "The service is not ready.")
    body = await read_capped(request)  # 413 over the `bit` cap
    part = parse_upload(request.headers.get("content-type", ""), body)
    actor = Actor(f"user:{principal.user_id}", principal.user_id)
    try:
        outcome = await run_in_threadpool(
            catalog.upload, part.data, part.client_name, actor
        )
    except CatalogStarting:
        retry = {"Retry-After": str(RETRY_AFTER_S)}
        raise Problem(503, ABOUT_BLANK, STARTING_DETAIL, retry) from None
    except PolicyManagedOnServer:
        raise Problem(409, "policy_managed_on_server", _MANAGED) from None
    except OSError:  # a stale temp file (O_EXCL) or another disk error (#98 (j))
        raise Problem(503, ABOUT_BLANK, _DISK) from None
    return _result(outcome)
