# TASK-206 REVIEW: schedule routes CRUD `/scan-schedules`

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-212 (1), REQ-224. High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-206-impl.md`:
- `manager/bitscan_manager/api/user/scan_schedules.py` (new, 212 lines);
- `manager/bitscan_manager/api/user/__init__.py` (+2);
- `manager/openapi.json` (re-exported; the current sha256 `74182d35…` is the one TASK-207 was generated from).

TEST: PASS (`work/reports/TASK-206-test.md`). 22/22 after a test fix (an idle session), and the role and extra-keys plants are red. G6 and G34 are green in the 622/622 security run.

Spec read: TS §6.2 L1084, L1124, §6.3 L1133–L1138, §4.4 L557, §4.3 L550, §5.2 L846–L857, L864; #122 (h), (i), #128 (d), (i), #129 (a).

My re-run (Windows): `ruff check`, `ruff format --check` and `mypy --strict` are clean on `manager/bitscan_manager`.

## Checks
1. **RBAC (TS §6.2 L1124, #122 (i)).** Operator on all five operations, GET included. A viewer gets 403, `bsa_` and no token get 401, and any operator may change any schedule (CHK-M9-257). None is a sensitive action, so `bsk_` is accepted.
2. **No command text (REQ-212 (1)).** Both bodies are `extra="forbid"` with strict types. `execute`, `plugins`, `command`, `payload` and `eval_spec` get 400, and `policy_id` can't be patched. A schedule holds only a policy id, target, cron, zone, name and enabled flag.
3. **Ids and cursor (builder checklist item 1).** A path id is digits only, and anything over `bigint` is 404 before the SQL. The cursor is decoded for this list's scope and range-checked. The `policy_id` bound is 2^53 − 1 (checklist item 3).
4. **Layering and errors.** The handlers call `schedules_admin` only and import no repository. Each change is one transaction that wakes the sink on commit. A refusal rolls back (no audit entry) and maps to a fixed-text problem naming the field (checklist item 12).
5. **Contract.** `ScheduleItem` has exactly the #122 (h) ten keys, with timestamps as RFC 3339 UTC `Z`. List pages are `{items, next_cursor}`.

## Findings
None blocking or should-fix.
