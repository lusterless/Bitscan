# TASK-188 REVIEW: scan targets (pure)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-208 (1), (2), (4). High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-188-impl.md`: one new file, `manager/bitscan_manager/services/jobs/targets.py` (110 lines).

TEST: PASS (`work/reports/TASK-188-test.md`). 73/73 in r1. The single r0 failure was a test bug (one tag over 64 characters). Plants CHK-M9-392, -392a and -392b are red.

Spec read: TS §4.4 L555, §5.2 L850, L865, §6.4 L1151; #122 (b)–(d), #68; decisions 2026-10-30 "M9 early rulings" (1) and (3).

My re-run (Windows): `test_scan_targets.py` passes in the combined run with `test_job_build.py`. ruff and ruff format are clean on `services/jobs/`.

## Checks
1. **Exactly one form (TS §4.4 L555).** The target must be a `dict` with exactly one key from `agents`, `tags` and `all`. `all` must be `True` itself, so `1`, `"true"` and `false` are refused.
2. **Limits (#122 (b)).**
   - Agents: 1–10,000, in the hyphenated 8-4-4-4-12 form only. Every character is checked, so the 32-hex, braced, `urn:` and `_` forms that `UUID()` or `int()` would take are refused (builder checklist item 5).
   - Agents are distinct by value, so a case variant counts as a duplicate (ruling (3)).
   - Tags: 1–32, each 1–64 characters by the #68 rule, distinct.
3. **Fixed messages (builder checklist item 12).** `InvalidTarget` carries one of four fixed strings, each naming `target`. No input appears in `str`, `repr` or `args` (CHK-M9-028).
4. **Stored value (#122 (d)).** It is the request (agent ids in lowercase) plus `resolved_agents`, distinct, lowercase and sorted.
5. **Copied tag constants (ruling (1)).** The copies are pinned equal to `services/agents/admin.py` (CHK-M9-032), so drift turns a test red.
6. **Purity.** Stdlib imports only.

## Findings
None blocking or should-fix.
