# TASK-234 TEST: PASS

Tester: tester-m11, 2026-11-08. Medium risk (standard rigor, plus a plant for each acceptance clause and each REQ-264 rule). REQ-264, REQ-265, REQ-266 and REQ-272 at repository level; #89, #145 (a)–(d); TS §4.3 L552. Code under test: `bm/repositories/scan_reads.py` (sha256 `c65e7a29168e34b4…`), impl-manager-a, `work/reports/TASK-234-impl.md`. Test file (new): `manager/tests/test_scan_reads_pg.py` (21 tests). Plan rows: CHK-M11-105 to -114 ([test plan](../../tests/m11/test-plan.md), "TP-M11-03"). Each test builds its own world in a time window of its own, on a database of the module's own. Expected sets come from a Python oracle over the world description: REQ-264's filters and its order (`created_at` desc, then `scan_id` desc, compared as UUID bytes).

## Runs (W, `/root/m11t`, `CI=true`, `-n 0`, PostgreSQL 16 by Testcontainers)

| Run | Command | Result |
| --- | --- | --- |
| 1 | `pytest tests/test_scan_reads_pg.py` | 17/17 passed, 0 failed, 0 errors, 0 skipped |
| 2 | same, after the `limit=1` keyset walk was added (found by a plant, below) | 21/21 passed, 0 failed, 0 errors, 0 skipped |
| Lint | `ruff check`, `ruff format --check`, `mypy --strict` | clean |

## Report rows (for tests/m11/report.md)

| Check | Command | Result | Evidence |
| --- | --- | --- | --- |
| CHK-M11-105 | `::test_no_filter_newest_first_with_scan_id_tiebreak`, `::test_scan_row_fields` | PASS | 5 scans in the window, in oracle order, including a tie on `created_at` broken by `scan_id` desc. Fields: policy id, name, version; state as stored; `target_kind` agents / tags / all; `resolved_count` = len(`resolved_agents`). |
| CHK-M11-106 | `::test_each_filter_alone_and_all_together`, `::test_date_bounds_inclusive_and_exclusive`, `::test_times_with_any_offset` | PASS | `policy_id`, `agent_id`, `state` (incl. `queued` → none), `created_after` (≥), `created_before` (<), and all together (one scan). A scan at `created_after` is included; one at `created_before` is excluded. A +18:00 instant selects by instant; a naive time raises `ValueError`. |
| CHK-M11-107 | `::test_keyset_limit_2_visits_every_scan_once` (4 filter sets × limit 1 and 2) | PASS | every scan once, in order, with the tie across a page boundary |
| CHK-M11-108 | `::test_agent_filter_matches_the_resolved_list_only` | PASS | a scan whose tag text equals agent A's id (resolved to C only) is not returned for A |
| CHK-M11-109 | `::test_a_deleted_anchor_raises_anchor_gone` | PASS | scan list and host history raise `AnchorGone` for a deleted anchor |
| CHK-M11-110 | `::test_scan_detail` | PASS | policy name; `target` = the request, no `resolved_agents`; a soft-deleted policy's scan still returned; unknown id → None |
| CHK-M11-111 | `::test_scan_jobs_with_hostnames_in_detail_order` | PASS | hostname, then `agent_id` (two hosts named `alpha`), original before retry; every state as stored; an inventory job of a host is not listed |
| CHK-M11-112 | `::test_agent_history`, `::test_decommissioned_agent_history` | PASS | agent A in 3 of 5: exactly those, newest first; `limit=1` visits each once; `agent_exists` true / false; a decommissioned agent's history returned |
| CHK-M11-113 | `::test_select_only_as_bitscan_app` | PASS | every statement starts with SELECT; no write, DDL or row lock (`FOR`); ids are parameters, never in the SQL text |
| CHK-M11-114 | `::test_select_only_as_bitscan_app`, `::test_wrong_grants_would_be_seen` | PASS | every statement is from login role `bitscan_app`; a page reads fine inside a READ ONLY transaction |

## Plants (throwaway copies; log `/root/m11t/logs/plants-234.jsonl`)

13 plants, 13 red.

| Plant | Fault | Red tests |
| --- | --- | --- |
| CHK-M11-406 (a) | order by `scan_id` only | order and keyset (9 failed) |
| CHK-M11-406 (b) | `created_after` exclusive | bounds (6 failed) |
| `created_before` inclusive | `<=` | bounds (2 failed) |
| keyset `<=` | anchor repeated | keyset and host history (5 failed) |
| keyset on time only | tie dropped across pages | `limit=1` keyset walk (1 failed), **after strengthening** |
| agent matched in any target text | `strpos(target::text, …)` | resolved-list-only and filters (3 failed) |
| `policy_id` filter dropped | | filters (1 failed) |
| `state` filter dropped | | filters (1 failed) |
| `AnchorGone` not raised | paging restarts | deleted anchor (1 failed) |
| detail keeps `resolved_agents` | | detail (1 failed) |
| retry listed first | | jobs order (1 failed) |
| deleted policy hidden | `p.deleted_at IS NULL` in the join | detail (1 failed) |
| G1: f-string SQL | a planted `f"SELECT … '{x}'"` in `scan_reads.py` | `ruff check`: S608 (TASK-234 acceptance "G1 is red on a planted f-string") |

The keyset-on-time-only plant survived the first round. At `limit=2`, the two tied scans always fell on the same page. The keyset test now also runs at `limit=1`, and the plant is red.

## Acceptance (TASK-234: "each filter and the keyset return the expected rows in order, the target containment test uses a parameter, a deleted anchor raises AnchorGone, a spy sees SELECT only, and G1 is red on a planted f-string")

Filters and keyset: CHK-M11-105 to -107. Containment with a parameter: CHK-M11-108 and -113 (the id is not in the SQL text). AnchorGone: CHK-M11-109. SELECT only: CHK-M11-113. G1: plant P234-G1-fstring.

## Notes

- `scan_jobs` filters `kind = 'compliance'`. A plant removing that filter would be equivalent, because inventory jobs have `scan_id` NULL (TS §5.2 CHECK), so it was not planted.
