"""Static checks of .github/workflows/release.yml (REQ-141 (1), (3); TP-M6-06 CHK-M6-111; G49).

Usage:
  python3 -I deploy/tests/check_release_workflow.py [--file release.yml]
      run every static check; exit 1 on any failure.
  python3 -I deploy/tests/check_release_workflow.py --file F --extract JOB STEP-NAME
      print that step's `run:` script (to run it locally, CHK-M6-112..117).

Checks (each prints PASS/FAIL with the reason):
- every `uses:` is pinned by a 40-hex commit and names its version in a comment;
- the top-level permissions are exactly `contents: read`;
- only the `publish` job has any permission beyond read, and it has exactly
  `contents: write`; no job sets `permissions: write-all` or an id-token;
- `publish` runs only on a tag push and needs `versions` and `sums`;
  `gh release create` is called once, with `--draft`;
- no `${{` expression inside any `run:` script (values reach scripts via env);
- every job has `timeout-minutes`; every checkout has persist-credentials false;
- triggers are only a `v*` tag push and workflow_dispatch (no pull_request);
- the `sums` job's expected file list is the plan TASK-135 §3 list (with the
  two TASK-136 manager SBOMs);
- `GH_TOKEN`/`github.token` appears only in `publish`;
- the `versions` step refuses a pre-release (`~`), and compares tag, pyproject
  and changelog (the functional checks run the extracted script).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
EXPECT_SUMS = sorted([
    "$base.deb", "$base.bitscan-agent.cdx.json", "$base.bitscan-runner.cdx.json", "$base.bitscan-capread.cdx.json",
    "bitscan_manager-${VERSION}-py3-none-any.whl", "bitscan-manager-${VERSION}-requirements.txt",
    "bitscan-manager-${VERSION}.python.cdx.json", "bitscan-manager-${VERSION}.web.cdx.json",
    "bitscan-manager.service", "bitscan-manager-migrate.service", "bitscan-manager-maintain.service", "bitscan-manager-maintain.timer",
])

results: list[tuple[bool, str, str]] = []


def check(ok: bool, what: str, why: str = "") -> None:
    results.append((ok, what, why))


def load(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    # PyYAML (YAML 1.1) reads the key `on` as True
    if True in doc and "on" not in doc:
        doc["on"] = doc.pop(True)
    return doc, text


def steps(job: dict) -> list[dict]:
    return job.get("steps") or []


def main() -> int:  # noqa: PLR0912, PLR0915
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=".github/workflows/release.yml")
    ap.add_argument("--extract", nargs=2, metavar=("JOB", "STEP"))
    a = ap.parse_args()
    doc, text = load(Path(a.file))
    jobs: dict[str, dict] = doc.get("jobs") or {}

    if a.extract:
        job, name = a.extract
        for s in steps(jobs[job]):
            if s.get("name") == name:
                sys.stdout.write(s["run"])
                return 0
        print(f"no step {name!r} in job {job!r}", file=sys.stderr)
        return 2

    # pins, read from the raw lines so the version comment is seen too
    uses = [(n, line.strip()) for n, line in enumerate(text.split("\n"), 1) if re.match(r"\s*(-\s+)?uses:", line)]
    bad = []
    for n, line in uses:
        m = re.match(r"(?:-\s+)?uses:\s*(\S+)\s*(#\s*v\d[\w.]*)?\s*$", line)
        if not m or not PIN.match(m.group(1)) or not m.group(2):
            bad.append(f"L{n}: {line}")
    check(bool(uses) and not bad, f"every uses: pinned by a 40-hex commit with a version comment ({len(uses)} uses)", "; ".join(bad))

    top = doc.get("permissions")
    check(top == {"contents": "read"}, "top-level permissions are exactly contents: read", repr(top))

    writers = {}
    for name, job in jobs.items():
        perms = job.get("permissions")
        if perms is None:
            continue
        if not isinstance(perms, dict) or any(v not in ("read", "none") for v in perms.values()):
            writers[name] = perms
    check(writers == {"publish": {"contents": "write"}}, "only publish can write, and only contents", repr(writers))

    pub = jobs.get("publish") or {}
    cond = str(pub.get("if", ""))
    check("github.event_name == 'push'" in cond and "startsWith(github.ref, 'refs/tags/v')" in cond and "||" not in cond,
          "publish runs only on a tag push", cond)
    check(sorted(pub.get("needs") or []) == ["sums", "versions"], "publish needs versions and sums", repr(pub.get("needs")))
    gh = [s.get("run", "") for j in jobs.values() for s in steps(j) if "gh release" in s.get("run", "")]
    creates = [r for r in gh if re.search(r"gh release create\b", r)]
    check(len(creates) == 1 and re.search(r"gh release create\b[^\n]*--draft", creates[0]) is not None
          and not re.search(r"gh release (edit|upload|delete)", "\n".join(gh)),
          "one gh release create, with --draft; no edit/upload/delete", "; ".join(creates))

    inline = [f"{jn}/{s.get('name', '?')}" for jn, j in jobs.items() for s in steps(j) if "${{" in str(s.get("run", ""))]
    check(not inline, "no ${{ }} inside any run: script", ", ".join(inline))

    no_to = [jn for jn, j in jobs.items() if "timeout-minutes" not in j]
    check(not no_to, "every job has timeout-minutes", ", ".join(no_to))
    co = [(jn, s) for jn, j in jobs.items() for s in steps(j) if str(s.get("uses", "")).startswith("actions/checkout@")]
    co_bad = [jn for jn, s in co if (s.get("with") or {}).get("persist-credentials") is not False]
    check(bool(co) and not co_bad, f"every checkout has persist-credentials: false ({len(co)} checkouts)", ", ".join(co_bad))

    on = doc.get("on") or {}
    check(set(on) == {"push", "workflow_dispatch"} and on["push"] == {"tags": ["v*"]}, "triggers: v* tag push and workflow_dispatch only", repr(on))

    tok = [jn for jn, j in jobs.items() if "github.token" in yaml.safe_dump(j) or "GITHUB_TOKEN" in yaml.safe_dump(j) or "secrets." in yaml.safe_dump(j)]
    check(tok == ["publish"], "the GitHub token is used only in publish (no other secret)", repr(tok))

    sums = next((s["run"] for s in steps(jobs.get("sums") or {}) if s.get("name") == "Write and check SHA256SUMS"), "")
    m = re.search(r'expect="\$\(printf .%s\\n. (.*?)\| sort\)"', sums, re.S)
    listed = sorted(re.findall(r'"([^"]+)"|(\S+)', m.group(1).replace("\\\n", " ")) if m else [])
    names = sorted(x or y for x, y in listed)
    check(names == EXPECT_SUMS, "sums expect list = plan TASK-135 §3 (+ the two manager SBOMs)", repr(names))
    check("sha256sum -c SHA256SUMS" in sums and "uniq -d" in sums, "sums checks listed-vs-present, duplicates and sha256sum -c", "")
    pubrun = next((s["run"] for s in steps(pub) if "gh release create" in s.get("run", "")), "")
    check(pubrun.index("sha256sum -c SHA256SUMS") < pubrun.index("gh release create") if "sha256sum -c SHA256SUMS" in pubrun else False,
          "publish re-checks SHA256SUMS before the upload", "")

    ver = next((s["run"] for s in steps(jobs.get("versions") or {}) if s.get("id") == "check"), "")
    check(all(k in ver for k in ('*"~"*', "manager/pyproject.toml", "dpkg-parsechangelog", "^v[0-9]+\\.[0-9]+\\.[0-9]+$")),
          "versions step compares tag, pyproject and changelog and refuses ~", "")
    needs_versions = [jn for jn, j in jobs.items() if jn != "versions" and "versions" not in (j.get("needs") if isinstance(j.get("needs"), list) else [j.get("needs")])]
    check(not needs_versions, "every job after versions needs versions (nothing builds before the check)", ", ".join(needs_versions))

    # every pip call builds or installs only hashed requirements or a local path, never a bare name
    pip_bad = []
    for jn, j in jobs.items():
        for s in steps(j):
            for line in str(s.get("run", "")).replace("\\\n", " ").split("\n"):
                m = re.search(r"-m pip (install|wheel|download)\b(.*)", line)
                if not m:
                    continue
                verb, rest = m.group(1), m.group(2)
                args = [a for a in re.findall(r'"[^"]*"|\S+', rest)]
                opts_with_value = {"-w", "--wheel-dir", "-r", "--requirement", "-c", "--constraint", "-d", "--dest"}
                targets, skip = [], False
                for a in args:
                    if skip:
                        skip = False
                        continue
                    if a in opts_with_value:
                        skip = True
                        continue
                    if not a.startswith("-"):
                        targets.append(a)
                hashed = "--require-hashes" in rest and ("-r" in args or "--requirement" in args)
                for t in targets:
                    if not re.match(r'^("?\$|\./|/|"\./|"/)', t):
                        pip_bad.append(f"{jn}: pip {verb} target {t!r} is not a path (pip resolves a bare name on PyPI)")
                if verb == "wheel" and "--no-index" not in rest:
                    pip_bad.append(f"{jn}: pip wheel without --no-index")
                if verb == "install" and not hashed and "--no-index" not in rest:
                    pip_bad.append(f"{jn}: pip install neither --require-hashes -r nor --no-index: {line.strip()}")
    check(not pip_bad, "every pip call is hashed (-r with --require-hashes) or a local path with --no-index", "; ".join(pip_bad))

    fails = 0
    for ok, what, why in results:
        print(("PASS " if ok else "FAIL ") + what + (f" :: {why}" if why and not ok else ""))
        fails += not ok
    print(f"check_release_workflow: {len(results) - fails}/{len(results)} passed, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
