# TASK-184 REVIEW: host scores service

Verdict: APPROVED

Reviewer: reviewer-m8, 2026-10-29. REQ-197 (3), REQ-199. High risk (evaluator; interface for M11). PD-38: one review, full rigor.

Scope reviewed, per `work/reports/TASK-184-impl.md`: one new file, `manager/bitscan_manager/services/evaluator/scores.py` (33 lines).

TEST: PASS (`work/reports/TASK-184-test.md`, tester-m8). 5/5 and 5/5 plants red.

Spec read: TS §2.1 L105; §4.5 L602; §4.4 L579, L583; #120.

My re-run: WSL PostgreSQL gives 60/60 across the three repository and score suites (`test_scores_pg.py` 5 of them). `ruff check` and `mypy --strict` are clean.

## Checks
1. **Computed on read (TS L579, L602).**
   - One `db.transaction()` makes one `host_counts` SELECT. `host_score` then runs outside the transaction, and nothing is stored or cached.
   - A late result and then a re-evaluation each change the next call (CHK-M8-181), and the memoising plant is red.
2. **Values (#120).**
   - The REQ-198 fixture gives the expected `HostScore` per host: None for the all-ERROR host and for the queued host, and 1.0 for the FAIL re-evaluated to PASS.
   - The error count is carried beside the score, and the swap and errors-in-failed plants are red.
3. **SQL and `effective()` agree (REQ-197 (3)).** On 200 seeded random sets, they agree on code, detail, id, version, user and the original. Both ordering plants turn it red.
4. **Layering.** The service calls the repository, with no SQL in the service and no logging. It imports no `api` and no `repositories.catalog*` (CHK-M8-221).

## Findings
None blocking or should-fix.
