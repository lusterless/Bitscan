# TASK-058 IMPL report: dev-only test libraries (PD-21)

REQ: REQ-061, REQ-074. Decision: PD-21 (a), `work/decisions.md` 2026-10-23. Lock command: `work/decisions.md` 2026-10-20 (TASK-001 revision 2), as recorded in each lock's header.

## Files (2)

- `manager/pyproject.toml`: 4 lines added to `[project.optional-dependencies] dev`: `"jsonschema>=4.23"` and `"hypothesis>=6.100"`, plus a two-line comment.
- `manager/requirements-dev.txt`: regenerated, 237 lines added and none removed.

## Command (run from `manager/`, unchanged cutoff)

```
uv pip compile --system-certs --universal --only-binary :all: --emit-build-options --generate-hashes --exclude-newer 2026-10-19T16:56:37Z --python-version 3.12 --extra dev pyproject.toml -o requirements-dev.txt
```

The cutoff `2026-10-19T16:56:37Z` resolves both packages, so `--exclude-newer` did **not** move. uv 0.13.1.

## Result

- New pins, all dev-only: `attrs==26.1.0`, `hypothesis==6.170.2`, `jsonschema==4.26.0`, `jsonschema-specifications==2025.9.1`, `referencing==0.37.0`, `rpds-py==2026.9.1`, `sortedcontainers==2.4.0`. No existing pin or hash changed: the pin list diff against HEAD shows only these seven additions.
- `manager/requirements.txt` is **byte-identical**. SHA-256 `b90907275b9fbc9bc4d00dc8e6a24b6fb2243e11e8c265a1fd516e0aebf2bbd6` before and after; `git diff` shows no change.
- Reproducible: a second run of the command gave a byte-identical `requirements-dev.txt` (`cmp` silent).

## Local evidence (Windows)

- A fresh Python 3.12.10 venv ran `pip install --require-hashes -r manager/requirements-dev.txt` and exited 0. In it, `import jsonschema, hypothesis` worked and reported 4.26.0 and 6.170.2.
- Linux proxy (no real Linux install): `uv pip install --dry-run --require-hashes --only-binary :all: --python-version 3.12 --python-platform {x86_64,aarch64}-manylinux_2_28 -r requirements-dev.txt` exited 0 for both platforms, 65 packages, `rpds-py` included (it has a compiled extension).
- The real Linux install in a fresh venv is the tester's (TP-M3-12, WSL).

## Gates

`ruff check manager`, `ruff format --check manager` and pytest are unaffected by this task: 1198 passed, 451 skipped; the 2 failures are TASK-056's expected ones.

## Deviations

None.
