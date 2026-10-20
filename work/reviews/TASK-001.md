# TASK-001 REVIEW: manager project config and hashed lock files

Reviewer: reviewer. Date: 2026-10-20. REQ-001 to REQ-005. Spec: TS §2.1 L102-104, TS §8.1 L1258 (hashed Python dependencies), TS §8.2 L1263-1264, TS §4.1, §4.5; security invariants "Data handling". Inputs: `work/plans/TASK-001.md`, `work/reports/TASK-001-impl.md` (incl. revision 1), `work/reports/TASK-001-test.md`, `tests/m0/report.md` CHK-M0-001 to -013, `work/decisions.md` 2026-10-20 (lock command hardening; `--exclude-newer` follow-up).

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268): manager project config is not importer, auth, agent or runner code.

## What was checked

- **Fresh-venv installs:** both done in a temp directory with `python -I -m venv` and its bundled pip, on Windows 11 with CPython 3.12.
  - `pip install --require-hashes -r manager/requirements.txt` exits 0 and installs 16 packages.
  - `fastapi`, `pydantic` (2.14.1), `apscheduler`, `defusedxml` and `re2` import, and `re2` is linear-time on `(a+)+$`.
  - The runtime venv has no `pytest`, `ruff`, `mypy`, `testcontainers` or `hatchling`.
  - The dev lock also installs with exit 0.
- **Planted lock changes (temp copies of the runtime lock):**

  | Plant | Exit | pip message |
  | --- | --- | --- |
  | altered digest of the installed `annotated-doc` wheel | 1 | "DO NOT MATCH THE HASHES" |
  | altered digest of its sdist | 0 | none (expected: with `--only-binary :all:` the sdist is never used) |
  | all hashes of one package removed | 1 | "Hashes are required" |
  | the transitive `idna` entry removed | 1 | "must have their versions pinned" |
  | unpinned `six` appended | 1 | "must have their versions pinned" |
  | `fastapi` version changed, old hashes kept | 1 | hash mismatch |
  | `--only-binary :all:` line removed, wheel hash altered | 0 | pip falls back to the sdist |

  The last row is the hole the 2026-10-20 decision closes. The option line is load-bearing, and `tests/test_lock_files.py:118` requires it.
- **Linux wheels, checked by pip itself (independent of the impl's uv proxy):** `pip download --require-hashes --only-binary :all: --python-version 3.12 --abi cp312` of the runtime lock, for the manylinux x86_64 and aarch64 tags, exits 0 with 16 files each. `google-re2` 1.1.20251105 has wheels `manylinux_2_27_x86_64` and `manylinux_2_26_aarch64`, and these hash-verify. glibc 2.27 or newer covers Ubuntu 22.04 and 24.04 and Debian 12.
- **Dependency content:**
  - The runtime lock is the TS §2.1 stack plus transitive dependencies only. Every runtime pin appears in the dev lock at the same version.
  - Licenses, from installed metadata, are MIT, BSD-3-Clause, PSF and Apache-2.0.
  - There are no `--index-url`, `--find-links`, VCS, URL or `-e` lines.
  - There is no OIDC, JWT, signing or identity-provider library (REQ-001 (3)).
  - Dev-only: `pywin32`, `colorama` and `tzdata` are marker-limited to win32. `docker`, `requests` and `python-dotenv` come in through `testcontainers`.
- **Python 3.12 only:** `requires-python = ">=3.12,<3.13"`, locks use `--python-version 3.12`, ruff targets `py312`, mypy targets `3.12`.
- **Banned-api and SQL rules are real:** probed from stdin as `manager/bitscan_manager/services/p.py`.
  - TID251 fires on all of these: `import re`, `from re import compile`, `import re as r`, `xml.etree.ElementTree`, `from xml.etree import ElementTree`, `xml.etree.cElementTree`, `from xml.dom import minidom`, `xml.dom.pulldom`, `from xml.sax import make_parser`, `xml.parsers.expat` and `from lxml import etree`. Bandit S314, S317 and S318 also fire on several.
  - `defusedxml.ElementTree` and `re2` are allowed.
  - S608 fires on SQL built with f-strings, `.format`, `%` and `+`, including a query held in a variable, lowercase `update`, `INSERT`, and `sql.SQL(f"...")`.
  - A parameterised `execute("... %s", (x,))` passes.
  - The `re` ban also applies in `manager/tests/`.
- **Gates on the tree:** `ruff check manager` and `ruff format --check manager` exit 0, and `mypy --strict --config-file manager/pyproject.toml manager` reports "no issues found in 6 source files".
- **Scope:** exactly the 3 listed files. `pyproject.toml` is 70 lines, and the locks are generated.

## Findings

1. **nit. The lock header does not record `--exclude-newer`.**
   - Where: `manager/requirements.txt:2` and `manager/requirements-dev.txt:2`.
   - Rule: `work/decisions.md` 2026-10-20 (CHK-M0-012).
   - Evidence: a regeneration picks up newer releases.
   - Fix: `main` has already asked impl-manager to add `--exclude-newer <timestamp>` to the header command. This approval covers that header-only change, as long as no pin or hash changes. If any pin or hash changes, it needs a new review.
2. **nit. Two XML parsers in the standard library are not banned.**
   - Where: `manager/pyproject.toml:46-52`.
   - Rule: security invariant "Parse XML only with `defusedxml`".
   - Evidence: `xmlrpc.client.loads(...)` and `plistlib.loads(...)` pass lint; both parse XML with expat.
   - Fix: add `"xmlrpc"` and `"plistlib"` to `banned-api`. The manager needs neither.
   - Dynamic imports (`importlib.import_module("xml.etree…")`, `__import__("re")`) and the third-party `regex` module (not a dependency) are left to review.
3. **nit (info). `opentelemetry-api` 1.45.1 is in the runtime lock.**
   - It is a hard dependency of fastapi 0.148.0: an unconditional `Requires-Dist`, Apache-2.0, which itself depends only on `typing-extensions`.
   - It is API-only. No SDK or exporter is in either lock, so it sends nothing. Adding an OpenTelemetry SDK or exporter later would be an egress decision for the lead.
4. **nit (for TASK-009).** CI must install both locks exactly as committed. It must never filter out the `--only-binary :all:` line (see the last plant row above). It should install the project with `pip install --no-deps --no-build-isolation -e manager` from the dev venv (plan step 3).
