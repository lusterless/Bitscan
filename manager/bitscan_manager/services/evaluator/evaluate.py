"""`classify()` and `evaluate()`: one result against its `eval_spec` entry
(TS §4.5 L587–L600; SR §2.4; open questions #12, #112, #113, #114).

Pure and total: any `str` operator, expected and stdout, `int | None` exit
code and two booleans give a verdict; nothing is logged, read or raised. The
runner `error` and the server-side caps are decided before this, at intake
(`verdict.result_verdict`, #12).
"""

from __future__ import annotations

from typing import Final

from bitscan_manager.services.evaluator.model import (
    ERROR,
    FAIL,
    PASS,
    Detail,
    Verdict,
    VerdictCode,
)
from bitscan_manager.services.evaluator.normalise import normalise
from bitscan_manager.services.evaluator.operators import (
    CannotEvaluate,
    NotNumeric,
    compare,
)

_CANNOT_RUN: Final = 126  # TS §4.5 L593: "126/127 (cannot run / not found)"
_NOT_FOUND: Final = 127
_SIGNAL_MIN: Final = 128  # "≥ 128 (killed by signal)"


def _run_error(
    exit_code: int | None, timed_out: bool, truncated: bool
) -> Detail | None:
    """The first ERROR cause about the run, in #112 (c) order, or None. The
    command's own exit code otherwise never decides the verdict (L598)."""
    if timed_out:
        return Detail.TIMED_OUT
    if exit_code is None:
        return Detail.NO_EXIT_CODE  # #114
    if exit_code == _CANNOT_RUN:
        return Detail.CANNOT_RUN
    if exit_code == _NOT_FOUND:
        return Detail.NOT_FOUND
    if exit_code >= _SIGNAL_MIN or exit_code < 0:
        return Detail.KILLED_BY_SIGNAL  # negative: #114
    if truncated:
        # One flag on the wire; it means stdout was cut at 64 KB (#113), and
        # makes every operator ERROR, whatever the kept text holds.
        return Detail.STDOUT_TRUNCATED
    return None


def classify(
    operator: str,
    expected: str,
    stdout: str,
    exit_code: int | None,
    timed_out: bool,
    truncated: bool,
) -> Verdict:
    """The verdict and its `eval_detail`: the run checks first, then both
    strings normalised (L597) and compared (#112 (c): the first cause wins)."""
    cause = _run_error(exit_code, timed_out, truncated)
    if cause is not None:
        return Verdict(ERROR, cause)
    try:
        holds = compare(operator, normalise(expected), normalise(stdout))
    except CannotEvaluate:
        return Verdict(ERROR, Detail.CANNOT_EVALUATE)
    except NotNumeric:
        return Verdict(ERROR, Detail.STDOUT_NOT_NUMERIC)
    return Verdict(PASS if holds else FAIL, None)


def evaluate(
    operator: str,
    expected: str,
    stdout: str,
    exit_code: int | None,
    timed_out: bool,
    truncated: bool,
) -> VerdictCode:
    """TS §4.5 L600: 0 PASS, 1 FAIL, 2 ERROR. The code of `classify()`, so
    there is one comparison implementation."""
    return classify(operator, expected, stdout, exit_code, timed_out, truncated).code
