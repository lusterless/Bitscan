"""The install runbook's Bootstrap block is TS §5.2 byte for byte (REQ-138 (3), CHK-M6-040).

Usage: python -I deploy/tests/check_runbook_bootstrap.py [--root DIR] [--runbook FILE]

The runbook must hold exactly one ```sql fenced block, and that block, fences
included, must equal TS §5.2 lines 1023-1038 byte for byte (LF endings, no
trailing blanks added or removed). The spec lines are checked to be the
```sql fence after the **Bootstrap** paragraph and its closing fence, so a
moved spec block fails loudly instead of comparing the wrong lines.
Exit 0 on a match, 1 on any difference (the first differing line is printed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SPEC = Path("docs/spec/Technical_Specification.md")
RUNBOOK = Path("deploy/runbooks/manager-install.md")
# 1-based: opening ```sql fence and closing fence of the TS §5.2 Bootstrap block
SPEC_START, SPEC_END = 1023, 1038


def spec_block(spec: bytes) -> bytes:
    lines = spec.split(b"\n")
    if not lines[SPEC_START - 3].startswith(b"**Bootstrap**"):
        raise SystemExit(f"TS line {SPEC_START - 2} is not the **Bootstrap** paragraph")
    if lines[SPEC_START - 1] != b"```sql" or lines[SPEC_END - 1] != b"```":
        raise SystemExit(f"TS lines {SPEC_START}/{SPEC_END} are not the sql fences")
    return b"\n".join(lines[SPEC_START - 1 : SPEC_END]) + b"\n"


def sql_blocks(runbook: bytes) -> list[bytes]:
    """Every ```sql block, fences included, as raw bytes (LF kept)."""
    blocks: list[bytes] = []
    current: list[bytes] | None = None
    for line in runbook.split(b"\n"):
        if current is None:
            if line.lstrip() == b"```sql":
                current = [line]
        else:
            current.append(line)
            if line.strip() == b"```":
                blocks.append(b"\n".join(current) + b"\n")
                current = None
    if current is not None:
        blocks.append(b"\n".join(current))  # unterminated: never equal
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--runbook", default=None)
    args = ap.parse_args()
    root = Path(args.root)
    spec_raw = (root / SPEC).read_bytes()
    book_raw = Path(args.runbook).read_bytes() if args.runbook else (root / RUNBOOK).read_bytes()
    problems = []
    if b"\r" in book_raw:
        problems.append("the runbook has CR characters (must be LF only)")
    want = spec_block(spec_raw)
    blocks = sql_blocks(book_raw)
    if len(blocks) != 1:
        problems.append(f"the runbook holds {len(blocks)} ```sql blocks, want exactly 1")
    elif blocks[0] != want:
        got_l, want_l = blocks[0].split(b"\n"), want.split(b"\n")
        for n, (g, w) in enumerate(zip(got_l, want_l, strict=False), 1):
            if g != w:
                problems.append(f"block line {n}: runbook {g!r} != spec {w!r}")
                break
        else:
            problems.append(f"block length differs: runbook {len(got_l)} lines, spec {len(want_l)}")
    for p in problems:
        print(p)
    n = len(want.split(b"\n")) - 1
    print("FAIL" if problems else "OK", f"Bootstrap block ({n} lines, fences included) vs TS L{SPEC_START}-L{SPEC_END}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
