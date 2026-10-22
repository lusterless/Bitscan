"""REQ-001 (3), REQ-002 (2), (4): hashed lock files.

Checks CHK-M0-004, CHK-M0-008 and CHK-M0-010 of tests/m0/test-plan.md.
"""

import string
from dataclasses import dataclass
from pathlib import Path

import pytest

MANAGER = Path(__file__).resolve().parents[1]
RUNTIME = MANAGER / "requirements.txt"
DEV = MANAGER / "requirements-dev.txt"
LOCKS = [RUNTIME, DEV]
IDS = ["runtime", "dev"]

TOOLS = {
    "pytest",
    "pytest-cov",
    "ruff",
    "mypy",
    "testcontainers",
    "coverage",
    "hatchling",
}
DEV_REQUIRED = TOOLS | {"httpx", "psycopg"}
OUT_OF_SCOPE = {
    "authlib",
    "oauthlib",
    "requests-oauthlib",
    "python-jose",
    "oic",
    "pyoidc",
    "fastapi-sso",
    "python-keycloak",
    "msal",
    "okta",
    "joserfc",
    "fastapi-users",
}
M2_STACK = {"uvicorn", "argon2-cffi", "httpx", "psycopg-pool", "prometheus-client"}
UVICORN_EXTRAS = {"uvloop", "httptools", "watchfiles", "websockets", "python-dotenv"}
NOT_CHOSEN = {"hvac", "pyotp"}


@dataclass(frozen=True)
class Entry:
    name: str
    version: str
    marker: str
    hashes: tuple[str, ...]


@dataclass(frozen=True)
class Lock:
    options: tuple[str, ...]
    entries: tuple[Entry, ...]


def normalise(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def is_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in string.hexdigits.lower() for c in value)


def logical_lines(text: str) -> list[str]:
    out: list[str] = []
    buf = ""
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        if buf.strip() and not buf.lstrip().startswith("#"):
            out.append(buf.strip())
        buf = ""
    return out


def parse(path: Path) -> Lock:
    options: list[str] = []
    entries: list[Entry] = []
    for line in logical_lines(path.read_text(encoding="utf-8")):
        if line.startswith("--"):
            assert not line.startswith("--hash="), f"{path.name}: orphan {line!r}"
            options.append(line)
            continue
        tokens = line.split()
        hashes = tuple(
            t.removeprefix("--hash=") for t in tokens if t.startswith("--hash=")
        )
        spec = line.split("--hash=")[0].strip()
        requirement, _, marker = spec.partition(";")
        name, sep, version = requirement.strip().partition("==")
        assert sep == "==", f"{path.name}: not pinned with ==: {line!r}"
        entries.append(Entry(normalise(name), version.strip(), marker.strip(), hashes))
    return Lock(tuple(options), tuple(entries))


def names(path: Path) -> set[str]:
    return {e.name for e in parse(path).entries}


@pytest.mark.parametrize("path", LOCKS, ids=IDS)
def test_every_line_is_pinned_and_hashed(path: Path) -> None:
    entries = parse(path).entries
    assert len(entries) >= 5
    for e in entries:
        assert e.name and all(c not in e.name for c in "<>=!~ ["), e
        assert e.version and e.version[0].isdigit(), e
        assert e.hashes, f"{path.name}: {e.name} has no --hash"
        for h in e.hashes:
            algo, _, digest = h.partition(":")
            assert algo == "sha256" and is_sha256(digest), f"{e.name}: bad {h!r}"


@pytest.mark.parametrize("path", LOCKS, ids=IDS)
def test_only_option_is_wheels_only(path: Path) -> None:
    assert parse(path).options == ("--only-binary :all:",)


@pytest.mark.parametrize("path", LOCKS, ids=IDS)
def test_header_names_the_uv_universal_command(path: Path) -> None:
    head = "\n".join(path.read_text(encoding="utf-8").split("\n")[:5])
    assert "uv pip compile" in head
    assert "--universal" in head
    assert "--generate-hashes" in head


def test_runtime_lock_has_no_test_or_lint_tool() -> None:
    assert names(RUNTIME) & TOOLS == set()


def test_runtime_lock_has_the_stack() -> None:
    entries = parse(RUNTIME).entries
    stack = {"fastapi", "pydantic", "apscheduler", "defusedxml", "google-re2"}
    assert stack <= {e.name for e in entries}
    versions = {e.name: e.version for e in entries}
    assert versions["pydantic"].startswith("2.")
    assert versions["apscheduler"].startswith("3.")


def test_runtime_lock_has_the_database_stack() -> None:
    """REQ-018: Alembic, SQLAlchemy and psycopg 3 with a bundled libpq (TS §5.3)."""
    entries = parse(RUNTIME).entries
    versions = {e.name: e.version for e in entries}
    for name in ("alembic", "sqlalchemy", "psycopg", "psycopg-binary"):
        assert name in versions, f"{name} missing from the runtime lock"
    assert versions["psycopg"].startswith("3.")
    assert versions["psycopg-binary"] == versions["psycopg"]
    assert versions["sqlalchemy"].startswith("2.")
    assert len([e for e in entries if e.name == "psycopg"]) == 1


def test_runtime_lock_has_the_m2_stack() -> None:
    """REQ-034 (2), PD-19: the five M2 runtime packages, each pinned once."""
    entries = parse(RUNTIME).entries
    found = [e.name for e in entries]
    for name in M2_STACK | {"argon2-cffi-bindings"}:
        assert found.count(name) == 1, f"{name}: {found.count(name)} entries"
    versions = {e.name: e.version for e in entries}
    assert versions["httpx"] == {e.name: e.version for e in parse(DEV).entries}["httpx"]


def test_runtime_lock_has_no_uvicorn_extras_or_unchosen_clients() -> None:
    """PD-19 (a), (f), (g): uvicorn without extras, no hvac, no pyotp."""
    assert names(RUNTIME) & (UVICORN_EXTRAS | NOT_CHOSEN) == set()


@pytest.mark.parametrize("path", LOCKS, ids=IDS)
def test_no_opentelemetry_sdk_exporter_or_instrumentation(path: Path) -> None:
    """REQ-034 (5); decisions 2026-10-20: only opentelemetry-api may be present."""
    otel = {n for n in names(path) if n.startswith("opentelemetry")}
    assert otel <= {"opentelemetry-api", "opentelemetry-semantic-conventions"}, otel
    assert not any(
        n == "opentelemetry-sdk"
        or n.startswith("opentelemetry-exporter")
        or n.startswith("opentelemetry-instrumentation")
        or n.startswith("opentelemetry-distro")
        for n in otel
    )


def test_dev_lock_is_a_superset_with_the_tools() -> None:
    runtime = {(e.name, e.version) for e in parse(RUNTIME).entries}
    dev = {(e.name, e.version) for e in parse(DEV).entries}
    assert DEV_REQUIRED <= {n for n, _ in dev}
    assert runtime <= dev


@pytest.mark.parametrize("path", LOCKS, ids=IDS)
def test_no_out_of_scope_identity_library(path: Path) -> None:
    found = names(path)
    assert found & OUT_OF_SCOPE == set()
    assert not any(n.startswith("social-auth") for n in found)


def test_parser_rejects_an_unpinned_line(tmp_path: Path) -> None:
    lock = tmp_path / "lock.txt"
    lock.write_text("six \\\n    --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="not pinned"):
        parse(lock)
