# TASK-023 REVIEW: runtime dependencies for M2 (PD-19)

Reviewer: reviewer. Date: 2026-10-21. REQ-034. Spec: TS §8.2 (`pip --require-hashes`), TS §8.1 (hashed dependencies); PD-19; decisions 2026-10-20 (the final lock command and the FastAPI telemetry row). Inputs: `work/reports/TASK-023-impl.md`; `work/reports/TASK-023-test.md` (PASS, CHK-M2-001 to -007 in `tests/m2/report.md`; 9 of 9 planted lock lines red).

Files reviewed: `manager/pyproject.toml`, `manager/requirements.txt`, `manager/requirements-dev.txt`. The tester's change to `manager/tests/test_lock_files.py` was read too.

Verdict: APPROVED

TASK-023 is not on the TS §8.2 two-approval list, so one approval is enough.

## What was checked

- **PD-19 set.** Five runtime additions: `uvicorn>=0.30` (no `standard` extra), `argon2-cffi>=23.1`, `httpx>=0.27`, `psycopg-pool>=3.2`, `prometheus-client>=0.20`. `httpx` moved from `dev` to runtime, as the vault client and the HTTPS sink need. There is no `hvac` or `pyotp`.
- **Locks.** The runtime lock adds only those packages and their transitive dependencies (`click`, `h11`, `argon2-cffi-bindings`, `cffi`, `pycparser`, `httpcore`, `certifi`). No existing pin or hash changed. Neither lock holds `uvloop`, `httptools`, `websockets`, `watchfiles`, `python-dotenv`, an OpenTelemetry SDK, exporter or instrumentation, or an OIDC library. `opentelemetry-api` was already there (via FastAPI). The runtime lock holds no test or lint tool.
- **Reproducible (REQ-034 (4)).** I ran both header commands into a temp folder myself. The bodies are byte-identical to the committed locks; only the `-o` path in header line 2 differs, as expected. The cutoff did not move.
- **Gates (my run, Windows).** ruff check and format are clean; `mypy --strict` is clean on 53 files; `pytest tests/test_lock_files.py` passes. The full suite has 484 passed and 181 skipped (pg). At the time, G5 was red at 36 %, only because TASK-033's `disk_queue.py` had no tests yet; it is green again with TASK-033's tests (97.63 %). TASK-023 adds no code under `services/`.
- **Tests.** The new lock tests check that each M2 package is pinned once, that the runtime and dev `httpx` versions match, that no uvicorn extras, `hvac` or `pyotp` are present, and that no OTel SDK, exporter, instrumentation or distro package is present. Each assertion would fail on its planted counterpart.
- **Scope.** 3 files, about 15 hand-written lines. The lock bodies are generated.

## Findings

None that block approval.

1. **note, no change.** `click` (via uvicorn) is a new runtime dependency. It is needed only by uvicorn's own CLI; `serve` (TASK-045) should start uvicorn programmatically, so `click` is never on a request path.
