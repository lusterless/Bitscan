# TASK-192 TEST: PASS

Tester: tester-m9, 2026-10-30. Full rigor (idempotency store, high risk). REQ-222 (1)–(3); TS §6.3 L1135, §6.4 L1149, §2.1 L103; #123. Code under test: `bm/api/user/idempotency.py` (impl-manager-m9, `work/reports/TASK-192-impl.md`; sha256 `157f93abee143589…`). Its interface (`IdempotencyStore[T](clock).run(user_id, key, body, call)`, `check_key`, `body_digest`, `InvalidKey`, `KeyReused`) is new; no plan fixed one. Test file (new): `manager/tests/test_idempotency.py`. Plan rows: CHK-M9-075 to -079. A fake clock is used, and threads are ordered only by `Barrier` and `Event`, each wait bounded at 10 s; there are no sleeps.

## Runs

| Run | Command (W, `/root/bstest-m9-base`, `/root/venv-m9`, `CI=true`, `PYTHONPATH` pinned, `-n 0`) | Count |
| --- | --- | --- |
| r1 | `pytest tests/test_idempotency.py` | **34/34 passed**, 0 failed, 0 errors, 0 skipped |
| r1-L | same on Windows (part of the M9 unit set run) | 34/34 passed |
| plants | 4 plants in `/root/bstest-m9-mut-<id>` | 4/4 red |
| static (L) | ruff, ruff format, mypy --strict | clean |

## Report rows (for tests/m9/report.md)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M9-075 | CODE | W, L | r1 | PASS | Same user, key and body → the first answer, `call` run once. Another user with the same key → a new answer, which is then remembered for that user. Same key with another body → `KeyReused` with exactly "Idempotency-Key was used with a different request.", and the first answer is still remembered. Bodies are compared after parsing: key order is ignored, but list order matters, and `1`, `1.0` and `true` stay distinct. The digest is 32 bytes | 2026-10-30 |
| CHK-M9-076 | CODE | W, L | r1 | PASS | At first + 24 h − 1 s: remembered. At first + 24 h + 1 s: `call` runs again. Once expired, the key takes another body. `TTL` 24 h, `MAX_ENTRIES` 100,000, `KEY_MAX` 255. **Recorded:** exactly 24 h is still remembered (`>` TTL expires) | 2026-10-30 |
| CHK-M9-077 | CODE | W, L | r1 | PASS | A first refusal (raised from `call`) is not remembered; the same key and body then run `call`. Three raising calls in a row leave the per-key lock free (a second thread completes within the bound). A refused body does not block another body on the same key | 2026-10-30 |
| CHK-M9-078 | CODE | W, L | r1 | PASS | REQ-222 (2): two threads at a barrier, the same user, key and body, `call` held on an event → `call` runs once and both threads get the same answer object. The lock is per key: while user 1's key A is held, user 1's key B and user 2's key A both complete. A repeat with another body that waits behind the first gets `KeyReused` once the first commits | 2026-10-30 |
| CHK-M9-079 | CODE | W, L | r1 | PASS | Accepted keys: `a`, 255 × `x`, `abc-123_~!`, `~`, `!`. Refused (`InvalidKey`, before `call` runs): `""`, 256 characters, NUL, U+001F, U+007F, LF, TAB, CR, `é`, an emoji. The message is fixed. Capacity: 100,000 entries are kept; the 100,001st drops the oldest stored (k0), while k1 and k99,999 are still remembered (a hit stores nothing); with `max_entries=3` the 4th drops the 1st. **Recorded:** a space inside a key, and a key that is a single space, are accepted (0x20 is printable ASCII) | 2026-10-30 |
| CHK-M9-367 | CODE | W | plants: (a) the body digest not compared; (b) the per-key lock replaced by a fresh lock per call | PASS (red) | (a) 3 failed: `test_same_key_other_body_is_a_conflict`, `test_bodies_are_compared_after_parsing`, `test_a_waiting_repeat_with_another_body_gets_the_conflict`. (b) 2 failed: `test_two_concurrent_identical_requests_run_once` (`call` runs twice), `test_a_waiting_repeat_with_another_body_gets_the_conflict` | 2026-10-30 |
| CHK-M9-388 | CODE | W | plant: entries never expire | PASS (red) | 2 failed: `test_kept_for_24_hours_then_forgotten`, `test_expired_key_can_take_another_body` | 2026-10-30 |
| CHK-M9-389 | CODE | W | plant: a refused first request is remembered and replayed | PASS (red) | 3 failed: `test_a_refused_first_request_is_not_remembered`, `test_a_failing_call_releases_the_key_lock`, `test_a_refused_body_does_not_block_another_body` | 2026-10-30 |

## Acceptance (TASK-192 row: "Unit with a fake clock and two threads: REQ-222 (1)–(3) hold")

- (1) → CHK-M9-075 to -077. (2) → CHK-M9-078. (3) → CHK-M9-079 (and through the API: CHK-M9-245, tester-m9b).

## Notes for TASK-205 (tester-m9b) and the reviewer

- **`body_digest` raises `ValueError` on a NaN body** (`allow_nan=False`; recorded by `test_body_digest_nan_is_recorded`). Python's `json.loads` accepts `NaN`. If the route calls `store.run()` before its strict body model has refused the body, `{"policy_id": 1, "target": {"agents": [NaN]}}` with an `Idempotency-Key` could answer 500 instead of 400. Please check the order in `api/user/scans.py`.
- The store remembers whatever `call()` returns. Only a 202 should be remembered, so the route must raise for every refusal and return only after its transaction commits (as the impl report says).
- `check_key` accepts spaces. A header value with leading or trailing spaces is trimmed by HTTP parsers, so a key of only spaces may arrive as `""` and be refused.
