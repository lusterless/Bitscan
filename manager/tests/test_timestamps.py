"""REQ-038 (5): the shared UTC timestamp type (TASK-026 revision 1).

Check CHK-M2-045 of tests/m2/test-plan.md (lead ruling 2026-10-21 (2)): RFC
3339, always UTC with a trailing Z; a naive datetime is refused.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter, ValidationError

from bitscan_manager.api.timestamps import UtcDatetime
from bitscan_manager.app import create_app

ADAPTER: TypeAdapter[datetime] = TypeAdapter(UtcDatetime)
INSTANT = datetime(2026, 10, 21, 11, 4, 5, 123456, tzinfo=UTC)


class Item(BaseModel):
    at: UtcDatetime


@pytest.mark.parametrize(
    "value",
    [
        INSTANT,
        INSTANT.astimezone(timezone(timedelta(hours=8))),
        INSTANT.astimezone(timezone(timedelta(hours=-5))),
        INSTANT.astimezone(timezone(timedelta(hours=5, minutes=45))),
    ],
)
def test_aware_values_serialise_as_the_utc_instant_with_z(value: datetime) -> None:
    text = ADAPTER.dump_python(ADAPTER.validate_python(value), mode="json")
    assert text == "2026-10-21T11:04:05.123456Z"
    assert datetime.fromisoformat(text) == INSTANT
    assert Item(at=value).model_dump_json() == '{"at":"2026-10-21T11:04:05.123456Z"}'


def test_whole_seconds_and_dates_across_midnight() -> None:
    local = datetime(2026, 10, 22, 3, 0, tzinfo=timezone(timedelta(hours=8)))
    assert Item(at=local).model_dump(mode="json") == {
        "at": "2026-10-21T19:00:00.000000Z"
    }


@pytest.mark.parametrize(
    "value", [datetime(2026, 10, 21, 11, 4, 5), "2026-10-21T11:04:05", "2026-10-21"]
)
def test_naive_values_are_refused(value: Any) -> None:
    with pytest.raises(ValidationError):
        Item(at=value)


def test_offset_strings_are_accepted_and_normalised() -> None:
    item = Item.model_validate({"at": "2026-10-21T19:04:05.123456+08:00"})
    assert item.at == INSTANT


def test_route_responses_and_naive_bodies() -> None:
    app = create_app()

    @app.post("/t/echo-at")
    def echo(item: Item) -> Item:
        return item

    with TestClient(app) as c:
        ok = c.post("/t/echo-at", json={"at": "2026-10-21T13:04:05.123456+02:00"})
        naive = c.post("/t/echo-at", json={"at": "2026-10-21T13:04:05"})
    assert ok.status_code == 200
    assert ok.json() == {"at": "2026-10-21T11:04:05.123456Z"}
    assert naive.status_code == 400
    assert naive.json()["type"] == "invalid_request"
    assert "body.at" in naive.json()["detail"]


def test_json_schema_is_date_time() -> None:
    assert ADAPTER.json_schema() == {"type": "string", "format": "date-time"}
