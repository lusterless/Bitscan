# TASK-001 TEST report: manager project config and hashed lock files

Tester: tester. REQ-001 to REQ-005. Date 2026-10-20. Impl report: `work/reports/TASK-001-impl.md` (including revision 1). CPython 3.12.10, pip 25.0.1 (bundled), uv 0.13.1.

## Verdict: PASS

The real `pip install --require-hashes` on Linux is NOT RUN locally (no Linux host, Docker or WSL). It runs in CI (TASK-009). Locally, the Linux wheel-hash proxy CHK-M0-013 passes.

Re-checked after revision 2 (lock headers carry `--exclude-newer`; regeneration is byte-identical, CHK-M0-012-r2) and revision 3 (`xmlrpc` and `plistlib` banned, CHK-M0-011-r3): still PASS.

## Tests added

- `manager/tests/test_lock_files.py` (11 tests): pins and hashes, the only option line is `--only-binary :all:`, the uv header, no tools in the runtime lock, the stack, the dev superset, no identity-provider library, and the parser rejects unpinned lines.
- `manager/tests/test_project_config.py` (11 tests): requires-python, version and script, mypy strict, coverage source and fail_under, no fail-under in addopts, the pg marker, ruff target.
- `ruff check manager`, `ruff format --check manager` and `mypy --strict --config-file manager/pyproject.toml manager` pass with them. 22 passed. 8 mutations of pyproject and the locks each turn at least one test red.

## Commands and counts

- 2 fresh-venv installs, both exit 0. 8 planted installs (4 per lock), all exit 1 with the expected pip message.
- Lock regeneration: 2/2 identical with `--exclude-newer` at the lock time.
- Linux proxy: 122 wheel downloads, 0 problems.

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| TASK-001: both locks install with `--require-hashes` in a fresh 3.12 venv, Windows | CHK-M0-002, CHK-M0-003 | PASS |
| same, Linux | CHK-M0-002, CHK-M0-003, CHK-M0-013 | NOT RUN locally (proxy PASS) |
| TASK-001 and REQ-002 (3): red on a removed hash, an altered digest, or an unpinned line | CHK-M0-005, CHK-M0-006, CHK-M0-007 | PASS |
| REQ-001 (1): requires-python 3.12 only | CHK-M0-001 | PASS |
| REQ-001 (2): imports and versions (pydantic 2, APScheduler 3) | CHK-M0-009 | PASS |
| REQ-001 (3): no OIDC or identity-provider library | CHK-M0-010 | PASS |
| REQ-002 (2): every line pinned and hashed | CHK-M0-004 | PASS |
| REQ-002 (4): no test or lint tools in the runtime lock | CHK-M0-008 | PASS |
| REQ-003 to REQ-005 config (ruff, mypy, coverage) | CHK-M0-011 | PASS (behaviour proved in TASK-002) |
| PD-14 (j): RE2 wheels for Windows amd64 and Linux x86_64 and aarch64 | CHK-M0-002, CHK-M0-013 | PASS |

## Info

- The lock command differs from the PD-13 wording by `--only-binary :all: --emit-build-options` (and `--system-certs`, needed locally only). Without these, pip falls back to an sdist built with unhashed build dependencies. This is recommended for `work/decisions.md`.
- Lock regeneration depends on the time unless `--exclude-newer` is recorded.
