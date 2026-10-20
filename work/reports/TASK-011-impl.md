# TASK-011 IMPL report: runtime database dependencies

REQ: REQ-018. Spec: TS §5.3 ("Migrations: Alembic"), TS §8.2 (`pip --require-hashes`), TS §8.1 "Install and supply chain"; PD-14 (i) psycopg 3; decisions 2026-10-20 (final lock command).

## Files (3)

- `manager/pyproject.toml`: runtime `dependencies` gain `alembic>=1.13`, `sqlalchemy>=2.0` and `psycopg[binary]>=3.2`. `psycopg[binary]` is removed from the `dev` extra; dev still gets it through the runtime set. Nothing else changed.
- `manager/requirements.txt`, `manager/requirements-dev.txt`: regenerated (below).

## Lock command (unchanged, same cutoff)

```
uv pip compile --system-certs --universal --only-binary :all: --emit-build-options --generate-hashes --exclude-newer 2026-10-19T16:56:37Z --python-version 3.12 [--extra dev] pyproject.toml -o <lock>
```

The existing cutoff `2026-10-19T16:56:37Z` resolves every new package, so it did not move.

## What changed in the locks

- Runtime lock, added: `alembic==1.20.0`, `sqlalchemy==2.1.5`, `mako==1.4.3` and `markupsafe==3.0.4` (both via alembic), `psycopg==3.3.6` and `psycopg-binary==3.3.6 ; implementation_name != 'pypy'`.
- Dev lock, added: `alembic`, `sqlalchemy`, `mako`, `markupsafe`. psycopg was already there.
- No existing pin or hash changed or was removed. The only removed line in either file is a `# via tzlocal` annotation; it became a multi-line `# via` block because the dependency graph changed. greenlet is not pulled in, since SQLAlchemy 2.1 makes it optional and it is not needed for sync use.
- `psycopg[binary]` brings its own libpq (version 18.4, `psycopg.pq.version()` = 180004), built with TLS. With `sslmode=require` and `verify-full` against a closed port, both Windows and Linux fail with a connection error, not "SSL support is not compiled in". This keeps the manager independent of the host's `libpq5`. Using the system libpq (plain `psycopg` plus `libpq5`) instead would tie it to the install method (#6). Lead: tell me if you prefer that.

## Checks run

| Check | Result |
| --- | --- |
| Regenerate both locks in a temp dir with the header command | byte-identical to the committed files |
| Windows, fresh `python -m venv` (pip 25.0.1): `pip install --require-hashes -r` of each lock | exit 0, 0 sdist builds |
| Windows: `import alembic, sqlalchemy, psycopg` after each install | ok (1.20.0, 2.1.5, 3.3.6, `pq.__impl__` = `binary`); the M0 stack imports still work |
| **Real Linux** x86_64 (WSL Ubuntu 24.04, `python3.12 -m venv`): `pip install --require-hashes -r` of each lock | exit 0, 0 builds; imports ok; runtime venv contains none of pytest, ruff, mypy, testcontainers |
| Linux proxy `uv pip install --require-hashes --python-platform {x86_64,aarch64}-manylinux_2_28 --target` | all four exit 0; the `psycopg_binary` native module is present for each arch |
| Runtime lock names pytest, ruff, mypy, testcontainers, coverage or hatchling | none |
| `manager/.venv` re-synced from the dev lock (`uv pip sync --require-hashes`) + editable install; `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 13 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` (Windows) | 65 passed, 3 skipped (pg), gate reached |
| aarch64 real install | NOT RUN locally (no arm64 host); proxy above, CI |

## For the tester

- The WSL venv `/root/venv` was not touched. Recreate it from the new dev lock before the next `pg` run (m1 brief).
- The aarch64 wheel-hash check is your CHK-M0-013 proxy. The new packages are pure Python wheels except `psycopg-binary` (and `markupsafe`'s optional speedups), which have manylinux x86_64 and aarch64 wheels in the lock.
