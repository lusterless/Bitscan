"""TP-M8-08: evaluator property suite (REQ-186 (3), REQ-187 (2), REQ-190,
REQ-203; grown with REQ-194, REQ-195, REQ-196 in the TASK-179 to -181 TESTs).

Totality, the exit-code rule, and a `Decimal` oracle for the numeric
operators. Expected behaviour from TS §4.5 L589-L600, SR §2.4 L153, #13, #112,
#114. CHK-M8-130 to -136 (tests/m8/test-plan.md).
"""

from __future__ import annotations

import operator as o
from collections.abc import Callable
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from bitscan_manager.services.evaluator.evaluate import classify, evaluate
from bitscan_manager.services.evaluator.model import Detail, Verdict
from bitscan_manager.services.evaluator.normalise import normalise
from bitscan_manager.services.importer.model import OPERATORS

NUMERIC = ("eq", "ne", "gt", "ge", "lt", "le")
ORACLE: dict[str, Callable[[Decimal, Decimal], bool]] = {
    "eq": o.eq,
    "ne": o.ne,
    "gt": o.gt,
    "ge": o.ge,
    "lt": o.lt,
    "le": o.le,
}

# Strings with lone surrogates, CR, NUL and Unicode spaces (codec=None allows
# surrogates).
ANY_TEXT = st.text(alphabet=st.characters(codec=None), max_size=40)
PIECES = st.lists(
    st.one_of(
        st.sampled_from(["\r\n", "\r", "\n", " ", "\t", " ", "\ud800", "\x00"]),
        st.sampled_from(["1", "-", "+", ".", "0", "a", "^", "$", "(", "[", "\\"]),
        st.characters(codec=None),
    ),
    max_size=30,
).map("".join)
TEXT = st.one_of(ANY_TEXT, PIECES)
OPERATOR = st.one_of(
    st.sampled_from(OPERATORS),
    st.sampled_from([o.upper() for o in OPERATORS]),
    st.sampled_from(["", " ", "equal", "regexp", "not_equal", "eq ", "\x00"]),
    ANY_TEXT,
)
EXIT_CODE = st.one_of(
    st.none(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.sampled_from([0, 1, 2, 125, 126, 127, 128, 255, 256, -1]),
)


# CHK-M8-130: REQ-186 (3)
@settings(max_examples=10_000, deadline=None)
@given(OPERATOR, TEXT, TEXT, EXIT_CODE, st.booleans(), st.booleans())
def test_classify_and_evaluate_are_total(
    op: str,
    expected: str,
    stdout: str,
    exit_code: int | None,
    timed_out: bool,
    truncated: bool,
) -> None:
    v = classify(op, expected, stdout, exit_code, timed_out, truncated)
    assert isinstance(v, Verdict)
    assert v.code in (0, 1, 2)
    assert (v.detail is None) is (v.code in (0, 1))
    if v.detail is not None:
        assert isinstance(v.detail, Detail)
    assert evaluate(op, expected, stdout, exit_code, timed_out, truncated) == v.code
    # Unknown operators never PASS or FAIL.
    if op not in OPERATORS:
        assert v.code == 2


# stdout that PASSes each numeric operator against expected "1"
NUMERIC_PASS_STDOUT = {"eq": "1", "ge": "1", "le": "1", "ne": "2", "gt": "2", "lt": "0"}


# CHK-M8-136: the exit-code rule (#114, TS §4.5 L593 and L598)
@settings(max_examples=3_000, deadline=None)
@given(EXIT_CODE, st.sampled_from(OPERATORS))
def test_exit_code_rule(exit_code: int | None, op: str) -> None:
    expected, stdout = {
        "equals": ("x", "x"),
        "not_equals": ("x", "y"),
        "contains": ("x", "axb"),
        "not_contains": ("x", "y"),
        "regex": ("^x$", "x"),
        "not_regex": ("^x$", "y"),
        "empty": ("", ""),
        "not_empty": ("", "x"),
    }.get(op, ("1", NUMERIC_PASS_STDOUT.get(op, "")))
    v = classify(op, expected, stdout, exit_code, False, False)
    is_error = (
        exit_code is None
        or exit_code < 0
        or exit_code in (126, 127)
        or exit_code >= 128
    )
    if is_error:
        assert v.code == 2
        assert v.detail in (
            Detail.NO_EXIT_CODE,
            Detail.CANNOT_RUN,
            Detail.NOT_FOUND,
            Detail.KILLED_BY_SIGNAL,
        )
    else:
        assert v == Verdict(0, None)


# CHK-M8-132: Decimal oracle for #13 numbers
SIGN = st.sampled_from(["", "+", "-"])
DIGITS = st.text(alphabet="0123456789", min_size=1, max_size=60)
NUMBER = st.builds(
    lambda s, w, f: s + w + ("." + f if f else ""),
    SIGN,
    DIGITS,
    st.one_of(st.just(""), DIGITS),
)


@settings(max_examples=5_000, deadline=None)
@given(NUMBER, NUMBER, st.sampled_from(NUMERIC))
def test_numeric_matches_decimal_oracle(a: str, b: str, op: str) -> None:
    want = ORACLE[op](Decimal(a), Decimal(b))
    v = classify(op, b, a, 0, False, False)
    assert v == Verdict(0 if want else 1, None)


@settings(max_examples=2_000, deadline=None)
@given(DIGITS, st.integers(min_value=0, max_value=5), st.sampled_from(["", "+"]))
def test_equal_values_in_different_spellings_are_eq(
    digits: str, zeros: int, sign: str
) -> None:
    padded = "0" * zeros + digits
    assert classify("eq", digits, sign + padded, 0, False, False).code == 0
    assert classify("eq", digits, padded + ".0", 0, False, False).code == 0
    same = sign + padded + "." + "0" * zeros + "0"
    assert classify("ne", digits, same, 0, False, False).code == 1


# CHK-M8-131: idempotence through classify: normalising first never changes a
# verdict (inputs without CR CR LF, ruling 2026-10-29).
@settings(max_examples=3_000, deadline=None)
@given(
    st.sampled_from(OPERATORS),
    TEXT.filter(lambda s: "\r\r\n" not in s),
    TEXT.filter(lambda s: "\r\r\n" not in s),
)
def test_prenormalised_input_gives_the_same_verdict(op: str, e: str, s: str) -> None:
    assert classify(op, e, s, 0, False, False) == classify(
        op, normalise(e), normalise(s), 0, False, False
    )


# CHK-M8-364 (G63 half): Verdict accepts exactly the 0/1/2 invariant
DETAIL_OR_NOT = st.one_of(
    st.none(),
    st.sampled_from(list(Detail)),
    st.sampled_from([d.value for d in Detail] + ["", "bogus"]),
)


@settings(max_examples=2_000, deadline=None)
@given(st.integers(min_value=-5, max_value=10), DETAIL_OR_NOT)
def test_verdict_constructs_exactly_when_valid(code: int, detail: object) -> None:
    valid = (code in (0, 1) and detail is None) or (
        code == 2 and isinstance(detail, Detail)
    )
    try:
        Verdict(code, detail)  # type: ignore[arg-type]
    except ValueError:
        assert not valid, (code, detail)
    else:
        assert valid, (code, detail)
