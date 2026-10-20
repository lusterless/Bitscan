# TASK-003 plan: Testcontainers PostgreSQL 16 harness

REQs: REQ-009, REQ-004. Owner: tester (test infrastructure). Depends on: TASK-001. TEST step owner: PD-17.

## Spec quotes

- TS §8.3 L1278: "Integration | API + PostgreSQL (Testcontainers) | …".
- TS §2.1 L106: "PostgreSQL 16 (`pg_trgm`, `debversion`)"; the TS §5.2 Bootstrap installs `pg_trgm`, `pgcrypto` and `debversion` (package `postgresql-16-debversion`, deploy rule "Database bootstrap"). The §2.1 omission of `pgcrypto` is a known spec inconsistency (open-questions part 5).
- testing.md: "Tests that need PostgreSQL run the TS §5.2 Bootstrap block, then `bitscan-manager db migrate` … never apply the raw spec DDL. … Tests never run as a superuser after the bootstrap." That is M1; M0 only provides the container.

## Approach

- `manager/tests/postgres/Dockerfile`: `FROM` the official PostgreSQL 16 image (pinned by digest, PD-14 (n)), then install `postgresql-16-debversion` from the PGDG apt repository the official image already configures. `pg_trgm` and `pgcrypto` ship in contrib with the base image.
- `manager/tests/conftest.py`: a session-scoped fixture that builds or reuses that image through Testcontainers, starts it, yields a connection factory (superuser, for the M1 Bootstrap step only), and stops and removes the container at session end.
- Docker missing: catch the Docker client error once. If `CI` is set to `true`, fail the session with the reason; otherwise skip the PostgreSQL-marked tests with the reason "not run: Docker unavailable" (PD-15). Unit tests that do not use the fixture must still run.
- `manager/tests/test_pg_harness.py`: the REQ-009 checks (version range, `pg_available_extensions`, `CREATE EXTENSION debversion`, and `'1.0~rc1'::debversion < '1.0'::debversion`).
- Everything must pass `mypy --strict manager` and ruff. If `testcontainers` lacks type information, ask impl-manager for a `[[tool.mypy.overrides]]` entry in `manager/pyproject.toml`; do not edit that file.

## Edge cases

- Building the image on every run is slow: tag it with a fixed local name and reuse it if present; CI may cache it (TASK-009).
- Windows Docker Desktop: the container host is not always `localhost`; take host and port from Testcontainers, never hard-code them.
- The container's superuser password is a throwaway value generated per run, never a committed secret.
- Skipped locally is a "not run" result with a reason, not a pass; it must show in `tests/m0/report.md` as NOT RUN.

## Not in this task

The Bootstrap block, migrations, grant probes, schema diff (M1).
