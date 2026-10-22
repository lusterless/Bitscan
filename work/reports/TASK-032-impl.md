# TASK-032 IMPL report: audit sink transports

REQ: REQ-053 (transport part: (3), (4), and the send half of (1)). Spec: TS §5.3 L1051, TS §8.6 L1315 (`BITSCAN_AUDIT_SINK`: syslog or HTTPS); #24 as decided 2026-10-21. The user's changes: both `syslog+tls://` (RFC 5424, RFC 5425 framing) and `https://` (JSON POST) are supported; plain udp, tcp and http are refused; HTTPS sends **one entry per POST** and a 2xx acknowledges exactly that entry ("M2 test-plan answers" (2)). Plan: `work/plans/TASK-034.md`, section TASK-032.

## Files (1)

- `manager/bitscan_manager/services/audit/sink_transport.py`: new, 176 non-blank lines including docstrings (the estimate was 160).

## Interface

```python
@dataclass(frozen=True)
class SinkRecord:  audit_id, actor, action, target, detail_text, at_text, prev_hash, row_hash
    def to_wire(self) -> dict[str, Any]          # dataclasses.asdict
    @classmethod
    def from_wire(cls, data) -> SinkRecord       # for the TASK-033 disk queue round trip
def record_json(record) -> bytes                 # compact, sorted keys, ASCII escapes
class DeliveryError(Exception):  .delivered: int  # leading records the sink accepted
class SinkTransport(Protocol):  send(records) -> None  /  close() -> None
def syslog_frame(record, hostname, procid) -> bytes
class SyslogTlsTransport, class HttpsTransport
def transport_from_url(value, *, timeout_s=5.0, ssl_context=None) -> SinkTransport
```

Two additions to the plan:
- `DeliveryError.delivered` tells the TASK-034 shipper how many leading records were accepted, so it can acknowledge those (one HTTPS POST per entry).
- `ssl_context` lets tests trust a local CA. `serve` never passes it.

## Wire format

- **Record JSON:** keys are the `SinkRecord` field names:
  - `audit_id`, `actor`, `action`, `target`;
  - `detail_text`, which is PostgreSQL's `detail::text` string exactly as hashed (#38), not re-parsed;
  - `at_text` (`YYYY-MM-DDTHH:MM:SS.ffffffZ`);
  - `prev_hash`, `row_hash`.

  The receiver can recompute `compute_row_hash(prev_hash, HashInput(audit_id, actor, action, target, detail_text, at_text))` and compare it with `row_hash` (REQ-053 (3)).
- **`syslog+tls://host[:port]`** (default port 6514, RFC 5425). One RFC 5424 message per record:
  - the message is `<110>1 <at_text> <short hostname> bitscan-manager <pid> <MSGID> - BOM<record JSON>`;
  - PRI 110 is facility 13 ("log audit") with severity 6 ("informational"). #24 names no facility; 13 is the RFC 5424 audit facility;
  - MSGID is the `action` when it is 1–32 printable ASCII characters, otherwise `-`;
  - the MSG starts with the UTF-8 BOM, as RFC 5424 §6.4 requires;
  - framing is octet-counted: `<byte length> <message>` (RFC 5425 §4.3).

  The TLS connection is opened on first use and kept. Any error closes it and raises `DeliveryError(<exception type>, delivered=<frames written>)`. Writing a frame with `sendall` counts as delivered, because syslog over TLS has no application acknowledgement (at-least-once is up to the shipper, #51). `close()` sends `close_notify` with `unwrap()`. Without it, closing on Windows with unread TLS 1.3 tickets reset the connection, and the fake sink lost frames it had not read (seen in 1 of 2 early scratch runs; 0 of 30 after the fix).
- **`https://…`.** For each record: `POST <url>` with body = the record JSON object and `Content-Type: application/json`. Redirects are not followed. A 2xx acknowledges that record. Any other status raises `DeliveryError("HTTP <status>", delivered=<index>)`, and the response body is never read into the error. A transport error raises `DeliveryError(<httpx exception type>, delivered=<index>)`. There are no credentials (#24).
- **TLS** for both: `ssl.create_default_context()` (the system CA store with host-name check), minimum TLS 1.2.
- **Refused when the transport is built** (`ConfigError`, from `config/startup.py`). Messages name `BITSCAN_AUDIT_SINK` only, never the value, and no parser error is chained:
  - any scheme other than `syslog+tls` or `https`: `udp://`, `tcp://`, `syslog://`, `syslog+tcp://`, `http://`, `ftp://`. Schemes are compared lower-case;
  - a URL with user info;
  - a missing host;
  - a bad port or an unparsable URL;
  - a `syslog+tls` URL with a path or query.

## Timeouts

- Syslog connect: `_tcp_connect()` resolves the host and tries each address with the **remaining** time, so `timeout_s` bounds the whole connect attempt. `socket.create_connection` would apply it per address, which took 2 s for `localhost` (::1 then 127.0.0.1) with `timeout_s=1` on Windows. The same timeout then applies to the TLS handshake and each send.
- HTTPS uses `httpx.Client(timeout=timeout_s)`, so the timeout applies per phase. httpx connects per resolved address, so `localhost` with a closed port took 2.08 s with `timeout_s=1`, and `127.0.0.1` 1.03 s. A tighter overall bound for HTTPS would need a worker thread; tell me if the tester's criterion needs it.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check`, `ruff format --check`, `mypy --strict` on `manager/bitscan_manager` | pass |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | **gate FAILS at 66.21 %** until TP-M2-10 adds tests (`sink_transport.py` has 140 statements, 0 % covered). There were also 2 failures in tester files that track revisions now handed back: `test_runtime.py` ping (TASK-025 rev 1) and `test_passwords.py` (TASK-028 rev 1, now passing) |
| Scratch script (deleted): a self-signed `localhost` cert made with Git Bash `openssl`, and a local TLS syslog listener | 2 frames arrived. Each parsed as `<110>1 2026-10-21T01:02:03.000004Z <host> bitscan-manager <pid> auth.login - ` + BOM + JSON, and each re-hashed to its `row_hash` |
| Scratch: the same listener with the system store (CA not trusted) | `DeliveryError: SSLCertVerificationError`, delivered 0 |
| Scratch: closed port, `timeout_s=1`, `localhost` and `127.0.0.1` | `DeliveryError: TimeoutError` after 1.03 s for both (Windows retries SYN; Linux refuses at once) |
| Scratch: local HTTPS sink answering 200, 204, 500 | three POSTs, each one JSON object; `DeliveryError: HTTP 500`, delivered 2. With the CA not trusted: `ConnectError`, delivered 0 |
| Scratch: refusals | `udp://`, `tcp://`, `syslog://`, `http://`, `syslog+tcp://`, `ftp://`, `HTTP://`, `https://u:CANARY@h/x` (message without the canary), `syslog+tls://h:99999`, `syslog+tls://h:abc`, `https://[x/`, `https://`, `syslog+tls://h/path`: all `ConfigError`, with `__context__` and `__cause__` None |

## For the tester (TP-M2-10)

- Give the transport a client context that trusts your test CA: `transport_from_url(url, ssl_context=ssl.create_default_context(cafile=...))`. For the untrusted-certificate case, omit `ssl_context`.
- A fake syslog sink should read until EOF and then `unwrap()`. It must accept `close_notify` from `close()`.
- `services/audit/` counts toward G5. A Windows run reaches it with local listeners only, with no network beyond loopback.

## Revision 1 (reviewer pre-review nits; lead acceptance 2026-10-21)

- **Lead acceptance:** the lead accepted all three choices, with one condition: the TASK-034 shipper's back-off must bound a whole delivery attempt. The choices are facility 13 (PRI 110), `DeliveryError.delivered`, and an HTTPS connect bound that applies per resolved address.
- **Proxy settings ignored:** `HttpsTransport` now builds its `httpx.Client` with `trust_env=False`, so `HTTPS_PROXY`, `ALL_PROXY` and `.netrc` in the service environment cannot route or authenticate audit traffic. The same will apply to the TASK-030 vault client.
- **DNS lookup not bounded:** `_tcp_connect` now says in its docstring that the name lookup (`getaddrinfo`) is not bounded by `timeout_s`. A slow DNS server can therefore exceed it; the reviewer accepted this.
- **Ports outside 1–65535 refused:** `transport_from_url` now refuses them when the transport is built, so `syslog+tls://h:0` and `https://h:0/x` raise `ConfigError("BITSCAN_AUDIT_SINK has an invalid port")`.

Re-checked:
- ruff and mypy `--strict` pass (74 files).
- `pytest -k sink` gives 64 passed, which includes the tester's `test_sink_transport.py`.
- With `HTTPS_PROXY` set, the client has `trust_env=False`; ports 1 and 65535 are accepted.
