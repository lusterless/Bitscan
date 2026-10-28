"""REQ-148 (7) journal canary for one VM (CHK-M6-286). Runs on the VM as root: `sudo python3 -I tokscan_vm.py ...`.

Reads the whole journal (`journalctl -o json`, every boot, every field of every entry, so a token in
_CMDLINE or any other field is found too, not only in MESSAGE) and counts:
  - token-shaped strings `bs[uaek]_` + at least 20 base64url characters (TS §6.2 token format);
  - the exact value of every file given with --exact (for example the agent's own bsa_ token), read
    here from the file, so the value is never on a command line;
  - the value of every file given with --control (a fake token-shaped line the harness logged with
    `logger -f`), which must be found: a scan that sees nothing can't pass.

Prints one JSON line per match (time, field, _COMM, SYSLOG_IDENTIFIER, _SYSTEMD_UNIT, prefix, length,
a masked context) and a last summary line. Never prints a token value: every match is masked to its
4-character prefix and its length.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

PAT = re.compile(r"bs[uaek]_[A-Za-z0-9_-]{20,}")
AGENT_UNITS = ("bitscan-agent.service", "bitscan-runner.service", "bitscan-capread.service")


def masked(text: str) -> str:
    return PAT.sub(lambda m: m.group(0)[:4] + f"<masked len={len(m.group(0))}>", text)


def values(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def field_text(v: object) -> str | None:
    if isinstance(v, str):
        return v
    if isinstance(v, list) and all(isinstance(x, int) for x in v):  # binary field: a byte array
        return bytes(v).decode("utf-8", "replace")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exact", action="append", default=[], help="file whose value(s) must appear nowhere")
    ap.add_argument("--control", action="append", default=[], help="file whose value must be found (control)")
    a = ap.parse_args()
    # globs are expanded here, as root (the ssh user can't list /root)
    exact = [v for g in a.exact for p in sorted(glob.glob(g)) for v in values(p)]
    control = {v: 0 for g in a.control for p in sorted(glob.glob(g)) for v in values(p)}
    p = subprocess.run(["journalctl", "--no-pager", "-o", "json"], stdout=subprocess.PIPE, text=True, errors="replace", check=False)
    entries = shape = shape_agent = exact_hits = 0
    for line in p.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        entries += 1
        unit = e.get("_SYSTEMD_UNIT")
        for k, v in e.items():
            t = field_text(v)
            if t is None:
                continue
            for c in control:
                if c in t:
                    control[c] += 1
            hits = [m.group(0) for m in PAT.finditer(t) if m.group(0) not in control]
            ex = [x for x in exact if x in t]
            exact_hits += len(ex)
            for tok in hits:
                shape += 1
                if unit in AGENT_UNITS or e.get("SYSLOG_IDENTIFIER") == "bitscan-agent":
                    shape_agent += 1
                ts = datetime.fromtimestamp(int(e.get("__REALTIME_TIMESTAMP", "0")) / 1e6, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                msg = field_text(e.get("MESSAGE")) or ""
                print(json.dumps({"time": ts, "field": k, "_COMM": e.get("_COMM"), "SYSLOG_IDENTIFIER": e.get("SYSLOG_IDENTIFIER"),
                                  "_SYSTEMD_UNIT": unit, "prefix": tok[:4], "length": len(tok), "message": masked(msg)[:300]}))
            if ex and not hits:
                print(json.dumps({"field": k, "_COMM": e.get("_COMM"), "_SYSTEMD_UNIT": unit, "exact_value_hit": len(ex)}))
    print(json.dumps({"entries": entries, "journalctl_rc": p.returncode, "token_shaped": shape, "token_shaped_agent_units": shape_agent,
                      "exact_values": len(exact), "exact_hits": exact_hits, "controls": len(control),
                      "controls_found": sum(1 for n in control.values() if n > 0)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
