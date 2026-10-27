"""Runbook and README text checks (REQ-138 (5)-(6), REQ-139 (4), REQ-145 (3); CHK-M6-041, -086, -153).

Usage: python -I deploy/tests/check_runbook_text.py FILE.md [FILE.md ...]

For every file:
- no secret on a command line: inside ```sh blocks no PGPASSWORD, no
  --password / -W with a value, no password= / token= / secret= assignment,
  no `echo`/`printf` piped or redirected into a file under /etc/bitscan/secrets,
  no `export` of a BITSCAN_ variable, no DSN given as a psql/pg_* argument
  with a password in it;
- no real-looking token anywhere (bsu_/bsk_/bsa_/bse_ followed by 20+ token
  characters) and no PEM private key;
- no process note: no TASK-/REQ-/CHK-/TP-M ids, no `#nn` question numbers, no
  "decisions 20..", "open question", "tester", "impl-", "reviewer", "PD-nn";
- every ```sh block parses with `bash -n` (blocks nested in lists dedented).
Exit 0 when clean; every finding is printed as FILE:LINE: reason.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

SH_BAD = [
    (re.compile(r"PGPASSWORD"), "PGPASSWORD on a command line"),
    (re.compile(r"--password(?:=|\s+\S)"), "--password with a value"),
    (re.compile(r"(?i)\b(?:password|passwd|token|secret)=(?!<)[^\s'\"]+"), "a secret assignment on a command line"),
    (re.compile(r"(?:echo|printf)\b[^|>]*(?:\||>)[^\n]*(?:/etc/bitscan/secrets|\.dsn|vault\.token|tls\.key)"), "a secret echoed into a file"),
    (re.compile(r"\bexport\s+BITSCAN_"), "a BITSCAN_ variable exported into the shell"),
    (re.compile(r"(?:psql|pg_dump|pg_restore|createdb|pg_basebackup)\b[^\n]*password\s*="), "a DSN with a password given as an argument"),
]
ANY_BAD = [
    (re.compile(r"\bbs[uaek]_[A-Za-z0-9_-]{20,}"), "a token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\b(?:TASK|REQ|CHK)-\d"), "a task, requirement or check id"),
    (re.compile(r"\bTP-M\d"), "a test-plan id"),
    (re.compile(r"(?<![\w&/])#\d{1,3}\b"), "a question number"),
    (re.compile(r"\bPD-\d"), "a planner decision id"),
    (re.compile(r"(?i)\bdecisions 20\d\d|\bopen question|\btester\b|\bimpl-[a-z]|\breviewer\b"), "a process note"),
]


def sh_blocks(lines: list[str]) -> list[tuple[int, list[str]]]:
    out: list[tuple[int, list[str]]] = []
    cur: list[str] | None = None
    start = 0
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if cur is None and s in ("```sh", "```bash"):
            cur, start = [], n
        elif cur is not None and s == "```":
            out.append((start, cur))
            cur = None
        elif cur is not None:
            cur.append(line)
    return out


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    found: list[str] = []
    for n, line in enumerate(lines, 1):
        for rx, why in ANY_BAD:
            if rx.search(line):
                found.append(f"{path}:{n}: {why}: {line.strip()[:100]}")
    for start, body in sh_blocks(lines):
        for i, line in enumerate(body, start + 1):
            for rx, why in SH_BAD:
                if rx.search(line):
                    found.append(f"{path}:{i}: {why}: {line.strip()[:100]}")
        # <placeholder> words are documentation, not redirections
        script = re.sub(r"<[a-z][a-z0-9 _.-]*>", "PLACEHOLDER", textwrap.dedent("\n".join(body)) + "\n")
        p = subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True)
        if p.returncode != 0:
            found.append(f"{path}:{start}: sh block does not parse: {p.stderr.strip()[:200]}")
    return found


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        print("usage: check_runbook_text.py FILE.md [...]")
        return 2
    total_blocks = 0
    findings: list[str] = []
    for f in files:
        total_blocks += len(sh_blocks(f.read_text(encoding="utf-8").split("\n")))
        findings += check(f)
    for line in findings:
        print(line)
    print("FAIL" if findings else "OK", f"{len(files)} files, {total_blocks} sh blocks, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
