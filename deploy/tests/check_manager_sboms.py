"""Independent check of the two manager SBOMs of a release folder (TP-M6-06 CHK-M6-116, REQ-141 (4)).

Usage: python3 -I deploy/tests/check_manager_sboms.py RELEASE_DIR VERSION TREE

- Python SBOM: CycloneDX 1.5, metadata.component bitscan-manager VERSION; one
  `library` component per requirement of bitscan-manager-VERSION-requirements.txt
  (parsed here with its own reader: `name==version` heads with their
  `--hash=sha256:` continuation lines), each with that version, a
  pkg:pypi purl and exactly the lock's SHA-256 set; nothing extra.
- Web SBOM: CycloneDX; every runtime package of web/package.json `dependencies`
  and their transitive runtime dependencies from web/package-lock.json (not dev)
  is a component with scope `required` and the lock's version; at least the six
  REQ-141 (4) names (react, react-dom, scheduler, openapi-fetch,
  openapi-typescript-helpers, qrcode-generator).
- Both files are listed in SHA256SUMS with their correct hash.
Exit 1 on any finding (each printed).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


def lock_entries(text: str) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    cur = None
    for line in text.splitlines():
        head = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)(?:\s*;.*?)?\s*\\?$", line)
        if head:
            cur = (head.group(1), head.group(2))
            out[cur] = set()
        for h in re.findall(r"--hash=sha256:([0-9a-f]{64})", line):
            assert cur is not None
            out[cur].add(h)
    return out


def runtime_closure(lock: dict, pkg: dict) -> dict[str, str]:
    pk = lock["packages"]
    want: dict[str, str] = {}
    todo = list(pkg.get("dependencies", {}))
    while todo:
        name = todo.pop()
        if name in want:
            continue
        node = pk.get(f"node_modules/{name}")
        if node is None:
            continue
        want[name] = node["version"]
        todo += list(node.get("dependencies", {})) + list(node.get("peerDependencies", {}))
    return want


def main() -> int:
    rel, version, tree = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    bad: list[str] = []
    lock_text = (rel / f"bitscan-manager-{version}-requirements.txt").read_text()
    want = lock_entries(lock_text)
    py = json.loads((rel / f"bitscan-manager-{version}.python.cdx.json").read_text())
    if py.get("bomFormat") != "CycloneDX" or py.get("specVersion") != "1.5":
        bad.append(f"python sbom format {py.get('bomFormat')} {py.get('specVersion')}")
    mc = py.get("metadata", {}).get("component", {})
    if (mc.get("name"), mc.get("version")) != ("bitscan-manager", version):
        bad.append(f"python sbom metadata.component {mc.get('name')} {mc.get('version')}")
    have = {}
    for c in py.get("components", []):
        key = (c.get("name"), c.get("version"))
        have[key] = {h["content"] for h in c.get("hashes", []) if h.get("alg") == "SHA-256"}
        norm = re.sub(r"[-_.]+", "-", str(c.get("name"))).lower()
        if c.get("type") != "library" or c.get("purl") != f"pkg:pypi/{norm}@{c.get('version')}":
            bad.append(f"python component {key}: type {c.get('type')} purl {c.get('purl')}")
    for key, hashes in want.items():
        if key not in have:
            bad.append(f"python sbom lacks {key[0]}=={key[1]}")
        elif have[key] != hashes:
            bad.append(f"python sbom hashes for {key[0]}=={key[1]}: {len(have[key])} vs lock {len(hashes)}")
    for key in set(have) - set(want):
        bad.append(f"python sbom has extra {key}")
    web = json.loads((rel / f"bitscan-manager-{version}.web.cdx.json").read_text())
    comps: dict[str, tuple[str, str]] = {}

    def walk(cs: list) -> None:
        for c in cs or []:
            name = f"{c['group']}/{c['name']}" if c.get("group") else c.get("name")
            comps[name] = (c.get("version"), c.get("scope", "required"))
            walk(c.get("components"))

    walk(web.get("components"))
    lock = json.loads((tree / "web/package-lock.json").read_text())
    pkg = json.loads((tree / "web/package.json").read_text())
    runtime = runtime_closure(lock, pkg)
    for name in ("react", "react-dom", "scheduler", "openapi-fetch", "openapi-typescript-helpers", "qrcode-generator"):
        if name not in runtime:
            bad.append(f"expected runtime package {name} not in the lock's runtime closure")
    for name, ver in sorted(runtime.items()):
        if comps.get(name) != (ver, "required"):
            bad.append(f"web sbom: {name}@{ver} is {comps.get(name)}")
    required = sorted(n for n, (_, s) in comps.items() if s == "required")
    sums = dict(reversed(line.split("  ", 1)) for line in (rel / "SHA256SUMS").read_text().splitlines())
    for f in (f"bitscan-manager-{version}.python.cdx.json", f"bitscan-manager-{version}.web.cdx.json"):
        if sums.get(f) != hashlib.sha256((rel / f).read_bytes()).hexdigest():
            bad.append(f"{f} not in SHA256SUMS with its hash")
    for b in bad:
        print(b)
    print(f"python: {len(want)} lock entries, {sum(len(v) for v in want.values())} hashes, {len(have)} components; "
          f"web: runtime closure {sorted(runtime.items())}; required components {required}")
    print("FAIL" if bad else "OK", f"{len(bad)} findings")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
