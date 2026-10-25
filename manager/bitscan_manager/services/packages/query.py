"""Package search parameters (TS §7.1; work/plans/TASK-110.md).

parse_search turns the raw query values of the eleven TS §7.1 names into a
SearchQuery, or raises InvalidSearch naming the parameters, never the values
(REQ-038 (2)). Pure: plain ASCII character checks, no regular expression.
"""

import hashlib
import json
import string
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Final
from uuid import UUID

from bitscan_manager.repositories.packages import (
    INSTALLED_STATUSES,
    SearchFilter,
    VersionOp,
)


class GroupBy(StrEnum):
    PACKAGE = "package"
    HOST = "host"


# #83 (h): characters (len), as the columns count them; os is 32 + 1 + 16.
MAX_LEN: Final[Mapping[str, int]] = {
    "q": 255,
    "name": 255,
    "version": 255,
    "arch": 16,
    "os": 49,
    "tag": 64,
    "host": 255,
}
Q_MIN: Final = 3
OS_ID_MAX: Final = 32  # os_info.os_id VARCHAR(32)
OS_VERSION_MAX: Final = 16  # os_info.os_version_id VARCHAR(16)
EPOCH_MAX: Final = 2_147_483_647

_ALNUM: Final = frozenset(string.ascii_letters + string.digits)
_REVISION: Final = _ALNUM | frozenset(".+~")
_UPSTREAM: Final = _REVISION | frozenset("-")
_HEX: Final = frozenset(string.hexdigits)
_OPS: Final = frozenset(op.value for op in VersionOp)
_GROUPS: Final = frozenset(g.value for g in GroupBy)


class InvalidSearch(Exception):
    """The named query parameters are refused (400 invalid_request)."""

    def __init__(self, params: tuple[str, ...]) -> None:
        self.params = tuple(sorted(params))
        super().__init__(*self.params)


@dataclass(frozen=True)
class SearchQuery:
    filter: SearchFilter
    group_by: GroupBy | None

    def shape(self) -> str:
        return "rows" if self.group_by is None else self.group_by.value

    def cursor_scope(self) -> str:
        """Bound to the shape and every filter (#83 (b)): a cursor reused
        with any other filter or group_by is refused by decode_cursor."""
        values: dict[str, object] = {}
        for fld in fields(SearchFilter):
            value = getattr(self.filter, fld.name)
            if isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, UUID | VersionOp):
                value = str(value)
            values[fld.name] = value
        text = json.dumps(
            values, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
        return f"packages:{self.shape()}:{digest}"


def _storable(value: str) -> bool:
    """PostgreSQL text holds no U+0000 (#88), and UTF-8 has no surrogates."""
    return not any(c == "\x00" or "\ud800" <= c <= "\udfff" for c in value)


def is_debian_version(value: str) -> bool:
    """dpkg's version syntax ([epoch:]upstream[-revision]), so every version
    dpkg can install passes (#83 (g))."""
    epoch, colon, rest = value.partition(":")
    if not colon:
        epoch, rest = "", value
    elif not (
        0 < len(epoch) <= 10
        and all(c in string.digits for c in epoch)
        and int(epoch) <= EPOCH_MAX
    ):
        return False
    upstream, hyphen, revision = rest.rpartition("-")
    if not hyphen:
        upstream, revision = rest, ""
    elif not revision or any(c not in _REVISION for c in revision):
        return False
    allowed = _UPSTREAM | frozenset(":") if colon else _UPSTREAM
    return (
        upstream != ""
        and upstream[0] in string.digits
        and all(c in allowed for c in upstream)
    )


def _os(value: str) -> tuple[str, str | None]:
    """#83 (c): <os_id> (every version) or <os_id>:<os_version_id>."""
    os_id, colon, version = value.partition(":")
    if (
        not os_id
        or len(os_id) > OS_ID_MAX
        or (colon and (not version or ":" in version))
        or len(version) > OS_VERSION_MAX
    ):
        raise InvalidSearch(("os",))
    return os_id, version if colon else None


def _agent_id(value: str) -> UUID:
    """The hyphenated 8-4-4-4-12 form only, either case (M3 ruling)."""
    if len(value) != 36 or not all(
        (c == "-") if i in (8, 13, 18, 23) else (c in _HEX) for i, c in enumerate(value)
    ):
        raise InvalidSearch(("agent_id",))
    return UUID(value)


def parse_search(params: Mapping[str, str | None]) -> SearchQuery:
    """params: the raw values of the TS §7.1 names, None when absent. Checks
    run in the plan's order; the first failure raises."""
    get = params.get
    for param, limit in MAX_LEN.items():
        value = get(param)
        if value is not None and (
            value == "" or not _storable(value) or len(value) > limit
        ):
            raise InvalidSearch((param,))

    raw_op, raw_status, raw_group = get("version_op"), get("status"), get("group_by")
    if raw_op is not None and raw_op not in _OPS:
        raise InvalidSearch(("version_op",))
    if raw_status not in (None, "installed", "any"):
        raise InvalidSearch(("status",))
    if raw_group is not None and raw_group not in _GROUPS:
        raise InvalidSearch(("group_by",))

    q, name, version = get("q"), get("name"), get("version")
    if q is not None and len(q) < Q_MIN:
        raise InvalidSearch(("q",))
    if q is not None and name is not None:
        raise InvalidSearch(("name", "q"))
    if raw_op is not None and version is None:
        raise InvalidSearch(("version", "version_op"))
    if version is not None and not is_debian_version(version):
        raise InvalidSearch(("version",))

    raw_os = get("os")
    os_id, os_version_id = (None, None) if raw_os is None else _os(raw_os)
    raw_agent = get("agent_id")
    agent_id = None if raw_agent is None else _agent_id(raw_agent)

    return SearchQuery(
        filter=SearchFilter(
            q=q,
            name=name,
            version=version,
            version_op=None if raw_op is None else VersionOp(raw_op),
            arch=get("arch"),
            statuses=None if raw_status == "any" else INSTALLED_STATUSES,
            os_id=os_id,
            os_version_id=os_version_id,
            tag=get("tag"),
            host=get("host"),
            agent_id=agent_id,
        ),
        group_by=None if raw_group is None else GroupBy(raw_group),
    )
