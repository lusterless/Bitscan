# TASK-262 IMPL: manager version 0.2.0

Owner: impl-manager-rel. REQ-290, REQ-141. Spec: TS §8.2 L1272 (semantic versioning), §8.7 L1353. Risk: low (released with the TASK-263 batch). Branch `release-0.2.0`, worktree `Bitscan-m11`.

## What changed

| File | Change |
| --- | --- |
| `manager/pyproject.toml` | `version = "0.1.0"` → `"0.2.0"` (L7) |
| `manager/bitscan_manager/__init__.py` | `__version__ = "0.1.0"` → `"0.2.0"` (L1) |
| `manager/openapi.json` | regenerated, not edited by hand: only `info.version` changes, `"0.1.0"` → `"0.2.0"` (L4888) |

`git diff --stat -- manager/` lists 3 files, 3 insertions and 3 deletions. No other file was changed for this task. `services/importer/` is unchanged against `main`: TASK-146 r2 is not in 0.2.0, and the tree holds r1 (`bit102.py` `279291cf…`, see `work/reports/TASK-146-impl.md` "Not in 0.2.0").

## How it was generated and checked

This ran in a copy of the tree in WSL Ubuntu-24.04 (`~/rel146-impl/repo`, as `bstester`), with a venv built from `manager/requirements.txt` and `requirements-dev.txt` using `--require-hashes`, and the manager installed editable with `--no-index`.

- **Export**, using the recorded command (G6): `python -m bitscan_manager.app <out>`, run twice.
  - Both exports are byte-identical, SHA-256 `bd2b2b5957ca694255c9cdd08ad659b8733960409c6d6bf7ad2b6858fa043146`.
  - The committed file before the change was `126c5429…`, the M11 gate's G6 hash. `diff` against it shows exactly one changed line, 4888, `"version": "0.1.0"` → `"0.2.0"` inside `"info"`.
  - The export was copied into `manager/openapi.json`. `git diff` on the Windows tree shows the same single line.
- **Distribution metadata:** `importlib.metadata.version("bitscan-manager")` gives `0.2.0`. `pip wheel --no-deps --no-index --no-build-isolation ./manager` builds `bitscan_manager-0.2.0-py3-none-any.whl` (REQ-137's name moves with the version).
- **Gates** (the r1 importer plus this change): `ruff check manager` passes, `ruff format --check manager` reports 421 files already formatted, and `mypy --strict --config-file manager/pyproject.toml manager` finds no issues in 421 files.

## For the tester

- **Pins to update (tester's files):**
  - `manager/tests/test_openapi.py` L75, `test_document_is_openapi_31`: `== "0.1.0"`.
  - `manager/tests/test_project_config.py` L42, `test_version_and_console_script`: `== "0.1.0"`.
- **Run before re-pinning:** `pytest tests/test_openapi.py tests/test_project_config.py` gives 2 failed, 14 passed. The only failures are those two assertions (`'0.2.0' == '0.1.0'`), and the byte-stability checks (L79, L95) pass against the new `openapi.json`.
- **Other `0.1.0` strings in `manager/tests/` are not the manager version and need no change:** agent versions in `m11_pg_fixtures.py`, `test_agent_cursors_pg.py`, `test_agent_jobs_api_pg.py`, `test_intake_pg.py` and `test_schema_fleet.py`, and an IP address in `test_cli_users_pg.py`.
- **TASK-263 batch:** the `release` workflow's "Tag, pyproject and changelog versions agree" check needs TASK-263's changelog, so it runs in the W2 batch, not here.

## Outside my area (for main)

`deploy/runbooks/manager-install.md` still names the 0.1.0 manager files: L165 `bitscan_manager-0.1.0-py3-none-any.whl`, L166 `bitscan-manager-0.1.0-requirements.txt`, and the install commands at L411–L412. The file is impl-deploy's and is not in TASK-263's list (`agent-install.md`, `manager-operations.md`). I didn't change it. Whether it should move to 0.2.0 is for main to decide.
