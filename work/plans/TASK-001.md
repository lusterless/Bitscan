# TASK-001 plan: manager project config and hashed lock files

REQs: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005. Owner: impl-manager. Depends on: none.

## Spec quotes

- TS §8.2 L1264: "**Python:** 3.12, type hints everywhere, `ruff` (lint + format), `mypy --strict`, layered as `api → services → repositories` … Dependencies installed with `pip --require-hashes`."
- TS §8.1 L1258: "… reproducible builds; SBOM per release; hashed Python dependencies."
- TS §8.3 L1275: "≥ 85 % line coverage on `manager/services`". testing.md: this means `manager/bitscan_manager/services/`, and the M0 coverage config must point there.
- TS §2.1 L102–L104: Python 3.12, FastAPI, Pydantic v2, APScheduler, `defusedxml`.

## Approach

1. `manager/pyproject.toml` holds:
   - `[project]`: name `bitscan-manager`, `requires-python = ">=3.12,<3.13"`, runtime dependencies (FastAPI, Pydantic 2, APScheduler, `defusedxml`, the RE2 binding), an optional `dev` extra (pytest, pytest-cov, ruff, mypy, testcontainers, the PostgreSQL driver, httpx for the FastAPI test client). Version and build backend per PD-14 (h), (m). Declare `[project.scripts] bitscan-manager = "bitscan_manager.cli:main"` here. Its target module arrives in TASK-002, and nothing installs the package itself before then (TASK-001 tests install only the lock files).
   - `[tool.ruff]`: `target-version = "py312"`; a rule selection that includes at least pyflakes (F), pycodestyle (E, W), isort (I), bugbear (B), pyupgrade (UP), bandit (S, which includes S608 for string-built SQL) and flake8-tidy-imports (TID). `[tool.ruff.lint.flake8-tidy-imports.banned-api]` bans `xml.etree`, `xml.dom`, `xml.sax`, `xml.parsers.expat` and `lxml`, with a message pointing at `defusedxml` (TS §4.1). Banning `re` is PD-14 (g): add it only if accepted. Per-file ignores for `tests/` may relax `S101` (assert) only.
   - `[tool.mypy]`: `strict = true`, `python_version = "3.12"`, the pydantic mypy plugin. How the CLAUDE.md command finds this config is PD-16; do not add a root-level file without the lead's answer.
   - `[tool.pytest.ini_options]`: `testpaths = ["tests"]`, a marker for PostgreSQL tests (for example `pg`). Do **not** put `--cov-fail-under` in `addopts`: the gate belongs in the CI command (PD-5), so a developer can run one test file.
   - `[tool.coverage.run]`: `source = ["bitscan_manager/services"]`, `branch = false` (the gate is line coverage). `[tool.coverage.report]`: `fail_under = 85`, `show_missing = true`.
2. Lock files are generated, never hand-edited, by the command chosen in PD-13. Recommended:
   - `uv pip compile --universal --generate-hashes --python-version 3.12 pyproject.toml -o requirements.txt`
   - `uv pip compile --universal --generate-hashes --python-version 3.12 --extra dev pyproject.toml -o requirements-dev.txt`

   `--universal` keeps environment markers, so one file installs on Windows (for example `pywin32`, pulled in by the Docker SDK under `testcontainers`) and on Linux. A plain `pip-compile` run on Windows drops such markers, and the result then fails on Linux under `--require-hashes` (and the reverse). Put the exact command in a comment at the top of each lock file.
3. Installing the project itself (`pip install -e manager`) uses build isolation, which downloads the build backend without hashes. Include the build backend in the dev lock and install the project with `--no-deps --no-build-isolation`, so every byte comes from a hashed lock. TASK-009 uses the same command.

## Edge cases

- `pip install --require-hashes` fails if any transitive dependency lacks a hash: check by installing into an empty venv, not into the dev venv.
- The RE2 binding must have CPython 3.12 wheels for Windows amd64, Linux x86_64 and Linux aarch64; if one is missing, stop and tell `main` (PD-14 (j)).
- APScheduler 4 is a pre-release line; pin the stable major (PD-14 (k)).
- No OIDC, signing or other out-of-scope library (REQ-001 (3)).

## Not in this task

Package code (TASK-002), tests (TASK-003), CI (TASK-009), any `.claude/` or CLAUDE.md edit.
