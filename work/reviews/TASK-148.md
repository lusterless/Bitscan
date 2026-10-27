# TASK-148 REVIEW: catalog repository for imports

Verdict: APPROVED (revision 1)

Reviewer: reviewer-m7, 2026-10-27. REQ-158, REQ-159. High risk (importer; TS §8.2 two approvals: this is the first). **r1 needs a user second approval in the W2 batch.**

Scope reviewed: the new `manager/bitscan_manager/repositories/catalog.py` (155 non-blank lines) and `manager/bitscan_manager/repositories/catalog_plugins.py` (132 after r1), per `work/reports/TASK-148-impl.md`. The split into two files is the lead's (decisions 2026-10-27) and stays one task. The signatures match `work/plans/TASK-151.md` §4.

r1 adds one function for the user's widening of #100 (a), as the lead requested: `retired_among(conn, uuids) -> frozenset[UUID]`.
- It is one parameterised SELECT on `plugin` (`state = 'retired' AND plugin_uuid = ANY(…)`), and needs SELECT only.
- With empty input it sends no query.

TEST: PASS, r0 and r1 (`work/reports/TASK-148-test.md`; 52 tests as `bitscan_app`). These planted faults turned it red:
- CHK-M7-336, an f-string in each file, and again in `retired_among` (r1);
- CHK-M7-375 to -377;
- the D3 `CASE` removed (my request);
- revival without +1, and +1 on every update;
- r1: the `state` filter dropped, and the filter inverted.

The `xmax = 0` variant stayed green, correctly: it is an equivalent mutant.

Spec read: SR §3.1–§3.4, §3.6 steps 1–5; TS §5.2 catalog DDL (`m0001_catalog.py`) and grants (`m0005_privileges_seeds.py` L51–L62); #14, #21, #100 (a) (widened 2026-10-27), #104; D3.

## Checks
1. **SQL.** Every statement is a constant string or a `psycopg.sql` composition of constant identifiers, with values bound as parameters. No `noqa`, and S608 is clean.
2. **Grants.** It needs only SELECT, INSERT and UPDATE on `family`, `policy` and `plugin`, INSERT and DELETE on `policy_plugin`, and USAGE on `policy_policy_id_seq`. No DELETE on `policy`, `family` or `plugin`.
3. **Family (#104 (e)).** `INSERT … ON CONFLICT DO NOTHING RETURNING`, then a SELECT. The row is never updated.
4. **Policy (SR §3.6 step 2; D3; #14).**
   - The lookups take `FOR UPDATE` and include deleted rows.
   - In `update_policy`:
     - the override `CASE` is decided inside the UPDATE (race tested in TASK-150 and TASK-151);
     - `status_overridden` is never written;
     - `version` goes up by 1 only on a hash change or a revival;
     - `deleted_at` is cleared;
     - `updated_at` moves only when a stored column changes.
5. **Plugins (#21).**
   - `ON CONFLICT … DO UPDATE … WHERE (…) IS DISTINCT FROM (…)` returns only inserted or changed rows.
   - "Inserted" is read from a CTE that sees the statement's snapshot.
   - Owner, family and `retired → active` changes count as updated.
   - Batches are 500 rows per statement.
6. **Membership, retire, BIT015 inputs and `retired_among`.**
   - The plugin order is 1-based.
   - Retire follows #104 (b) and never deletes.
   - `owners_of` covers every id in one query.
   - `retired_among` returns exactly the retired ids; the store reads it before the displaced delete (TASK-151 r2).
7. **Re-run by me:** ruff, ruff format and mypy (CI form) are clean on product code. I relied on the tester's WSL runs for PostgreSQL.

## Findings
None blocking or should-fix.

1. nit, `catalog_plugins.py:68`: "inserted" from the snapshot CTE is right only while the catalog lock serialises writers. The module docstring already says the caller holds the lock.
