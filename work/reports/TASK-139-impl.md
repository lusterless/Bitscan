# TASK-139 IMPL: runtime dependency `python-multipart` (PD-33 (a))

Implementer: impl-manager-m7. REQ-185. Worktree `Bitscan-m7`, branch `m7-catalog`.

## What changed

| File | Change |
| --- | --- |
| `manager/pyproject.toml` | `"python-multipart>=0.0.20"` added to `[project].dependencies`, with a two-line PD-33 comment. Nothing else changed. |
| `manager/requirements.txt` | Regenerated: adds `python-multipart==0.0.32` (2 hashes, `# via bitscan-manager (pyproject.toml)`). No other line changed. |
| `manager/requirements-dev.txt` | Regenerated: the same single entry added. No other line changed. |

No source file changed. The package brings no transitive dependencies.

## Recorded lock command (unchanged, decisions 2026-10-20)

Run from `manager/`:

```sh
uv pip compile --system-certs --universal --only-binary :all: --emit-build-options --generate-hashes --exclude-newer 2026-10-19T16:56:37Z --python-version 3.12 pyproject.toml -o requirements.txt
uv pip compile --system-certs --universal --only-binary :all: --emit-build-options --generate-hashes --exclude-newer 2026-10-19T16:56:37Z --python-version 3.12 --extra dev pyproject.toml -o requirements-dev.txt
```

The `--exclude-newer` cutoff is not moved; 0.0.32 is the newest release before it. uv 0.13.1 on Windows.

## Acceptance points

1. **Fresh CPython 3.12 venvs, `pip install --require-hashes` exits 0** (Windows, done here):
   - runtime lock in a fresh venv: exit 0; `import multipart, python_multipart` works, version 0.0.32.
   - dev lock in a fresh `manager/.venv` (README "Setup (development)"), then `pip install --no-deps --no-build-isolation -e manager`: both exit 0.
   - Linux (WSL Ubuntu 24.04, CPython 3.12.3, the implementer's own copy at `/root/impl-m7`, separate from the tester's): the runtime lock in a fresh venv exits 0, and `python -W error -c "import python_multipart"` gives 0.0.32; the dev lock in a fresh venv `/root/venv-impl-m7` exits 0, then the editable install. The package is a pure `py3-none-any` wheel.
2. **The recorded command reproduces both files byte for byte.** Before editing, a rerun to a temp path matched both locks from line 3 on (line 2 is the command line, which holds the `-o` path). After editing, both locks were regenerated, then regenerated again into temp files (identical from line 3), and the runtime lock was regenerated in place a third time: `cmp` showed it byte-identical.
3. **The runtime lock names no test or lint tool:** `grep -c "pytest\|ruff\|mypy\|hypothesis\|coverage\|testcontainers\|jsonschema\|hatchling" manager/requirements.txt` gives 0, and `pip list` in the runtime-only venv shows none of them.

## Static gates (Windows, `manager/.venv`)

- `ruff check manager`: All checks passed. `ruff format --check manager`: 233 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager` (the CI command, `.github/workflows/manager.yml` L117): Success, no issues in 236 source files.
- Note: the bare `mypy --strict manager` run from the repo root (as CLAUDE.md "Commands" writes it) does not find `manager/pyproject.toml`. It therefore runs without the `pydantic.mypy` plugin and reports 8 `arg-type` errors in `api/user/packages.py`, `agents.py` and `enrolment.py`. The same happens with `python-multipart` uninstalled. That is a difference in the command, not in the code or this lock. Reported to `main`.

## For the tester

- `import multipart` works, but in 0.0.32 it is a shim that raises `PendingDeprecationWarning` ("Please use `import python_multipart` instead."). Under `-W error` it fails. Product code (TASK-162) should import `python_multipart`. A check written as "`import multipart` works" passes only without `-W error`; `import python_multipart` is the warning-free form.
- PD-35: TASK-139 also gets the user's second look (new runtime dependency).
