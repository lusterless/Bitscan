"""Check deploy/systemd/* and deploy/dbus/* against the TS blocks (REQ-016, REQ-106 (2)).

Usage: python deploy/tests/check_units_verbatim.py [agent|manager|all] [--root DIR]
Exit 0 when every selected file is byte-identical to its spec block with the
fence lines removed (LF endings, one final newline), units have no end-of-line
comment, and the set of files in each checked folder is exact. `agent` and
`all` also check the D-Bus policy (TS §3.7, M4 TP-M4-07).

One documented exception (DEVIATIONS below): bitscan-capread.socket must be its
spec block plus exactly one added line, `RemoveOnStop=yes`, right after
`SocketMode=0660` (user decision 2026-10-26, TASK-138; a recorded deviation
from the verbatim TS §3.7 unit). Any other difference in that unit, the line
anywhere else, or the unit without it, still fails.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SPEC = Path("docs/spec/Technical_Specification.md")

# file name -> (opening fence line, closing fence line), 1-based, from work/tasks.md
AGENT: dict[str, tuple[int, int]] = {
    "bitscan-runner.socket": (289, 302),
    "bitscan-runner.service": (308, 363),
    "bitscan-agent.service": (369, 408),
    "bitscan-capread.socket": (437, 449),
    "bitscan-capread.service": (451, 482),
}
MANAGER: dict[str, tuple[int, int]] = {
    "bitscan-manager.service": (1352, 1401),
    "bitscan-manager-migrate.service": (1405, 1435),
    "bitscan-manager-maintain.service": (1439, 1467),
    "bitscan-manager-maintain.timer": (1469, 1480),
}
# D-Bus policy (TS §3.7): ```xml fence at L412, closing fence at L431
DBUS: dict[str, tuple[int, int]] = {
    "bitscan-runner.conf": (412, 431),
}

# Recorded deviations from the verbatim TS blocks: file name -> (the spec line
# the added line follows, the added line). Only these exact bytes, only there.
# bitscan-capread.socket: user decision 2026-10-26 (TASK-138), so systemd
# removes /run/bitscan/capread.sock on stop and the heartbeat reports [] again.
DEVIATIONS: dict[str, tuple[bytes, bytes]] = {
    "bitscan-capread.socket": (b"SocketMode=0660\n", b"RemoveOnStop=yes\n"),
}


def apply_deviation(name: str, want: bytes) -> bytes:
    """The spec block with the file's one recorded added line, if it has one."""
    if name not in DEVIATIONS:
        return want
    anchor, added = DEVIATIONS[name]
    lines = want.splitlines(keepends=True)
    if lines.count(anchor) != 1 or added in lines:
        raise SystemExit(
            f"{name}: spec block has not exactly one {anchor!r}, or already has"
            f" {added!r}; review the recorded deviation"
        )
    i = lines.index(anchor) + 1
    print(f"DEVIATION {name}: +{added.rstrip().decode()} after spec line {i}")
    return b"".join([*lines[:i], added, *lines[i:]])


def spec_block(lines: list[bytes], start: int, end: int, lang: bytes = b"ini") -> bytes:
    if lines[start - 1].rstrip(b"\r\n") != b"```" + lang:
        raise SystemExit(f"spec line {start} is not an ```{lang.decode()} fence")
    if lines[end - 1].rstrip(b"\r\n") != b"```":
        raise SystemExit(f"spec line {end} is not a closing fence")
    body = lines[start : end - 1]
    return b"".join(line.rstrip(b"\r\n") + b"\n" for line in body)


def eol_comment_lines(data: bytes) -> list[int]:
    bad = []
    for n, line in enumerate(data.split(b"\n"), 1):
        stripped = line.lstrip()
        if stripped.startswith((b"#", b";")) or not stripped:
            continue
        if b"#" in line:
            bad.append(n)
    return bad


def check_file(
    path: Path, name: str, want: bytes, start: int, end: int, unit: bool
) -> int:
    if not path.is_file():
        print(f"MISSING {name}")
        return 1
    got = path.read_bytes()
    if got != want:
        for i, (a, b) in enumerate(
            zip(got.split(b"\n"), want.split(b"\n"), strict=False), 1
        ):
            if a != b:
                print(f"DIFF {name} line {i}: got {a!r} want {b!r}")
                break
        else:
            print(f"DIFF {name}: length got {len(got)} want {len(want)}")
        return 1
    failures = 0
    if b"\r" in got:
        print(f"CR {name}")
        failures += 1
    if unit:
        bad = eol_comment_lines(got)
        if bad:
            print(f"EOL-COMMENT {name} lines {bad}")
            failures += 1
        if name == "bitscan-capread.service" and b"[Install]" in got:
            print("INSTALL-SECTION bitscan-capread.service")
            failures += 1
    if not failures:
        print(f"IDENTICAL {name} (TS L{start + 1}-L{end - 1}, {len(got)} bytes)")
    return failures


def exact_set(folder: Path, expected: set[str], label: str) -> int:
    present = (
        {p.name for p in folder.iterdir() if p.is_file()} if folder.is_dir() else set()
    )
    extra = present - expected
    if extra:
        print(f"EXTRA files in {label}: {sorted(extra)}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "which", choices=["agent", "manager", "all"], default="all", nargs="?"
    )
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root)
    units: dict[str, tuple[int, int]] = {}
    if args.which in ("agent", "all"):
        units.update(AGENT)
    if args.which in ("manager", "all"):
        units.update(MANAGER)
    policies = DBUS if args.which in ("agent", "all") else {}

    spec_lines = (root / SPEC).read_bytes().splitlines(keepends=True)
    unit_dir = root / "deploy" / "systemd"
    dbus_dir = root / "deploy" / "dbus"
    failures = 0
    for name, (start, end) in units.items():
        want = apply_deviation(name, spec_block(spec_lines, start, end))
        failures += check_file(unit_dir / name, name, want, start, end, unit=True)
    for name, (start, end) in policies.items():
        want = spec_block(spec_lines, start, end, b"xml")
        failures += check_file(dbus_dir / name, name, want, start, end, unit=False)

    if args.which == "all":
        failures += exact_set(unit_dir, set(units), "deploy/systemd")
    if policies:
        failures += exact_set(dbus_dir, set(policies), "deploy/dbus")
    total = len(units) + len(policies)
    print("FAIL" if failures else "OK", f"{total} files checked, {failures} problems")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
