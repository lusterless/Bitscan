"""Start-up configuration (TS §8.6, §8.7).

Secrets are read only from the files named by the ``*_FILE`` variables. Error
messages name the variable and the problem, never a value or file content.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr

TLS_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})
DEFAULT_LISTEN = "0.0.0.0:8443"
DEFAULT_BITS_DIR = "/var/lib/bitscan/bits"
MAX_SECRET_FILE_BYTES = 64 * 1024


class ConfigError(Exception):
    """Message names the variable and the problem only; never a value or file content."""


@dataclass(frozen=True)
class ServeConfig:
    db_dsn: SecretStr
    retention_dsn: SecretStr
    vault_addr: str
    totp_key_ref: str
    vault_token: SecretStr
    tls_cert_file: Path
    tls_key_file: Path
    audit_sink: str
    listen_host: str
    listen_port: int
    bits_dir: Path
    uploads_dir: Path


@dataclass(frozen=True)
class DbConfig:
    migrate_dsn: SecretStr


class _Loader:
    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ
        self.errors: list[str] = []

    def required(self, name: str) -> str:
        value = (self._environ.get(name) or "").strip()
        if not value:
            self.errors.append(f"{name} is not set")
        return value

    def optional(self, name: str, default: str) -> str:
        return (self._environ.get(name) or "").strip() or default

    def secret_file(self, name: str) -> SecretStr:
        path = self.required(name)
        if not path:
            return SecretStr("")
        # No exception is raised inside an except block, so no OSError or
        # UnicodeDecodeError (which can hold file bytes) is ever chained.
        data: bytes | None = None
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_SECRET_FILE_BYTES + 1)
        except OSError:
            pass
        if data is None:
            self.errors.append(f"{name}: cannot read the file it points to")
            return SecretStr("")
        if len(data) > MAX_SECRET_FILE_BYTES:
            self.errors.append(f"{name}: file is larger than 64 KiB")
            return SecretStr("")
        text: str | None = None
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            pass
        if text is None:
            self.errors.append(f"{name}: file is not valid UTF-8")
            return SecretStr("")
        if not text:
            self.errors.append(f"{name}: file is empty")
        return SecretStr(text)

    def dsn_file(self, name: str) -> SecretStr:
        dsn = self.secret_file(name)
        if dsn.get_secret_value():
            self._check_dsn(name, dsn.get_secret_value())
        return dsn

    def _check_dsn(self, name: str, dsn: str) -> None:
        # Imported here so profiles that read no DSN never load psycopg.
        import psycopg
        from psycopg.conninfo import conninfo_to_dict

        params: dict[str, object] | None = None
        if "\x00" not in dsn:
            try:
                params = dict(conninfo_to_dict(dsn))
            except psycopg.Error:
                # psycopg's message can quote the DSN, password included.
                pass
        if params is None:
            self.errors.append(f"{name}: not a valid PostgreSQL DSN")
            return
        # sslmode must be in the DSN itself; PGSSLMODE and service files do
        # not count (question #45, all three DSNs).
        if params.get("sslmode") not in TLS_SSLMODES:
            self.errors.append(
                f"{name}: DSN must set sslmode to require, verify-ca or verify-full"
            )

    def readable_file(self, name: str) -> Path:
        value = self.required(name)
        path = Path(value)
        if value and not (path.is_file() and os.access(path, os.R_OK)):
            self.errors.append(f"{name}: file is missing or unreadable")
        return path

    def listen(self, name: str) -> tuple[str, int]:
        value = self.optional(name, DEFAULT_LISTEN)
        host, sep, port = value.rpartition(":")
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
            valid_host = bool(host)
        else:
            valid_host = bool(host) and ":" not in host and "[" not in host
        valid_port = port.isascii() and port.isdigit() and 1 <= int(port) <= 65535
        if not (sep and valid_host and valid_port):
            self.errors.append(f"{name} must be host:port with a port from 1 to 65535")
            return "", 0
        return host, int(port)

    def finish(self) -> None:
        if self.errors:
            raise ConfigError("\n".join(self.errors))


def load_serve_config(environ: Mapping[str, str]) -> ServeConfig:
    loader = _Loader(environ)
    db_dsn = loader.dsn_file("BITSCAN_DB_DSN_FILE")
    retention_dsn = loader.dsn_file("BITSCAN_RETENTION_DSN_FILE")
    # Vault address, key reference and audit sink stay opaque until #24 fixes
    # the vault API and the sink wire format.
    vault_addr = loader.required("BITSCAN_VAULT_ADDR")
    totp_key_ref = loader.required("BITSCAN_TOTP_KEY_REF")
    vault_token = loader.secret_file("BITSCAN_VAULT_TOKEN_FILE")
    tls_cert_file = loader.readable_file("BITSCAN_TLS_CERT_FILE")
    tls_key_file = loader.readable_file("BITSCAN_TLS_KEY_FILE")
    audit_sink = loader.required("BITSCAN_AUDIT_SINK")
    listen_host, listen_port = loader.listen("BITSCAN_LISTEN")
    bits_dir = Path(loader.optional("BITSCAN_BITS_DIR", DEFAULT_BITS_DIR))
    loader.finish()
    return ServeConfig(
        db_dsn=db_dsn,
        retention_dsn=retention_dsn,
        vault_addr=vault_addr,
        totp_key_ref=totp_key_ref,
        vault_token=vault_token,
        tls_cert_file=tls_cert_file,
        tls_key_file=tls_key_file,
        audit_sink=audit_sink,
        listen_host=listen_host,
        listen_port=listen_port,
        bits_dir=bits_dir,
        uploads_dir=bits_dir / "uploaded",
    )


def load_db_config(environ: Mapping[str, str]) -> DbConfig:
    loader = _Loader(environ)
    migrate_dsn = loader.dsn_file("BITSCAN_MIGRATE_DSN_FILE")
    loader.finish()
    return DbConfig(migrate_dsn=migrate_dsn)
