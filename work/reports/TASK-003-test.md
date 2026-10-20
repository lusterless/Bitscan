# TASK-003 TEST report: Testcontainers PostgreSQL 16 harness with debversion

Tester: tester-b (PD-17: independent of `tester`, who implemented TASK-003). REQ-009, REQ-004. Date 2026-10-20. Impl report: `work/reports/TASK-003-impl.md`. Plan: `work/plans/TASK-003.md`. CPython 3.12.10, `manager/.venv`, testcontainers 4.15.0, docker 7.2.0, psycopg 3.3.6. Docker and WSL are not installed (PD-15).

## Verdict: PASS

Every check that can run here passes. CHK-M0-050, -051, -052 and -057 need Docker. They are NOT RUN locally and run in CI (TASK-009, `CI=true`, where a missing Docker fails the run), so they do not count as passes. I re-ran every implementer claim myself instead of relying on it.

## Tests and mutations

- Files reviewed: `manager/tests/__init__.py` (empty), `conftest.py` (84 lines), `test_pg_harness.py` (3 `pg` tests), `postgres/Dockerfile`. Only these 4 files, as listed in `work/tasks.md`.
- SQL review: the version range is inclusive 160000 to 169999; the extension set must be exactly the three names (parameterised query); `debversion` returns `(True, False, False)` with a text control that is false under any collation, so a text-ordered type fails.
- 10 mutations in a throwaway copy of `manager/` (without `.venv`, deleted afterwards). The copy itself was the control: CI unset exits 0, `CI=true` exits 1, `-m "not pg"` exits 0. Every mutation turned its check red:
  - `CI` comparison broken (CI=true exits 0);
  - `.lower()` removed (CI=TRUE exits 0);
  - exit code 1 changed to 0;
  - `trylast` changed to `tryfirst` (`CI=true -m "not pg"` exits 1);
  - skip loop removed (exit 1);
  - Docker probe forced to succeed (exit 1);
  - skip reason changed (wrong reason text);
  - unannotated function (mypy exits 1);
  - Dockerfile digest removed, and `postgres:15` swapped in (static check red for both).
- Robustness (static, testcontainers source): host and port come from Testcontainers; the container is removed with its volumes on normal end, on test failure and on a failed start; Ryuk reaps after a killed session; readiness is checked with `psql` over 127.0.0.1 inside the container, which avoids the init-phase race.

## Commands and counts

- `cd manager && env -u CI pytest -rs`: exit 0, 55 passed, 3 skipped (`not run: Docker unavailable`). `CI=false` and `CI=1` give the same result.
- `CI=true`, `CI=TRUE` and `CI=True` pytest: each exits 1 with the Docker-unavailable message. `CI=true pytest -m "not pg"`: exit 0, 55 passed, 3 deselected.
- ruff check, ruff format --check and `mypy --strict --config-file manager/pyproject.toml manager`: exit 0 (12 files). Coverage gate: exit 0, 100 %.
- Registry (anonymous, read-only): the pin equals today's `postgres:16-bookworm` index digest. It contains amd64 and arm64 with PG 16.15, and PGDG has `postgresql-16-debversion 1.2.0-3.pgdg12+1` for both architectures.

## Acceptance criteria and rows in [tests/m0/report.md](../../tests/m0/report.md)

| Criterion | Check | Result |
| --- | --- | --- |
| REQ-009 (1): `server_version_num` 160000 to 169999; three extensions available | CHK-M0-050 | NOT RUN (Docker; CI) |
| REQ-009 (2): `CREATE EXTENSION debversion`; `'1.0~rc1' < '1.0'` true | CHK-M0-051 | NOT RUN (Docker; CI) |
| REQ-009 (3): container removed at session end | CHK-M0-052 | NOT RUN (Docker; CI); static review OK |
| REQ-009 (4): local run reports "not run: Docker unavailable" | CHK-M0-053 | PASS |
| REQ-009 (4): `CI=true` fails the run | CHK-M0-054 | PASS |
| PD-14 (n): image pinned by digest, debversion installed, no secret | CHK-M0-055 | PASS |
| REQ-004: ruff, format, `mypy --strict` with harness files | CHK-M0-056 | PASS |
| Image builds | CHK-M0-057 | NOT RUN (Docker; CI) |

## Observations for the reviewer (not failures)

1. `postgresql-16-debversion` is installed without an apt version pin. The image is pinned by digest, which is what PD-14 (n) requires. A version pin would break once PGDG drops the old version from `dists`.
2. Nothing in the suite tests the skip and exit hook itself. CI has Docker, so a regression in that hook would go unnoticed there. Suggest a `pytester` test in M1.
3. Only `CI=true` (any case) fails the run; `CI=1` is treated as local. GitHub Actions sets `true`.
4. The Ryuk image is Testcontainers' default tag (`testcontainers/ryuk:0.8.1`), not a digest. PD-14 (n) does not cover it.
