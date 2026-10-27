# TASK-139 TEST: PASS

Tester: tester-m7, 2026-10-27. REQ-185, PD-33 (a). Checks CHK-M7-016 to -019 (tests/m7/test-plan.md).

| Check | Command | Result |
| --- | --- | --- |
| CHK-M7-016 | fresh CPython 3.12 venvs (Windows 3.12.10, WSL 3.12.3): `pip install --require-hashes -r manager/requirements.txt` and `-r manager/requirements-dev.txt`; `python -W error -c "import python_multipart; from python_multipart.multipart import MultipartParser"` | PASS: all four installs exit 0; python_multipart 0.0.32 imports with no warning |
| CHK-M7-017 | recorded `uv pip compile` commands run in place in a throwaway copy, then `cmp` | PASS: both locks byte-identical |
| CHK-M7-018 | `git diff -U0`; tool grep of the runtime lock; `pip list` of the runtime venv | PASS: only `python-multipart==0.0.32` added; no test or lint tool |
| CHK-M7-019 | WSL `CI=true pytest -n 0 tests/test_lock_files.py tests/test_project_config.py tests/test_module_imports.py` | PASS: 139/139 passed, 0 failed, 0 skipped |

The 8 mypy errors from the bare `mypy --strict manager` are a missing pydantic plugin, not this task: the CI form (`--config-file manager/pyproject.toml`) is clean on 248 files.

## Report rows (tests/m7/report.md format)

W = WSL2 Ubuntu 24.04, copy `/root/bstest-m7-w1`, venv `/root/venv-m7` (`--require-hashes` dev lock + editable manager), `CI=true`, `BSTEST_RUN_LABEL=m7t-<label>`, `-n 0` (one PostgreSQL 16 container), leftover-own 0 after each run. L = Windows 11, `manager/.venv`. Plants in `/root/bstest-m7-mut-<id>` (deleted after the run), imported first through `PYTHONPATH` (asserted).

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-016 | APP | L, W | fresh CPython 3.12 venvs: `pip install --require-hashes -r manager/requirements.txt` and `-r manager/requirements-dev.txt`; `python -W error -c "import python_multipart; from python_multipart.multipart import MultipartParser"` | PASS | Windows 3.12.10 runtime and dev exit 0; WSL 3.12.3 runtime and dev exit 0, editable exit 0; python_multipart 0.0.32, no warning | 2026-10-27 |
| CHK-M7-017 | CODE | L | recorded `uv pip compile` commands (uv 0.13.1) run in place in a throwaway copy, then `cmp` | PASS | both locks byte-identical (runtime b6bf600e…4a26, dev 7dd909a9…c041) | 2026-10-27 |
| CHK-M7-018 | CODE | L, W | `git diff -U0` of pyproject and both locks; tool grep of the runtime lock; `pip list` of the runtime venv | PASS | only `python-multipart==0.0.32` (2 hashes) added; 0 test or lint tools | 2026-10-27 |
| CHK-M7-019 | APP | W | `pytest -q -n 0 tests/test_lock_files.py tests/test_project_config.py tests/test_module_imports.py` (m7t-u1) | PASS | 17 + 10 + 112 = 139/139 passed; whole run 437/437, 0 failed, 0 errors, 0 skipped | 2026-10-27 |
