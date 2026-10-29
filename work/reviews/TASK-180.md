# TASK-180 REVIEW: the `eval_spec` contract

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-195. High risk (evaluator; interface frozen for M9). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-180-impl.md`: one new file, `manager/bitscan_manager/services/evaluator/eval_spec.py` (127 lines).

TEST: PASS (`work/reports/TASK-180-test.md`, tester-m8). 101/101 after r2, all plants red. The tester found and closed a test gap in r2: the quote plant was green until a fixed-message test was added. There's no product defect.

Spec read: TS §4.5 L587, L603; §5.2 L880, L888, L907–L910; §3.5 L248; §6.5 L1165–L1180; SR §2.3; #117.

My re-run on Windows: 216 passed across the four pure-module files. `mypy --strict` and `ruff` are clean.

## Checks
1. **Shape (#117).** `{"plugins": [{plugin_uuid, name, operator, expected}]}` in payload order. `build_eval_spec` can't write `execute` or `timeout_s`, because `PluginSpec` has neither field. So Operator and ExpectedResult stay in `eval_spec` (manager-only, TS L880, security invariants) and nothing here goes into the agent payload (CHK-M8-114 key walk; -345 red).
2. **Strict parse.**
   - Exact key sets at both levels, and only `str` values (a `bool` and numbers are refused).
   - `plugin_uuid` only in the canonical lowercase hyphenated form (`str(UUID(v)) == v`).
   - 1–5,000 entries, checked before any entry is parsed.
   - Operator one of the 14, name 1–400 characters (the `VARCHAR(400)` snapshot), expected at most 4,000, and no duplicate uuid (CHK-M8-111, 52 refusals; -344 red).
3. **One rule set.** The value rules live in `EvalSpec.__post_init__`, so anything M9 builds also parses. The index behind `get` is read-only and excluded from `eq` and `repr`.
4. **Errors quote nothing.** Messages are fixed, and the `UUID()` `ValueError` is suppressed (`from None`). CHK-M8-112 checks `str`, `repr`, `args`, `__cause__` and `__context__`.
5. **Totality.** On 2,000 random JSON-like values, `parse_eval_spec` raises only `EvalSpecError` (CHK-M8-116).
6. **Purity (REQ-202).** The imports are stdlib, `evaluator.model` and `importer.model` only.

## Findings
None blocking or should-fix.

1. nit (confirmed, no change): an empty `expected` is accepted for every operator. That matches #117, which gives 0–4,000, and the importer (BIT014 refuses empty for non-presence operators at import). This answers the note in my TASK-177 review.
2. Carried to M9 (the tester's note): `parse_eval_spec` accepts a lone surrogate or U+0000 in `name` or `expected`. JSONB refuses both on write, so M9's job builder must stop them before the insert to avoid a 500 (builder checklist item 1). They can't come from the catalog today.
