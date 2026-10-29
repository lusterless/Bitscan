"""Evaluator types shared by intake (M9), re-evaluation and the views
(TS §4.5, §5.2; SR §2.4; open questions #12, #112, #116, #117).

Pure: no I/O, no logging, no clock, no module state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol
from uuid import UUID

# The 14 SR §2.4 operators, in the order of `importer.model.OPERATORS`.
# Evaluation functions take `operator: str` (the value comes from JSONB and
# must be total, #112 (d)); this Literal is for callers that know the value.
Operator = Literal[
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
]

VerdictCode = Literal[0, 1, 2]
PASS: Final[VerdictCode] = 0
FAIL: Final[VerdictCode] = 1
ERROR: Final[VerdictCode] = 2  # TS §4.5: "Anything else (stored as 2)"


class Detail(StrEnum):
    """The stored `eval_detail` of an ERROR verdict (#112 (a)). Fixed words
    only: a detail never quotes stdout, stderr, the expected value or a
    pattern (REQ-193)."""

    OVERSIZE = "oversize"
    SPOOL_OVERFLOW = "spool_overflow"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    TIMED_OUT = "timed out"
    NO_EXIT_CODE = "no exit code"
    CANNOT_RUN = "cannot run"
    NOT_FOUND = "not found"
    KILLED_BY_SIGNAL = "killed by signal"
    STDOUT_TRUNCATED = "stdout truncated"
    CANNOT_EVALUATE = "cannot evaluate"
    STDOUT_NOT_NUMERIC = "stdout not numeric"


# Decided by intake before `classify()`, and kept as they are by
# re-evaluation (#12, #118 (e)).
INTAKE_DETAILS: Final = frozenset(
    {Detail.OVERSIZE, Detail.SPOOL_OVERFLOW, Detail.RUNNER_UNAVAILABLE}
)

# Server-side caps in UTF-8 bytes, a result is `oversize` when strictly over
# (TS §4.5 L599; #57: 1 KB = 1,024 bytes; #116 (a), (b)).
STDOUT_CAP: Final = 65_536
STDERR_CAP: Final = 16_384


@dataclass(frozen=True, slots=True)
class Verdict:
    """`eval_code` and `eval_detail`: detail is None exactly when the code is
    PASS or FAIL, and a `Detail` member when it is ERROR (REQ-193 (4))."""

    code: VerdictCode
    detail: Detail | None

    def __post_init__(self) -> None:
        # `type(...) is int` also refuses True and False.
        if type(self.code) is not int or self.code not in (PASS, FAIL, ERROR):
            raise ValueError("verdict code must be 0, 1 or 2")
        if self.code == ERROR:
            if not isinstance(self.detail, Detail):
                raise ValueError("an ERROR verdict needs a detail")
        elif self.detail is not None:
            raise ValueError("a PASS or FAIL verdict has no detail")


@dataclass(frozen=True, slots=True)
class PluginSpec:
    """One `eval_spec` entry (#117), built and parsed by `eval_spec`.
    `operator` is a `str`, not an `Operator`: it is read from JSONB, and a
    value outside the 14 evaluates to ERROR `cannot evaluate`."""

    plugin_uuid: UUID
    name: str
    operator: str
    expected: str


class ResultLike(Protocol):
    """The result fields evaluation reads, as the M3 `ResultItem` has them."""

    @property
    def exit_code(self) -> int | None: ...
    @property
    def stdout(self) -> str: ...
    @property
    def stderr(self) -> str: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def truncated(self) -> bool: ...
    @property
    def error(self) -> str | None: ...
