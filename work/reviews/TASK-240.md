# TASK-240 REVIEW: scan views service

Reviewer: reviewer-m11, 2026-11-08. Round 1. One approval (medium risk).

Verdict: APPROVED

Scope reviewed: `manager/bitscan_manager/services/jobs/scan_views.py` (new, 138 lines, the only file).

Checked against:
- TS §6.2 L1113, L1120, L1122; TS §4.5 L602–L604; TS §4.4 L577–L585; TS §4.3 L552.
- REQ-264, REQ-265, REQ-266.
- #119, #120, #145; the M9 interface note on `scan.state`.
- Plan `work/plans/TASK-232.md` §5.

Reports: `work/reports/TASK-240-impl.md`, `work/reports/TASK-240-test.md` (PASS, 39/39 on PostgreSQL 16 in WSL, 9/9 plants red).

## Checks

- **State is stored, not re-derived (M9 note):** the service returns `ScanRow.state` from `scan_reads`, which selects `s.state::text`. The four "derivation would differ" worlds and plant CHK-M11-333 are red as required.
- **Score is M8's (#120, TS §4.5 L604):**
  - The counts come from M8's frozen `results.host_counts`, which gives effective counts with the latest `reeval_id`.
  - The score comes from `score.host_score(passed, failed, errors, not_run)`. Nothing is computed here.
  - A retry joins its original's agent group, so its results count once.
  - The 50-scan agreement with M8's `scores.scan_host_scores()` passes, and plants -332 and -419 are red.
- **One read-only snapshot (REQ-265):** the first statement of `scan_detail`'s transaction is TASK-235's `read_only_snapshot`. The detail, jobs and counts are read inside it. The tester's commit-in-the-middle hook shows the pre-commit counts, and plant -415 is red.
- **Errors:**
  - `ScanNotFound` and `AgentNotFound` are defined here.
  - `AnchorGone` is re-exported, so TASK-244's route needn't import a repository.
  - A decommissioned agent's history is returned, and the plant that hid it is red.
- **Layering and SQL:** there is no SQL in the service. It calls `scan_reads`, `result_reads` and M8 `results`, and imports `score` from the evaluator. It writes nothing and logs nothing, and the tester's spy sees `bitscan_app` SELECT/WITH/SET only. The frozen M8 and M9 files are unchanged.
- **Hosts (#145 (b)):** hosts are ordered by hostname and then `agent_id`, as the repository returns them. A dict keeps that insertion order. Jobs are listed original first, and the target is the request without `resolved_agents`.
- **Re-run (Windows):** `ruff check`, `ruff format --check` and `mypy --strict` on the module and its test file are clean. The PostgreSQL suite runs only on Linux, so I relied on the tester's WSL run.

## Findings

None.
