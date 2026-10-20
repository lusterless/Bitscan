"""REQ-019: start-up configuration loader (TP-M1-03).

Checks CHK-M1-010 to CHK-M1-019 and CHK-M1-025 of tests/m1/test-plan.md, written
from REQ-019 and the interface in work/plans/TASK-012.md. Every DSN file holds a
canary password and the vault-token file a canary token; every case sweeps
repr/str, the exception chain, captured output and log records for them.
"""

import logging
import os
import secrets
import socket
import traceback
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import NoReturn

import pytest
from pydantic import SecretStr

from bitscan_manager.config import (
    ConfigError,
    DbConfig,
    ServeConfig,
    load_db_config,
    load_serve_config,
)

SERVE_VARS = (
    "BITSCAN_DB_DSN_FILE",
    "BITSCAN_RETENTION_DSN_FILE",
    "BITSCAN_VAULT_ADDR",
    "BITSCAN_TOTP_KEY_REF",
    "BITSCAN_VAULT_TOKEN_FILE",
    "BITSCAN_TLS_CERT_FILE",
    "BITSCAN_TLS_KEY_FILE",
    "BITSCAN_AUDIT_SINK",
)
SECRET_FILE_VARS = (
    "BITSCAN_DB_DSN_FILE",
    "BITSCAN_RETENTION_DSN_FILE",
    "BITSCAN_VAULT_TOKEN_FILE",
)
DSN_VARS = ("BITSCAN_DB_DSN_FILE", "BITSCAN_RETENTION_DSN_FILE")
MIGRATE = "BITSCAN_MIGRATE_DSN_FILE"
LOOKALIKES = {
    "BITSCAN_DB_DSN_FILE": "BITSCAN_DB_DSN",
    "BITSCAN_RETENTION_DSN_FILE": "BITSCAN_RETENTION_DSN",
    "BITSCAN_VAULT_TOKEN_FILE": "BITSCAN_VAULT_TOKEN",
    MIGRATE: "BITSCAN_MIGRATE_DSN",
}
HOST = "db-zq7.internal.example"


class RecordingEnv(Mapping[str, str]):
    """A mapping that records every key the loader looks up."""

    def __init__(self, data: Mapping[str, str]) -> None:
        self._data = dict(data)
        self.read: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.read.append(key)
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


@dataclass
class Setup:
    env: dict[str, str]
    dir: Path
    canaries: tuple[str, ...]
    dsns: dict[str, str]
    token: str


def dsn(role: str, password: str, sslmode: str | None = "require") -> str:
    tail = f" sslmode={sslmode}" if sslmode is not None else ""
    return f"host={HOST} port=5432 dbname=bitscan user={role} password={password}{tail}"


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    for name in list(os.environ):
        if name.startswith(("BITSCAN_", "PG")):
            monkeypatch.delenv(name)
    pw = {k: f"CANARY-{k[8:12]}-{secrets.token_hex(8)}" for k in (*DSN_VARS, MIGRATE)}
    token = f"CANARY-VT-{secrets.token_hex(8)}"
    dsns = {
        "BITSCAN_DB_DSN_FILE": dsn("bitscan_app", pw["BITSCAN_DB_DSN_FILE"]),
        "BITSCAN_RETENTION_DSN_FILE": dsn(
            "bitscan_retention", pw["BITSCAN_RETENTION_DSN_FILE"]
        ),
        MIGRATE: dsn("bitscan_migrate", pw[MIGRATE]),
    }
    files = {
        "BITSCAN_DB_DSN_FILE": "app_dsn",
        "BITSCAN_RETENTION_DSN_FILE": "retention_dsn",
        MIGRATE: "migrate_dsn",
    }
    env: dict[str, str] = {}
    for var, name in files.items():
        (tmp_path / name).write_text(dsns[var] + "\n", encoding="utf-8")
        env[var] = str(tmp_path / name)
    (tmp_path / "vault_token").write_text(token + "\n", encoding="utf-8")
    (tmp_path / "tls_cert").write_text("cert\n", encoding="utf-8")
    (tmp_path / "tls_key").write_text("key\n", encoding="utf-8")
    env.update(
        {
            "BITSCAN_VAULT_ADDR": "https://vault.example:8200",
            "BITSCAN_TOTP_KEY_REF": "transit/keys/totp",
            "BITSCAN_VAULT_TOKEN_FILE": str(tmp_path / "vault_token"),
            "BITSCAN_TLS_CERT_FILE": str(tmp_path / "tls_cert"),
            "BITSCAN_TLS_KEY_FILE": str(tmp_path / "tls_key"),
            "BITSCAN_AUDIT_SINK": "syslog://audit.example:6514",
        }
    )
    return Setup(env, tmp_path, (*pw.values(), token, HOST), dsns, token)


def serve_env(s: Setup) -> dict[str, str]:
    return {k: v for k, v in s.env.items() if k != MIGRATE}


def chain_text(exc: BaseException) -> str:
    parts = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        parts += [str(cur), repr(cur), *[repr(a) for a in cur.args]]
        cur = cur.__cause__ or cur.__context__
    parts.append("".join(traceback.format_exception(exc)))
    return "\n".join(parts)


def assert_no_leak(
    s: Setup,
    caps: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    *objs: object,
    secrets_only: bool = False,
) -> None:
    out = caps.readouterr()
    texts = [out.out, out.err, caplog.text]
    for o in objs:
        texts.append(chain_text(o) if isinstance(o, BaseException) else repr(o))
        if not isinstance(o, BaseException):
            texts.append(str(o))
    blob = "\n".join(texts)
    canaries = s.canaries[:-1] if secrets_only else s.canaries
    for canary in canaries:
        assert canary not in blob, f"leaked {canary[:12]}..."


def load_error(
    environ: Mapping[str, str], db: bool = False
) -> ConfigError:  # pragma: no cover - helper
    with pytest.raises(ConfigError) as err:
        load_db_config(environ) if db else load_serve_config(environ)
    return err.value


@pytest.fixture(autouse=True)
def _debug_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)


# --- CHK-M1-010: success, defaults, overrides ---------------------------------


def test_serve_profile_loads_and_reads_secrets_from_files(
    setup: Setup, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    cfg = load_serve_config(serve_env(setup))
    assert isinstance(cfg, ServeConfig)
    for f in ("db_dsn", "retention_dsn", "vault_token"):
        assert isinstance(getattr(cfg, f), SecretStr)
    assert cfg.db_dsn.get_secret_value() == setup.dsns["BITSCAN_DB_DSN_FILE"]
    assert (
        cfg.retention_dsn.get_secret_value() == setup.dsns["BITSCAN_RETENTION_DSN_FILE"]
    )
    assert cfg.vault_token.get_secret_value() == setup.token
    default_listen = ("0.0.0.0", 8443)  # noqa: S104  # TS §8.6 default, asserted only
    assert (cfg.listen_host, cfg.listen_port) == default_listen
    assert Path(cfg.bits_dir) == Path("/var/lib/bitscan/bits")
    assert Path(cfg.uploads_dir) == Path("/var/lib/bitscan/bits") / "uploaded"
    assert Path(cfg.tls_cert_file) == Path(setup.env["BITSCAN_TLS_CERT_FILE"])
    assert Path(cfg.tls_key_file) == Path(setup.env["BITSCAN_TLS_KEY_FILE"])
    assert_no_leak(
        setup, capsys, caplog, cfg, *[getattr(cfg, f.name) for f in fields(cfg)]
    )


def test_listen_and_bits_dir_overrides(setup: Setup, tmp_path: Path) -> None:
    env = serve_env(setup) | {
        "BITSCAN_LISTEN": "127.0.0.1:9443",
        "BITSCAN_BITS_DIR": str(tmp_path / "bits"),
    }
    cfg = load_serve_config(env)
    assert (cfg.listen_host, cfg.listen_port) == ("127.0.0.1", 9443)
    assert Path(cfg.bits_dir) == tmp_path / "bits"
    assert Path(cfg.uploads_dir) == tmp_path / "bits" / "uploaded"


# --- CHK-M1-011: each required variable unset or empty ------------------------


@pytest.mark.parametrize("var", SERVE_VARS)
@pytest.mark.parametrize("how", ["unset", "empty", "blank"])
def test_each_required_variable_is_named_when_missing(
    setup: Setup,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    var: str,
    how: str,
) -> None:
    env = serve_env(setup)
    if how == "unset":
        del env[var]
    else:
        env[var] = "" if how == "empty" else "   "
    err = load_error(env)
    assert var in str(err)
    for other in SERVE_VARS:
        if other != var and not var.startswith(other):
            assert other not in str(err), f"{other} wrongly reported"
    assert_no_leak(setup, capsys, caplog, err)


def test_all_missing_variables_are_reported(setup: Setup) -> None:
    err = load_error({})
    for var in SERVE_VARS:
        assert var in str(err)


# --- CHK-M1-012: *_FILE pointing to a bad file --------------------------------


FILE_VARS = (*SECRET_FILE_VARS, "BITSCAN_TLS_CERT_FILE", "BITSCAN_TLS_KEY_FILE")


# TLS files are checked, not read (plan item 5): an empty one is refused under
# REQ-019 (3) (main's ruling 2026-10-20), whitespace-only content is out of scope.
BAD_FILE_CASES = [
    (var, kind)
    for var in FILE_VARS
    for kind in ("missing", "directory", "empty", "whitespace")
    if not (var.startswith("BITSCAN_TLS") and kind == "whitespace")
]


@pytest.mark.parametrize(("var", "kind"), BAD_FILE_CASES)
def test_bad_credential_file_names_the_variable(
    setup: Setup,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    var: str,
    kind: str,
) -> None:
    env = serve_env(setup)
    target = setup.dir / f"bad_{kind}"
    if kind == "directory":
        target.mkdir()
    elif kind == "empty":
        target.write_text("", encoding="utf-8")
    elif kind == "whitespace":
        target.write_text(" \n\t\n", encoding="utf-8")
    env[var] = str(target)
    err = load_error(env)
    assert var in str(err)
    assert_no_leak(setup, capsys, caplog, err)


# --- CHK-M1-013: plain-value look-alikes are never read -----------------------


@pytest.mark.parametrize("var", SECRET_FILE_VARS)
def test_plain_lookalike_is_not_read(setup: Setup, var: str) -> None:
    env = serve_env(setup)
    secret_path = Path(env.pop(var))
    env[LOOKALIKES[var]] = secret_path.read_text(encoding="utf-8").strip()
    rec = RecordingEnv(env)
    err = load_error(rec)
    assert var in str(err)
    assert LOOKALIKES[var] not in rec.read
    assert not any(k in rec.read for k in LOOKALIKES.values())


def test_plain_migrate_lookalike_is_not_read(setup: Setup) -> None:
    rec = RecordingEnv({"BITSCAN_MIGRATE_DSN": setup.dsns[MIGRATE]})
    err = load_error(rec, db=True)
    assert MIGRATE in str(err)
    assert "BITSCAN_MIGRATE_DSN" not in rec.read


# --- CHK-M1-014: TLS rule for all three DSNs (#45) ----------------------------


REFUSED_MODES: tuple[str | None, ...] = (None, "disable", "allow", "prefer", "REQUIRE")
ACCEPTED_MODES = ("require", "verify-ca", "verify-full")


def _with_dsn(s: Setup, var: str, text: str) -> dict[str, str]:
    path = s.dir / f"{var}.dsn"
    path.write_text(text + "\n", encoding="utf-8")
    env = dict(s.env) if var == MIGRATE else serve_env(s)
    env[var] = str(path)
    return env


def _load(var: str, env: Mapping[str, str]) -> object:
    return load_db_config(env) if var == MIGRATE else load_serve_config(env)


@pytest.mark.parametrize("var", (*DSN_VARS, MIGRATE))
@pytest.mark.parametrize("mode", REFUSED_MODES)
@pytest.mark.parametrize("form", ["kv", "uri"])
def test_dsn_without_required_tls_is_refused(
    setup: Setup,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    var: str,
    mode: str | None,
    form: str,
) -> None:
    pw = f"CANARY-T-{secrets.token_hex(6)}"
    setup.canaries += (pw,)
    if form == "kv":
        text = dsn("bitscan_app", pw, mode)
    else:
        query = f"?sslmode={mode}" if mode is not None else ""
        text = f"postgresql://bitscan_app:{pw}@{HOST}:5432/bitscan{query}"
    with pytest.raises(ConfigError) as err:
        _load(var, _with_dsn(setup, var, text))
    assert var in str(err.value)
    assert_no_leak(setup, capsys, caplog, err.value)


@pytest.mark.parametrize("var", (*DSN_VARS, MIGRATE))
@pytest.mark.parametrize("mode", ACCEPTED_MODES)
@pytest.mark.parametrize("form", ["kv", "uri", "kv-spaced"])
def test_dsn_with_required_tls_is_accepted(
    setup: Setup, var: str, mode: str, form: str
) -> None:
    if form == "kv":
        text = dsn("bitscan_app", "pw", mode)
    elif form == "kv-spaced":
        text = dsn("bitscan_app", "pw", None) + f" sslmode = {mode}"
    else:
        text = f"postgresql://bitscan_app:pw@{HOST}:5432/bitscan?sslmode={mode}"
    _load(var, _with_dsn(setup, var, text))


@pytest.mark.parametrize("var", (*DSN_VARS, MIGRATE))
def test_sslmode_outside_the_dsn_does_not_count(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, var: str
) -> None:
    monkeypatch.setenv("PGSSLMODE", "require")
    env = _with_dsn(setup, var, dsn("bitscan_app", "pw", None)) | {
        "PGSSLMODE": "require"
    }
    with pytest.raises(ConfigError) as err:
        _load(var, env)
    assert var in str(err.value)
    env = _with_dsn(setup, var, "service=bitscan")
    with pytest.raises(ConfigError):
        _load(var, env)


@pytest.mark.parametrize("var", (*DSN_VARS, MIGRATE))
def test_last_sslmode_wins_like_libpq(setup: Setup, var: str) -> None:
    text = dsn("bitscan_app", "pw", "require") + " sslmode=disable"
    with pytest.raises(ConfigError):
        _load(var, _with_dsn(setup, var, text))


# --- CHK-M1-015: unparsable DSN leaks nothing ---------------------------------


@pytest.mark.parametrize(
    "template",
    [
        "host={host} password='{pw} sslmode=require",
        "host={host} password={pw} =oops sslmode=require",
        "postgresql://u:{pw}@[{host}/bitscan?sslmode=require",
        "host={host} password={pw} nosuchkey=1 sslmode=require",
    ],
    ids=["unterminated-quote", "missing-key", "bad-uri", "unknown-key"],
)
@pytest.mark.parametrize("var", (*DSN_VARS, MIGRATE))
def test_unparsable_dsn_is_refused_without_quoting_it(
    setup: Setup,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    template: str,
    var: str,
) -> None:
    pw = f"CANARY-P-{secrets.token_hex(6)}"
    setup.canaries += (pw,)
    text = template.format(host=HOST, pw=pw)
    with pytest.raises(ConfigError) as err:
        _load(var, _with_dsn(setup, var, text))
    assert var in str(err.value)
    assert_no_leak(setup, capsys, caplog, err.value)


# --- CHK-M1-016 / -017: profile separation ------------------------------------


def test_serve_profile_never_reads_the_migrate_dsn(setup: Setup) -> None:
    env = serve_env(setup) | {MIGRATE: str(setup.dir / "does" / "not" / "exist")}
    rec = RecordingEnv(env)
    load_serve_config(rec)
    assert MIGRATE not in rec.read
    assert not any(k.startswith("BITSCAN_MIGRATE") for k in rec.read)


def test_db_profile_needs_only_the_migrate_dsn(
    setup: Setup, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    rec = RecordingEnv({MIGRATE: setup.env[MIGRATE]})
    cfg = load_db_config(rec)
    assert isinstance(cfg, DbConfig)
    assert isinstance(cfg.migrate_dsn, SecretStr)
    assert cfg.migrate_dsn.get_secret_value() == setup.dsns[MIGRATE]
    assert set(rec.read) <= {MIGRATE}
    assert_no_leak(setup, capsys, caplog, cfg, cfg.migrate_dsn)


def test_db_profile_ignores_the_serve_variables(setup: Setup) -> None:
    env = dict(setup.env)
    env["BITSCAN_DB_DSN_FILE"] = str(setup.dir / "missing")
    rec = RecordingEnv(env)
    load_db_config(rec)
    assert set(rec.read) <= {MIGRATE}


@pytest.mark.parametrize("how", ["unset", "empty", "missing-file"])
def test_db_profile_names_the_migrate_variable(
    setup: Setup,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    how: str,
) -> None:
    env = {
        "unset": {},
        "empty": {MIGRATE: ""},
        "missing-file": {MIGRATE: str(setup.dir / "nope")},
    }[how]
    err = load_error(env, db=True)
    assert MIGRATE in str(err)
    assert_no_leak(setup, capsys, caplog, err)


# --- CHK-M1-019: opaque values, no network ------------------------------------


def _no_network(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("network access attempted")


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("BITSCAN_VAULT_ADDR", "not a url"),
        ("BITSCAN_VAULT_ADDR", "vault:k"),
        ("BITSCAN_TOTP_KEY_REF", "  odd ref with spaces "),
        ("BITSCAN_AUDIT_SINK", "syslog://x"),
        ("BITSCAN_AUDIT_SINK", "https://sink.example/ingest?x=1"),
    ],
)
def test_opaque_values_are_kept_and_nothing_connects(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, var: str, value: str
) -> None:
    import psycopg

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket, "getaddrinfo", _no_network)
    monkeypatch.setattr(psycopg, "connect", _no_network)
    cfg = load_serve_config(serve_env(setup) | {var: value})
    attr = {
        "BITSCAN_VAULT_ADDR": "vault_addr",
        "BITSCAN_TOTP_KEY_REF": "totp_key_ref",
        "BITSCAN_AUDIT_SINK": "audit_sink",
    }[var]
    assert getattr(cfg, attr) in (value, value.strip())


# --- CHK-M1-025: BITSCAN_LISTEN -----------------------------------------------


@pytest.mark.parametrize(
    ("value", "host", "port"),
    [
        ("0.0.0.0:8443", "0.0.0.0", 8443),  # noqa: S104  # parsed, never bound
        ("127.0.0.1:1", "127.0.0.1", 1),
        ("host.example:443", "host.example", 443),
        ("[::1]:65535", "::1", 65535),
    ],
)
def test_valid_listen_addresses(setup: Setup, value: str, host: str, port: int) -> None:
    cfg = load_serve_config(serve_env(setup) | {"BITSCAN_LISTEN": value})
    assert cfg.listen_port == port
    assert cfg.listen_host.strip("[]") == host


@pytest.mark.parametrize(
    "value",
    [
        "8443",
        ":8443",
        "host:",
        "host:0",
        "host:65536",
        "host:-1",
        "host:abc",
        "host:+80",
        "host: 80",
        "::1:8443",
        "[::1]",
        "host:８０",
        "host:" + "9" * 5000,
    ],
    ids=lambda v: v if len(v) < 20 else "5000-digit-port",
)
def test_invalid_listen_addresses_name_the_variable(setup: Setup, value: str) -> None:
    err = load_error(serve_env(setup) | {"BITSCAN_LISTEN": value})
    assert "BITSCAN_LISTEN" in str(err)
