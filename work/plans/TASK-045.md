# TASK-045 plan: `bitscan-manager serve`

REQs: REQ-057, REQ-039, REQ-047 (flush), REQ-053 (shipper lifecycle). Owner: impl-manager. A second look at the TLS set-up is recommended. Depends on: TASK-030 (vault cipher), TASK-034 (shipper), TASK-036 (rate limits), TASK-044 (health routes, `create_app(runtime)`). Files: `bm/cli/serve.py`, `bm/cli/__init__.py`, `README.md` ("Starting the app": the serve variables, the TLS files, `SIGHUP`, the queue folder). Tests: TP-M2-22 (gate G27, Linux only).

**Blocked on:** #55 (d) for turning proxy headers off (recommended), #58 (a) for start-up without the vault, #24 for the sink URL forms.

## Spec quotes

- TS §8.7 L1343: "the manager runs as the system user `bitscan-manager` under `bitscan-manager.service` (below), one instance in v1, listening on `BITSCAN_LISTEN` over HTTPS only. A `SIGHUP` reloads the TLS certificate."
- TS §8.7 L1359–L1371: `ExecStart=/usr/bin/bitscan-manager serve`, `ExecReload=/bin/kill -HUP $MAINPID`, credentials `app_dsn`, `retention_dsn`, `tls_cert`, `tls_key`, `vault_token`, and the `BITSCAN_*_FILE` variables pointing at `%d/…`.
- TS §6 L1056 and §2.3 L118: JSON over HTTPS, TLS 1.2+.
- TS §8.6 L1308: `BITSCAN_MIGRATE_DSN_FILE` is "loaded only by those two units" (migrate and maintain).
- TS §2.1 L103: one manager instance in v1.

## Flow

```python
def serve_main(environ: Mapping[str, str]) -> int:
    config = load_serve_config(environ)            # ConfigError → print each line as "serve: …", return 2 (as `db` does)
    transport = transport_from_url(config.audit_sink)   # plain transports refused here → return 2 (REQ-053 (4))
    ssl_ctx = make_tls_context(config.tls_cert_file, config.tls_key_file)   # fails → return 2, no key material in the message
    runtime = build_runtime(config, transport, ssl_ctx, queue_dir=AUDIT_QUEUE_DIR)   # Runtime.lifecycle set (TASK-025 plan)
    app = create_app(runtime)                       # its lifespan calls runtime.lifecycle.start() and .stop() (TASK-044)
    return run_server(app, config.listen_host, config.listen_port, ssl_ctx, config)

AUDIT_QUEUE_DIR = Path("/var/lib/bitscan/audit-queue")    # TS §8.7 L1344; tests pass a temporary folder to build_runtime()
```

- `make_tls_context`: `ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)`, `minimum_version = ssl.TLSVersion.TLSv1_2`, `load_cert_chain(cert, key)`, no client-certificate request (`verify_mode = CERT_NONE`: agents and users have no certificates, TS §2.2), compression off (default). Cipher list: Python defaults.
- `run_server`: `uvicorn.Config(app, host, port, workers=1, lifespan="on", proxy_headers=False, forwarded_allow_ips="", server_header=False, access_log=False, log_config=None)`. The request log of TASK-027 replaces uvicorn's access log (no query strings, REQ-039 (3)); `log_config=None` keeps uvicorn's loggers on the JSON handler. Then `config.load()`, replace `config.ssl` with `ssl_ctx`, and run `uvicorn.Server(config).run()`. This hand-over must be checked against the pinned uvicorn version (it is how one keeps a reloadable context); if that version re-creates the context in `serve()`, subclass `Config` and override `load()` instead. Record which in the report.
- Plain HTTP on the TLS port fails the handshake; there is no HTTP listener and no redirect (REQ-057 (2)).

## `SIGHUP`

```python
def reload_certificate(ctx: ssl.SSLContext, cert: Path, key: Path) -> bool:
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        probe.load_cert_chain(cert, key)        # validate the new pair first
    except (OSError, ssl.SSLError):
        log.error("tls reload failed; keeping the current certificate")   # no path content, no key bytes
        return False
    ctx.load_cert_chain(cert, key)              # new handshakes use it; open connections keep theirs
    return True
```

Installed with `loop.add_signal_handler(signal.SIGHUP, …)` in the lifespan start-up (the event loop thread), and only where `signal.SIGHUP` exists, so the module still imports on Windows. uvicorn handles `SIGINT` and `SIGTERM` itself; this adds only `SIGHUP`. The listening socket is never closed, so the PID and port stay (REQ-057 (3)).

## Lifecycle (lifespan)

Start-up, in order: `AppDatabase.open()` (does not fail if the database is down; `/readyz` reports it); `Shipper.start()`; the failed-check flusher thread (every 10 s it writes the aggregated entries for minutes that have ended, REQ-047 (4)); the `SIGHUP` handler. The vault is not contacted at start-up (#58 (a) default).

Shutdown (`SIGTERM`): flush every pending failed-check count, including the current minute; `Shipper.stop()` (the queue stays on disk); `AppDatabase.close()`. Exit 0.

## Edge cases

- `BITSCAN_MIGRATE_DSN_FILE` is never read (the serve profile already ignores it, REQ-019 (6)); REQ-057 (7) points it at an unreadable file to prove it.
- `retention_dsn` is loaded by the profile but unused until M11; it is not opened.
- Binding errors (port in use, permission): exit non-zero with the address in the message (not a secret).
- Logs: one start-up line with the listen address, the TLS minimum and the sink scheme (never the full sink URL if it carries a user-info part).
- On Windows `serve` is not supported for production; the tests that send signals run on Linux only (G27).
- `bm/cli/__init__.py` routes `serve` to `serve_main(os.environ)`; `bits rebuild` and unknown commands keep the M0 behaviour (REQ-008 as narrowed).
