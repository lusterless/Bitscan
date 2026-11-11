"""CHK-R020-044 (Release 0.2.0, PD-51): manager_walk.py takes the release file
names of the manager-install.md §6 block from the --rel wheel's version.

Usage (Linux; the walk imports pty): python3 -I e2e/m6/check_walk_rel_version.py [--runbook FILE]

Expected values come from the runbook as written and from the release file
names release.yml writes (`bitscan_manager-X.Y.Z-py3-none-any.whl`,
`bitscan-manager-X.Y.Z-requirements.txt`), not from the walk:
- the version is read from the one wheel in --rel (0.1.0 and 0.2.0), and a
  --rel with no wheel, two wheels or a non-release name stops the walk;
- on the runbook's §6 block, setting the version to the --rel version changes
  only the version inside the two file names (nightly and compat-a: 0.2.0, no
  change at all; compat-b and the upgrade base: the v0.1.0 files);
- a block that lost the wheel or the requirements file name stops the walk.
Exit 0 when every row passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import manager_walk as mw  # noqa: E402

ROOT = HERE.parent.parent
ROWS: list[tuple[bool, str]] = []


def ok(cond: bool, what: str) -> None:
    ROWS.append((cond, what))
    print(("PASS " if cond else "FAIL ") + what)


def stops(fn, *args) -> str:  # noqa: ANN001
    try:
        fn(*args)
    except mw.Stop as e:
        return str(e)
    return ""


def rel_dir(names: list[str]) -> Path:
    d = Path(tempfile.mkdtemp(prefix="rel020-"))
    for n in names:
        (d / n).write_bytes(b"")
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runbook", type=Path, default=ROOT / "deploy" / "runbooks" / "manager-install.md")
    a = ap.parse_args()

    # rel_version
    for v in ("0.1.0", "0.2.0", "10.20.30"):
        got = mw.rel_version(rel_dir([f"bitscan_manager-{v}-py3-none-any.whl", f"bitscan-manager-{v}-requirements.txt"]))
        ok(got == v, f"rel_version of a --rel with the {v} wheel is {v!r} (got {got!r})")
    for names, what in (([], "no wheel"),
                        (["bitscan_manager-0.1.0-py3-none-any.whl", "bitscan_manager-0.2.0-py3-none-any.whl"], "two wheels"),
                        (["bitscan_manager-0.2.0rc1-py3-none-any.whl"], "a non-release wheel name")):
        msg = stops(mw.rel_version, rel_dir(names))
        ok("exactly one" in msg, f"rel_version stops on {what} (got {msg!r})")

    # the runbook's §6 block, found the way the walk finds it
    md = a.runbook.read_text(encoding="utf-8")
    B, errors, loose, _, _ = mw.resolve(md)
    ok(not errors and not loose and "venv" in B, f"the runbook resolves against the walk's plan (errors {errors}, loose {loose})")
    body = B["venv"]
    want_names = sorted(re.findall(r"bitscan(?:_manager-\S+?\.whl|-manager-\S+?-requirements\.txt)", body))
    ok(len(want_names) == 2, f"the §6 block names two release files: {want_names}")
    tree_ver = re.search(r"bitscan_manager-(\d+\.\d+\.\d+)-py3-none-any\.whl", body)
    tv = tree_ver.group(1) if tree_ver else ""

    same, written = mw.rel_files(body, tv)
    ok(same == body, f"version {tv} (the runbook's own, nightly and compat-a): the block is unchanged")
    ok(sorted(written) == want_names, f"the names reported as written are the runbook's: {written}")

    old, _ = mw.rel_files(body, "0.1.0")
    ok("-r bitscan-manager-0.1.0-requirements.txt" in old and "./bitscan_manager-0.1.0-py3-none-any.whl" in old,
       "version 0.1.0 (compat-b, upgrade base): the block installs bitscan-manager-0.1.0-requirements.txt and ./bitscan_manager-0.1.0-py3-none-any.whl")
    ok(tv == "0.1.0" or tv not in old, f"no {tv} left in the 0.1.0 block")
    ok(old.replace("0.1.0", tv) == body if tv else False, "the 0.1.0 block differs from the runbook's only in the version of the two names")
    ok(len(old.splitlines()) == len(body.splitlines()), "same number of lines")

    for drop, what in ((r"\./bitscan_manager-\S+?\.whl", "the wheel"), (r"bitscan-manager-\S+?-requirements\.txt", "the requirements file")):
        msg = stops(mw.rel_files, re.sub(drop, "x", body), "0.1.0")
        ok("want one requirements file and one wheel" in msg, f"a block without {what} name stops the walk (got {msg!r})")
    msg = stops(mw.rel_files, body + "\n# bitscan_manager-0.3.0-py3-none-any.whl\n", "0.1.0")
    ok("want one requirements file and one wheel" in msg, f"a block naming a second wheel stops the walk (got {msg!r})")

    bad = [w for c, w in ROWS if not c]
    print(f"{len(ROWS) - len(bad)}/{len(ROWS)} passed, {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
