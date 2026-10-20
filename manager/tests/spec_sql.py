"""SQL taken from the spec at test time (TP-M1-02, REQ-032 (1)).

The TS §5.2 Bootstrap block is read from ``docs/spec/Technical_Specification.md``
when the tests run, so a change to the spec shows up in the harness. It is found
by its heading and fence, not by line number. ``\\c bitscan`` is the only psql
meta-command allowed; the harness carries it out as a reconnect to ``bitscan``.
"""

from dataclasses import dataclass
from pathlib import Path

SPEC = (
    Path(__file__).resolve().parents[2] / "docs" / "spec" / "Technical_Specification.md"
)
BOOTSTRAP_HEADING = "**Bootstrap**"
RECONNECT = "\\c bitscan"


@dataclass(frozen=True)
class Bootstrap:
    on_postgres: tuple[str, ...]  # before \c bitscan, on the maintenance database
    on_bitscan: tuple[str, ...]  # after \c bitscan


def sql_block_after(text: str, heading: str) -> list[str]:
    """Lines of the first ```sql fence after the line that starts with ``heading``."""
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        raise ValueError(f"spec has no line starting with {heading!r}")
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "```sql":
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == "```":
                    return lines[i + 1 : j]
            raise ValueError(f"unclosed sql fence after {heading!r}")
        if lines[i].startswith("**") or lines[i].startswith("#"):
            break
    raise ValueError(f"no sql block directly after {heading!r}")


def split_statements(lines: list[str]) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("--"):
            continue
        buf.append(line)
        if line.endswith(";"):
            statements.append("\n".join(buf))
            buf = []
    if buf:
        raise ValueError(f"statement without a closing semicolon: {buf!r}")
    return statements


def bootstrap(text: str | None = None) -> Bootstrap:
    if text is None:
        text = SPEC.read_text(encoding="utf-8")
    lines = sql_block_after(text, BOOTSTRAP_HEADING)
    metas = [i for i, line in enumerate(lines) if line.lstrip().startswith("\\")]
    if len(metas) != 1 or lines[metas[0]].strip() != RECONNECT:
        found = [lines[i].strip() for i in metas]
        raise ValueError(f"expected exactly one {RECONNECT!r}, found {found!r}")
    cut = metas[0]
    before = split_statements(lines[:cut])
    after = split_statements(lines[cut + 1 :])
    if not before or not after:
        raise ValueError("bootstrap block has an empty half")
    return Bootstrap(tuple(before), tuple(after))
