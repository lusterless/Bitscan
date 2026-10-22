# TASK-045 REVIEW: `bitscan-manager serve`

Reviewer: reviewer. Date: 2026-10-22. REQ-057, REQ-039, REQ-047 (the flush), REQ-053 (the shipper lifecycle). Spec: TS §8.7 L1343–L1371, TS §8.6, TS §6 L1056, TS §2.3 L118, TS §2.1 L103.

Decisions and carry-overs:
- #55 (d), #58 (a);
- 2026-10-21 "Database time bounds";
- 2026-10-22 "Lead rulings on TASK-045": a graceful SIGTERM exits 0; `serve.py` at about 230 lines;
- my carry-overs: uvicorn `access_log=False` and `log_config=None` with `limit_concurrency` unset (TASK-024, TASK-027); the vault client closed (TASK-030); the flusher drains even when writes fail (TASK-036); README guidance on the sink and the token (TASK-032, TASK-030).

Plan: `work/plans/TASK-045.md`.

Inputs:
- `work/reports/TASK-045-impl.md`;
- `work/reports/TASK-045-test.md`: PASS, rows CHK-M2-250 to -263b, G27 on Linux. CHK-M2-263a covers my uvicorn-logger point and CHK-M2-263b my flusher point, and both mutant pairs are red.

Files reviewed: `manager/bitscan_manager/cli/serve.py`, `manager/bitscan_manager/cli/__init__.py`, `README.md` (the M2 sections).

Verdict: APPROVED

TASK-045 is not on the TS §8.2 two-approval list. The lead recommends a second look at the TLS set-up; it is covered under "TLS" below.

## What was checked

- **Start-up (REQ-057 (1), (7)).**
  - `load_serve_config` runs before anything binds. Each problem prints one `serve: …` line naming the variable, and the exit code is 2.
  - An unusable certificate or key gets a fixed message printed outside the `except` block, so no key material can be chained.
  - A plain sink transport (`ConfigError`) or an unsafe queue folder (`QueueError`) also exits 2, naming the setting only.
  - `BITSCAN_MIGRATE_DSN_FILE` is never read.
  - The start-up log shows the sink scheme only.
  - The vault is not contacted at start-up (#58 (a)).
- **TLS (REQ-057 (2), (3); second look).**
  - The context is `SSLContext(PROTOCOL_TLS_SERVER)` with a TLS 1.2 minimum, Python's default ciphers and no client certificates (TS §2.2: no mTLS). This is the only certificate.
  - uvicorn gets *our* context object through `ssl_context_factory`, so a `SIGHUP` reload with `load_cert_chain` on that same context changes the certificate for new handshakes, while the PID and socket stay the same.
  - The new pair is validated in a throwaway context first, so a broken pair keeps the old one; that is logged by exception type only.
  - The tester showed on Linux that TLS 1.0 and 1.1 are refused, plain HTTP fails, and a `SIGHUP` with a good pair or a broken pair behaves as required. The G27 plants (minimum lowered to 1.0, `SIGHUP` handler removed) are red.
- **uvicorn settings.**
  - `workers=1` (TS §2.1).
  - `proxy_headers=False`, so `X-Forwarded-For` is ignored (#55 (d), REQ-057 (5)).
  - `server_header=False`.
  - `access_log=False` and `log_config=None`, so uvicorn's own loggers reach the JSON handler and never write a query string. CHK-M2-263a sweeps stdout and stderr for a query canary and an exception canary.
  - `limit_concurrency` is not set, so there is no uvicorn-written 503 without the security headers.
- **SIGTERM (REQ-057 (6), lead ruling).**
  - The `_Server.capture_signals` override restores the handlers without re-raising, so a graceful stop exits 0 and systemd records no failure.
  - The lifespan stop order is `SIGHUP` handler removed, then flusher (final drain including the current minute), then shipper (the queue stays on disk), then the vault client, then the pool. That is the right order: the flusher's final writes can still use the pool and wake the shipper before the shipper stops.
  - The tester checked the flushed count and that the queue stays intact with the sink down.
- **Database time bounds (decision 2026-10-21).** `bounded_dsn` adds keepalives, `tcp_user_timeout=300000` and `-c statement_timeout=300000`, appended to any existing `options`, to every pooled connection and the ping probe; the probe overrides the timeout with its own 2 s. No role, grant or schema changed. The known limit is documented: a frozen server whose network still answers keepalives is caught only by `statement_timeout`, once it runs again.
- **Flusher (TASK-036 carry-over).** It drains every 10 s, and draining also prunes the limiter's keys, so the limiter cannot grow without bound while writes fail. Entries whose write fails are held in order and retried first. At most 10,000 are held, the oldest dropped first, and only the dropped count is logged. A `token_check_failures` alert goes through `raise_alert` with the counter on commit.
- **README.** I checked the commands and variable names against the code: `serve`, the variable formats (`https://` vault without credentials, a key-name charset of up to 128 characters, `https://` or `syslog+tls://` sink with default port 6514), the health route bodies and the sign-in body all match. It prefers `https://` for the sink and says to watch for `audit_id` gaps with syslog, both from my TASK-032 note. The OpenBao token guidance (a periodic or non-expiring token, limited to the Transit paths) covers my TASK-030 note. It is user-guide content only.
- **Gates (my run).** ruff, format and `mypy --strict` are clean on 108 files. `test_cli.py` passes, with the `serve` refusal case updated as REQ-008 was narrowed. `test_serve_linux.py` runs on Linux only.
- **Scope.** 3 files, about 230 lines in `serve.py`. Accepted per the lead's ruling.

## Findings

None block approval.

1. **nit.** `serve.py:238`: `config.audit_sink.split(":", 1)[0]` logs the text before the first `:`. For the validated values that is `https` or `syslog+tls`, because `transport_from_url` already refused everything else and credentials before it. Using `urlsplit(...).scheme` would make that independent of the validation order.
2. **nit.** `FailedCheckFlusher.flush` runs on the flusher thread and, during `stop()`, on the event-loop thread after `join()`. If `join` times out (a write stuck for more than 15 s), the two can run at the same time over `_held`. Database writes are bounded by `statement_timeout` (5 min), not 15 s. This is a rare shutdown-only race, and the cost is a duplicate or a lost aggregated entry. Taking a lock in `flush` would remove it.
3. **note, the tester's point, accepted.** The known limit on a frozen database server is the documented residual from the user's decision. `/readyz` stays bounded at 2 s regardless.
4. **note.** Two uvicorn behaviours are relied on: 0.54's `ssl_context_factory` returning the live context, and its `capture_signals` re-raise. Both are pinned in the lock. A uvicorn upgrade must re-run G27, which the `SIGHUP` and `SIGTERM` tests do.
