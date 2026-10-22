"""The one timestamp type for API bodies (TS §6.3: RFC 3339 UTC).

UtcDatetime refuses naive datetimes and always serialises in UTC with a
trailing Z, whatever time zone a value (or the psycopg session) carries.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, PlainSerializer, WithJsonSchema


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a time zone")
    return value.astimezone(UTC)


def _to_text(value: datetime) -> str:
    return _to_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


UtcDatetime = Annotated[
    datetime,
    AfterValidator(_to_utc),
    PlainSerializer(_to_text, return_type=str),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
