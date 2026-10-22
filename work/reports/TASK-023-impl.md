# TASK-023 IMPL report: runtime dependencies for M2 (PD-19)

REQ: REQ-034. Spec: TS §8.2 (`pip --require-hashes`), TS §8.1 "Install and supply chain"; PD-19 (user-approved 2026-10-21); decisions 2026-10-20 (final lock command).

## Files (3)

- `manager/pyproject.toml`: runtime `dependencies` gain `uvicorn>=0.30` (no `standard` extra), `argon2-cffi>=23.1`, `httpx>=0.27`, `psycopg-pool>=3.2`, `prometheus-client>=0.20`, with a one-line PD-19 comment. `httpx` is removed from the `dev` extra (dev still gets it through the runtime set). No vault client library (no `hvac`), no `pyotp` (PD-19 (f), (g)).
- `manager/requirements.txt`, `manager/requirements-dev.txt`: regenerated.

## Lock command (unchanged, same cutoff)

```
uv pip compile --system-certs --universal --only-binary :all: --emit-build-options --generate-hashes --exclude-newer 2026-10-19T16:56:37Z --python-version 3.12 [--extra dev] pyproject.toml -o <lock>
```

Run from `manager/`. The cutoff `2026-10-19T16:56:37Z` resolves every new package, so `--exclude-newer` did **not** move.

## What changed in the locks

- Runtime lock, added: `uvicorn==0.54.0` (+ `click==8.5.0`, `h11==0.16.0`), `argon2-cffi==25.1.0` (+ `argon2-cffi-bindings==26.1.0`, `cffi==2.1.1`, `pycparser==3.11 ; implementation_name != 'PyPy'`), `httpx==0.28.1` (+ `httpcore==1.0.9`, `certifi==2026.10.18`), `psycopg-pool==3.3.3`, `prometheus-client==0.26.0`. These are the same versions the dev lock already had for httpx, httpcore, h11 and certifi.
- Dev lock, added: `uvicorn`, `click`, `argon2-cffi`, `argon2-cffi-bindings`, `cffi`, `pycparser`, `psycopg-pool`, `prometheus-client`. The only removed line is a `# via httpcore` annotation for h11, which became a multi-line `# via` block (h11 is now also via uvicorn).
- No existing pin or hash changed or was removed in either file.
- No `uvloop`, `httptools`, `websockets`, `watchfiles` or `python-dotenv` (no `uvicorn[standard]`). No OpenTelemetry SDK or exporter; `opentelemetry-api==1.45.1` was already in the runtime lock via fastapi before this task (REQ-034 (5) names only `opentelemetry-sdk` and `opentelemetry-exporter-*`). No OIDC library.
- Native wheels: `argon2-cffi-bindings` (abi3) and `cffi` (cp312) have Windows amd64 and manylinux x86_64/aarch64 wheels in the lock; the rest are pure Python.

## Checks run (Windows 11 + Git Bash)

| Check | Result |
| --- | --- |
| Regenerate both locks with the header command, compare with `cmp` | byte-identical |
| Fresh `python -m venv` (CPython 3.12, pip 25.0.1): `pip install --require-hashes -r requirements.txt` | exit 0 |
| Same venv: `python -I -c "import uvicorn, argon2, httpx, psycopg_pool, prometheus_client"`; `PasswordHasher().hash(...)` | ok; hash starts `$argon2id$`; uvicorn 0.54.0, httpx 0.28.1 |
| Same venv: `pip list` for pytest, ruff, mypy, testcontainers, opentelemetry-sdk/exporter, uvloop, httptools | none (only `opentelemetry-api`, pre-existing) |
| Fresh venv: `pip install --require-hashes -r requirements-dev.txt` | exit 0 |
| Linux proxy: `uv pip install --require-hashes --python-platform {x86_64,aarch64}-manylinux_2_28 --python-version 3.12 --target <tmp>` for both locks | all four OK |
| `manager/.venv` updated from the dev lock (`uv pip install --require-hashes -r requirements-dev.txt`; the venv has no pip) | 8 packages added |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 46 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 366 passed, 181 skipped (pg), 98.15 % |
| Real Linux install (WSL) | NOT RUN by me (only the tester runs WSL) |

## For the tester

- Recreate `/root/venv` in WSL from the new dev lock before the next `pg` run.
- `test_lock_files.py` `DEV_REQUIRED` still holds (httpx now comes into the dev lock through the runtime set).
