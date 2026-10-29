"""`result_verdict()`: the verdict result intake (M9) stores for one posted
result (TS §4.5 L593, L599; §3.3; open questions #12, #112 (c), #116).

The manager's own size measurement comes first, then the runner's error, and
only then the comparison (`classify`). Only stdout is compared; stderr counts
only toward its cap. Pure and total.
"""

from __future__ import annotations

from bitscan_manager.services.evaluator.evaluate import classify
from bitscan_manager.services.evaluator.model import (
    ERROR,
    STDERR_CAP,
    STDOUT_CAP,
    Detail,
    PluginSpec,
    ResultLike,
    Verdict,
)


def utf8_size(text: str) -> int:
    """`text`'s size in UTF-8 bytes (#116 (a)). A lone surrogate counts as
    3 bytes rather than raising."""
    return len(text.encode("utf-8", "surrogatepass"))


def over_caps(stdout: str, stderr: str) -> bool:
    """True when stdout is over 65,536 or stderr over 16,384 UTF-8 bytes;
    exactly the cap is accepted (#116 (b))."""
    return utf8_size(stdout) > STDOUT_CAP or utf8_size(stderr) > STDERR_CAP


def result_verdict(spec: PluginSpec, result: ResultLike) -> Verdict:
    """ERROR `oversize`, whatever the agent's flags claim (L599); else ERROR
    with the runner's error, without comparing (#12); else `classify()`."""
    if over_caps(result.stdout, result.stderr):
        return Verdict(ERROR, Detail.OVERSIZE)
    if result.error == "spool_overflow":
        return Verdict(ERROR, Detail.SPOOL_OVERFLOW)
    if result.error == "runner_unavailable":
        return Verdict(ERROR, Detail.RUNNER_UNAVAILABLE)
    if result.error is not None:
        # Outside the wire contract (the schema allows only the two above).
        return Verdict(ERROR, Detail.CANNOT_EVALUATE)
    return classify(
        spec.operator,
        spec.expected,
        result.stdout,
        result.exit_code,
        result.timed_out,
        result.truncated,
    )
