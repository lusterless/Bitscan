"""Scripted debconf frontend for testing deploy/debian/config (M4 TP-M4-11, REQ-107).

Usage: python3 debconf_protocol.py CONFIG_SCRIPT ARG... --answers JSON

Runs CONFIG_SCRIPT under the debconf confmodule protocol (DEBIAN_HAS_FRONTEND
set, commands read from the script's fd 3 = our stdout pipe, replies written
to its stdin), answering from the JSON object
  {"values": {question: value}, "seen": {question: true|false}}
and prints one JSON document: {"rc": exit code, "log": [command, ...]}.
INPUT on a seen question answers 30 (skipped), as debconf does; every other
command answers 0. The protocol commands are what config asks for, so a test
can assert which questions are shown and that config never SETs a value.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def main() -> int:
    argv = sys.argv[1:]
    if "--answers" not in argv:
        print(
            "usage: debconf_protocol.py SCRIPT ARG... --answers JSON", file=sys.stderr
        )
        return 2
    i = argv.index("--answers")
    answers = json.loads(argv[i + 1])
    cmd = argv[:i]
    values: dict[str, str] = dict(answers.get("values", {}))
    seen: dict[str, bool] = dict(answers.get("seen", {}))
    env = dict(os.environ)
    env["DEBIAN_HAS_FRONTEND"] = "1"
    env.pop("DEBCONF_REDIR", None)
    proc = subprocess.Popen(
        ["sh", *cmd],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None
    log: list[str] = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        log.append(line)
        words = line.split(" ")
        verb = words[0].upper()
        reply = "0"
        if verb == "STOP":
            break
        if verb == "GET" and len(words) >= 2:
            reply = "0 " + values.get(words[1], "")
        elif verb == "FGET" and len(words) >= 3:
            reply = "0 " + ("true" if seen.get(words[1], False) else "false")
        elif verb == "FSET" and len(words) >= 4 and words[2] == "seen":
            seen[words[1]] = words[3] == "true"
            reply = "0 " + words[3]
        elif verb == "INPUT" and len(words) >= 3:
            reply = (
                "30 question skipped"
                if seen.get(words[2], False)
                else "0 question will be asked"
            )
        elif verb == "SET" and len(words) >= 2:
            values[words[1]] = " ".join(words[2:])
            reply = "0 value set"
        elif verb == "GO":
            reply = "0 ok"
        try:
            proc.stdin.write(reply + "\n")
            proc.stdin.flush()
        except BrokenPipeError:
            break
    try:
        proc.stdin.close()
    except BrokenPipeError:
        pass
    stderr = proc.stderr.read() if proc.stderr else ""
    rc = proc.wait(timeout=30)
    print(json.dumps({"rc": rc, "log": log, "stderr": stderr}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
