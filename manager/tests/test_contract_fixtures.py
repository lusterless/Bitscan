"""REQ-061 (1), (2), (5): the shared contract fixtures are complete (TP-M3-01).

Check CHK-M3-010 of tests/m3/test-plan.md. Needs no product code: it checks the
fixture set itself against TS §6.5 and #60, so that a gap in the fixtures
cannot hide a gap in the contract test (TP-M3-02).
"""

import hashlib
import json
from collections import defaultdict

import pytest
import re2  # type: ignore[import-untyped]

from tests.contract import loader

TOKEN_SHAPE = re2.compile(r"bs[aeku]_[A-Za-z0-9_-]*")
TOKEN_FORMAT = re2.compile(r"^bs[ae]_[A-Za-z0-9_-]{43}$")
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ROUTES = {"enrol", "heartbeat", "jobs", "results", "inventory", "rotate"}


def test_manifest_and_folder_agree() -> None:
    listed = {f.file for f in loader.fixtures()}
    # Shared non-wire files (M10: the redaction corpus) are listed by name in
    # "shared_files"; every file on disk is still listed exactly once.
    shared = [e["file"] for e in loader.manifest().get("shared_files", [])]
    on_disk = {
        p.relative_to(loader.FIXTURES).as_posix()
        for p in loader.FIXTURES.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    assert listed | set(shared) == on_disk
    assert len(listed) == len(loader.fixtures())  # no duplicate entries
    assert len(set(shared)) == len(shared)
    assert not listed & set(shared)  # a wire fixture is never also "shared"
    assert shared == ["redaction/corpus.json"]  # M10; extend deliberately


def test_every_fixture_is_utf8_json_with_lf() -> None:
    for f in loader.fixtures():
        raw = f.raw_bytes()
        assert b"\r" not in raw, f.file
        json.loads(raw.decode("utf-8"))


def test_routes_match_ts_6_1() -> None:
    m = loader.manifest()
    assert set(m["routes"]) == ROUTES
    paths = {(r["method"], r["path"]) for r in m["routes"].values()}
    assert paths == {
        ("POST", "/api/v1/agent/enroll"),
        ("POST", "/api/v1/agent/{id}/heartbeat"),
        ("GET", "/api/v1/agent/{id}/jobs"),
        ("POST", "/api/v1/agent/{id}/jobs/{job_id}/results"),
        ("PUT", "/api/v1/agent/{id}/inventory"),
        ("POST", "/api/v1/agent/{id}/token/rotate"),
    }
    assert {f.route for f in loader.fixtures()} == ROUTES


def test_each_route_has_valid_request_and_response() -> None:
    no_body = {"jobs/request", "inventory/response"}
    for route in ROUTES:
        for direction in ("request", "response"):
            key = f"{route}/{direction}"
            valid = [f for f in loader.select(route, direction) if f.valid]
            if key in no_body:
                assert not list(loader.select(route, direction)), key
            else:
                assert valid, key


def _ids(route: str, direction: str, valid: bool) -> set[str]:
    return {
        f.file.split("/")[1].removesuffix(".json")
        for f in loader.select(route, direction)
        if f.valid is valid
    }


def test_required_shapes_present() -> None:
    """REQ-061 (1): the shapes the requirement names explicitly."""
    jobs = {f.file: f.body() for f in loader.select("jobs", "response") if f.valid}
    kinds = {j["kind"] for body in jobs.values() for j in body["jobs"]}
    assert kinds == {"inventory", "compliance"}
    assert {"jobs": []} in jobs.values()
    starts = [f.body() for f in loader.select("results", "request") if f.valid]
    assert {"results": [], "final": False} in starts
    inv = [
        f.body()
        for f in loader.select("inventory", "request")
        if f.valid and not f.decoder
    ]
    assert any(b["packages"] == [] for b in inv)
    assert any(
        len({p["architecture"] for p in b["packages"] if p["name"] == "libc6"}) >= 2
        for b in inv
    )


def test_every_constraint_class_covered_per_body() -> None:
    """REQ-061 (2): at least one invalid fixture per applicable #60 class and body."""
    have: dict[str, set[str]] = defaultdict(set)
    for f in loader.fixtures():
        if not f.valid:
            assert f.cls is not None, f.file
            have[f.body_key].add(f.cls)
    required = loader.manifest()["required_invalid_classes"]
    # The seven classes REQ-061 (2) names must each appear somewhere.
    named = {
        "extra_key",
        "missing_key",
        "wrong_type",
        "over_length",
        "bad_uuid",
        "bad_timestamp",
    }
    all_required = set().union(*map(set, required.values()))
    assert named <= all_required
    assert {"enum", "range"} & all_required == {"enum", "range"}
    for key, classes in required.items():
        missing = set(classes) - have[key]
        assert not missing, (key, missing)
    # every body with a payload has at least extra_key (unknown keys refused)
    for key in required:
        assert "extra_key" in have[key], key


def test_only_the_one_fake_token() -> None:
    """REQ-061 (5): token fields use one fixed fake value."""
    fake = loader.manifest()["fake_token"]
    assert TOKEN_FORMAT.search(fake)
    for f in loader.fixtures():
        text = f.raw_bytes().decode("utf-8")
        for m in TOKEN_SHAPE.finditer(text):
            tok = m.group(0)
            if f.valid:
                assert tok == fake, f.file
            else:
                # invalid token fixtures are the fake body with a wrong prefix,
                # length or padding, never another secret
                body = fake[4:]
                assert body.startswith(tok[4:]) or tok[4:].startswith(body[:42]), f.file


@pytest.mark.parametrize(
    "fx", list(loader.select("inventory", "request")), ids=lambda f: f.id
)
def test_inventory_list_sha256_oracle(fx: loader.Fixture) -> None:
    """REQ-074 (3): a valid inventory body's hash equals the test's own value."""
    body = fx.body()
    if not isinstance(body, dict) or not isinstance(body.get("packages"), list):
        return
    if not all(
        isinstance(p, dict)
        and all(
            isinstance(p.get(k), str)
            for k in ("name", "version", "architecture", "status")
        )
        for p in body["packages"]
    ):
        return
    if not (fx.valid or fx.id.endswith("hash_mismatch")):
        return  # invalid bodies (e.g. a lone surrogate) need no hash oracle
    computed = loader.list_sha256(body["packages"])
    if fx.id.endswith("hash_mismatch"):
        assert body["list_sha256"] != computed
    elif fx.valid:
        assert body["list_sha256"] == computed


def test_list_sha256_oracle_known_answers() -> None:
    assert loader.list_sha256([]) == EMPTY_SHA256
    one = [
        {
            "name": "apt",
            "version": "2.7.14",
            "architecture": "amd64",
            "status": "install ok installed",
        }
    ]
    assert (
        loader.list_sha256(one)
        == hashlib.sha256(b"apt\t2.7.14\tamd64\tinstall ok installed\n").hexdigest()
    )
    # sorted by bytes: "Zz" (0x5A) sorts before "apt" (0x61); input order is irrelevant
    two = [
        {"name": "apt", "version": "1", "architecture": "all", "status": "s"},
        {"name": "Zz", "version": "1", "architecture": "all", "status": "s"},
    ]
    expect = hashlib.sha256(b"Zz\t1\tall\ts\napt\t1\tall\ts\n").hexdigest()
    assert loader.list_sha256(two) == loader.list_sha256(list(reversed(two))) == expect


def test_generated_fixtures_build() -> None:
    sizes = {}
    for f in loader.fixtures():
        if f.generate is None:
            continue
        body = f.body()
        op = f.generate["op"]
        if op == "plugins_count":
            plugins = body["jobs"][0]["plugins"]
            assert len(plugins) == f.generate["count"]
            assert len({p["plugin_uuid"] for p in plugins}) == len(plugins)
        elif op == "packages_count":
            assert len(body["packages"]) == f.generate["count"]
            assert body["list_sha256"] == loader.list_sha256(body["packages"])
        elif op == "ip_addresses_count":
            ips = body["os_info"]["ip_addresses"]
            assert len(ips) == len(set(ips)) == f.generate["count"]
        elif op == "raw_bytes":
            raw = json.dumps(body["os_info"]["raw"], separators=(",", ":")).encode()
            assert len(raw) == f.generate["bytes"]
        sizes[f.id] = len(f.body_bytes())
    assert sizes  # the generated set is not empty
