"""In-memory rate limits and the failed-token-check aggregator (TS §6.3 L1136;
#54, #55; decisions 2026-10-21 "M2 test-plan answers" (3)).

One manager instance (TS §2.1), so state lives in this process. Windows are
fixed UTC minutes read from the Clock. Limits: sign-in 10 per IP (every
attempt counts), 600 requests per user, 20 failed token checks per IP. Every
failed check counts, including requests answered 429 because the IP is
already over the limit. Valid tokens are never counted or blocked.
"""

import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from bitscan_manager.runtime import Clock

WINDOW_S: Final = 60
LOGIN_PER_MIN: Final = 10
USER_PER_MIN: Final = 600
FAILED_PER_MIN: Final = 20
ALERT_EVERY: Final = timedelta(hours=1)  # #54 (b): one alert per IP per hour
ACTION: Final = "auth.token_check_failed"  # #50 (a)


@dataclass(frozen=True)
class FailedChecks:
    """One aggregated audit entry: action, and detail per #50 (e). alert is
    True when the IP went over the limit in that minute and has had no
    alert in the hour before (#54 (b)); the caller then writes the entry
    with raise_alert(kind="token_check_failures")."""

    ip: str
    window_start: datetime
    count: int
    alert: bool
    action: str = ACTION

    @property
    def detail(self) -> dict[str, object]:
        start = self.window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"ip": self.ip, "window_start": start, "count": self.count}


class RateLimiter:
    """Implements runtime.RateLimits, plus retry_after(), drain() and size()."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._login: dict[str, tuple[int, int]] = {}  # ip -> (window, count)
        self._user: dict[int, tuple[int, int]] = {}
        self._failed: dict[tuple[str, int], int] = {}  # (ip, window) -> count
        self._last_alert: dict[str, datetime] = {}

    def _window(self) -> int:
        return math.floor(self._clock.now().timestamp()) // WINDOW_S

    @staticmethod
    def _bump[K](table: dict[K, tuple[int, int]], key: K, window: int) -> int:
        seen, count = table.get(key, (window, 0))
        count = count + 1 if seen == window else 1
        table[key] = (window, count)
        return count

    def allow_login(self, ip: str) -> bool:
        with self._lock:
            return self._bump(self._login, ip, self._window()) <= LOGIN_PER_MIN

    def allow_user(self, user_id: int) -> bool:
        with self._lock:
            return self._bump(self._user, user_id, self._window()) <= USER_PER_MIN

    def failed_check_blocked(self, ip: str) -> bool:
        with self._lock:
            return self._failed.get((ip, self._window()), 0) >= FAILED_PER_MIN

    def record_failed_check(self, ip: str) -> None:
        with self._lock:
            key = (ip, self._window())
            self._failed[key] = self._failed.get(key, 0) + 1

    def retry_after(self) -> int:
        """Whole seconds until the current window ends (1 to 60), for 429."""
        now = self._clock.now().timestamp()
        return max(1, math.ceil(WINDOW_S - now % WINDOW_S))

    def drain(self, *, final: bool = False) -> list[FailedChecks]:
        """Take the aggregated entries for every finished minute (and the
        current one too when final, for shutdown), and drop expired keys."""
        with self._lock:
            current = self._window()
            out: list[FailedChecks] = []
            for ip, window in sorted(self._failed, key=lambda k: (k[1], k[0])):
                if window >= current and not final:
                    continue
                count = self._failed.pop((ip, window))
                start = datetime.fromtimestamp(window * WINDOW_S, UTC)
                last = self._last_alert.get(ip)
                alert = count > FAILED_PER_MIN and (
                    last is None or start - last >= ALERT_EVERY
                )
                if alert:
                    self._last_alert[ip] = start
                out.append(FailedChecks(ip, start, count, alert))
            now = datetime.fromtimestamp(current * WINDOW_S, UTC)
            self._prune(self._login, current)
            self._prune(self._user, current)
            for ip in [
                i for i, t in self._last_alert.items() if now - t >= ALERT_EVERY
            ]:
                del self._last_alert[ip]
            return out

    @staticmethod
    def _prune[K](table: dict[K, tuple[int, int]], current: int) -> None:
        for key in [k for k, (window, _) in table.items() if window < current]:
            del table[key]

    def size(self) -> int:
        """Keys held in memory (for tests of REQ-047 (7))."""
        with self._lock:
            return (
                len(self._login)
                + len(self._user)
                + len(self._failed)
                + len(self._last_alert)
            )
