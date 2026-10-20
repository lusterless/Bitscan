# TASK-003 REVIEW: Testcontainers PostgreSQL 16 harness with debversion

Reviewer: reviewer. Date: 2026-10-20. REQ-009, REQ-004. Spec: TS §8.3 L1278 (Integration: API + PostgreSQL through Testcontainers), TS §2.1 L106, TS §5.2 Bootstrap (M1); `.claude/rules/testing.md`; decisions PD-14 (n), PD-15 and PD-17. Inputs: `work/plans/TASK-003.md`, `work/reports/TASK-003-impl.md` (tester), `work/reports/TASK-003-test.md` (tester-b, PASS), `tests/m0/report.md` CHK-M0-050 to -057.

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268). The Docker checks CHK-M0-050, -051, -052 and -057 are NOT RUN locally and are carried to CI (TASK-009, `CI=true`). This approval covers the code; those checks must pass there.

## What was checked

- **Scope:** exactly the 4 listed files:
  - `tests/__init__.py`, empty;
  - `conftest.py`, 84 lines;
  - `test_pg_harness.py`, 3 tests;
  - `postgres/Dockerfile`, 9 lines.

  The other files in `manager/tests/` belong to TASK-001 and TASK-002.
- **Digest pin, checked against registry-1.docker.io (anonymous, read-only):**
  - `sha256:0ea6700a…c4` is an OCI image index and is the current `postgres:16-bookworm` tag digest;
  - it has linux/amd64 and linux/arm64 entries;
  - both image configs have `PG_MAJOR=16` and `PG_VERSION=16.15-1.pgdg12+2`.
- **Skip and exit hook, re-run from `manager/`:**

  | Run | Result |
  | --- | --- |
  | `CI` unset | exit 0: 55 passed, 3 skipped `not run: Docker unavailable` |
  | `CI=1` | the same (treated as local) |
  | `CI=true` and `CI=True` | exit 1, `Exit: not run: Docker unavailable and CI=true: PostgreSQL tests must run (DockerException …)` |
  | `CI=true -m "not pg"` | exit 0, 3 deselected |
  | `CI=true` with only `tests/test_cli.py` | exit 0; the hook probes Docker only when `pg` tests are selected |

- **Secrets:**
  - the superuser password is `secrets.token_urlsafe(24)`, generated per run;
  - no password literal under `manager/tests/`;
  - the `FROM` line carries no credentials.
- **Cleanup (static review of testcontainers 4.15.0):** `PostgresContainer.__exit__` calls `remove(force=True, v=True)`. Ryuk (`core/container.py:245`) reaps after a killed session. Host and port come from Testcontainers (`get_container_host_ip`, `get_exposed_port`).
- **SQL and test quality:**
  - all queries are static or parameterised (`= ANY(%s)`);
  - the version range is inclusive;
  - the extension check requires the exact three-name set;
  - the debversion test has both a reversed comparison and a plain-text control, so a text-ordered type would fail.
- **Gates:** `ruff check`, `ruff format --check` and `mypy --strict --config-file manager/pyproject.toml manager` are clean (12 files).

## Findings

1. **nit, for M1 (tester-b observation 2). Nothing tests the skip and exit hook itself.** In CI Docker is present, so a regression in that hook would go unnoticed.
   - Where: `manager/tests/conftest.py:38-51`.
   - Fix: add a `pytester` test in M1 covering: no Docker plus `CI` unset gives a skip with the reason; no Docker plus `CI=true` exits 1; `-m "not pg"` does not probe Docker.
2. **nit, for TASK-009 (tester-b observation 4). The Ryuk reaper image is pulled by tag.** Ryuk is `testcontainers/ryuk:0.8.1` (`testcontainers/core/config.py:105`) and mounts the Docker socket, so a re-pointed tag would get the runner's Docker daemon.
   - Fix: in CI set `RYUK_CONTAINER_IMAGE=testcontainers/ryuk:0.8.1@sha256:<digest>`.
3. **nit. The container port is published on every host interface.** testcontainers maps `5432` with `ports={"5432": None}` (`core/container.py:219`), so the superuser database is reachable from the host's network for the length of the session. The 24-byte random password makes this acceptable on dev boxes and ephemeral CI runners. If M1 wants it tighter, bind the host side to `127.0.0.1` where the Docker host allows.
4. **nit, accepted as is (tester-b observation 1). `postgresql-16-debversion` has no apt version pin.**
   - Where: `manager/tests/postgres/Dockerfile:8`.
   - The base is pinned by digest, which is what PD-14 (n) requires. apt verifies PGDG signatures with the keyring already in the image. A version pin would break once PGDG prunes the old version.
   - Optional: have CI log `dpkg-query -W postgresql-16-debversion` after the build.
5. **nit, accepted (tester-b observation 3). Only `CI=true`, in any case, fails the run.** GitHub Actions sets `CI=true`, which matches PD-15's wording.
6. **note for M1 (`.claude/rules/testing.md`).** The fixture connects as the superuser, which is right for M0 and for the M1 Bootstrap step. M1 tests must switch to the `bitscan_app` and `bitscan_retention` roles after the Bootstrap, and never apply the raw spec DDL.
