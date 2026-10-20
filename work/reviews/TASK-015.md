# TASK-015 REVIEW: migration `m0002` (fleet and inventory)

Reviewer: reviewer. Date: 2026-10-20. REQ-022, REQ-029. Spec: TS §5.2 L709-825, TS §7.2 L1219 (debversion; test against `dpkg --compare-versions` on at least 500 pairs), TS §6.2 (tokens stored as hashes), TS §5.3 L1046. Inputs: `work/plans/TASK-014.md` (split table row `m0002_fleet_inventory`), `work/reports/TASK-015-impl.md`, `work/reports/TASK-015-test.md` (PASS; WSL, `CI=true`, 318 passed), `tests/m1/report.md` CHK-M1-080 to -084, -100, -101, -103 to -106, -050-r3; `work/decisions.md` 2026-10-20 (REQ-029 (2) ruling).

Verdict: APPROVED

One approval is enough here (TS §8.2 L1268).

## What was checked

- **Verbatim against the spec, by my own script.**
  - Method: TS L709-825 read from the spec file; each `--` comment outside string literals removed, plus trailing whitespace and blank lines; then compared line by line with the joined `STATEMENTS` (15 statements).
  - Result: 106 lines, identical. Only comments were removed.
  - That covers the type `agent_status` (labels in spec order), the nine tables, and the five indexes:
    - `ix_agent_status ON agent(status, last_heartbeat_at)`;
    - `ix_agent_hostname_trgm` and `ix_package_name_trgm` (GIN `gin_trgm_ops`);
    - `ix_package_name_debver ON package (name, (version::debversion))`;
    - `ix_agent_package_pkg`.
- **Token and machine-id columns** (as the spec writes them):
  - `agent.token_hash`, `enrollment_token.token_hash` and `enrollment_request.new_token_hash` are `CHAR(64) NOT NULL UNIQUE`;
  - `agent.prev_token_hash` is a nullable `CHAR(64)` (the rotation grace period);
  - `agent.machine_id` is `CHAR(32) NOT NULL UNIQUE`; `enrollment_request.machine_id` is `CHAR(32) NOT NULL`;
  - no column can hold a raw token: the tester's catalog scan (CHK-M1-081) finds that every token text column is a `*token_hash` `character(64)`.
- **`::debversion` survives bind handling:**
  - `text(stmt).compile(dialect=postgresql.psycopg)` returns the index statement unchanged, `(version::debversion)`;
  - 0 bind parameters over all 15 statements; no `%`, f-strings or `.format`;
  - the tester's bind-trap scanner (CHK-M1-059) is green.
- **Nothing extra:**
  - no grants, seeds (`INSERT`), `SET ROLE`, `RESET` or `search_path`, and no index beyond the spec's five plus the PK and UNIQUE constraints;
  - `system_schedule` and `setting` are absent (they belong to m0004, plan split table).
- **Forward-only:** `revision = "m0002"`, `down_revision = "m0001"`, and `downgrade()` only raises `NotImplementedError`.
- **E501 `noqa`:** the only line over 88 characters is the 110-character `CREATE TYPE agent_status …` line (`m0002_fleet_inventory.py:15`). The `noqa` sits after that literal's closing quotes (line 16), so it covers only that literal.
- **Behaviour on real PostgreSQL** (tester's WSL run, written from the spec before the migration was read):
  - diff-equal to the reference database (CHK-M1-080);
  - `max_uses` limits, defaults and `uses <= max_uses`; `kind` and `decision` sets (CHK-M1-082, -083);
  - `ON DELETE RESTRICT` checked through `pg_constraint.confdeltype = 'r'`, because RESTRICT and NO ACTION share a SQLSTATE; agent cascades (CHK-M1-083);
  - package identity, and the index definitions from `pg_indexes` (CHK-M1-084);
  - `EXPLAIN` uses `ix_package_name_debver` (CHK-M1-105);
  - 7 mutations of m0002 each turn a test red.
- **Gates:** ruff and format are clean, and `mypy --strict` reports no issues in 28 files (tester).

## Rulings

1. **REQ-029 (2): dpkg on the pg host instead of inside the container. I agree with the lead.**
   - TS §7.2 asks for a unit test of the `debversion` comparison against `dpkg --compare-versions` on at least 500 pairs. It does not say where dpkg runs.
   - The two halves stay independent and real:
     - dpkg 1.22.6 on the host checks every recorded relation (CHK-M1-101, 1275/1275);
     - the extension inside the PostgreSQL 16 container is checked against the same fixture (CHK-M1-103, 0 mismatches);
     - a flipped fixture row turns both red (G21 plant).
   - The dpkg comparison algorithm is the same in Debian 12's and Ubuntu 24.04's dpkg for these inputs, so the host choice does not weaken the oracle.
2. **The fixture is acceptable.** `tests/fixtures/debversion_pairs.tsv` holds 1275 pairs, every unordered pair of 51 curated versions (945 lt, 7 eq, 323 gt). It records the dpkg version in its header and covers:
   - epochs (including `0:1.0` = `1.0`);
   - `~` ordering;
   - revisions with and without;
   - `+` and `.`, letters, leading zeros, and a 12-digit run.

   At least 20 pairs order differently as text (CHK-M1-104). The generator script is outside the tree. That is fine, because CHK-M1-101 re-verifies every pair with dpkg on each pg run.

## Findings

None.
