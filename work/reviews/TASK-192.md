# TASK-192 REVIEW: idempotency store (pure, in memory)

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-222 (1)–(3). High risk, full rigor. Not a PD-39 task.

Scope reviewed, per `work/reports/TASK-192-impl.md`: one new file, `manager/bitscan_manager/api/user/idempotency.py` (143 lines).

TEST: PASS (`work/reports/TASK-192-test.md`). 34/34 on Linux (W) and Windows (L). Plants CHK-M9-367 (a, b), -388 and -389 are red. Threads are ordered by barriers and events, with no sleeps (decisions 2026-10-26).

Spec read: TS §6.3 L1135, §6.4 L1149, §2.1 L103; #123.

My re-run: 34/34 on Windows (in the 144-test run with `test_cron.py`). ruff and `mypy --strict` are clean.

## Checks
1. **#123 (a), the key.** 1–255 printable ASCII characters, checked before the lock or `call()`. The message is fixed.
2. **#123 (b)–(e), scope, TTL, repeat and reuse.** Entries are keyed by user and key and kept for 24 h. When full at 100,000, expired entries and then the oldest are dropped. A repeat with the same parsed body (canonical JSON, keys sorted) returns the first answer. A different body raises `KeyReused`, which carries the #123 (e) text.
3. **#123 (f), concurrency.** A per-key lock serialises `call()`, so two concurrent identical requests run once (CHK-M9-078). The global guard is held only for dict access, never across `call()`. Lock entries are reference-counted and removed, so the map stays bounded by the number of in-flight keys.
4. **#123 (g), only successes remembered.** An exception from `call()` stores nothing and releases the lock (CHK-M9-077).
5. **No body kept.** Only a 32-byte digest is stored, which bounds memory at about 100,000 × (digest + answer).

## Findings
None blocking or should-fix.

1. nit, `idempotency.py:53-57`: `body_digest` raises a bare `ValueError` on NaN or Infinity (`allow_nan=False`), and `run()` calls it before `call()`. The docstring doesn't mention this. The store itself is correct. **Carried to TASK-205 as a check:** the route must refuse NaN or Infinity (strict model, or `json.loads` with `parse_constant`) before `store.run()`, so it answers 400 and not 500 (builder checklist item 1).
