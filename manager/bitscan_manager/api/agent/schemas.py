"""Agent wire contract (TS §6.5) with the #60 field constraints.

Every model refuses unknown keys, so its JSON Schema has additionalProperties
false and the Go agent can refuse unknown keys too. Integers, booleans and
strings are strict (true is not 1, 1.0 is not an integer). Timestamps are RFC
3339 with an explicit offset, normalised to UTC; UUIDs are hyphenated strings.
Each format check uses RE2, and the same pattern is in the exported schema.
Every string the agent sends refuses U+0000 and lone surrogates (they cannot
be stored), raw's keys and values included; results stdout and stderr are the
exception until M9 (user ruling 2026-10-23).
No model here has an operator, expected_result, expected or eval_spec field:
those stay on the manager (TS §3.5).
"""

import ipaddress
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal
from uuid import UUID

import re2  # type: ignore[import-untyped]
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    PlainSerializer,
    PlainValidator,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    WithJsonSchema,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

I32: Final = 2**31 - 1
# The largest integer every JSON implementation holds exactly (RFC 8259 §6):
# OpenAPI tools export bounds as floats, so 2^63 - 1 would read as 2^63
# (user ruling 2026-10-23, TASK-048 revision 2).
JSON_SAFE_MAX: Final = 2**53 - 1

UUID_PATTERN: Final = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# RFC 3339 date-time with an offset, fields in range (no leap second, which
# Python cannot hold); only impossible dates such as 02-30 need the parser.
RFC3339_PATTERN: Final = (
    "^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])[Tt]"
    "([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,9})?"
    "([Zz]|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$"
)
MACHINE_ID_PATTERN: Final = "^[0-9a-f]{32}$"  # machine-id(5); agent.machine_id CHAR(32)
SHA256_PATTERN: Final = "^[0-9a-f]{64}$"
HELPER_PATTERN: Final = "^[a-z][a-z0-9_-]{0,31}$"
BSA_PATTERN: Final = "^bsa_[A-Za-z0-9_-]{43}$"  # #56 (a)
# The NUL half of the storable-text rule, in a form ECMA-262, Python re and
# RE2 all read; lone surrogates cannot be written portably, so only the
# models refuse those.
NO_NUL_PATTERN: Final = r"^[^\x00]*$"

_V4: Final = (
    "(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
    "([.](25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3}"
)
_H: Final = "[0-9A-Fa-f]{1,4}"
_V6: Final = "|".join(
    (
        f"({_H}:){{7}}{_H}",
        f"({_H}:){{1,7}}:",
        f"({_H}:){{1,6}}:{_H}",
        f"({_H}:){{1,5}}(:{_H}){{1,2}}",
        f"({_H}:){{1,4}}(:{_H}){{1,3}}",
        f"({_H}:){{1,3}}(:{_H}){{1,4}}",
        f"({_H}:){{1,2}}(:{_H}){{1,5}}",
        f"{_H}:(:{_H}){{1,6}}",
        f":((:{_H}){{1,7}}|:)",
        f"({_H}:){{6}}{_V4}",
        f"::([Ff]{{4}}(:0{{1,4}})?:)?{_V4}",
        f"({_H}:){{1,4}}:{_V4}",
    )
)
# PostgreSQL INET input text: an address with an optional prefix length.
INET_PATTERN: Final = (
    f"^(({_V4})(/(3[0-2]|[12]?[0-9]))?|({_V6})(/(12[0-8]|1[01][0-9]|[1-9]?[0-9]))?)$"
)


def _matching(pattern: str) -> Callable[[str], str]:
    compiled = re2.compile(pattern)

    def check(value: str) -> str:
        if compiled.fullmatch(value) is None:
            raise ValueError("value does not have the required format")
        return value

    return check


_is_uuid = _matching(UUID_PATTERN)
_is_rfc3339 = _matching(RFC3339_PATTERN)
_is_inet = _matching(INET_PATTERN)


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError("must be a UUID string")
    return UUID(_is_uuid(value))


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(_is_rfc3339(value).upper())
    else:
        raise ValueError("must be an RFC 3339 timestamp string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a time zone")
    try:
        return parsed.astimezone(UTC)
    except OverflowError:
        raise ValueError("timestamp is out of range") from None


def _inet(value: str) -> str:
    ipaddress.ip_interface(_is_inet(value))  # also refuses what INET would
    return value


def _storable(value: str) -> str:
    if "\x00" in value:
        raise ValueError("U+0000 is not allowed")
    try:
        value.encode("utf-8")  # a lone surrogate cannot be encoded
    except UnicodeEncodeError:
        raise ValueError("lone surrogates are not allowed") from None
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _distinct(values: list[str]) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError("items must be distinct")
    return values


AgentUuid = Annotated[
    UUID,
    PlainValidator(_uuid),
    PlainSerializer(str, return_type=str),
    WithJsonSchema({"type": "string", "pattern": UUID_PATTERN}),
]
Timestamp = Annotated[
    datetime,
    PlainValidator(_timestamp),
    PlainSerializer(_utc_text, return_type=str),
    WithJsonSchema(
        {"type": "string", "format": "date-time", "pattern": RFC3339_PATTERN}
    ),
]


def _text(low: int, high: int) -> Any:
    return Field(min_length=low, max_length=high)


def _schema(pattern: str) -> WithJsonSchema:
    return WithJsonSchema({"type": "string", "pattern": pattern})


MachineId = Annotated[
    StrictStr,
    AfterValidator(_matching(MACHINE_ID_PATTERN)),
    _schema(MACHINE_ID_PATTERN),
]
Sha256Hex = Annotated[
    StrictStr, AfterValidator(_matching(SHA256_PATTERN)), _schema(SHA256_PATTERN)
]
HelperName = Annotated[
    StrictStr, AfterValidator(_matching(HELPER_PATTERN)), _schema(HELPER_PATTERN)
]
AgentToken = Annotated[
    StrictStr,
    AfterValidator(_matching(BSA_PATTERN)),
    _schema(BSA_PATTERN),
]
InetText = Annotated[StrictStr, AfterValidator(_inet), _schema(INET_PATTERN)]
Text = Annotated[
    StrictStr,
    AfterValidator(_storable),
    Field(json_schema_extra={"pattern": NO_NUL_PATTERN}),
]
RawKey = Annotated[StrictStr, AfterValidator(_storable)]


class _NoNulKeys:
    """Adds propertyNames to an object schema, so the schema refuses NUL keys
    as the model does (a key pattern alone would give patternProperties)."""

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        value = handler(schema)
        value["propertyNames"] = {"pattern": NO_NUL_PATTERN}
        return value


# os_info.raw values at any depth (user ruling 2026-10-23): one recursive
# definition, emitted as $defs/RawValue with plain $refs, which FastAPI turns
# into components/schemas/RawValue. Deeper nesting than pydantic-core's
# recursion guard is refused as a validation error (see the impl report).
type RawValue = (
    Text
    | StrictInt
    | Annotated[StrictFloat, Field(allow_inf_nan=False)]  # jsonb has no NaN or inf
    | StrictBool
    | None
    | list[RawValue]
    | Annotated[dict[RawKey, RawValue], _NoNulKeys()]
)
# A non-negative count up to JSON_SAFE_MAX (2^53 - 1), not 2^63 - 1: it fits
# the bigint columns and every JSON reader holds it exactly.
Count64 = Annotated[StrictInt, Field(ge=0, le=JSON_SAFE_MAX)]
Count32 = Annotated[StrictInt, Field(ge=0, le=I32)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrolRequest(_Closed):
    hostname: Annotated[Text, _text(1, 255)]
    machine_id: MachineId
    agent_version: Annotated[Text, _text(1, 32)]
    os_id: Annotated[Text, _text(0, 32)] | None  # validated, not stored
    os_version_id: Annotated[Text, _text(0, 16)] | None  # validated, not stored
    os_pretty_name: Annotated[Text, _text(0, 128)] | None


class EnrolResponse(_Closed):
    agent_id: AgentUuid
    agent_token: AgentToken
    issued_at: Timestamp
    expires_at: Timestamp
    status: Literal["enrolled", "awaiting_approval"]


class HeartbeatRequest(_Closed):
    agent_version: Annotated[Text, _text(1, 32)]
    uptime_s: Count64
    last_pull_at: Timestamp | None
    current_job_id: AgentUuid | None
    spool_bytes: Count64
    last_error: Annotated[Text, _text(0, 1024)] | None
    runner_helpers: Annotated[
        list[HelperName],
        Field(max_length=8, json_schema_extra={"uniqueItems": True}),
        AfterValidator(_distinct),
    ]
    clock: Timestamp  # any value: the skew is alerted on, never refused


class HeartbeatResponse(_Closed):
    """Configuration only (TS §6.1 L1063): never jobs or commands."""

    job_pull_seconds: Annotated[StrictInt, Field(ge=60, le=3600)]
    max_parallel_plugins: Annotated[StrictInt, Field(ge=1, le=8)]
    server_time: Timestamp


class InventoryJob(_Closed):
    """No plugins or redaction_patterns (TS §6.5 L1182): a key more is refused."""

    job_id: AgentUuid
    agent_id: AgentUuid
    kind: Literal["inventory"]
    pickup_by: Timestamp


class PluginSpec(_Closed):
    plugin_uuid: AgentUuid
    execute: Annotated[StrictStr, Field(min_length=1)]
    timeout_s: Annotated[StrictInt, Field(ge=1, le=600)]


class ComplianceJob(_Closed):
    job_id: AgentUuid
    agent_id: AgentUuid
    kind: Literal["compliance"]
    pickup_by: Timestamp
    plugins: Annotated[list[PluginSpec], Field(min_length=1, max_length=5000)]
    redaction_patterns: Annotated[list[StrictStr], Field(max_length=50)]


Job = Annotated[InventoryJob | ComplianceJob, Field(discriminator="kind")]


class JobsResponse(_Closed):
    jobs: Annotated[list[Job], Field(max_length=10)]  # TS §6.1 L1064: up to 10


class ResultItem(_Closed):
    plugin_uuid: AgentUuid
    exit_code: Annotated[StrictInt, Field(ge=-(2**31), le=I32)] | None
    stdout: StrictStr
    stderr: StrictStr
    started_at: Timestamp
    finished_at: Timestamp
    timed_out: StrictBool
    truncated: StrictBool
    error: Literal["spool_overflow", "runner_unavailable"] | None


class ResultsRequest(_Closed):
    results: Annotated[list[ResultItem], Field(max_length=50)]  # TS §3.5 L253
    final: StrictBool


class ResultsResponse(_Closed):
    accepted: Annotated[StrictInt, Field(ge=0)]
    duplicates: Annotated[StrictInt, Field(ge=0)]


class OsInfo(_Closed):
    os_id: Annotated[Text, _text(0, 32)] | None
    os_version_id: Annotated[Text, _text(0, 16)] | None
    os_pretty_name: Annotated[Text, _text(0, 128)] | None
    kernel_release: Annotated[Text, _text(0, 64)] | None
    architecture: Annotated[Text, _text(0, 16)] | None
    cpu_count: Count32 | None
    memory_mb: Count32 | None
    ip_addresses: Annotated[list[InetText], Field(max_length=256)]
    uptime_s: Count64 | None
    # its 256 KiB limit is the decoder's (TASK-060)
    raw: Annotated[dict[RawKey, RawValue], _NoNulKeys()]


class PackageItem(_Closed):
    name: Annotated[Text, _text(1, 255)]
    version: Annotated[Text, _text(1, 255)]
    architecture: Annotated[Text, _text(1, 16)]
    status: Annotated[Text, _text(1, 64)]
    source: Annotated[Text, _text(0, 255)] | None  # "" is stored as NULL
    installed_size_kb: Count32 | None


class InventoryBody(_Closed):
    os_info: OsInfo
    packages: Annotated[list[PackageItem], Field(max_length=50_000)]
    list_sha256: Sha256Hex


class RotateRequest(_Closed):
    """Rotate takes no body; an empty body or {} only (#60)."""


class RotateResponse(_Closed):
    agent_token: AgentToken
    issued_at: Timestamp
    expires_at: Timestamp
