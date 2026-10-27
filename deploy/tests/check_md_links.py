"""Relative links and anchors in Markdown files resolve (TP-M6-09 CHK-M6-150, REQ-145 (1)).

Usage: python3 -I deploy/tests/check_md_links.py FILE.md [...]
Checks every [text](target) that is not http(s)/mailto: the file exists
(relative to the Markdown file), and a #anchor matches a heading slug of the
target (GitHub style: lower case, punctuation removed, spaces to hyphens).
Also checks every "<runbook>.md section N" / "section N" citation next to a
runbook link against that runbook's "## N." headings. Exit 1 on a finding,
on a missing file, or when 0 links were checked in total; exit 2 with no file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def slugs(md: Path) -> set[str]:
    out = set()
    for line in md.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            s = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
            out.add(s)
    return out


def sections(md: Path) -> set[str]:
    return set(re.findall(r"^## (\d+)\.", md.read_text(encoding="utf-8"), re.MULTILINE))


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        # No file list (or a glob that came out empty) would check nothing and pass.
        print("usage: check_md_links.py FILE.md [...]")
        return 2
    bad, n = [], 0
    for f in files:
        if not f.is_file():
            bad.append(f"{f}: not a file")
            continue
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\[([^\]]*)\]\(([^)\s]+)\)", text):
            target = m.group(2)
            if re.match(r"^(https?:|mailto:)", target):
                continue
            n += 1
            path, _, anchor = target.partition("#")
            dest = (f.parent / path) if path else f
            if not dest.exists():
                bad.append(f"{f}: link {target}: {dest} missing")
                continue
            if anchor and dest.suffix == ".md" and anchor not in slugs(dest):
                bad.append(f"{f}: link {target}: no heading for #{anchor}")
            after = text[m.end() : m.end() + 40]
            sm = re.match(r"\)?\s*section (\d+)", after)
            if sm and dest.suffix == ".md" and sm.group(1) not in sections(dest):
                bad.append(f"{f}: {target} section {sm.group(1)}: no '## {sm.group(1)}.' heading")
    if n == 0 and not bad:
        bad.append(f"0 relative links in {len(files)} files: nothing was checked")
    for b in bad:
        print(b)
    print("FAIL" if bad else "OK", f"{n} relative links checked, {len(bad)} findings")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
