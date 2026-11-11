"""TASK-233 TEST: the results view, pure (TP-M11-02; CHK-M11-001 to -014).

Expected values: TS §6.2 L1083 (the current role at each request), L1123
(stdout and stderr only for operator and admin), §6.3 L1144 (CSV formula
escaping, every export), §4.5 L603 (`result` and `original_result`), §4.4
L585 (Not run); #144 (a)-(d), #146 (b)-(c) as approved 2026-11-08; the
security invariant "whitespace followed by one of these"; REQ-267 to REQ-269
at view level. Model names: ScanResultItem / ScanResultItemWithOutput (lead
approved, TASK-232).
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from bitscan_manager.api.user.scan_views import (
    ScanResultItem,
    ScanResultItemWithOutput,
)
from bitscan_manager.repositories.result_reads import ResultRow
from bitscan_manager.services.jobs import results_view as rv
from bitscan_manager.services.packages import csv_export

OUT, ERR = "M11OUT-view", "M11ERR-view"
T = datetime(2026, 11, 8, 12, 30, 15, 123456, tzinfo=UTC)
VIEWER_KEYS = {
    "agent_id", "hostname", "job_id", "retry", "plugin_uuid", "plugin_name",
    "result", "eval_detail", "original_result", "original_eval_detail",
    "reeval_policy_version", "reevaluated_by", "reevaluated_at", "operator",
    "expected", "execute", "exit_code", "timed_out", "truncated", "started_at",
    "finished_at", "received_at",
}  # fmt: skip
HEADER = (
    "hostname", "agent_id", "plugin_uuid", "plugin_name", "result", "eval_detail",
    "original_result", "original_eval_detail", "reevaluated_at",
    "reeval_policy_version", "exit_code", "timed_out", "truncated", "started_at",
    "finished_at", "job_id", "retry",
)  # fmt: skip


def row(**over: Any) -> ResultRow:
    """A stored, re-evaluated result in the original job (defaults)."""
    orig = over.pop("orig_job_id", UUID("11111111-1111-4111-8111-111111111111"))
    base: dict[str, Any] = {
        "agent_id": UUID("22222222-2222-4222-8222-222222222222"),
        "hostname": "web-01",
        "position": 1,
        "plugin_uuid": UUID("33333333-3333-4333-8333-333333333333"),
        "orig_job_id": orig,
        "job_id": orig,
        "original_code": 1,
        "original_detail": "orig detail",
        "code": 0,
        "detail": "re detail",
        "reeval_policy_version": 4,
        "reevaluated_by": 7,
        "reevaluated_at": T + timedelta(hours=1),
        "plugin_name": "CIS Ubuntu 24.04 - 1.1 Check",
        "operator": "equals",
        "expected": "install ok installed",
        "execute": "dpkg-query -W apparmor",
        "exit_code": 0,
        "timed_out": False,
        "truncated": True,
        "started_at": T - timedelta(seconds=2),
        "finished_at": T - timedelta(seconds=1),
        "received_at": T,
        "stdout": OUT,
        "stderr": ERR,
    }
    return ResultRow(**(base | over))


def not_run(**over: Any) -> ResultRow:
    nulls = {
        "job_id": None, "original_code": None, "original_detail": None, "code": None,
        "detail": None, "reeval_policy_version": None, "reevaluated_by": None,
        "reevaluated_at": None, "exit_code": None, "timed_out": None,
        "truncated": None, "started_at": None, "finished_at": None,
        "received_at": None, "stdout": None, "stderr": None,
    }  # fmt: skip
    return row(**(nulls | over))


def parse_csv(text: str) -> list[list[str]]:
    """A strict RFC 4180 reader written here (not the code under test):
    CRLF record ends, quoted cells with doubled quotes."""
    records: list[list[str]] = []
    cell, rec, i, quoted = "", [], 0, False
    while i < len(text):
        c = text[i]
        if quoted:
            if c == '"' and text[i + 1 : i + 2] == '"':
                cell, i = cell + '"', i + 2
                continue
            if c == '"':
                quoted, i = False, i + 1
                continue
            cell, i = cell + c, i + 1
            continue
        if c == '"' and cell == "":
            quoted, i = True, i + 1
        elif c == ",":
            rec.append(cell)
            cell, i = "", i + 1
        elif text.startswith("\r\n", i):
            rec.append(cell)
            records.append(rec)
            cell, rec, i = "", [], i + 2
        else:
            assert c not in "\r\n", f"bare line break at {i}"
            cell, i = cell + c, i + 1
    assert cell == "" and rec == [], "text must end with CRLF"
    return records


# ------------------------------------------------------------ CHK-M11-001


@pytest.mark.parametrize(
    ("role", "want"),
    [
        ("operator", True),
        ("admin", True),
        ("viewer", False),
        ("", False),
        ("Admin", False),
        ("OPERATOR", False),
        (" admin", False),
        ("admin ", False),
        ("root", False),
        ("api", False),
        ("session", False),
    ],
)
def test_include_output_only_for_operator_and_admin(role: str, want: bool) -> None:
    assert rv.include_output(role) is want


# ------------------------------------------------------------ CHK-M11-002


def test_viewer_item_has_no_output_keys() -> None:
    got = rv.item(row(), with_output=False)
    assert set(got) == VIEWER_KEYS
    assert "stdout" not in got and "stderr" not in got
    assert OUT not in repr(got) and ERR not in repr(got)


def test_operator_item_has_both_output_keys() -> None:
    got = rv.item(row(), with_output=True)
    assert set(got) == VIEWER_KEYS | {"stdout", "stderr"}
    assert (got["stdout"], got["stderr"]) == (OUT, ERR)


def test_item_values_effective_and_original() -> None:
    """#119, TS §4.5 L603: `result` is the effective verdict, `original_result`
    the stored one, each with its own detail; the re-evaluation fields."""
    got = rv.item(row(), with_output=False)
    assert (got["result"], got["eval_detail"]) == ("PASS", "re detail")
    assert (got["original_result"], got["original_eval_detail"]) == (
        "FAIL",
        "orig detail",
    )
    assert (got["reeval_policy_version"], got["reevaluated_by"]) == (4, 7)
    assert got["reevaluated_at"] == T + timedelta(hours=1)
    r = row()
    for k in (
        "agent_id",
        "hostname",
        "job_id",
        "plugin_uuid",
        "plugin_name",
        "operator",
        "expected",
        "execute",
        "exit_code",
        "timed_out",
        "truncated",
        "started_at",
        "finished_at",
        "received_at",
    ):
        assert got[k] == getattr(r, k), k


@pytest.mark.parametrize(("code", "word"), [(0, "PASS"), (1, "FAIL"), (2, "ERROR")])
def test_never_reevaluated_both_verdicts_equal(code: int, word: str) -> None:
    r = row(
        original_code=code,
        code=code,
        original_detail="d",
        detail="d",
        reeval_policy_version=None,
        reevaluated_by=None,
        reevaluated_at=None,
    )
    got = rv.item(r, with_output=False)
    assert got["result"] == got["original_result"] == word
    assert (
        got["reeval_policy_version"],
        got["reevaluated_by"],
        got["reevaluated_at"],
    ) == (
        None,
        None,
        None,
    )


# ------------------------------------------------------------ CHK-M11-003


def test_not_run_item() -> None:
    """TS §4.4 L585, #144 (a), (c): result null; the name, operator, expected
    and execute of the planned plugin; every result field null."""
    r = not_run(
        plugin_name="Fam - planned", operator="contains", expected="x", execute="cmd"
    )
    got = rv.item(r, with_output=True)
    for k in (
        "result",
        "job_id",
        "original_result",
        "original_eval_detail",
        "eval_detail",
        "exit_code",
        "timed_out",
        "truncated",
        "started_at",
        "finished_at",
        "received_at",
        "reeval_policy_version",
        "reevaluated_by",
        "reevaluated_at",
        "stdout",
        "stderr",
    ):
        assert got[k] is None, k
    assert (got["plugin_name"], got["operator"], got["expected"], got["execute"]) == (
        "Fam - planned",
        "contains",
        "x",
        "cmd",
    )
    assert got["retry"] is False


# ------------------------------------------------------------ CHK-M11-004


def test_retry_true_only_for_a_result_in_the_retry() -> None:
    assert rv.item(row(), with_output=False)["retry"] is False
    retry_job = uuid4()
    assert rv.item(row(job_id=retry_job), with_output=False)["retry"] is True
    assert rv.item(not_run(), with_output=False)["retry"] is False


# ------------------------------------------------------------ CHK-M11-005


def test_items_validate_against_the_route_models() -> None:
    for r in (row(), not_run(), row(job_id=uuid4())):
        ScanResultItem.model_validate(rv.item(r, with_output=False))
        out = ScanResultItemWithOutput.model_validate(rv.item(r, with_output=True))
        assert out.stdout == r.stdout
    with pytest.raises(ValidationError):
        ScanResultItemWithOutput.model_validate(rv.item(row(), with_output=False))
    dumped = ScanResultItem.model_validate(
        rv.item(row(), with_output=False)
    ).model_dump()
    assert "stdout" not in dumped


# ------------------------------------------------------------ CHK-M11-006


def test_csv_constants() -> None:
    assert rv.CSV_HEADER == HEADER
    assert rv.OUTPUT_COLUMNS == ("stdout", "stderr")
    assert rv.CSV_MAX_ROWS == 100_000
    assert rv.csv_header(with_output=False) == HEADER
    assert rv.csv_header(with_output=True) == (*HEADER, "stdout", "stderr")


# ------------------------------------------------------------ CHK-M11-007


def test_viewer_csv_has_no_output_column() -> None:
    text = rv.csv_text([row(), not_run()], with_output=False)
    recs = parse_csv(text)
    assert recs[0] == list(HEADER)
    assert all(len(r) == 17 for r in recs)
    assert OUT not in text and ERR not in text
    assert "stdout" not in text and "stderr" not in text


def test_operator_csv_has_output_columns_last() -> None:
    recs = parse_csv(rv.csv_text([row()], with_output=True))
    assert recs[0] == [*HEADER, "stdout", "stderr"]
    assert recs[1][-2:] == [OUT, ERR]


# ------------------------------------------------------------ CHK-M11-008


def test_csv_cell_forms() -> None:
    r = row()
    recs = parse_csv(rv.csv_text([r, not_run()], with_output=True))
    cell = dict(zip(recs[0], recs[1], strict=True))
    assert cell["hostname"] == "web-01"
    assert cell["agent_id"] == str(r.agent_id) and cell["job_id"] == str(r.job_id)
    assert (cell["result"], cell["original_result"]) == ("PASS", "FAIL")
    assert (cell["timed_out"], cell["truncated"], cell["retry"]) == (
        "false",
        "true",
        "false",
    )
    assert (cell["exit_code"], cell["reeval_policy_version"]) == ("0", "4")
    for k, want in (
        ("started_at", r.started_at),
        ("finished_at", r.finished_at),
        ("reevaluated_at", r.reevaluated_at),
    ):
        assert cell[k].endswith("Z"), cell[k]
        assert datetime.fromisoformat(cell[k].replace("Z", "+00:00")) == want
    empty = dict(zip(recs[0], recs[2], strict=True))
    for k in (
        "result",
        "original_result",
        "eval_detail",
        "job_id",
        "exit_code",
        "timed_out",
        "truncated",
        "started_at",
        "reevaluated_at",
        "stdout",
    ):
        assert empty[k] == "", k
    assert empty["retry"] == "false"


def test_csv_times_are_utc_whatever_the_zone() -> None:
    plus8 = timezone(timedelta(hours=8))
    r = row(started_at=T.astimezone(plus8))
    cell = dict(
        zip(HEADER, parse_csv(rv.csv_text([r], with_output=False))[1], strict=True)
    )
    assert cell["started_at"].endswith("Z")
    assert datetime.fromisoformat(cell["started_at"].replace("Z", "+00:00")) == T


def test_csv_text_is_bom_free_and_crlf_only() -> None:
    text = rv.csv_text([row(stdout="a\nb\r\nc")], with_output=True)
    assert not text.startswith("﻿")
    assert text.endswith("\r\n")
    lines = text.encode("utf-8")
    assert b"\xef\xbb\xbf" not in lines


# ------------------------------------------------------------ CHK-M11-009

TRIGGERS = [
    "=1+2",
    "+1",
    "-1",
    "@SUM(1)",
    "\tx",
    "\rx",
    " =1",
    "  +x",
    "\t-1",
    " \r@",
    " =1",
]
SAFE = ["a=b", "1-2", "", "plain", "x@y"]
STR_COLUMNS = (
    "hostname",
    "plugin_name",
    "eval_detail",
    "original_eval_detail",
    "stdout",
    "stderr",
)


@pytest.mark.parametrize("column", STR_COLUMNS)
@pytest.mark.parametrize("value", TRIGGERS)
def test_formula_cells_get_a_quote_in_every_text_column(
    column: str, value: str
) -> None:
    field = {"eval_detail": "detail", "original_eval_detail": "original_detail"}.get(
        column, column
    )
    recs = parse_csv(rv.csv_text([row(**{field: value})], with_output=True))
    cell = dict(zip(recs[0], recs[1], strict=True))[column]
    assert cell == "'" + value, (column, value, cell)


@pytest.mark.parametrize("value", SAFE)
def test_safe_cells_are_unchanged(value: str) -> None:
    recs = parse_csv(
        rv.csv_text([row(stdout=value, hostname=value or "h")], with_output=True)
    )
    cell = dict(zip(recs[0], recs[1], strict=True))
    assert cell["stdout"] == value


def test_every_cell_of_a_row_passes_through_escape_cell() -> None:
    """All 19 columns: cells that cannot hold free text (ids, times, codes)
    never start with a trigger, so the escape is shown on the text columns
    above; here a negative exit code shows the numeric columns go through it."""
    recs = parse_csv(rv.csv_text([row(exit_code=-9)], with_output=True))
    cell = dict(zip(recs[0], recs[1], strict=True))
    assert cell["exit_code"] == "'-9"


# ------------------------------------------------------------ CHK-M11-010


def test_rfc4180_quoting_round_trips() -> None:
    nasty = 'he said "hi", then\nleft\r\nagain,,'
    recs = parse_csv(rv.csv_text([row(stdout=nasty, stderr='"')], with_output=True))
    cell = dict(zip(recs[0], recs[1], strict=True))
    assert (cell["stdout"], cell["stderr"]) == (nasty, '"')


# ------------------------------------------------------------ CHK-M11-011


def test_every_cell_goes_through_m5_escape_cell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real: Callable[[str], str] = csv_export.escape_cell

    def spy(cell: str) -> str:
        seen.append(cell)
        return real(cell)

    monkeypatch.setattr(csv_export, "escape_cell", spy)
    text = rv.csv_text([row(), not_run()], with_output=True)
    assert len(seen) == 19 * 3, len(seen)
    assert seen[:19] == [*HEADER, "stdout", "stderr"]
    assert len(parse_csv(text)) == 3


def test_results_view_does_not_use_the_csv_module() -> None:
    tree = ast.parse(inspect.getsource(rv))
    imported = {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    } | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "csv" not in imported and "re" not in imported, imported


# ------------------------------------------------------------ CHK-M11-012


@pytest.mark.parametrize("status", ["PASS", "FAIL", "ERROR", "NOT_RUN"])
def test_status_values_accepted(status: str) -> None:
    q = rv.parse_query(status, None)
    assert q.status == status and q.agent_id is None


def test_no_filter_is_none() -> None:
    aid = uuid4()
    assert rv.parse_query(None, aid) == rv.ResultQuery(None, aid)


@pytest.mark.parametrize(
    "status",
    ["pass", "Pass", "NOTRUN", "NOT RUN", "", "OK", "ERROR ", " FAIL", "M11CANARY"],
)
def test_unknown_status_raises_naming_the_parameter_only(status: str) -> None:
    with pytest.raises(rv.InvalidResultQuery) as exc:
        rv.parse_query(status, None)
    assert str(exc.value) == "status"
    assert "M11CANARY" not in repr(exc.value)


# ------------------------------------------------------------ CHK-M11-013


def test_hostile_text_is_returned_verbatim() -> None:
    """TS §6.3 L1143: plain text is the UI's job; the server neither escapes
    nor drops it."""
    hostile = "<script>alert(1)</script> <img src=x onerror=alert(1)> ‮ �"
    r = row(hostname=hostile, plugin_name=hostile, stdout=hostile)
    got = rv.item(r, with_output=True)
    assert got["hostname"] == got["plugin_name"] == got["stdout"] == hostile
    cell = dict(zip(*parse_csv(rv.csv_text([r], with_output=True)), strict=True))
    assert cell["hostname"] == hostile and cell["stdout"] == hostile


# ------------------------------------------------------------ CHK-M11-014


def test_module_imports_only_the_allowed_names() -> None:
    """Purity read on the module's own import statements (the transitive
    reading cannot hold: csv_export's package already loads psycopg)."""
    tree = ast.parse(inspect.getsource(rv))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    project = {m for m in modules if m and m.startswith("bitscan_manager")}
    assert project <= {
        "bitscan_manager.services.packages.csv_export",
        "bitscan_manager.repositories.result_reads",
    }, project
    stdlib = {m for m in modules if m and not m.startswith("bitscan_manager")}
    assert stdlib <= {
        "__future__",
        "collections.abc",
        "dataclasses",
        "datetime",
        "typing",
        "uuid",
    }, stdlib
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"logging", "logger", "open", "print"}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"now", "utcnow", "connect", "cursor", "transaction"}
    from_rr = {
        a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        and n.module == "bitscan_manager.repositories.result_reads"
        for a in n.names
    }
    assert from_rr <= {"ResultRow"}, from_rr


def test_row_type_is_a_plain_value() -> None:
    """The view maps any row with the documented fields; replace() works."""
    assert {f.name for f in fields(ResultRow)} >= {
        "stdout",
        "stderr",
        "code",
        "original_code",
    }
    assert rv.item(replace(row(), hostname="b"), with_output=False)["hostname"] == "b"
