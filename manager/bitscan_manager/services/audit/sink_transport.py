"""Audit sink transports for BITSCAN_AUDIT_SINK (TS §5.3 L1051, §8.6 L1315; #24).

syslog+tls://host[:port] sends one RFC 5424 message per entry with RFC 5425
octet-counted framing. https://... POSTs one entry per request as a JSON object;
a 2xx acknowledges exactly that entry. Both verify the sink's certificate
against the system CA store with TLS 1.2 or later. Plain transports are refused
when the transport is built. No error message holds entry content.
"""

import json
import os
import socket
import ssl
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

import httpx

from bitscan_manager.config.startup import ConfigError

SYSLOG_TLS_PORT: Final = 6514  # RFC 5425
APP_NAME: Final = "bitscan-manager"
PRI: Final = 13 * 8 + 6  # facility 13 "log audit", severity 6 "informational"
_BOM: Final = b"\xef\xbb\xbf"  # RFC 5424 §6.4: a UTF-8 MSG starts with the BOM
_VARIABLE: Final = "BITSCAN_AUDIT_SINK"


@dataclass(frozen=True)
class SinkRecord:
    """Every audit_log column, in the text form that was hashed (#38)."""

    audit_id: int
    actor: str
    action: str
    target: str | None
    detail_text: str | None
    at_text: str
    prev_hash: str
    row_hash: str

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> "SinkRecord":
        return cls(**{name: data[name] for name in cls.__dataclass_fields__})


def record_json(record: SinkRecord) -> bytes:
    data = json.dumps(record.to_wire(), sort_keys=True, separators=(",", ":"))
    return data.encode("utf-8")


class DeliveryError(Exception):
    """delivered = how many leading records the sink accepted before the error."""

    def __init__(self, reason: str, delivered: int = 0) -> None:
        super().__init__(f"audit sink delivery failed: {reason}")
        self.delivered = delivered


class SinkTransport(Protocol):
    def send(self, records: Sequence[SinkRecord]) -> None: ...  # all, or raise

    def close(self) -> None: ...


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _msgid(action: str) -> str:
    ok = action and len(action) <= 32 and all(33 <= ord(c) <= 126 for c in action)
    return action if ok else "-"


def syslog_frame(record: SinkRecord, hostname: str, procid: str) -> bytes:
    header = f"<{PRI}>1 {record.at_text} {hostname} {APP_NAME} {procid}"
    message = f"{header} {_msgid(record.action)} - ".encode("ascii")
    message += _BOM + record_json(record)
    return str(len(message)).encode("ascii") + b" " + message


class SyslogTlsTransport:
    def __init__(
        self, host: str, port: int, timeout_s: float, context: ssl.SSLContext
    ) -> None:
        self._host, self._port, self._timeout = host, port, timeout_s
        self._context = context
        self._sock: ssl.SSLSocket | None = None
        name = socket.gethostname().split(".")[0]
        self._hostname = name if name.isascii() and name.isprintable() else "-"
        self._procid = str(os.getpid())

    def _connect(self) -> ssl.SSLSocket:
        if self._sock is None:
            raw = self._tcp_connect()
            try:
                self._sock = self._context.wrap_socket(raw, server_hostname=self._host)
            except BaseException:
                raw.close()
                raise
        return self._sock

    def _tcp_connect(self) -> socket.socket:
        """Like socket.create_connection, but the timeout bounds the whole
        attempt across every address the host name resolves to. The name
        lookup itself (getaddrinfo) is not bounded by it."""
        deadline = time.monotonic() + self._timeout
        infos = socket.getaddrinfo(self._host, self._port, type=socket.SOCK_STREAM)
        error: OSError = TimeoutError("connect timed out")
        for family, kind, proto, _, address in infos:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock = socket.socket(family, kind, proto)
            sock.settimeout(remaining)
            try:
                sock.connect(address)
            except OSError as exc:
                sock.close()
                error = exc
                continue
            sock.settimeout(self._timeout)
            return sock
        raise error

    def send(self, records: Sequence[SinkRecord]) -> None:
        sent = 0
        failure: str | None = None
        try:
            sock = self._connect()
            for record in records:
                sock.sendall(syslog_frame(record, self._hostname, self._procid))
                sent += 1
        except (OSError, ValueError) as exc:
            failure = type(exc).__name__
            self.close()
        if failure is not None:
            raise DeliveryError(failure, sent)

    def close(self) -> None:
        if self._sock is not None:
            sock, self._sock = self._sock, None
            try:
                # close_notify, reading what the peer sent (TLS 1.3 tickets);
                # closing with unread data would reset the connection and
                # could drop frames the sink has not read yet.
                sock.unwrap().close()
            except (OSError, ValueError):
                sock.close()


class HttpsTransport:
    def __init__(self, url: str, timeout_s: float, context: ssl.SSLContext) -> None:
        self._url = url
        self._client = httpx.Client(
            # trust_env=False: no proxy or netrc from the service environment.
            verify=context,
            timeout=timeout_s,
            follow_redirects=False,
            trust_env=False,
        )

    def send(self, records: Sequence[SinkRecord]) -> None:
        for sent, record in enumerate(records):
            failure: str | None = None
            try:
                response = self._client.post(
                    self._url,
                    content=record_json(record),
                    headers={"Content-Type": "application/json"},
                )
                if not response.is_success:
                    failure = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                failure = type(exc).__name__
            if failure is not None:
                raise DeliveryError(failure, sent)

    def close(self) -> None:
        self._client.close()


def transport_from_url(
    value: str, *, timeout_s: float = 5.0, ssl_context: ssl.SSLContext | None = None
) -> SinkTransport:
    """Build the transport for a BITSCAN_AUDIT_SINK value. Errors name the
    variable only, never the value. ssl_context exists for tests."""
    port: int | None = None
    parsed = True
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        parsed = False
    # Raised outside the except block, so no parser error (which can quote
    # part of the value) is chained.
    if not parsed:
        raise ConfigError(f"{_VARIABLE} is not a valid URL")
    context = ssl_context or _tls_context()
    if parts.username is not None or parts.password is not None:
        raise ConfigError(f"{_VARIABLE} must not contain credentials")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError(f"{_VARIABLE} has an invalid port")
    if not parts.hostname:
        raise ConfigError(f"{_VARIABLE} must name a host")
    if parts.scheme == "syslog+tls" and parts.path in ("", "/") and not parts.query:
        return SyslogTlsTransport(
            parts.hostname, port or SYSLOG_TLS_PORT, timeout_s, context
        )
    if parts.scheme == "https":
        return HttpsTransport(value.strip(), timeout_s, context)
    raise ConfigError(f"{_VARIABLE} must be a syslog+tls:// or https:// URL")
