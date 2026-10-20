# M1 team brief (impl-manager, impl-deploy, tester, tester-b, reviewer)

Written by the lead (`main`). Read `work/m0-brief.md` first; it still applies (decisions, Windows PATH line, ownership, protocol, FINAL). This file only adds what changed for M1. Date: 2026-10-20.

## What we are doing
Milestone M1 (database and audit core), approved by the user: `work/tasks.md` section "M1 database and audit core" (TASK-011 to TASK-022, ten waves), `work/requirements.md` (REQ-018 to REQ-033), plans in `work/plans/TASK-012.md`, `-013`, `-014`, `-019`, `-020`. Branch: `m1-db-audit-core` (branched from `m0-scaffolding`). Never commit or push; the lead commits.

## Decisions since M0 (work/decisions.md, 2026-10-20 rows)
- The TS §5.2 schema ships as five forward-only Alembic migrations (`m0001` to `m0005`), one per PR, split by domain; seeds and the `scan_result` partitions are in the last. The schema-diff test compares the final schema with TS §5.2.
- Lock files are produced with the final command recorded in decisions.md; changing dependencies means regenerating both locks with that command (new `--exclude-newer` cutoff only if a package must move; say so).
- Reorder: this is M1 of M0..M11; compliance work is M7..M11. Do not build anything from M2 on (no sink, no auth, no routes).

## Environment additions since M0
- Docker works only inside WSL2 (Ubuntu 24.04, Docker Engine). PostgreSQL tests (marker `pg`) run there: copy the working tree to `/root/bitscan` (exclude `manager/.venv`, `node_modules`, `__pycache__`), use the venv at `/root/venv` (installed from the hashed dev lock), set `CI=true`, `RYUK_CONTAINER_IMAGE=testcontainers/ryuk:0.8.1@sha256:bf3f74a47dee0acda89aba4b2fc9c7fdcf994a084db02a2d06566f07baae022e`, `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`. Run with `wsl -d Ubuntu-24.04 -u root -- bash <script>` (write the script to a file under `%TEMP%` and call it via `/mnt/c/Users/kaiquan.koh/AppData/Local/Temp/...`; do not inline quotes). After the lock changes, recreate `/root/venv` from the new dev lock.
- On Windows (`CI` unset) the `pg` tests skip with `not run: Docker unavailable`; the coverage gate must pass on the pure unit tests alone.
- The harness refuses subagent writes to report-named files. The tester sends file-ready Markdown for `tests/m1/report.md` and `work/reports/TASK-###-test.md` to `main`, who writes them verbatim; reviewers do the same if their write is refused.

## Rules for this milestone
- SQL only via parameterised queries or `op.execute` of fixed text (no f-strings, no string building; ruff S608 is on). Alembic reads `:word` as a bind parameter: migrations must not contain SQL comments with colons or patterns with `:`; seeds are inserted with bound parameters (REQ plan TASK-018).
- Forward-only: no `downgrade()` anywhere. Migrations are hand-written SQL that reproduces TS §5.2 in order; do not invent columns, indexes or grants; if the spec is silent, message `main` (the planner has numbered the open questions #38 to #45).
- Never log a DSN or password; replace psycopg parse errors that quote the DSN (REQ-019).
- The tester drafts `tests/m1/test-plan.md` first; implementers hand off to `tester` with the report path as in M0.
