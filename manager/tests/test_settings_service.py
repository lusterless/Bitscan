"""TASK-055: runtime settings, typed read and whole-patch validation (pure).

Checks CHK-M3-091 to CHK-M3-094 of tests/m3/test-plan.md (TP-M3-09). Expected
values: TS §8.6 L1317-L1339 (keys, defaults, ranges, at most 50 RE2 patterns),
TS §3.4 L237 and §6.2 L1129 (no key disables inventory; interval 1-24 h),
#42 (JSON shapes), #68 (one object of eight keys, a non-empty partial patch),
REQ-083 (2), (3), REQ-088 (2), security invariant "RE2 for every pattern".
The defaults are read from the spec text itself.
"""

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.services import settings as settings_pkg
from bitscan_manager.services.settings import (
    INT_RANGES,
    KEYS,
    Settings,
    SettingsInvalid,
    SettingsUnavailable,
    read_settings,
    validate_patch,
)

ROOT = Path(__file__).resolve().parents[2]
TS = ROOT / "docs" / "spec" / "Technical_Specification.md"
SPEC_RANGES = {
    "agent_token_ttl_days": (60, 730),
    "job_pull_seconds": (60, 3600),
    "decommission_after_days": (0, 365),
    "max_parallel_plugins": (1, 8),
    "enrolment_alert_per_hour": (1, 10_000),
    "inventory_interval_s": (3600, 86_400),
    "max_parallel_jobs": (1, 4),  # owner decision 2026-11-14 (TS §8.6)
}
SPEC_DEFAULTS = {
    "agent_token_ttl_days": 365,
    "job_pull_seconds": 300,
    "decommission_after_days": 7,
    "max_parallel_plugins": 2,
    "enrolment_alert_per_hour": 50,
    "inventory_interval_s": 21_600,
    "max_parallel_jobs": 2,
}
CANARY = "CANARY-5e7f0a1b2c3d4e5f"


def spec_patterns() -> list[str]:
    """The five default patterns, verbatim from TS §8.6 (the ```text block)."""
    text = TS.read_text(encoding="utf-8")
    start = text.index("**Default redaction patterns**")
    block = text[text.index("```text\n", start) + len("```text\n") :]
    return block[: block.index("\n```")].split("\n")


DEFAULT_PATTERNS = spec_patterns()


class FakeRepo:
    def __init__(self, values: Mapping[str, Any], interval: int | None) -> None:
        self.values = dict(values)
        self.interval = interval
        self.asked: list[str] = []

    def read_values(self) -> Mapping[str, Any]:
        return self.values

    def schedule_interval(self, job_kind: str) -> int | None:
        self.asked.append(job_kind)
        return self.interval


def seeds() -> dict[str, Any]:
    """The setting rows as #42 seeds them (bare numbers, an array of five)."""
    out: dict[str, Any] = {
        k: v for k, v in SPEC_DEFAULTS.items() if k != "inventory_interval_s"
    }
    out["redaction_patterns"] = list(DEFAULT_PATTERNS)
    return out


def test_spec_patterns_read() -> None:
    assert len(DEFAULT_PATTERNS) == 5
    assert DEFAULT_PATTERNS[2] == r"\bbs[aeku]_[A-Za-z0-9_-]{20,}"


# ------------------------------------------------------------ keys and read


def test_keys_are_the_eight_spec_keys() -> None:
    # TS §8.6 order; max_parallel_jobs: owner decision 2026-11-14.
    assert list(KEYS) == [
        "agent_token_ttl_days",
        "job_pull_seconds",
        "decommission_after_days",
        "redaction_patterns",
        "max_parallel_plugins",
        "max_parallel_jobs",
        "enrolment_alert_per_hour",
        "inventory_interval_s",
    ]
    assert dict(INT_RANGES) == SPEC_RANGES


def test_read_settings_returns_the_defaults_with_interval_from_schedule() -> None:
    repo = FakeRepo(seeds(), 21_600)
    s = read_settings(repo)
    assert repo.asked == ["inventory"]
    assert isinstance(s, Settings)
    assert s.as_dict() == {**SPEC_DEFAULTS, "redaction_patterns": DEFAULT_PATTERNS}
    assert list(s.as_dict()) == list(KEYS)
    for key in SPEC_DEFAULTS:
        assert type(getattr(s, key)) is int


def test_read_settings_takes_the_interval_from_the_schedule_not_setting() -> None:
    values = seeds() | {
        "inventory_interval_s": 99_999
    }  # a stray setting row is ignored
    assert read_settings(FakeRepo(values, 7200)).inventory_interval_s == 7200


@pytest.mark.parametrize("missing", [k for k in KEYS if k != "inventory_interval_s"])
def test_read_settings_refuses_a_missing_row(missing: str) -> None:
    values = seeds()
    del values[missing]
    with pytest.raises(SettingsUnavailable):
        read_settings(FakeRepo(values, 21_600))


def test_read_settings_refuses_a_missing_schedule_row() -> None:
    with pytest.raises(SettingsUnavailable):
        read_settings(FakeRepo(seeds(), None))


# ------------------------------------------------------------ CHK-M3-091


@pytest.mark.parametrize("key", sorted(SPEC_RANGES))
def test_every_integer_key_at_its_bounds(key: str) -> None:
    low, high = SPEC_RANGES[key]
    assert validate_patch({key: low}) == {key: low}
    assert validate_patch({key: high}) == {key: high}


@pytest.mark.parametrize("key", sorted(SPEC_RANGES))
def test_every_integer_key_one_beyond_its_bounds(key: str) -> None:
    low, high = SPEC_RANGES[key]
    for bad in (low - 1, high + 1):
        with pytest.raises(SettingsInvalid) as exc:
            validate_patch({key: bad})
        assert exc.value.key == key


@pytest.mark.parametrize("key", sorted(SPEC_RANGES))
@pytest.mark.parametrize(
    "bad",
    [True, False, 1.5, 300.0, "300", None, [300], {"v": 300}],
    ids=[
        "true",
        "false",
        "float",
        "integral-float",
        "string",
        "null",
        "list",
        "object",
    ],
)
def test_every_integer_key_refuses_wrong_types(key: str, bad: object) -> None:
    with pytest.raises(SettingsInvalid) as exc:
        validate_patch({key: bad})
    assert exc.value.key == key


@pytest.mark.parametrize(
    "unknown",
    [
        "inventory_enabled",
        "inventory_disabled",
        "enabled",
        "inventory",
        "Inventory_Interval_S",
        "inventory_interval_s ",
        "offline_sweep_interval_s",
        "retention_interval_s",
        "",
        CANARY,
    ],
)
def test_unknown_keys_are_refused(unknown: str) -> None:
    with pytest.raises(SettingsInvalid) as exc:
        validate_patch({unknown: True})
    assert exc.value.key is None  # the client's key is never echoed
    assert CANARY not in str(exc.value) and CANARY not in repr(exc.value)


def test_empty_patch_is_refused() -> None:
    with pytest.raises(SettingsInvalid) as exc:
        validate_patch({})
    assert exc.value.key is None


def test_every_key_together_is_accepted() -> None:
    patch: dict[str, object] = {k: v[1] for k, v in SPEC_RANGES.items()}
    patch["redaction_patterns"] = list(DEFAULT_PATTERNS)
    assert validate_patch(patch) == patch


# ------------------------------------------------------------ CHK-M3-092


@pytest.mark.parametrize(
    "patch",
    [
        {"job_pull_seconds": 120, "max_parallel_plugins": 9},
        {"max_parallel_plugins": 9, "job_pull_seconds": 120},
        {"job_pull_seconds": 120, "inventory_enabled": False},
        {"redaction_patterns": [r"(a)\1"], "job_pull_seconds": 120},
        {"agent_token_ttl_days": 365, "inventory_interval_s": 3599},
    ],
)
def test_one_bad_key_refuses_the_whole_patch(patch: dict[str, object]) -> None:
    with pytest.raises(SettingsInvalid):
        validate_patch(patch)


# ------------------------------------------------------------ CHK-M3-093


@pytest.mark.parametrize("value", [3599, 86_401, 0, -1, -21_600, 2**63])
def test_inventory_interval_cannot_leave_one_to_24_hours(value: int) -> None:
    with pytest.raises(SettingsInvalid) as exc:
        validate_patch({"inventory_interval_s": value})
    assert exc.value.key == "inventory_interval_s"


@pytest.mark.parametrize("value", [3600, 21_600, 86_400])
def test_inventory_interval_inside_is_accepted(value: int) -> None:
    assert validate_patch({"inventory_interval_s": value}) == {
        "inventory_interval_s": value
    }


# ------------------------------------------------------------ redaction patterns (RE2)


def test_fifty_patterns_accepted_fifty_one_refused() -> None:
    fifty = [f"secret{i}=\\S+" for i in range(50)]
    assert validate_patch({"redaction_patterns": fifty}) == {
        "redaction_patterns": fifty
    }
    assert validate_patch({"redaction_patterns": []}) == {"redaction_patterns": []}
    with pytest.raises(SettingsInvalid) as exc:
        validate_patch({"redaction_patterns": [*fifty, "x"]})
    assert exc.value.key == "redaction_patterns"


def test_the_five_defaults_compile() -> None:
    assert validate_patch({"redaction_patterns": DEFAULT_PATTERNS}) == {
        "redaction_patterns": DEFAULT_PATTERNS
    }


@pytest.mark.parametrize(
    "bad",
    [
        [r"(a)\1"],  # backreference: not RE2
        [r"(?=a)b"],  # lookahead: not RE2
        [r"(?<=a)b"],  # lookbehind: not RE2
        ["(unclosed"],
        ["ok", 3],
        ["ok", None],
        "a single string",
        {"p": "x"},
        None,
    ],
    ids=[
        "backref",
        "lookahead",
        "lookbehind",
        "unclosed",
        "int-item",
        "null-item",
        "bare-string",
        "object",
        "null",
    ],
)
def test_bad_patterns_are_refused(bad: object) -> None:
    with pytest.raises(SettingsInvalid) as exc:
        validate_patch({"redaction_patterns": bad})
    assert exc.value.key == "redaction_patterns"


def test_refused_pattern_text_never_reaches_stderr_or_the_error(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """RE2's own C++ logging would print the pattern to stderr, outside the logs."""
    with pytest.raises(SettingsInvalid) as exc:
        validate_patch({"redaction_patterns": [f"({CANARY})\\1"]})
    out, err = capfd.readouterr()
    assert CANARY not in out and CANARY not in err
    assert CANARY not in str(exc.value) and CANARY not in repr(exc.value)


def test_validate_patch_does_not_alias_the_input_list() -> None:
    pats = ["a+"]
    got = validate_patch({"redaction_patterns": pats})
    pats.append("b+")
    assert got == {"redaction_patterns": ["a+"]}


# ------------------------------------------------------------ CHK-M3-094


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
    ]


def test_no_inventory_switch_anywhere_in_settings_code() -> None:
    """REQ-088 (2): no key, constant or field names an inventory switch."""
    pkg = Path(settings_pkg.__file__).resolve().parent
    files = [*pkg.glob("*.py"), pkg.parents[1] / "repositories" / "settings.py"]
    assert len(files) >= 3
    for f in files:
        for s in _string_constants(f):
            low = s.lower()
            assert "enabled" not in low and "disable" not in low, (f.name, s)
    fields = set(Settings.__dataclass_fields__)
    assert fields == set(KEYS)
    assert not any("enable" in k or "disable" in k for k in KEYS)
