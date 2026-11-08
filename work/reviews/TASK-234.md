# TASK-234 REVIEW: scan reads repository

Reviewer: reviewer-m11, 2026-11-08. Round 1. One approval (medium risk).

Verdict: APPROVED

Scope reviewed: `manager/bitscan_manager/repositories/scan_reads.py` (new, 233 lines, the only file), against TS §6.2 L1113, L1120, L1122, §6.3 L1136, §4.3 L552, §5.2 (`scan`, `scan_job`, `policy`, `agent`), REQ-264, REQ-265, REQ-266, REQ-272, #89, #145 (a)–(d), and plan `work/plans/TASK-232.md`. Reports: `work/reports/TASK-234-impl.md` and `work/reports/TASK-234-test.md` (PASS, 21/21 on PostgreSQL 16 in WSL, 13/13 plants red).

## Checks

- **Spec and answers:**
  - Lists are newest first (`created_at DESC, scan_id DESC`), with the keyset `(created_at, scan_id) < anchor`.
  - The cursor holds only the `scan_id`. The anchor's `created_at` is re-read, and a deleted anchor raises `AnchorGone` (#89, #145 (d)).
  - `created_after` is inclusive and `created_before` exclusive (REQ-264).
  - `agent_id` is a JSONB containment test on `target -> 'resolved_agents'` only, with a bound parameter. It uses `str(UUID)`, which matches the lowercase strings `services/jobs/targets.py:109` `stored_target` writes (#145 (a)).
  - Host history reads only the stored target and never `scan_job` (#145 (c)).
  - The detail strips `resolved_agents` in SQL, so the list never leaves the database (#145 (b)).
  - A soft-deleted policy's scan is still returned (TS §4.3 L552, REQ-265 (4)).
  - `state` is `scan.state` as stored and is never derived.
  - Jobs are compliance-only, ordered hostname, `agent_id`, original before retry.
- **SQL and grants:** every statement is a SELECT built from constant `psycopg.sql` fragments with `%(name)s` parameters. There is no string building (S608 is enabled, and the G1 plant was red). There is no row lock, no write and no DDL. The tester's spy saw only `bitscan_app` running SELECTs, and they work inside a READ ONLY transaction.
- **Client values before PostgreSQL casts them (builder checklist 1):** time filters are converted to UTC before binding, so an offset such as `+18:00` that `AwareDatetime` accepts can't fail the `timestamptz` cast. Python overflow at the year 1 and 9999 ends clamps to the same row set, and a naive time raises `ValueError`. `state` is compared as text, so a bad value can't fail an enum cast.
- **Layering:** a repository only. It imports only `psycopg` and the existing `AnchorGone` from `repositories/packages.py`, re-exported so callers map one type to 400. It does not import a service.
- **Scope:** one file. No frozen file, migration or dependency touched.
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` on the module and its test file are clean. The PostgreSQL suite is Linux-only (testing rule), so I relied on the tester's WSL run. The tests compare against a Python oracle built from the world description, not against the module. The one first-round survivor (a keyset on time only) was closed with a `limit=1` walk.

## Findings

None.
