# TASK-036 REVIEW: rate limiter and failed-token-check aggregator

Reviewer: reviewer. Date: 2026-10-21. REQ-047: (1) to (4), (6) and (7). The 429 answers themselves and `X-Forwarded-For` are TASK-037, TASK-038 and TASK-045. Spec: TS §6.3 L1136, TS §2.1 L103, TS §8.1 L1248, L1253. Decisions:
- #50 (a), (c), (e); #54 (b); #55 (c), (e);
- 2026-10-21 "M2 test-plan answers" (1) and (3);
- 2026-10-21 "Lead ruling on #54 (b)": the alert fires at more than 20 per IP per minute, at most once per IP per hour.

Inputs: `work/reports/TASK-036-impl.md`; `work/reports/TASK-036-test.md` (PASS, CHK-M2-140 to -146, 27 tests with a fake clock, 12 of 12 mutations red, including an alert at 20).

File reviewed: `manager/bitscan_manager/api/ratelimit.py`.

Verdict: APPROVED

TASK-036 is not on the TS §8.2 two-approval list. The lead recommends a second look, because these are the failed-token limits.

## What was checked

- **Limits (TS §6.3 L1136).**
  - Sign-in: 10 per IP per minute, and every attempt counts (#55 (c)).
  - Per user: 600 per minute, keyed by `user_id`, so all of a user's tokens share it (REQ-047 (2)).
  - Failed token checks: blocked once 20 are recorded, so the 21st request onward gets 429. Valid tokens are never recorded or blocked: the module only counts what the caller records.

  Windows are fixed UTC minutes from the TASK-025 `Clock`. One `threading.Lock` guards all state. Everything is in memory (one instance, TS §2.1).
- **User decision (3).** A request answered 429 is still recorded, so it counts in the aggregate and the alert (20 × 401 plus 5 × 429 gives `count` 25). Decision (1), an admin's `bsk_` with no TOTP not being counted, belongs to the caller in TASK-037; this module has no way to count it by itself.
- **Aggregation (REQ-047 (4)).** `drain()` returns one entry per (IP, finished minute) with at least one failure, and removes it, so a repeat drain returns nothing. The action is `auth.token_check_failed` (#50 (a)) and `detail` is `{ip, window_start, count}` (#50 (e)), with no token. `final=True` also flushes the current minute, for the shutdown flush (REQ-057 (6)). The once-a-minute writer is TASK-045.
- **Alert (#54 (b) and the lead's ruling).** `alert = count > 20` and no alert for that IP in the preceding hour (`ratelimit.py:101-103`). A count of exactly 20 does not alert, and 21 does; the mutation "alert at 20" is red.
- **Expiry (REQ-047 (7)).** `drain()` prunes earlier minutes' sign-in and per-user keys and alert stamps an hour old. `size()` exposes the count for tests.
- **`Retry-After` (#55 (e)).** Whole seconds to the end of the window, from 1 to 60.
- **Gates (my run).** ruff, format and `mypy --strict` are clean, `test_ratelimit.py` passes, and a `RateLimiter` type-checks as `runtime.RateLimits`.
- **Scope.** 1 file, about 110 lines.

## Findings

None block approval.

1. **note, the tester's point, accepted.** The once-per-hour suppression compares window starts in `drain()` (`start - last >= ALERT_EVERY`), not wall-clock instants. If drains are delayed, the gap between alerts is still measured on the minutes the failures happened, which is the more faithful reading of "one alert per IP per hour". The pruning at `:110-113` uses the current window. A stamp is therefore dropped only once it is an hour older than the current minute, and since any minute still waiting to be drained is newer than that, no suppression is lost.
2. **should be checked in TASK-045: memory under attack.** `_failed` keys are pruned only by `drain()`. Between drains, a flood from many source IPs grows `_failed`, `_login` and `_user` without bound, by one key per IP per minute. With the once-a-minute flusher that is bounded by one minute of distinct IPs, which is acceptable. If the flusher stops (an exception, or a DB outage while writing), the dicts grow until the next successful drain. TASK-045 must drain, and so prune, even when the audit write fails: drain first, then write, keeping unwritten entries in a bounded list or logging their count.
3. **nit.** `drain()` sorts every key under the lock. With 10,000 IPs that is a few milliseconds per minute, which is fine.
