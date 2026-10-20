# TASK-003 IMPL report: Testcontainers PostgreSQL 16 harness with debversion

Implementer: tester (test infrastructure; PD-17: TEST by a second tester instance). REQ-009, REQ-004. Spec: TS §8.3 Integration (L1278), TS §2.1 (L106), deploy rule "Database bootstrap". Plan: `work/plans/TASK-003.md`. Date 2026-10-20.

## Files (4, all tester-owned)

- `manager/tests/__init__.py`: empty. It makes `tests` a package, so the test modules can import each other (`from .conftest import Connect`, `from .test_app import EnvRecorder`).
- `manager/tests/conftest.py`:
  - `pg_connect`, a session fixture. It builds `tests/postgres/Dockerfile` with Testcontainers `DockerImage` (tag `bitscan-test-postgres:16`, `clean_up=False`, so the Docker layer cache reuses it). It then starts `testcontainers.community.postgres.PostgresContainer` with user `postgres` and a password generated per run (`secrets.token_urlsafe(24)`, never committed).
  - The fixture yields a factory that returns `psycopg.Connection`, with `autocommit=True`. Host and port come from Testcontainers (`get_container_host_ip`, `get_exposed_port`), never hard-coded.
  - The container is removed when the session ends (`PostgresContainer.__exit__` calls `remove(force=True, v=True)`).
  - A `pytest_collection_modifyitems` hook (`trylast`, so it runs after `-m` and `-k` deselection) checks Docker only when `pg`-marked tests are selected:
    - no Docker and `CI` is not `true`: each `pg` test is skipped with the reason `not run: Docker unavailable`;
    - no Docker and `CI=true` (any case): `pytest.exit(..., 1)` with "not run: Docker unavailable and CI=true: PostgreSQL tests must run (<error>)".
  - The superuser is for the M1 Bootstrap step only (docstring).
- `manager/tests/test_pg_harness.py`: `pytestmark = pytest.mark.pg`, three tests:
  - `SHOW server_version_num` is in 160000 to 169999;
  - `pg_available_extensions` contains exactly `{pg_trgm, pgcrypto, debversion}` among those names;
  - `CREATE EXTENSION IF NOT EXISTS debversion`, then `('1.0~rc1'::debversion < '1.0'::debversion, '1.0'::debversion < '1.0~rc1'::debversion, '1.0~rc1' < '1.0')` must be `(true, false, false)`. The text comparison proves debversion is not plain text ordering.
- `manager/tests/postgres/Dockerfile`:
  - `FROM postgres:16-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4`. This is the OCI multi-arch index digest read from registry-1.docker.io on 2026-10-20; the index lists amd64 and arm64.
  - Then `apt-get install -y --no-install-recommends postgresql-16-debversion` from the PGDG repo that the official image configures.
  - `pg_trgm` and `pgcrypto` ship in contrib.

No change was needed to `manager/pyproject.toml`: testcontainers and psycopg ship `py.typed`, and mypy --strict passes. The `pg` marker already exists (TASK-001).

## What I verified locally (Windows, no Docker)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager` | exit 0 (12 files) |
| CHK-M0-053: `cd manager && pytest -rs` with `CI` unset | exit 0: `55 passed, 3 skipped`, `SKIPPED [3] tests\test_pg_harness.py: not run: Docker unavailable`. The unit tests still run. `CI=false` gives the same result |
| CHK-M0-054: `CI=true pytest` | exit 1: `Exit: not run: Docker unavailable and CI=true: PostgreSQL tests must run (DockerException: Error while fetching server API version ...)`. The same with `CI=TRUE` |
| `CI=true pytest -m "not pg"` | exit 0, 55 passed, 3 deselected (the hook runs after deselection; the first draft got this wrong and was fixed) |
| Coverage gate `pytest --cov=bitscan_manager/services --cov-fail-under=85` | exit 0 (100 %) |
| CHK-M0-055 (static) | `FROM` pinned by `@sha256:` digest; installs `postgresql-16-debversion`; no password literal in `conftest.py` |

## NOT RUN locally (Docker unavailable; needs a Docker host or CI)

- CHK-M0-050: version range and the three extensions available.
- CHK-M0-051: `CREATE EXTENSION debversion` and the ordering.
- CHK-M0-052: no container left after the session. Check with `docker ps -a --filter label=org.testcontainers=true`.
- CHK-M0-057: `docker build manager/tests/postgres`.

## For the TEST tester

- On a Docker host: `cd manager && pytest -m pg -rs tests/test_pg_harness.py`; expect 3 passed. Then run `docker ps -a` and expect no harness container (the Ryuk reaper container is removed too).
- Planted violations for the red cases:
  - change `FROM` to a `postgres:15` digest: version test red;
  - drop the `apt-get` line: extension and debversion tests red;
  - remove the `@sha256:` pin: CHK-M0-055 red.
- Windows Docker Desktop: host and port come from Testcontainers. If the Ryuk reaper is blocked, set `TESTCONTAINERS_RYUK_DISABLED=true` and check the cleanup by hand.
- The first `docker build` needs network access (Docker Hub and apt.postgresql.org). CI (TASK-009) may cache the image.
