# TASK-153 REVIEW: M7 alert kinds, import-failure counter, importer alert builders

Verdict: APPROVED (revision 4)

Reviewer: reviewer-m7, 2026-10-27. REQ-162, REQ-165, REQ-166, REQ-167, REQ-168. High risk (importer; TS §8.2 two approvals: this is the first; r4 goes into the same W2 batch).

Scope reviewed: per `work/reports/TASK-153-impl.md` (rounds 1 to 4), the `git diff` of these files:
- `manager/bitscan_manager/services/audit/alerts.py` (+12);
- `manager/bitscan_manager/services/audit/metrics.py` (+14);
- the new `manager/bitscan_manager/services/importer/alerts.py`.

Also the tester's pin changes in `test_alerts.py`, `test_thresholds.py` and `test_metrics_api_pg.py`. The size was kept as one task by the lead and is not a finding.

TEST: PASS, rounds 1 to 4 (`work/reports/TASK-153-test.md`).
- Round 1: 51 unit tests; 12 plants red.
- Round 2: the long-name rows, unit and PostgreSQL; the "cut removed" plant turned 6 red.
- Round 3: `reason`; the "reason dropped" plant turned it red.
- Round 4: `removed_leftovers`, in order, storable and required; 59/59 plus 2/2 on PostgreSQL. The plants "always `[]`", "sorted" and "not through `_storable`" all turned it red.
- The tester restored the accidentally truncated `test_import_alerts.py` byte for byte before adding the rows. It runs 59 tests here.

Re-run by me on Windows: `tests/test_import_alerts.py` 59 passed; ruff, ruff format and `mypy --strict --config-file manager/pyproject.toml manager` are clean (274 files).

REQ-162 (4) and (5), rollback and the sink, run at TASK-154 and G60 as planned.

Spec read: TS §8.4 L1287–L1291; §5.2 `audit_log` DDL; §5.3; #20, #23, #100 (widened), #101, #103; decisions 2026-10-27 L213–L214 (crash window: a rebuild removes leftovers and lists them).

## Checks
1. **Kinds and metric (#101).** The six M7 kinds; a move is not an alert; `bitscan_import_failures_total{mode}` covers the three modes, is exported from zero and is counted on commit only. Unknown kinds are still refused.
2. **Delivery (TS §8.4 L1289, §5.3).** Every alert goes through `raise_alert` and the chain, is counted on commit, and nothing logs.
3. **"Policy imported" alert (#100).** Each `changed_executes` item is `{plugin_uuid, plugin_name, execute, execute_sha256, reason, flags}`, with `execute` in full. Only commands that go live are listed (the store decides).
4. **r4, rebuild alert.** `rebuilt()` now requires `removed_leftovers`. These are the `uploaded/` files of deleted policies that the rebuild removed (L214), kept in the given order and passed through `_storable`. It is a list in the `policy_rebuilt` detail, so the alert shows every leftover removed. The target is still `task:<uuid>`.
5. **Targets (TS §5.2).** `policy:<id>`, `task:<uuid>`, null, or the rejected file name cut to 255 characters (round 2).
6. **Changed pins.** No M2 or M3 guarantee is loosened.

## Findings
1. should-fix (round 1), `services/importer/alerts.py:146`: the fallback target of `rejected()` could exceed `audit_log.target VARCHAR(255)`. **Closed by round 2** (`name[:TARGET_MAX]`; builder checklist 16).
2. nit, `_storable`: it is applied to paths only. `policy_name` and `execute` come from strict UTF-8 XML; correct as written.
3. nit: `policy.import_refused` (#99 (e)) has no builder here. TASK-155 or TASK-162 can build it with `AuditEvent`; checklist 16 applies.
4. Carry to TASK-158: the integrity alert must list leftovers (L214). `integrity_failed` takes `Difference(subject, check)`, so a leftover is `subject` = the relative path, `check` = a fixed name. No builder change is needed.
