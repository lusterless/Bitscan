# TASK-045 IMPL report: `bitscan-manager serve`

REQ: REQ-057, REQ-039, REQ-047 (the flush), REQ-053 (the shipper's lifecycle). Spec: TS §8.7 L1343–L1371, TS §8.6, TS §6 L1056, TS §2.3 L118, TS §2.1 L103. Plan: `work/plans/TASK-045.md`.

Lead carry-overs, all done:
- per-connection database time bounds;
- uvicorn with `access_log=False` and `log_config=None`, and `limit_concurrency` left unset;
- the vault client closed on shutdown;
- the minute flusher's retry rules;
- README guidance on the sink and the OpenBao token.

A second look at the TLS set-up is recommended.

## Files (3)

- `manager/bitscan_manager/cli/serve.py`: new, 230 non-blank lines including docstrings. That is above the 190 estimate, because the flusher retry rules and the database bounds arrived after planning.
- `manager/bitscan_manager/cli/__init__.py`: `serve` is routed to `serve_main(os.environ)` through a lazy import, and the help epilog lists `serve`. `bits rebuild`, `users …` and unknown commands keep the M0 behaviour.
- `README.md`:
  - status line;
  - the variable table, now that the vault and sink formats are fixed;
  - "Starting the app": how it listens, `SIGHUP`, `SIGTERM`, logs, start-up errors, the health routes, the audit sink (prefer `https://`; with `syslog+tls://` watch for `audit_id` gaps), OpenBao (a periodic or non-expiring token limited to the Transit encrypt and decrypt paths for the key; replacing it is an operational step) and sign-in.

## Start-up (`serve_main(environ, *, queue_dir=AUDIT_QUEUE_DIR)`)

1. `configure_logging()`: JSON lines on stderr (TASK-027).
2. `load_serve_config(environ)`. A `ConfigError` prints one `serve: <line>` per problem and returns 2. `BITSCAN_MIGRATE_DSN_FILE` is never read.
3. `make_tls_context(cert, key)`:
   - `SSLContext(PROTOCOL_TLS_SERVER)` with `minimum_version = TLSv1_2` and `load_cert_chain`;
   - no client certificates (TS §2.2); Python's default ciphers.

   On failure it returns 2 with `serve: BITSCAN_TLS_CERT_FILE and BITSCAN_TLS_KEY_FILE are not a usable certificate and key`. The message is printed outside the `except` block, so no key material can be chained.
4. `build_runtime(config, tls, queue_dir)`:
   - `AppDatabase(bounded_dsn(db_dsn))`;
   - `transport_from_url(BITSCAN_AUDIT_SINK)`, which refuses plain transports with `ConfigError`;
   - `DiskQueue(queue_dir)`, which creates the folder 0700 or refuses an unsafe one with `QueueError`;
   - `Shipper(PgAuditTail(db), queue, transport, clock, DbOutageAudit(db))`, which is also the runtime's `SinkGate`;
   - `VaultCipher(...)`, with no network call (#58 (a));
   - `RateLimiter(clock)` and a `FailedCheckFlusher`;
   - `ServeLifecycle`.

   A `ConfigError` or `QueueError` here returns 2; both messages name the setting only.
5. One start-up log line with the listen address, `TLS 1.2+` and the sink **scheme** only.
6. Run uvicorn through `_Server(uvicorn.Config(...))`:
   - `create_app(runtime)`, host and port from `BITSCAN_LISTEN`, `workers=1`, `lifespan="on"`;
   - `ssl_context_factory=lambda _c, _d: tls`, which hands over **our** context object;
   - `proxy_headers=False` (#55 (d)) and `server_header=False`;
   - `access_log=False` (`RequestLog` writes access records without query strings) and `log_config=None` (keeps the JSON handler);
   - `limit_concurrency` **not set**, because uvicorn's own 503 would bypass the security headers.
7. **The uvicorn hand-over, checked against the pinned uvicorn 0.54.0:** `Config.load()` calls `ssl_context_factory(config, default_factory)` once and stores the returned object as `config.ssl`. The server then serves that same context, so `SIGHUP` can reload it in place. No `Config` subclass is needed.
8. **`_Server`** overrides only `capture_signals`. uvicorn 0.54 re-raises the caught `SIGTERM`/`SIGINT` after a graceful shutdown, which would end the process killed by the signal. The override restores the original handlers without re-raising, so a graceful stop exits **0** (REQ-057 (6)). The return code is 0 if the server started, else 1 (for example, the port is in use; uvicorn logs the address).

## Database time bounds (`bounded_dsn`)

Decisions 2026-10-21, "Database time bounds". The DSN that `load_serve_config` has already checked is parsed with `conninfo_to_dict` and rebuilt with `make_conninfo`, adding:
- `keepalives=1`, `keepalives_idle=60`, `keepalives_interval=15`, `keepalives_count=4`;
- `tcp_user_timeout=300000` ms;
- `options` with `-c statement_timeout=300000` appended to any existing options.

Every pooled connection, and the separate ping probe, therefore carries the bounds from the moment it connects. The ping probe overrides `options` with its own 2 s `statement_timeout`. No role, grant or schema changed.

**Known limit:** a frozen server whose network stack still answers keepalives is caught only by `statement_timeout`, and only once the server runs again. The `/readyz` and `ping()` client-side bounds still hold.

## Lifecycle (`ServeLifecycle`, run by the `create_app` lifespan)

- **start:**
  - `db.open()`, which does not wait for the database;
  - `shipper.start()`;
  - `flusher.start()`;
  - `loop.add_signal_handler(SIGHUP, reload_certificate, tls, cert, key)`, only where `signal.SIGHUP` exists, so the module still imports on Windows.
- **stop:**
  - remove the `SIGHUP` handler;
  - `flusher.stop()`: final `drain(final=True)` and write;
  - `shipper.stop()`: the queue stays on disk;
  - `cipher.close()`: the vault client;
  - `db.close()`.
- **`reload_certificate`** loads the new pair into a probe context first. If that works, it calls `load_cert_chain` on the live context: new handshakes use the new certificate, and the PID and listening socket stay the same. On `OSError` or `ssl.SSLError` it logs `tls reload failed, keeping the current certificate (<type>)` and keeps the old one. The log line holds no path content and no key bytes.
- **`FailedCheckFlusher`:**
  - Every 10 s it adds `limits.drain()` to its held list. `drain` also prunes expired limiter keys, so this happens even while writes fail.
  - It writes each held entry in order, each in its own transaction: `raise_alert(kind="token_check_failures")` when `entry.alert`, else `append_entry`, with actor `system`, action `auth.token_check_failed` and detail `{ip, window_start, count}`. The shipper is woken on commit.
  - On the first failed write it stops and keeps that entry and the rest for the next flush, so order is kept.
  - At most 10,000 entries are held; the oldest are dropped first, and only the dropped **number** is logged.
  - `stop()` joins the thread and runs a final flush that includes the current minute.

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager`, `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 105 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 1017 passed, 278 skipped (pg), 97.13 %. Failures: `test_cli.py::test_refused_commands_touch_no_env_socket_or_db[serve]` is **expected**, because REQ-057 (8) and REQ-008 are narrowed again and `serve` is now real; please update it. The TASK-038 test items are covered in the TASK-038 revision 1 note |
| Windows smoke (scratch driver, deleted), `serve` started as a subprocess with a self-signed `localhost` cert. The DSNs pointed at a closed port with a canary password, OpenBao and the sink at closed ports, and `BITSCAN_MIGRATE_DSN_FILE` at a missing file | (1) |
| Start-up refusals | `BITSCAN_AUDIT_SINK=http://x/` printed `serve: BITSCAN_AUDIT_SINK must be a syslog+tls:// or https:// URL`; a DSN file used as the key printed the TLS line; an empty `BITSCAN_VAULT_ADDR` printed `serve: BITSCAN_VAULT_ADDR is not set`. Each exited 2 with no canary |
| `SIGHUP` reload, a `SIGTERM` exit code on Linux, bind errors, TLS 1.0 | NOT RUN here: Windows has no `SIGHUP`. G27 (`tests/test_serve_linux.py`) runs on Linux |

(1) Smoke results:
- `/healthz` returned 200 `{"status":"ok"}` with HSTS. `/readyz` returned 503 `{"…", "detail": "db", …}`.
- A TLS 1.1 handshake was refused; TLS 1.2 and TLS 1.3 worked. Plain HTTP on the port got the connection dropped.
- `CTRL_BREAK` (the Windows stand-in for `SIGTERM`) stopped the server: the lifespan shutdown ran, and the process exited **0**.
- No canary appeared in stdout or stderr. Every line was JSON, including the scrubbed `psycopg.pool` warnings.

## For the tester (TP-M2-22, G27)

- Use `serve_main(environ, queue_dir=tmp)` or a subprocess, as in the smoke run above. The `AUDIT_QUEUE_DIR` default is the production path.
- `bounded_dsn` is importable for a unit check of the added parameters.
- REQ-057 (6): count the flushed entries after `SIGTERM` with a database up. A single entry for the current minute is written by the final flush.

## Lead rulings (decisions.md 2026-10-22, "Lead rulings on TASK-045")

Both points were accepted: a graceful `SIGTERM` exits 0 (the `capture_signals` override), and `serve.py` may stay at about 230 lines.
