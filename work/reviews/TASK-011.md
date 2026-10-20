# TASK-011 REVIEW: runtime database dependencies (Alembic, SQLAlchemy, psycopg 3)

Reviewer: reviewer. Date: 2026-10-20. REQ-018. Spec: TS §5.3 L1046 (Alembic), TS §8.2 L1264 (`pip --require-hashes`), TS §8.1 L1258 (hashed Python dependencies); PD-14 (i). Inputs: `work/tasks.md` TASK-011, `work/reports/TASK-011-impl.md`, `work/reports/TASK-011-test.md` (PASS), `tests/m1/report.md` CHK-M1-001 to -007, `work/decisions.md` 2026-10-20 (bundled libpq; LGPL and advisory notes).

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268): this is manager dependency config, not importer, auth, agent or runner code.

## What was checked (my own runs)

- **Scope:** the 3 listed files. `pyproject.toml` adds `alembic>=1.13`, `sqlalchemy>=2.0` and `psycopg[binary]>=3.2` to the runtime dependencies and removes `psycopg[binary]` from `dev`. Nothing else changed. The locks are generated.
- **Reproducibility (REQ-018 (4)):** I regenerated both locks in a temp directory with the recorded header command, cutoff `--exclude-newer 2026-10-19T16:56:37Z`. Both bodies are byte-identical to the committed files.
- **Pins:**
  - the 16 existing runtime pins are unchanged, including the `annotated-doc` hash;
  - the runtime lock adds `alembic 1.20.0`, `sqlalchemy 2.1.5`, `mako 1.4.3`, `markupsafe 3.0.4`, `psycopg 3.3.6` and `psycopg-binary 3.3.6`;
  - the dev lock goes from 49 to 53 entries;
  - all entries are pinned and hashed, the `--only-binary :all:` line is kept, and every source is PyPI.
- **Install (REQ-018 (1)-(3)):**
  - a fresh `python -I -m venv` with bundled pip, then `pip install --require-hashes -r manager/requirements.txt`, exits 0;
  - `import alembic, sqlalchemy, psycopg, fastapi, re2` works: 1.20.0, 2.1.5, 3.3.6, `pq.__impl__ = binary`, `pq.version() = 180004`;
  - the runtime venv has no pytest, ruff, mypy, testcontainers, coverage or hatchling.
- **Linux wheels, checked by pip itself:** `pip download --require-hashes --only-binary :all:` of the runtime lock for the manylinux x86_64 and aarch64 tags exits 0. That covers `psycopg_binary`, `sqlalchemy` and `markupsafe` wheels for both architectures. The tester ran the real Linux x86_64 install in WSL (CHK-M1-001).
- **Gates (REQ-018 (5)):**
  - `ruff check` and `ruff format --check` are clean;
  - `mypy --strict --config-file manager/pyproject.toml manager` reports no issues in 13 files;
  - `pytest --cov=bitscan_manager/services --cov-fail-under=85` gives 66 passed and 3 skipped (pg), and the gate is reached.
- **Test quality:** `test_runtime_lock_has_the_database_stack` asserts that alembic, sqlalchemy 2.x, psycopg 3.x and psycopg-binary are present at the same version, with psycopg listed once. A planted removal of alembic turns it red (tester).
- **Licenses of the new packages:**
  - alembic, SQLAlchemy and Mako are MIT; MarkupSafe is BSD-3-Clause;
  - psycopg and psycopg-binary are LGPL-3.0-only;
  - psycopg-binary bundles libpq, libssl and libcrypto (OpenSSL 3).

## Findings

1. **nit (recorded in `work/decisions.md`).** psycopg and psycopg-binary are LGPL-3.0-only. This is fine for an imported library. The owner should confirm it is acceptable for how Bitscan is distributed.
2. **nit (recorded for M4).** psycopg-binary's bundled libpq and OpenSSL get security fixes only through a re-lock. The M4 SBOM and release check should watch psycopg-binary advisories (`work/decisions.md`, bundled-libpq decision).
3. **note.** The real aarch64 install is NOT RUN, because there is no arm64 host. The pip wheel-hash check for aarch64 passes (mine and CHK-M1-003).
