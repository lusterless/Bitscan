# TASK-139 REVIEW: runtime dependency `python-multipart` (PD-33 (a))

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-27. REQ-185; PD-33 (a); TS §8.2 L1264, §8.1 L1258. Low risk, but the user's second look applies (PD-35: new runtime dependency).

Scope reviewed: `git diff` of `manager/pyproject.toml` (+3), `manager/requirements.txt` (+4), `manager/requirements-dev.txt` (+4), per `work/reports/TASK-139-impl.md`. TEST: PASS (`work/reports/TASK-139-test.md`, CHK-M7-016 to -019).

## Checks
1. **Spec and PD-33.** One package added, `python-multipart>=0.0.20`, under `[project].dependencies`; the comment states the low-level-parser-only use (TS §4.1 L522 in-memory parsing). Nothing else in `pyproject.toml` changed.
2. **Locks.** Each lock gains exactly the one entry `python-multipart==0.0.32` with two `sha256` hashes and `# via bitscan-manager (pyproject.toml)`; no other line moved. The header still records the unchanged command and `--exclude-newer 2026-10-19T16:56:37Z` cutoff.
3. **Nothing extra in the runtime lock.** `grep` for pytest, ruff, mypy, hypothesis, coverage, testcontainers, jsonschema, hatchling at line start in `manager/requirements.txt`: 0.
4. **The package itself** (installed metadata in `manager/.venv`): Apache-2.0, `Requires-Dist` empty (no transitive dependencies), pure Python. It ships `python_multipart/` and the deprecated `multipart/` alias shim. The lower bound 0.0.20 is above the 0.0.18 fix for CVE-2024-53981 (boundary DoS). FastAPI only exercises the package for routes that declare `Form`/`File`; none exist, so no current route changes behaviour.
5. **Re-run by me (Windows, `manager/.venv`):**
   - `ruff check manager`: clean;
   - `ruff format --check manager`: 248 files formatted;
   - `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 248 files;
   - `pytest tests/test_lock_files.py tests/test_project_config.py tests/test_bit_model.py`: 98 passed;
   - `python -I -W error -c "import python_multipart; from python_multipart.multipart import MultipartParser"`: 0.0.32, no warning.

## Findings
None blocking or should-fix.

1. nit, for TASK-162 (not this diff): import `python_multipart`, never `multipart`. The alias raises `PendingDeprecationWarning` (impl report, "For the tester"). Add a check in TASK-162's review.

## For the user's second look (PD-35)
- New runtime dependency: `python-multipart` 0.0.32 (Starlette/FastAPI maintainers), Apache-2.0, no dependencies of its own, hash-pinned in both locks.
- Use is limited to the low-level `MultipartParser` over the already-capped in-memory body (TASK-162, design note D5); the high-level form API that spools to disk is not used.
