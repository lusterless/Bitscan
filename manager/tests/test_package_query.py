"""TASK-109: package search query parsing (TP-M5-02, REQ-113).

Checks CHK-M5-010 to CHK-M5-025 of tests/m5/test-plan.md. Expected values come
from TS §7.1 (L1196-L1212), the approved answers #83 (a)-(h) and #88
(work/decisions.md 2026-10-24, "M5 breakdown approved": #83 (f) counts
`hold ok installed` as installed; a later user ruling, relayed by the lead
2026-10-24, also counts `deinstall ok installed`), the rule list of
work/plans/TASK-110.md
and dpkg's own version syntax (the M1 corpus `fixtures/debversion_pairs.tsv`,
recorded with dpkg 1.22.6). Every refusal names the parameter only, never
the value (REQ-038 (2)).
"""

import ast
from collections.abc import Iterator
from dataclasses import fields, replace
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bitscan_manager.repositories.packages import SearchFilter, VersionOp
from bitscan_manager.services.packages.query import (
    GroupBy,
    InvalidSearch,
    SearchQuery,
    parse_search,
)

TESTS = Path(__file__).resolve().parent
CORPUS = TESTS / "fixtures" / "debversion_pairs.tsv"
QUERY_PY = TESTS.parent / "bitscan_manager" / "services" / "packages" / "query.py"

# #83 (f) as answered by the user (2026-10-24): held packages, and packages
# selected for removal but still installed, are installed.
INSTALLED = {"install ok installed", "hold ok installed", "deinstall ok installed"}
TEXT_PARAMS = ("q", "name", "version", "arch", "os", "tag", "host")
ALL_PARAMS = (*TEXT_PARAMS, "version_op", "status", "agent_id", "group_by")
# #83 (h): characters.
LIMITS = {"q": 255, "name": 255, "version": 255, "host": 255, "arch": 16, "tag": 64}
UUID_LOWER = "0f8fad5b-d9cb-469f-a165-70867728950e"
CANARY = "CANARY-5e1f0c2d9a7b4e63"


def refused(params: dict[str, str | None]) -> tuple[str, ...]:
    with pytest.raises(InvalidSearch) as info:
        parse_search(params)
    return info.value.params


def ok(params: dict[str, str | None]) -> SearchQuery:
    return parse_search(params)


def corpus_versions() -> list[str]:
    out: set[str] = set()
    for line in CORPUS.read_text(encoding="utf-8").split("\n"):
        if line and not line.startswith("#"):
            a, b, _ = line.split("\t")
            out.update((a, b))
    return sorted(out)


def valid_version(length: int) -> str:
    """A dpkg-valid version of exactly `length` characters."""
    return "1" + "0" * (length - 1)


# ---------------------------------------------------------------- CHK-M5-010


def test_q_shorter_than_three_is_refused() -> None:
    assert refused({"q": "ab"}) == ("q",)
    assert refused({"q": "a"}) == ("q",)


@pytest.mark.parametrize("q", ["abc", "   ", "%%%", "_\\_", "ssl"])
def test_q_of_three_characters_is_accepted(q: str) -> None:
    assert ok({"q": q}).filter.q == q


def test_q_two_non_ascii_characters_is_still_refused() -> None:
    assert refused({"q": "üß"}) == ("q",)
    assert ok({"q": "üßa"}).filter.q == "üßa"


# ---------------------------------------------------------------- CHK-M5-011


def test_q_with_name_is_refused_naming_both() -> None:
    assert refused({"q": "openssl", "name": "openssl"}) == ("name", "q")


# ---------------------------------------------------------------- CHK-M5-012


def test_version_op_without_version_is_refused() -> None:
    assert refused({"version_op": "lt"}) == ("version", "version_op")


@pytest.mark.parametrize("op", ["lt", "le", "eq", "ge", "gt"])
def test_each_version_op_with_a_version_is_accepted(op: str) -> None:
    f = ok({"version": "1:2.0-1", "version_op": op}).filter
    assert f.version_op is VersionOp(op)
    assert f.version == "1:2.0-1"


def test_version_alone_is_exact_with_no_op() -> None:
    f = ok({"version": "3.0.13-0ubuntu3.5"}).filter
    assert f.version == "3.0.13-0ubuntu3.5"
    assert f.version_op is None


# ---------------------------------------------------------------- CHK-M5-013


@pytest.mark.parametrize(
    ("param", "value"),
    [
        ("version_op", "ne"),
        ("version_op", "LT"),
        ("version_op", "<"),
        ("version_op", "lt "),
        ("status", "removed"),
        ("status", "Installed"),
        ("status", "ANY"),
        ("status", "all"),
        ("group_by", "name"),
        ("group_by", "PACKAGE"),
        ("group_by", "hosts"),
        ("group_by", "version"),
    ],
)
def test_value_outside_an_enum_is_refused(param: str, value: str) -> None:
    extra = {"version": "1.0"} if param == "version_op" else {}
    assert refused({param: value, **extra}) == (param,)


def test_status_default_and_installed_keep_installed_statuses() -> None:
    absent = ok({}).filter.statuses
    installed = ok({"status": "installed"}).filter.statuses
    assert absent is not None and installed is not None
    assert set(absent) == INSTALLED
    assert set(installed) == INSTALLED


def test_status_any_is_no_status_filter() -> None:
    assert ok({"status": "any"}).filter.statuses is None


# ---------------------------------------------------------------- CHK-M5-014


def test_installed_statuses_are_exactly_the_three_installed_states() -> None:
    statuses = ok({}).filter.statuses
    assert statuses is not None
    assert len(statuses) == len(set(statuses)) == 3
    assert set(statuses) == INSTALLED
    for other in ("deinstall ok config-files", "purge ok not-installed",
                  "install ok unpacked", "install ok half-configured"):  # fmt: skip
        assert other not in statuses


@pytest.mark.parametrize(
    ("group_by", "shape", "enum"),
    [(None, "rows", None), ("package", "package", GroupBy.PACKAGE),
     ("host", "host", GroupBy.HOST)],
)  # fmt: skip
def test_group_by_values_and_shape(
    group_by: str | None, shape: str, enum: GroupBy | None
) -> None:
    query = ok({"group_by": group_by})
    assert query.group_by is enum
    assert query.shape() == shape


# ---------------------------------------------------------------- CHK-M5-015


def test_os_id_alone_means_every_version() -> None:
    f = ok({"os": "ubuntu"}).filter
    assert (f.os_id, f.os_version_id) == ("ubuntu", None)


def test_os_id_and_version() -> None:
    f = ok({"os": "ubuntu:24.04"}).filter
    assert (f.os_id, f.os_version_id) == ("ubuntu", "24.04")


def test_os_case_is_kept() -> None:
    f = ok({"os": "Ubuntu:24.04"}).filter
    assert (f.os_id, f.os_version_id) == ("Ubuntu", "24.04")


@pytest.mark.parametrize(
    "value",
    [":24.04", "ubuntu:", ":", "a:b:c", "ubuntu:24.04:1", "::",
     "u" * 33, "u" * 33 + ":1", "ubuntu:" + "1" * 17],
)  # fmt: skip
def test_malformed_os_is_refused(value: str) -> None:
    assert refused({"os": value}) == ("os",)


def test_os_at_its_limits_is_accepted() -> None:
    value = "u" * 32 + ":" + "1" * 16
    assert len(value) == 49
    f = ok({"os": value}).filter
    assert (f.os_id, f.os_version_id) == ("u" * 32, "1" * 16)
    assert ok({"os": "u" * 32}).filter.os_id == "u" * 32


def test_os_one_over_49_is_refused() -> None:
    assert refused({"os": "u" * 33 + ":" + "1" * 16}) == ("os",)


# ---------------------------------------------------------------- CHK-M5-016


@pytest.mark.parametrize("value", [UUID_LOWER, UUID_LOWER.upper()])
def test_hyphenated_uuid_in_either_case_is_accepted(value: str) -> None:
    assert ok({"agent_id": value}).filter.agent_id == UUID(UUID_LOWER)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        "{" + UUID_LOWER + "}",
        "urn:uuid:" + UUID_LOWER,
        UUID_LOWER.replace("-", ""),
        UUID_LOWER[:8] + UUID_LOWER[9:13] + "-" + "-" + UUID_LOWER[14:],
        "0f8fad5bd-9cb-469f-a165-70867728950e",
        UUID_LOWER[:-1] + "g",
        UUID_LOWER[:-1],
        UUID_LOWER + "0",
        UUID_LOWER[:-1] + "٣",  # ARABIC-INDIC DIGIT THREE
        UUID_LOWER[:-1] + "ａ",  # FULLWIDTH a
        " " + UUID_LOWER[1:],
    ],
)
def test_non_hyphenated_uuid_forms_are_refused(value: str) -> None:
    assert refused({"agent_id": value}) == ("agent_id",)


# ---------------------------------------------------------------- CHK-M5-017


@pytest.mark.parametrize("param", sorted(LIMITS))
def test_text_parameter_at_its_limit_is_accepted(param: str) -> None:
    n = LIMITS[param]
    value = valid_version(n) if param == "version" else "x" * n
    query = ok({param: value})
    assert len(getattr(query.filter, param)) == n


@pytest.mark.parametrize("param", sorted(LIMITS))
def test_text_parameter_one_over_its_limit_is_refused(param: str) -> None:
    n = LIMITS[param] + 1
    value = valid_version(n) if param == "version" else "x" * n
    assert refused({param: value}) == (param,)


@pytest.mark.parametrize("param", ["q", "name", "host", "tag", "arch"])
def test_limits_count_characters_not_bytes(param: str) -> None:
    n = LIMITS[param]
    value = "é" * n  # 2 bytes each in UTF-8
    assert len(getattr(ok({param: value}).filter, param)) == n
    assert refused({param: value + "é"}) == (param,)


# ---------------------------------------------------------------- CHK-M5-018


@pytest.mark.parametrize("param", ALL_PARAMS)
def test_empty_value_is_refused(param: str) -> None:
    params: dict[str, str | None] = {param: ""}
    if param == "version_op":
        params["version"] = "1.0"
    assert refused(params) == (param,)


# ---------------------------------------------------------------- CHK-M5-019


@pytest.mark.parametrize("param", TEXT_PARAMS)
def test_nul_is_refused_in_every_text_parameter(param: str) -> None:
    base = {"version": "1.0", "os": "ubuntu"}.get(param, "abc")
    assert refused({param: base + "\x00"}) == (param,)
    assert refused({param: "\x00" + base}) == (param,)


def test_nul_alone_is_refused_in_q() -> None:
    assert refused({"q": "\x00\x00\x00"}) == ("q",)


@pytest.mark.parametrize("param", ["version_op", "status", "group_by", "agent_id"])
def test_nul_is_refused_in_enum_and_id_parameters(param: str) -> None:
    value = {"version_op": "lt", "status": "any", "group_by": "host"}.get(
        param, UUID_LOWER
    )
    params: dict[str, str | None] = {param: value[:-1] + "\x00"}
    if param == "version_op":
        params["version"] = "1.0"
    assert refused(params) == (param,)


# ---------------------------------------------------------------- CHK-M5-020


def test_every_corpus_version_is_accepted() -> None:
    versions = corpus_versions()
    assert len(versions) >= 40
    bad = [v for v in versions if not _accepts({"version": v})]
    assert bad == []
    bad_op = [v for v in versions if not _accepts({"version": v, "version_op": "ge"})]
    assert bad_op == []


def _accepts(params: dict[str, str | None]) -> bool:
    try:
        parse_search(params)
    except InvalidSearch:
        return False
    return True


# ---------------------------------------------------------------- CHK-M5-021


@pytest.mark.parametrize(
    "value",
    [
        "1.0 beta",
        "a1",
        "1:",
        ":1.0",
        ":1",
        "1.0-",
        "-1",
        "1:a1",
        "x:1.0",
        "1a:1.0",
        "99999999999:1.0",  # 11-digit epoch
        "2147483648:1",  # epoch over 2,147,483,647
        "1.0-a_b",
        "1.0-1:2",  # ':' in the revision
        "1.0\t",
        " 1.0",
        "1.0 ",
        "١.0",  # ARABIC-INDIC DIGIT ONE
        "1.0-ü",
        "1.0_1",
        "1.0/1",
        "~1",
        ".1",
        "1:-1",
    ],
)
def test_malformed_version_is_refused(value: str) -> None:
    assert refused({"version": value}) == ("version",)
    assert refused({"version": value, "version_op": "lt"}) == ("version",)


@pytest.mark.parametrize(
    "value",
    [
        "0:1.0",
        "2147483647:1",
        "0000000001:1",  # 10 digits
        "1.0-1-2",  # revision after the last '-'
        "1:1.0:2",  # ':' in upstream with an epoch
        "1.0+dfsg~rc1-0ubuntu1",
        "1.0~~",
        "1",
        "1-1",
        "9.9.9+really1.0-0.1~deb12u1",
    ],
)
def test_edge_versions_dpkg_accepts_are_accepted(value: str) -> None:
    assert ok({"version": value}).filter.version == value


def test_colon_in_upstream_without_epoch_is_not_possible() -> None:
    # With a ':' the part before the first one is the epoch, so "1.0:2" has a
    # non-digit epoch and dpkg refuses it.
    assert refused({"version": "1.0:2"}) == ("version",)


# ---------------------------------------------------------------- CHK-M5-022


def test_unknown_parameters_are_ignored() -> None:
    query = ok({"q": "abc", "limit": "9999", "cursor": "x", "nonsense": "\x00"})
    assert query.filter.q == "abc"


@pytest.mark.parametrize(
    "params",
    [
        {"q": CANARY[:2]},
        {"name": CANARY + "\x00"},
        {"version": CANARY},
        {"version_op": CANARY, "version": "1.0"},
        {"status": CANARY},
        {"group_by": CANARY},
        {"os": CANARY + ":" + CANARY},
        {"agent_id": CANARY},
        {"arch": CANARY},
        {"tag": CANARY * 5},
        {"host": CANARY * 20},
        {"q": CANARY, "name": CANARY},
    ],
)
def test_refusal_carries_parameter_names_only(params: dict[str, str | None]) -> None:
    with pytest.raises(InvalidSearch) as info:
        parse_search(params)
    exc = info.value
    assert exc.params, "a refusal names at least one parameter"
    assert set(exc.params) <= set(ALL_PARAMS)
    assert list(exc.params) == sorted(exc.params)
    for text in (str(exc), repr(exc), *map(str, exc.args)):
        assert CANARY[:2] not in text


def test_first_failing_rule_wins_and_is_deterministic() -> None:
    # Rule 1 (text values) runs before rule 3 (q with name).
    assert refused({"q": "ab", "name": ""}) == ("name",)
    # Enums (rule 2) before q length (rule 3).
    assert refused({"q": "ab", "status": "x"}) == ("status",)
    # q length before q with name.
    assert refused({"q": "ab", "name": "x"}) == ("q",)


# ---------------------------------------------------------------- CHK-M5-023


FIELD_CHANGES: dict[str, Any] = {
    "q": "other",
    "name": "other",
    "version": "2.0",
    "version_op": VersionOp.GT,
    "arch": "i386",
    "statuses": None,
    "os_id": "debian",
    "os_version_id": "12",
    "tag": "other",
    "host": "other",
    "agent_id": UUID("11111111-2222-3333-4444-555555555555"),
}


def base_query() -> SearchQuery:
    return SearchQuery(
        filter=SearchFilter(
            q="abc",
            version="1.0",
            version_op=VersionOp.LT,
            arch="amd64",
            os_id="ubuntu",
            os_version_id="24.04",
            tag="t",
            host="h",
            agent_id=UUID(UUID_LOWER),
        ),
        group_by=None,
    )


def test_every_filter_field_is_covered_by_the_change_table() -> None:
    assert {f.name for f in fields(SearchFilter)} == set(FIELD_CHANGES)


def test_equal_queries_give_equal_scopes() -> None:
    a = parse_search({"q": "abc", "os": "ubuntu:24.04", "agent_id": UUID_LOWER})
    b = parse_search({"agent_id": UUID_LOWER.upper(), "os": "ubuntu:24.04", "q": "abc"})
    assert a.cursor_scope() == b.cursor_scope()


@pytest.mark.parametrize("field_name", sorted(FIELD_CHANGES))
def test_any_one_changed_field_changes_the_scope(field_name: str) -> None:
    base = base_query()
    changed = SearchQuery(
        filter=replace(base.filter, **{field_name: FIELD_CHANGES[field_name]}),
        group_by=None,
    )
    assert changed.filter != base.filter
    assert changed.cursor_scope() != base.cursor_scope()


def test_group_by_changes_the_scope() -> None:
    f = base_query().filter
    scopes = {SearchQuery(f, g).cursor_scope() for g in (None, *GroupBy)}
    assert len(scopes) == 3


def test_status_any_and_installed_scopes_differ() -> None:
    assert (
        parse_search({"status": "any"}).cursor_scope()
        != parse_search({}).cursor_scope()
    )


def scopes() -> Iterator[str]:
    long = "é" * 255
    yield parse_search({}).cursor_scope()
    yield parse_search({"q": long, "host": long, "tag": "t" * 64}).cursor_scope()
    yield parse_search({"name": long, "group_by": "package"}).cursor_scope()
    yield parse_search(
        {"version": valid_version(255), "group_by": "host"}
    ).cursor_scope()


def test_scope_is_short_and_fixed_length_per_shape() -> None:
    lengths: dict[str, set[int]] = {}
    for scope in scopes():
        assert len(scope) < 100
        assert scope.isascii()
        lengths.setdefault(scope.split(":")[1], set()).add(len(scope))
    assert all(len(v) == 1 for v in lengths.values())


# ---------------------------------------------------------------- CHK-M5-024


def test_values_are_kept_as_given() -> None:
    f = parse_search(
        {
            "q": "OpenSSL",
            "version": "1:3.0.13-0ubuntu3.5",
            "arch": "AMD64",
            "tag": "Prod-Web",
            "host": "WEB-0",
        }
    ).filter
    assert (f.q, f.version, f.arch, f.tag, f.host) == (
        "OpenSSL",
        "1:3.0.13-0ubuntu3.5",
        "AMD64",
        "Prod-Web",
        "WEB-0",
    )
    assert parse_search({"name": "LibSSL3"}).filter.name == "LibSSL3"


def test_agent_id_is_normalised_to_a_uuid() -> None:
    f = parse_search({"agent_id": UUID_LOWER.upper()}).filter
    assert isinstance(f.agent_id, UUID)
    assert str(f.agent_id) == UUID_LOWER


def test_empty_query_is_every_installed_row() -> None:
    q = parse_search({})
    assert q.group_by is None
    f = q.filter
    assert (f.q, f.name, f.version, f.version_op, f.arch) == (None,) * 5
    assert (f.os_id, f.os_version_id, f.tag, f.host, f.agent_id) == (None,) * 5


# ---------------------------------------------------------------- CHK-M5-025


def test_query_module_imports_no_regular_expression_module() -> None:
    tree = ast.parse(QUERY_PY.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"re", "re2", "regex"}
