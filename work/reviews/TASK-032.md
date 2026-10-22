# TASK-032 REVIEW: audit sink transports

Reviewer: reviewer. Date: 2026-10-21. REQ-053: the send half of (1), and (3), (4). Spec: TS §5.3 L1051, TS §8.6 L1315 (`BITSCAN_AUDIT_SINK`: syslog or HTTPS), TS §8.1 L1240, L1256; #24 as decided 2026-10-21 (`syslog+tls://` RFC 5424 with RFC 5425 framing, and `https://` JSON POST; plain transports refused); decisions 2026-10-21 "M2 test-plan answers" (2) (one entry per POST). Plan: `work/plans/TASK-034.md`, section TASK-032. Inputs: `work/reports/TASK-032-impl.md` (revision 1, which carries my pre-review nits), `work/reports/TASK-032-test.md` (PASS, CHK-M2-100 to -106, 15 of 15 mutations red).

File reviewed: `manager/bitscan_manager/services/audit/sink_transport.py`.

Verdict: APPROVED

This task is not on the TS §8.2 two-approval list. The lead recommends a second look at the sink path (TASK-034), because the sink is the only control against a full rewrite of the chain.

## Pre-review nits (round 0), all fixed in revision 1

1. The HTTPS client now ignores proxy and netrc settings from the environment (`trust_env=False`, `:167`). The same is due in the TASK-030 vault client.
2. `_tcp_connect` now documents that the DNS lookup is not bounded by `timeout_s`.
3. Ports outside 1 to 65535, port 0 included, are refused when the transport is built (`:209`). The tester also found port 0 silently mapping to 6514 before this fix.

## What was checked

- **Every column, in the hashed form (REQ-053 (3)).** `SinkRecord` carries all eight `audit_log` columns. `detail_text` and `at_text` are the exact strings that were hashed (#38). The tester re-hashed the delivered fields to `row_hash` and checked the chain links.
- **Wire formats (#24).**
  - syslog: RFC 5424 with PRI 110 (facility 13, log audit), the UTF-8 BOM before the MSG, and octet-counted framing (RFC 5425 §4.3). MSGID is the `action` only when it is valid printable ASCII.
  - HTTPS: one compact JSON object per POST; a 2xx acknowledges exactly that entry. Redirects are not followed and the response body is never read into an error.
- **TLS (REQ-053 (4)).** `ssl.create_default_context()` with the system CA store and host-name check, TLS 1.2 minimum. The tester showed an untrusted certificate and TLS 1.0 and 1.1 are refused on both transports. `ssl_context` is a test hook only.
- **Refusals at build time.** `udp`, `tcp`, `syslog`, `syslog+tcp`, `http` and any other scheme are refused, as are user info, a missing host, a bad port and a `syslog+tls` URL with a path or query. Messages name the variable only, and no parser error is chained.
- **Errors.** `DeliveryError` holds the exception type or the HTTP status, plus `delivered`, never record content. The syslog connect deadline covers every resolved address.
- **Gates (my run).** ruff, format and `mypy --strict` are clean. `test_sink_transport.py` passes, and the file is 98 % covered; the misses are `:120` and `:155-156`, a deadline-exhausted branch and the `unwrap()` fallback, both defensive. G5 is at 97.73 %.
- **Scope.** 1 file, about 180 lines.

## Findings

None block approval.

1. **note for TASK-034 and the user: syslog has no delivery receipt.** Over `syslog+tls://`, a frame counts as `delivered` once `sendall` returns (`:133-145`), because RFC 5425 has no acknowledgement. If the connection breaks after that, frames still in the kernel or TLS buffers, or not yet read by the sink, are lost. The shipper will have acknowledged them and removed them from the disk queue, so they are not resent. HTTPS acknowledges each entry. The TS §5.3 control is therefore stronger over HTTPS. If syslog is used, the external store should check `audit_id` for gaps (the chain makes a gap detectable). This is how RFC 5425 works, not a code defect. I suggest README or runbook text in TASK-045.
2. **nit.** A test-only line: `test_sink_transport.py:310-311` uses the deprecated `ssl.TLSVersion.TLSv1` and `TLSv1_1`, which give 9 DeprecationWarnings. That is fine until the suite runs with `-W error` (decisions 2026-10-20).
3. **note for TASK-034.** `DeliveryError.delivered` is the count of leading records accepted. The shipper must acknowledge exactly those, and resend from the next one.
