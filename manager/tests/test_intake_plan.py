"""TP-M9-06: intake plan (TASK-190; REQ-214 to REQ-216 at plan level).

TS §6.1 L1071, §4.4 L578, §4.5 L587, L596, L599, L603; open questions #12,
#116 (d), #121, #124 (a), (b). Items are the M3 `ResultItem`, built with
`json.loads` + `model_validate` as the results route does. Expected values
come from the spec and the approved answers; verdicts are computed by the
test directly from M8's `result_verdict` / `classify`. CHK-M9-053 to -066.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.api.agent.schemas import ResultItem, ResultsRequest
from bitscan_manager.services.evaluator.eval_spec import EvalSpec
from bitscan_manager.services.evaluator.evaluate import classify
from bitscan_manager.services.evaluator.model import PluginSpec
from bitscan_manager.services.evaluator.verdict import result_verdict
from bitscan_manager.services.jobs.intake_plan import (
    Plan,
    PluginNotInJob,
    ResultRow,
    plan,
    storable,
)

FIXTURES = Path(__file__).resolve().parent / "contract" / "fixtures" / "results"
CANARY = "M9CANARY-" + uuid.uuid4().hex
OPERATORS = (
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "regex",
    "not_regex",
    "eq",
    "ne",
    "gt",
    "ge",
    "lt",
    "le",
    "empty",
    "not_empty",
)


def pid(n: int) -> UUID:
    return UUID(int=(0x5EED << 112) + n)


def spec_of(entries: dict[int, tuple[str, str]]) -> EvalSpec:
    return EvalSpec(
        tuple(
            PluginSpec(
                plugin_uuid=pid(n), name=f"Fam - plugin {n}", operator=op, expected=exp
            )
            for n, (op, exp) in entries.items()
        )
    )


def commands(*ns: int) -> dict[UUID, str]:
    return {pid(n): f"payload command {n}" for n in ns}


def item(n: int | UUID, **over: Any) -> ResultItem:
    body: dict[str, Any] = {
        "plugin_uuid": str(pid(n) if isinstance(n, int) else n),
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "started_at": "2026-10-30T12:00:00Z",
        "finished_at": "2026-10-30T12:00:01Z",
        "timed_out": False,
        "truncated": False,
        "error": None,
    }
    body.update(over)
    return ResultItem.model_validate(json.loads(json.dumps(body)))


def raw_item(json_text: str) -> ResultItem:
    """An item from raw JSON text, so escapes like \\ud800 reach json.loads."""
    return ResultItem.model_validate(json.loads(json_text))


EQ_OK = spec_of({1: ("equals", "ok"), 2: ("equals", "ok"), 3: ("equals", "ok")})


# --- CHK-M9-053: membership first -------------------------------------------


def test_foreign_plugin_refuses_the_whole_batch() -> None:
    entries = {n: ("equals", "ok") for n in range(1, 51)}
    spec = spec_of(entries)
    good = [item(n) for n in range(1, 50)]
    with pytest.raises(PluginNotInJob):
        plan(spec, commands(*range(1, 51)), set(), [*good, item(999)])
    with pytest.raises(PluginNotInJob):
        plan(spec, commands(*range(1, 51)), set(), [item(999), *good])


def test_in_payload_but_not_in_eval_spec_is_refused() -> None:
    with pytest.raises(PluginNotInJob):
        plan(spec_of({1: ("equals", "ok")}), commands(1, 2), set(), [item(2)])


def test_in_eval_spec_but_not_in_payload_is_refused() -> None:
    with pytest.raises(PluginNotInJob):
        plan(
            spec_of({1: ("equals", "ok"), 2: ("equals", "ok")}),
            commands(1),
            set(),
            [item(2)],
        )


def test_membership_before_duplicates() -> None:
    with pytest.raises(PluginNotInJob):
        plan(EQ_OK, commands(1, 2, 3), {pid(1), pid(999)}, [item(1), item(999)])


def test_plugin_not_in_job_message_is_fixed() -> None:
    with pytest.raises(PluginNotInJob) as info:
        plan(EQ_OK, commands(1, 2, 3), set(), [item(999, stdout=CANARY)])
    assert CANARY not in str(info.value) and str(pid(999)) not in str(info.value)


# --- CHK-M9-054 / -055: duplicates and order --------------------------------


def test_existing_results_are_duplicates() -> None:
    p = plan(EQ_OK, commands(1, 2, 3), {pid(1), pid(3)}, [item(1), item(2), item(3)])
    assert [r.plugin_uuid for r in p.rows] == [pid(2)]
    assert p.duplicates == 2


def test_two_items_for_one_plugin_first_wins() -> None:
    p = plan(
        EQ_OK, commands(1, 2, 3), set(), [item(1, stdout="first"), item(1, stdout="ok")]
    )
    assert len(p.rows) == 1
    assert p.rows[0].stdout == "first"
    assert p.rows[0].eval_code == 1  # "first" != "ok"
    assert p.duplicates == 1


def test_three_items_for_one_plugin() -> None:
    p = plan(
        EQ_OK,
        commands(1, 2, 3),
        set(),
        [item(2, stdout="a"), item(2, stdout="b"), item(2)],
    )
    assert [r.stdout for r in p.rows] == ["a"]
    assert p.duplicates == 2


def test_sibling_results_passed_as_existing_are_duplicates() -> None:
    # The caller passes the job's and its sibling's result uuids (#124 (b)).
    p = plan(EQ_OK, commands(1, 2, 3), {pid(2)}, [item(2)])
    assert p == Plan(rows=(), duplicates=1)


def test_rows_in_batch_order_and_counts_add_up() -> None:
    spec = spec_of({n: ("equals", "ok") for n in range(1, 51)})
    order = list(range(50, 0, -1))
    p = plan(spec, commands(*range(1, 51)), set(), [item(n) for n in order])
    assert [r.plugin_uuid for r in p.rows] == [pid(n) for n in order]
    assert len(p.rows) + p.duplicates == 50
    assert p.duplicates == 0


def test_empty_batch() -> None:
    assert plan(EQ_OK, commands(1, 2, 3), set(), []) == Plan(rows=(), duplicates=0)
    assert plan(EQ_OK, commands(1, 2, 3), {pid(1)}, []) == Plan(rows=(), duplicates=0)


# --- CHK-M9-056: verdicts equal M8 result_verdict ---------------------------

# (operator, expected, passing stdout, failing stdout)
OP_CASES = [
    ("equals", "install ok installed", "install ok installed", "deinstall"),
    ("not_equals", "x", "y", "x"),
    (
        "contains",
        "PermitRootLogin no",
        "a\nPermitRootLogin no\nb",
        "PermitRootLogin yes",
    ),
    ("not_contains", "nullok", "auth required", "auth nullok"),
    ("regex", r"^MaxAuthTries\s+[1-4]$", "Port 22\nMaxAuthTries 3", "MaxAuthTries 6"),
    (
        "not_regex",
        r"^\s*PermitEmptyPasswords\s+yes",
        "PermitEmptyPasswords no",
        "PermitEmptyPasswords yes",
    ),
    ("eq", "0", "0", "1"),
    ("ne", "0", "1", "0"),
    ("gt", "13", "14", "13"),
    ("ge", "14", "14", "13"),
    ("lt", "91", "90", "91"),
    ("le", "90", "90", "91"),
    ("empty", "", "", "x"),
    ("not_empty", "", "x", ""),
]


def _expected_codes(entry: PluginSpec, it: ResultItem) -> tuple[int, str | None]:
    v = result_verdict(entry, it)
    return v.code, None if v.detail is None else v.detail.value


def _matrix() -> list[tuple[str, str, dict[str, Any]]]:
    rows: list[tuple[str, str, dict[str, Any]]] = []
    for op, exp, good, bad in OP_CASES:
        rows.append((op, exp, {"stdout": good}))
        rows.append((op, exp, {"stdout": bad}))
        rows.append((op, exp, {"stdout": good, "exit_code": 1}))
    op, exp = "equals", "ok"
    for over in (
        {"exit_code": 126},
        {"exit_code": 127},
        {"exit_code": 137},
        {"exit_code": None},
        {"exit_code": -1},
        {"timed_out": True},
        {"truncated": True},
        {"error": "spool_overflow"},
        {"error": "runner_unavailable"},
        {"stdout": "abc"},
    ):
        rows.append((op, exp, over))
    rows.append(("eq", "5", {"stdout": "five"}))
    rows.append(("regex", "(", {"stdout": "x"}))
    return rows


@pytest.mark.parametrize(("op", "exp", "over"), _matrix())
def test_verdict_is_m8_result_verdict(op: str, exp: str, over: dict[str, Any]) -> None:
    spec = spec_of({1: (op, exp)})
    it = item(1, **over)
    p = plan(spec, commands(1), set(), [it])
    (row,) = p.rows
    entry = spec.get(pid(1))
    assert entry is not None
    assert (row.eval_code, row.eval_detail) == _expected_codes(entry, it)
    assert row.eval_code in (0, 1, 2)
    assert (row.eval_detail is None) is (row.eval_code != 2)


def test_matrix_covers_pass_fail_and_error() -> None:
    codes = set()
    for op, exp, over in _matrix():
        codes.add(
            plan(spec_of({1: (op, exp)}), commands(1), set(), [item(1, **over)])
            .rows[0]
            .eval_code
        )
    assert codes == {0, 1, 2}


# --- CHK-M9-057: caps -------------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "stderr", "oversize"),
    [
        ("a" * 65_537, "", True),
        ("a" * 65_536, "", False),
        ("", "e" * 16_385, True),
        ("", "e" * 16_384, False),
        ("\u20ac" * 21_846, "", True),  # 65,538 bytes in 21,846 chars
        ("\u20ac" * 21_845 + "a", "", False),  # 65,536 bytes
        ("a" * 65_537, "e" * 16_385, True),
    ],
    # Short ids: a 65 KB id breaks PYTEST_CURRENT_TEST on Windows (32,767 chars).
    ids=[
        "stdout_over_cap",
        "stdout_at_cap",
        "stderr_over_cap",
        "stderr_at_cap",
        "stdout_multibyte_over_cap",
        "stdout_multibyte_at_cap",
        "both_over_cap",
    ],
)
def test_caps(stdout: str, stderr: str, oversize: bool) -> None:
    spec = spec_of({1: ("not_empty", "")})
    (row,) = plan(
        spec, commands(1), set(), [item(1, stdout=stdout, stderr=stderr)]
    ).rows
    if oversize:
        assert (row.eval_code, row.eval_detail) == (2, "oversize")
        assert row.stdout == "" and row.stderr == ""
    else:
        assert row.eval_detail != "oversize"
        assert row.stdout == stdout and row.stderr == stderr


def test_oversize_wins_over_flags_and_runner_error() -> None:
    spec = spec_of({1: ("equals", "ok")})
    (row,) = plan(
        spec,
        commands(1),
        set(),
        [
            item(
                1,
                stdout="a" * 70_000,
                error="runner_unavailable",
                truncated=True,
                timed_out=True,
            )
        ],
    ).rows
    assert (row.eval_code, row.eval_detail, row.stdout, row.stderr) == (
        2,
        "oversize",
        "",
        "",
    )


# --- CHK-M9-058 / -059: #121 order and evaluation of the stored text --------


def test_caps_are_measured_on_the_received_text() -> None:
    # 65,535 + 1 NUL byte = 65,536 bytes as received; U+FFFD is 3 bytes.
    stdout = "a" * 65_535 + "\x00"
    (row,) = plan(
        spec_of({1: ("not_empty", "")}), commands(1), set(), [item(1, stdout=stdout)]
    ).rows
    assert row.eval_detail != "oversize"
    assert row.eval_code == 0
    assert row.stdout == "a" * 65_535 + "\ufffd"
    assert len(row.stdout.encode("utf-8")) == 65_538


def test_many_nuls_under_the_cap_stay_under_it() -> None:
    stdout = "x" * 65_000 + "\x00" * 300  # 65,300 bytes received, 65,900 stored
    (row,) = plan(
        spec_of({1: ("contains", "\ufffd")}),
        commands(1),
        set(),
        [item(1, stdout=stdout)],
    ).rows
    assert (row.eval_code, row.eval_detail) == (0, None)
    assert "\x00" not in row.stdout and row.stdout.count("\ufffd") == 300


def test_oversize_with_nuls_stores_empty_streams() -> None:
    stdout = "\x00" * 65_537
    (row,) = plan(
        spec_of({1: ("equals", "ok")}),
        commands(1),
        set(),
        [item(1, stdout=stdout, stderr="\x00")],
    ).rows
    assert (row.eval_code, row.eval_detail, row.stdout, row.stderr) == (
        2,
        "oversize",
        "",
        "",
    )


def test_verdict_is_on_the_replaced_nul_text() -> None:
    (row,) = plan(
        spec_of({1: ("equals", "a\ufffdb")}),
        commands(1),
        set(),
        [item(1, stdout="a\x00b")],
    ).rows
    assert row.stdout == "a\ufffdb"
    assert (row.eval_code, row.eval_detail) == (0, None)
    # the raw text would FAIL
    assert classify("equals", "a\ufffdb", "a\x00b", 0, False, False).code == 1


def test_verdict_is_on_the_replaced_surrogate_text() -> None:
    it = raw_item(
        '{"plugin_uuid": "' + str(pid(1)) + '", "exit_code": 0, "stdout": "\\ud800", '
        '"stderr": "", "started_at": "2026-10-30T12:00:00Z", '
        '"finished_at": "2026-10-30T12:00:01Z", '
        '"timed_out": false, "truncated": false, "error": null}'
    )
    assert it.stdout == "\ud800"
    (row,) = plan(spec_of({1: ("equals", "\ufffd")}), commands(1), set(), [it]).rows
    assert row.stdout == "\ufffd"
    assert (row.eval_code, row.eval_detail) == (0, None)


def test_regex_on_replaced_surrogate_text() -> None:
    # M8 gives `cannot evaluate` for a regex over a lone surrogate (CHK-M8-034).
    raw = "\ud800\nx"
    assert classify("regex", "^x$", raw, 0, False, False).detail is not None
    (row,) = plan(
        spec_of({1: ("regex", "^x$")}), commands(1), set(), [item(1, stdout=raw)]
    ).rows
    assert row.stdout == "\ufffd\nx"
    assert (row.eval_code, row.eval_detail) == (0, None)


def test_stderr_replacement_does_not_change_the_verdict() -> None:
    (row,) = plan(
        spec_of({1: ("equals", "ok")}),
        commands(1),
        set(),
        [item(1, stderr="e\x00\ud800")],
    ).rows
    assert row.stderr == "e\ufffd\ufffd"
    assert (row.eval_code, row.eval_detail) == (0, None)


def test_runner_error_with_nul_keeps_its_verdict_and_replaces_text() -> None:
    (row,) = plan(
        spec_of({1: ("equals", "ok")}),
        commands(1),
        set(),
        [item(1, stdout="ok\x00", error="spool_overflow")],
    ).rows
    assert (row.eval_code, row.eval_detail) == (2, "spool_overflow")
    assert row.stdout == "ok\ufffd"


def test_timed_out_with_nul_stays_timed_out() -> None:
    (row,) = plan(
        spec_of({1: ("equals", "a\ufffd")}),
        commands(1),
        set(),
        [item(1, stdout="a\x00", timed_out=True)],
    ).rows
    assert (row.eval_code, row.eval_detail) == (2, "timed out")


# --- CHK-M9-060: the shared NUL fixture -------------------------------------


def test_nul_fixture_is_stored_with_replacement_characters() -> None:
    body = json.loads(
        (FIXTURES / "request_valid_nul_in_stdout_and_stderr.json").read_text(
            encoding="utf-8"
        )
    )
    request = ResultsRequest.model_validate(body)
    assert request.results, "fixture has items"
    entries = {}
    for i, r in enumerate(request.results):
        entries[r.plugin_uuid] = PluginSpec(
            plugin_uuid=r.plugin_uuid,
            name=f"N {i}",
            operator="contains",
            expected="\ufffd",
        )
    spec = EvalSpec(tuple(entries.values()))
    cmds = {u: "cmd" for u in entries}
    p = plan(spec, cmds, set(), request.results)
    assert len(p.rows) + p.duplicates == len(request.results)
    saw_nul = False
    for row, it in zip(p.rows, request.results, strict=False):
        saw_nul = saw_nul or "\x00" in it.stdout or "\x00" in it.stderr
        assert "\x00" not in row.stdout and "\x00" not in row.stderr
        assert row.stdout == it.stdout.replace("\x00", "\ufffd")
        assert row.stderr == it.stderr.replace("\x00", "\ufffd")
        row.stdout.encode("utf-8")
        row.stderr.encode("utf-8")
        if "\x00" in it.stdout and it.error is None:
            entry = spec.get(it.plugin_uuid)
            assert entry is not None
            want = classify(
                entry.operator,
                entry.expected,
                row.stdout,
                it.exit_code,
                it.timed_out,
                it.truncated,
            )
            assert (row.eval_code, row.eval_detail) == (
                want.code,
                None if want.detail is None else want.detail.value,
            )
    assert saw_nul


# --- CHK-M9-061: storable ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("", ""),
        ("plain text", "plain text"),
        ("\ufffd", "\ufffd"),
        ("\U0001f600", "\U0001f600"),
        ("\x00", "\ufffd"),
        ("a\x00b\x00", "a\ufffdb\ufffd"),
        ("\ud800", "\ufffd"),
        ("\udbff", "\ufffd"),
        ("\udc00", "\ufffd"),
        ("\udfff", "\ufffd"),
        (
            "\ud83d\ude00",
            "\ufffd\ufffd",
        ),  # two surrogate code points, not one character
        ("x\ud800\x00y", "x\ufffd\ufffdy"),
        ("\x01\x7f\u0085", "\x01\x7f\u0085"),
    ],
)
def test_storable(text: str, want: str) -> None:
    got = storable(text)
    assert got == want
    assert len(got) == len(text)
    got.encode("utf-8")


def test_json_escaped_pair_is_one_character_and_kept() -> None:
    text = json.loads('"\\ud83d\\ude00"')
    assert text == "\U0001f600"
    assert storable(text) == text


# --- CHK-M9-062 / -063 / -064: snapshots, runner errors, SR §1.1 ------------


def test_snapshots_and_sent_values() -> None:
    spec = EvalSpec(
        (
            PluginSpec(
                plugin_uuid=pid(1),
                name="CIS X - 1.1 - name " + CANARY,
                operator="contains",
                expected="exp " + CANARY,
            ),
        )
    )
    cmds = {pid(1): "the payload command"}
    it = item(
        1,
        exit_code=3,
        stdout="exp " + CANARY,
        stderr="warn",
        timed_out=False,
        truncated=False,
        started_at="2026-10-30T12:00:00.250Z",
        finished_at="2026-10-30T12:05:00Z",
    )
    (row,) = plan(spec, cmds, set(), [it]).rows
    assert row.plugin_name_snap == "CIS X - 1.1 - name " + CANARY
    assert row.operator_snap == "contains"
    assert row.expected_snap == "exp " + CANARY
    assert row.execute_snap == "the payload command"
    assert row.exit_code == 3
    assert (row.timed_out, row.truncated) == (False, False)
    assert row.started_at == it.started_at and row.finished_at == it.finished_at
    assert row.stderr == "warn"
    assert row.plugin_uuid == pid(1)


@pytest.mark.parametrize("flag", ["timed_out", "truncated"])
def test_flags_are_stored_as_sent(flag: str) -> None:
    (row,) = plan(EQ_OK, commands(1, 2, 3), set(), [item(1, **{flag: True})]).rows
    assert getattr(row, flag) is True


@pytest.mark.parametrize("error", ["runner_unavailable", "spool_overflow"])
def test_runner_errors(error: str) -> None:
    (row,) = plan(
        EQ_OK,
        commands(1, 2, 3),
        set(),
        [item(1, stdout="ok", stderr="", exit_code=None, error=error)],
    ).rows
    assert (row.eval_code, row.eval_detail) == (2, error)
    assert row.stdout == "ok"


def test_sr_1_1() -> None:
    spec = spec_of({1: ("equals", "install ok installed")})
    p = plan(
        spec, commands(1), set(), [item(1, stdout="install ok installed", exit_code=0)]
    )
    assert (p.rows[0].eval_code, p.rows[0].eval_detail) == (0, None)
    p = plan(spec, commands(1), set(), [item(1, stdout="", exit_code=1)])
    assert (p.rows[0].eval_code, p.rows[0].eval_detail) == (1, None)


# --- CHK-M9-065 / -066: no output in errors or logs; frozen ------------------


def test_no_output_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    spec = spec_of({1: ("equals", CANARY), 2: ("regex", "(")})
    plan(
        spec,
        commands(1, 2),
        set(),
        [item(1, stdout=CANARY + "\x00", stderr=CANARY), item(2, stdout=CANARY)],
    )
    with pytest.raises(PluginNotInJob):
        plan(
            spec,
            commands(1, 2),
            set(),
            [item(1, stdout=CANARY), item(7, stdout=CANARY)],
        )
    for rec in caplog.records:
        assert CANARY not in rec.getMessage() and CANARY not in repr(rec.args)


def test_plan_types_are_frozen_and_inputs_untouched() -> None:
    existing = {pid(1)}
    p = plan(EQ_OK, commands(1, 2, 3), existing, [item(2), item(1)])
    assert existing == {pid(1)}
    with pytest.raises(FrozenInstanceError):
        p.duplicates = 0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        p.rows[0].stdout = "x"  # type: ignore[misc]
    assert isinstance(p.rows, tuple) and isinstance(p.rows[0], ResultRow)


def test_existing_may_be_any_collection() -> None:
    for existing in ([pid(1)], (pid(1),), frozenset({pid(1)}), {pid(1): None}.keys()):
        assert (
            plan(EQ_OK, commands(1, 2, 3), existing, [item(1), item(2)]).duplicates == 1
        )
