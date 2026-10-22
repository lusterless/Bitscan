# TASK-036 IMPL report: rate limiter and failed-token-check aggregator

REQ: REQ-047 (limits, aggregation, key expiry; the 429 answers themselves are TASK-037/038). Spec: TS §6.3 L1136, TS §2.1 L103 (one instance, in memory), TS §8.1 L1248/L1253. Decisions:
- #54 (b): one alert per IP per hour once it goes over the failed-check limit in a minute.
- #55: (a) and (b) are TASK-038; (c) every sign-in attempt counts; (e) `Retry-After` is the seconds to the end of the window.
- #50: (a) action `auth.token_check_failed`; (c) kind `token_check_failures`; (e) detail `{ip, window_start, count}`.
- User decisions 2026-10-21, "M2 test-plan answers": (3) requests answered 429 by the failed-token limit count toward the aggregate and its alert; (1) an admin's `bsk_` with no TOTP is a genuine token and is never counted.

Second look recommended (not on the two-approval list).

## Files (1)

- `manager/bitscan_manager/api/ratelimit.py`: new, 108 non-blank lines. It is a plain module, not middleware (task owner notes).

## Interface

```python
WINDOW_S = 60; LOGIN_PER_MIN = 10; USER_PER_MIN = 600; FAILED_PER_MIN = 20
ALERT_EVERY = timedelta(hours=1); ACTION = "auth.token_check_failed"

@dataclass(frozen=True)
class FailedChecks:              # one aggregated audit entry
    ip: str; window_start: datetime; count: int; alert: bool; action: str = ACTION
    detail -> {"ip", "window_start": "YYYY-MM-DDTHH:MM:SSZ", "count"}

class RateLimiter:               # implements runtime.RateLimits
    def __init__(self, clock: Clock)
    def allow_login(self, ip) -> bool
    def allow_user(self, user_id) -> bool
    def failed_check_blocked(self, ip) -> bool
    def record_failed_check(self, ip) -> None
    def retry_after(self) -> int
    def drain(self, *, final: bool = False) -> list[FailedChecks]
    def size(self) -> int
```

## Behaviour

- **Windows** are fixed UTC minutes, `floor(clock.now().timestamp()) // 60`, read from the TASK-025 `Clock`, so a fake clock drives every test. All state sits behind one `threading.Lock`, because sync handlers run in a threadpool.
- **`allow_login(ip)`** counts every call, whether the attempt succeeds, fails or was itself refused. The 11th call from one IP in a minute returns `False`. Another IP, or the next minute, starts again from zero.
- **`allow_user(user_id)`** is keyed by user, not token, so all of a user's tokens share it. The 601st call in a minute returns `False`.
- **`record_failed_check(ip)` and `failed_check_blocked(ip)`:** each failed check adds one for the IP's current minute. `failed_check_blocked` is `True` once 20 have been recorded, so the 21st and later bad-token requests get 429. Valid tokens are never recorded and never limited by this.
  - Per the user's decision (3), a request answered 429 because the IP is blocked is still recorded. Its token is not checked, so it is counted as a failure, and it appears in the aggregate count and the alert detail: 20 × 401 plus 5 × 429 gives `count` 25.
  - Decision (1) lives in TASK-037: an admin's `bsk_` with no TOTP is answered 403 `totp_enrolment_required` and is never passed to `record_failed_check`.
- **`retry_after()`** returns whole seconds to the end of the current minute, from 1 to 60. TASK-037/038 put it in `Retry-After` on 429 (#55 (e)).
- **`drain(final=False)`** returns one `FailedChecks` per (IP, finished minute) that had at least one failure, sorted by minute then IP, and removes those counts.
  - The current minute is kept unless `final=True`, which is for the shutdown flush (REQ-057 (6)).
  - A second `drain` returns nothing new. Minutes without failures produce nothing.
- **Alert (#54 (b)).** `alert` is `True` when the minute's `count` is **over** 20 ("passes the 20-per-minute limit", so at least one request was answered 429) and that IP has had no alert whose `window_start` is less than 60 min earlier.
  - The caller writes such an entry with `raise_alert(repo, tx.on_commit, kind="token_check_failures", actor="system", action=entry.action, detail=entry.detail)`. That is still **one** entry for that IP and minute, and its detail carries the count.
  - Otherwise the caller writes it with `append_entry(repo, actor="system", action=entry.action, detail=entry.detail)`.
  - The writer (a once-a-minute flusher and the shutdown flush) is part of `serve` (TASK-045).
- **Key expiry (REQ-047 (7)).** `drain` also deletes sign-in and per-user keys from earlier minutes, and alert timestamps an hour old. `size()` reports the total number of keys held. In the scratch run, 10,000 IPs and users gave 30,000 keys, and 0 after a minute's drain.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 83 files. A `RateLimiter` is accepted where `runtime.RateLimits` is expected |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 835 passed and 2 failed: the 2 were the in-progress `test_vault.py` cases fixed in TASK-030 revision 1, and `test_vault.py` now gives 55 passed. 229 skipped (pg). The coverage gate passes. `api/` is outside G5 |
| Scratch with a fake clock | Sign-in: 10 allowed, the 11th refused, another IP allowed. Per user: 600 allowed, the next refused, another user allowed. 25 failures from A left A blocked and B not; `retry_after` was 55 at :05. An early drain returned nothing. After the clock moved: A's minute gave `count` 25 with an alert, B's gave 1 without, and A's minute +2 gave 1 without. A repeat drain returned `[]`. 62 min later, a minute with 21 failures alerted, and another 21 in the next minute did not. A final drain included the current minute. `retry_after` was 60 at :00.000 and 1 at :59.5 |

## For the tester (TP-M2-14)

- Drive it with any object that has `now() -> aware datetime`.
- CHK-M2-143: the "emits entries" check maps to `drain()` returning `FailedChecks` with `.action` and `.detail`. The audit write itself belongs to the TASK-045 flusher.
- CHK-M2-144 boundary: 20 failures in a minute raise **no** alert, 21 raise one. The lead confirmed this reading (decisions.md 2026-10-21, "Lead ruling on #54 (b)"): a count over 20, at most once per IP per hour.
