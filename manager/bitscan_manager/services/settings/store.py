"""Runtime settings (TS §8.6 L1317–L1327; #42, #68).

Seven keys: six in the setting table, inventory_interval_s in system_schedule.
A patch is validated as a whole before anything is written: one bad key
refuses it all. No key disables inventory, and its interval stays within
3,600–86,400 s (TS §3.4 L237, §6.2 L1129).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

import re2  # type: ignore[import-untyped]

from bitscan_manager.services.settings.redaction import removed_defaults

INVENTORY_KEY: Final = "inventory_interval_s"
REDACTION_KEY: Final = "redaction_patterns"
MAX_REDACTION_PATTERNS: Final = 50

# Integer keys and their inclusive ranges, in TS §8.6 table order.
INT_RANGES: Final[Mapping[str, tuple[int, int]]] = {
    "agent_token_ttl_days": (60, 730),
    "job_pull_seconds": (60, 3600),
    "decommission_after_days": (0, 365),  # 0 = never
    "max_parallel_plugins": (1, 8),
    "enrolment_alert_per_hour": (1, 10_000),
    INVENTORY_KEY: (3600, 86_400),
}
# A refused pattern is never written to stderr by RE2 itself.
_RE2_OPTIONS: Final = re2.Options()
_RE2_OPTIONS.log_errors = False

KEYS: Final = (
    "agent_token_ttl_days",
    "job_pull_seconds",
    "decommission_after_days",
    REDACTION_KEY,
    "max_parallel_plugins",
    "enrolment_alert_per_hour",
    INVENTORY_KEY,
)


@dataclass(frozen=True)
class Settings:
    agent_token_ttl_days: int
    job_pull_seconds: int
    decommission_after_days: int
    redaction_patterns: tuple[str, ...]
    max_parallel_plugins: int
    enrolment_alert_per_hour: int
    inventory_interval_s: int

    def as_dict(self) -> dict[str, Any]:
        """The seven keys, in TS §8.6 order (the GET /settings body, #68)."""
        values: dict[str, Any] = {key: getattr(self, key) for key in KEYS}
        values[REDACTION_KEY] = list(self.redaction_patterns)
        return values


class SettingsInvalid(Exception):
    """A patch refused as a whole. key is the offending known key, or None for
    an empty patch or an unknown key (never echoed: the client chose it)."""

    def __init__(self, key: str | None) -> None:
        super().__init__(key or "patch")
        self.key = key


class SettingsUnavailable(Exception):
    """A seeded setting or the inventory schedule row is missing, or a stored
    value does not have its type."""


class SettingsReader(Protocol):
    def read_values(self) -> Mapping[str, Any]: ...

    def schedule_interval(self, job_kind: str) -> int | None: ...


class SettingsStore(SettingsReader, Protocol):
    def lock_settings(self) -> None: ...

    def write_value(
        self, key: str, value: object, updated_by: int | None, now: datetime
    ) -> bool: ...

    def write_schedule_interval(self, job_kind: str, interval_s: int) -> bool: ...


class Alerter(Protocol):  # services.users.TxAudit
    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


def _stored_int(key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsUnavailable(key)
    return value


def read_settings(repo: SettingsReader) -> Settings:
    values = dict(repo.read_values())
    values[INVENTORY_KEY] = repo.schedule_interval("inventory")
    missing = [key for key in KEYS if values.get(key) is None]
    if missing:
        raise SettingsUnavailable(", ".join(missing))
    patterns = values[REDACTION_KEY]
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise SettingsUnavailable(REDACTION_KEY)
    return Settings(
        **{key: _stored_int(key, values[key]) for key in INT_RANGES},
        redaction_patterns=tuple(patterns),
    )


def apply_patch(
    repo: SettingsStore,
    audit: Alerter,
    *,
    patch: Mapping[str, object],
    user_id: int,
    now: datetime,
) -> Settings:
    """Validates the whole patch, then writes it inside the caller's
    transaction (rows locked, so concurrent patches apply one at a time):
    inventory_interval_s to system_schedule, the rest to setting. One
    settings.change entry, alert kind settings_changed, holds the old and new
    values of the patched keys (#71: one entry per event). A TTL change only
    affects tokens issued or rotated later; existing tokens keep their expiry."""
    checked = validate_patch(patch)
    repo.lock_settings()
    before = read_settings(repo).as_dict()
    for key, value in checked.items():
        if key == INVENTORY_KEY:
            written = repo.write_schedule_interval("inventory", _stored_int(key, value))
        else:
            written = repo.write_value(key, value, user_id, now)
        if not written:
            raise SettingsUnavailable(key)
    after = read_settings(repo)
    new = after.as_dict()
    audit.alert(
        "settings_changed",
        f"user:{user_id}",
        "settings.change",
        "settings",
        {"old": {k: before[k] for k in checked}, "new": {k: new[k] for k in checked}},
    )
    if REDACTION_KEY in checked:  # TS §8.6 L1324: removing a default alerts
        gone = removed_defaults(before[REDACTION_KEY], new[REDACTION_KEY])
        if gone:
            audit.alert(
                "redaction_default_removed",
                f"user:{user_id}",
                "settings.redaction_default_removed",
                "settings",
                {"removed": gone},
            )
    return after


def _compiles(pattern: str) -> bool:
    """A storable pattern that RE2 compiles. U+0000 cannot be stored in jsonb,
    and a lone surrogate cannot be encoded for RE2: both are refused first."""
    if "\x00" in pattern:
        return False
    try:
        pattern.encode("utf-8")
        re2.compile(pattern, _RE2_OPTIONS)
    except (UnicodeEncodeError, re2.error):
        return False
    return True


def _check(key: str, value: object) -> object:
    if key in INT_RANGES:
        low, high = INT_RANGES[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsInvalid(key)
        if not low <= value <= high:
            raise SettingsInvalid(key)
        return value
    # redaction_patterns: at most 50 strings, each compiled with RE2 before
    # it is saved (TS §8.6 L1324). The removed-default alert is REQ-084.
    if (
        not isinstance(value, list)
        or len(value) > MAX_REDACTION_PATTERNS
        or not all(isinstance(p, str) and _compiles(p) for p in value)
    ):
        raise SettingsInvalid(key)
    return list(value)


def validate_patch(patch: Mapping[str, object]) -> dict[str, object]:
    """The checked patch, or SettingsInvalid for the whole of it. Pure."""
    if not patch or any(key not in KEYS for key in patch):
        raise SettingsInvalid(None)  # inventory_enabled and any other key
    return {key: _check(key, value) for key, value in patch.items()}
