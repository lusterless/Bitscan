# M1 test plan (database and audit core)

Owner: tester. Written 2026-10-20 from `work/tasks.md` "M1 database and audit core" (acceptance tests, TP-M1-00 to TP-M1-16, gate G1 to G6 and G18 to G24) and `work/requirements.md` REQ-018 to REQ-033, before any M1 implementation was read. Results go to [report.md](report.md) (written by `main` from the tester's messages).

## Conventions

- Type: **CODE** = static gate, unit test or script on the tree. **APP** = the real `bitscan-manager` CLI run end to end against a PostgreSQL container (`db migrate`, `db maintain`). M1 has no HTTP app.
- Where: **L** = Windows 11 + Git Bash (`$P;` PATH line from `work/m0-brief.md`; `PY` = `manager/.venv/Scripts/python.exe`). **W** = WSL2 Ubuntu 24.04 with Docker Engine: the working tree copied to `/root/bitscan` (without `.venv`, `node_modules`, `__pycache__`), venv `/root/venv` from the hashed dev lock, `CI=true`, `RYUK_CONTAINER_IMAGE` pinned, `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`, run as `wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/.../script.sh` (`work/m1-brief.md`). **CI** = GitHub Actions only. On L, every `pg` test is "not run: Docker unavailable"; the W run is the evidence for those checks.
- `pytest -m pg` checks all start from the REQ-032 harness: a fresh container, the TS §5.2 Bootstrap (L1018–L1033) read from the spec at test time, then `bitscan-manager db migrate` through the CLI. Constraint checks (TP-M1-05 to -09) connect as `bitscan_owner` (`bitscan_migrate` + `SET ROLE bitscan_owner`); grant behaviour is tested only in TP-M1-10.
- "Diff-equal" uses the schema-diff helper (TP-M1-05; method #40). "Grant probe" = statement as the named role (`session_user`), result success or SQLSTATE 42501.
- Planted violations: a throwaway copy of the tree (or a throwaway extra migration `m0006` in that copy), never the tree. Each planted check also runs on the unmodified copy (must be green). "Red" = non-zero exit **and** the expected test, rule or message.
- Re-test rows in the report use suffixes on the plan id (`-rN`, `-ctl`).
- Blocking open questions are named where a check depends on them; such a check is drafted to the REQ text and finalised when `main` relays the answer.

## Superuser statements allowed in the harness (REQ-032 (1))

Only these run as the container superuser, all inside `bootstrapped_server()` before it yields; every other statement runs as `bitscan_migrate`, `bitscan_app` or `bitscan_retention` (testing.md L51; ruling 2026-10-20):
1. The TS §5.2 Bootstrap block, verbatim from L1018–L1033, with `\c bitscan` executed as a reconnect to database `bitscan`.
2. `ALTER ROLE bitscan_migrate|bitscan_app|bitscan_retention PASSWORD <random per run>` (test-only passwords; never committed).
3. The `bitscan_ref` Bootstrap-phase statements (#40): the database half of the Bootstrap block (`CREATE DATABASE`, `REVOKE ALL ... FROM PUBLIC`, `GRANT CONNECT` to the three LOGIN roles, then the post-`\c` statements) for database `bitscan_ref`, with only the database name changed. The TS §5.2 DDL and view blocks are applied later by the `reference_db` fixture to `bitscan_ref` as `bitscan_owner`, never as the superuser and never to `bitscan`.

No superuser credential is reachable by a test: `PgServer` holds only the three LOGIN roles' passwords and the container's port bindings (not the container object, whose environment carries `POSTGRES_PASSWORD`); `PgServer.dsn("postgres")` raises.

Read-only third-party statements before the Bootstrap (not harness code): the official image entrypoint's check for existing databases during initdb (a `SELECT` on `pg_database` over the local socket), and Testcontainers' readiness probe `psql ... -c 'select version();'` inside the container.

Server configuration, not SQL (#45): the server starts with `ssl=on` and a throwaway self-signed key and certificate generated at image build, and `pg_hba.conf` allows TCP only over `hostssl`.

## Gate map

| Gate | Checks |
| --- | --- |
| G1 ruff (S608, `re` ban) | CHK-M1-020, CHK-M1-021, CHK-M1-061, CHK-M1-178, CHK-M1-200 |
| G2 ruff format | CHK-M1-022 |
| G3 mypy --strict | CHK-M1-007, CHK-M1-023 |
| G4 pip --require-hashes | CHK-M1-001 to CHK-M1-005 |
| G5 coverage gate (local, unit only) | CHK-M1-201, CHK-M1-226 |
| G6 OpenAPI export diff (no M1 route) | CHK-M1-024 |
| G18 full WSL/CI run, 0 skipped | CHK-M1-240 |
| G19 schema diff | CHK-M1-150 to CHK-M1-152 |
| G20 grant probes | CHK-M1-130 to CHK-M1-139 |
| G21 debversion | CHK-M1-100 to CHK-M1-106 |
| G22 migrate, maintain, seeds | CHK-M1-050 to CHK-M1-060, CHK-M1-140 to CHK-M1-146, CHK-M1-170 to CHK-M1-179 |
| G23 audit append and verify | CHK-M1-200 to CHK-M1-228 |
| G24 CI migration gate | CHK-M1-250 to CHK-M1-256 |

## TASK-011 Runtime database dependencies (REQ-018)

| Id | Type | REQ | Check and command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-001 | CODE | REQ-018 (1) | Fresh `python -m venv` (bundled pip, not upgraded): `pip install --require-hashes -r manager/requirements.txt`, then the same for `requirements-dev.txt` in a second fresh venv; both exit 0, no sdist build | — | L; Linux: W (`python3.12 -m venv`) and CI |
| CHK-M1-002 | CODE | REQ-018 (1), G4 | Copies of each lock: the first `alembic` hash of the wheel pip installs altered by one character; all hashes of `alembic` removed; an unpinned line appended. Each install exits non-zero with the pip hash or pin message | altered `alembic` hash | L |
| CHK-M1-003 | CODE | REQ-018 (1) | Linux wheel-hash proxy: every Linux-applicable line of both locks downloaded with `pip download --no-deps --only-binary :all: --python-version 3.12 --implementation cp --platform manylinux_2_{17..28}_{x86_64,aarch64}` (+ manylinux2014); each SHA-256 is in that line's hashes. In particular `psycopg-binary` (libpq with TLS), `sqlalchemy` and `alembic` | — | L (needs PyPI) |
| CHK-M1-004 | CODE | REQ-018 (2) | In the CHK-M1-001 runtime venv: `python -c "import alembic, sqlalchemy, psycopg; print(psycopg.pq.version(), psycopg.pq.__impl__)"` exits 0; the libpq build supports SSL (`psycopg.pq.PGconn` has `ssl_in_use`; `pq.version() >= 160000` or at least 130000) | — | L, W |
| CHK-M1-005 | CODE | REQ-018 (3) | `tests/test_lock_files.py` (updated): the runtime lock contains `alembic`, `sqlalchemy`, `psycopg` and a binary libpq package, and none of pytest, pytest-cov, ruff, mypy, testcontainers, coverage, hatchling; `psycopg` moved, not duplicated at a different version; dev lock is still a superset with the same versions | `pytest` added to the runtime lock (test red) | L |
| CHK-M1-006 | CODE | REQ-018 (4) | Rerun the command recorded in line 2 of each lock header (with its `--exclude-newer` cutoff) in a temp dir; `cmp` with the committed lock: byte-identical | hand-edited lock | L (needs PyPI) |
| CHK-M1-007 | CODE | REQ-018 (5), G3 | `mypy --strict --config-file manager/pyproject.toml manager` exits 0; ruff and ruff format pass; existing suite green with `pg` skipped locally | — | L |

## TASK-012 Start-up configuration loader (REQ-019)

Unit tests in `manager/tests/test_config.py`, all without Docker. Each case uses an explicit environment mapping and `tmp_path` credential files, a canary password `CANARY-<random>` in every DSN file and a canary in the vault-token file; every case also asserts the canary is absent from `repr()`/`str()` of results and errors, the full exception chain (`__cause__`, `__context__`, traceback text), `capsys` and `caplog`.

| Id | Type | REQ | Check | Planted violation (mutation that must turn it red) | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-010 | CODE | REQ-019 (1) | Serve profile, all eight variables valid: success; DSNs and vault token read from their files; listen default `0.0.0.0:8443`, bits folder default `/var/lib/bitscan/bits`, upload folder `<bits>/uploaded`; `BITSCAN_LISTEN` and `BITSCAN_BITS_DIR` overrides honoured | wrong default | L |
| CHK-M1-011 | CODE | REQ-019 (2) | For each of the eight: unset, and empty string: configuration error whose message names that variable (8 x 2 cases) | one variable treated as optional | L |
| CHK-M1-012 | CODE | REQ-019 (3) | Each `*_FILE` variable pointing to a missing path, a directory (unreadable as file), an empty file and a whitespace-only file: error names the variable; the file content (canary) is not in the message | content echoed in the error | L |
| CHK-M1-013 | CODE | REQ-019 (4) | Plain look-alikes `BITSCAN_DB_DSN`, `BITSCAN_RETENTION_DSN`, `BITSCAN_VAULT_TOKEN`, `BITSCAN_MIGRATE_DSN` set to valid values with the `_FILE` partner unset: failure "missing `..._FILE`"; a recording mapping shows the plain names are never read | plain variable accepted | L |
| CHK-M1-014 | CODE | REQ-019 (5), #45 (answered 2026-10-20) | For each of the three DSNs (app `BITSCAN_DB_DSN_FILE`, retention `BITSCAN_RETENTION_DSN_FILE`, migrate `BITSCAN_MIGRATE_DSN_FILE`), in key=value and URI form: no `sslmode`, and `sslmode` = `disable`, `allow`, `prefer` are refused, with the error naming that DSN's variable; `require`, `verify-ca`, `verify-full` are accepted. `sslmode` counts only when written in the DSN: with `PGSSLMODE=require` set in the environment (and a `service=` DSN), a DSN without `sslmode` is still refused. Case and spacing variants (`sslmode = require`, `sslmode=REQUIRE`) are decided by libpq parsing (the test records what libpq accepts and asserts the loader agrees) | `prefer` accepted; `PGSSLMODE` honoured; only the app DSN checked | L |
| CHK-M1-015 | CODE | REQ-019 (5) | Unparsable DSN (unbalanced quote, bad URI): refused; neither the message nor any chained exception or traceback text contains any substring of the DSN (canary and host) | psycopg error re-raised with `from exc` | L |
| CHK-M1-016 | CODE | REQ-019 (6) | Serve profile with `BITSCAN_MIGRATE_DSN_FILE` pointing to an unreadable path: success; a recording mapping shows the key is never looked up | serve reads the migrate DSN | L |
| CHK-M1-017 | CODE | REQ-019 (7) | db profile with only `BITSCAN_MIGRATE_DSN_FILE`: success, DSN read; missing: error names it; none of the serve variables is required or read | db profile needs a serve variable | L |
| CHK-M1-018 | CODE | REQ-019 (8) | Canary sweep across every success and failure case above (repr, str, exception chain, stdout, stderr, log records at DEBUG) | `repr` of the config shows the DSN | L |
| CHK-M1-019 | CODE | REQ-019 (9), (10) | Vault address, TOTP key ref and audit sink kept as given opaque strings (values such as `not a url`, `syslog://x`, `vault:k` accepted unchanged, no scheme parsing); `socket.socket`, `socket.create_connection`, `getaddrinfo` and `psycopg.connect` patched to raise: loading succeeds | loader parses the vault URL or connects | L |
| CHK-M1-025 | CODE | REQ-019 (11) | `BITSCAN_LISTEN`: accepted `0.0.0.0:8443`, `127.0.0.1:1`, `[::1]:65535`, `host.example:443`; refused `8443`, `:8443`, `host:`, `host:0`, `host:65536`, `host:-1`, `host:abc`, `::1:8443` (unbracketed v6), `[::1]`; each error names `BITSCAN_LISTEN` | port 0 accepted | L |
| CHK-M1-020 | CODE | G1 | `ruff check manager` exits 0; in a copy, `import re` in `bm/config/startup.py` is red (TID251) | `import re` | L |
| CHK-M1-021 | CODE | G1 | In a copy, f-string SQL `cur.execute(f"...{x}")` in `bm/config/startup.py` (or any M1 module) is red (S608) | f-string SQL | L |
| CHK-M1-022 | CODE | G2 | `ruff format --check manager` exits 0; in a copy, one misformatted line in a migration is red | misformatted line | L |
| CHK-M1-023 | CODE | G3 | mypy exits 0; in a copy, an untyped function in `bm/config/startup.py` and an unannotated `upgrade()` in a migration are each red (`no-untyped-def`) | untyped function | L |
| CHK-M1-024 | CODE | G6 | Export then compare with the committed `manager/openapi.json` (paths still `{}`); a route added in a copy without re-export makes the comparison differ | added route | L |

## TP-M1-01 / TP-M1-02 Harness (REQ-032; TASK-013 TEST)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-030 | CODE | REQ-032 (6), REQ-009 (4) | `tests/test_conftest_hook.py` (pytester, inner sessions use the real `tests/conftest.py` hook with the Docker probe stubbed): Docker unreachable, `CI` unset: inner `pg` tests skipped with `not run: Docker unavailable`, non-pg tests pass, exit 0. `CI=true` (also `TRUE`): inner session exits non-zero with that message. No `pg` test selected (none collected, or `-m "not pg"`): the probe is never called. Docker reachable: `pg` tests not skipped by the hook | hook ignores `CI`; probe called with no pg test | L (no Docker needed) |
| CHK-M1-031 | CODE | REQ-032 (1) | `spec_sql.py` extracts the Bootstrap block from TS §5.2 at test time (by fence, not by line number), checks it starts with the expected `CREATE ROLE` lines, and splits `\c bitscan` into a reconnect; a unit test runs without Docker. A copy of the spec with one Bootstrap line changed changes the extracted SQL | Bootstrap text hard-coded in the test | L (unit); W (applied) |
| CHK-M1-032 | APP | REQ-032 (2) | The `migrated_db` fixture runs the installed `bitscan-manager db migrate` CLI with `BITSCAN_MIGRATE_DSN_FILE` pointing to a `tmp_path` file (no in-process shortcut) | — | W |
| CHK-M1-033 | CODE | REQ-032 (3) | Each handed-out connection: `session_user` in {`bitscan_app`, `bitscan_retention`, `bitscan_migrate`} and `SELECT rolsuper FROM pg_roles WHERE rolname = session_user` is false; no fixture yields the superuser | fixture yields `postgres` | W |
| CHK-M1-034 | CODE | REQ-032 (4) | `docker inspect` of the test container: port 5432 published on `127.0.0.1` only (no `0.0.0.0`, no `::`) | default all-interfaces bind | W |
| CHK-M1-035 | CODE | REQ-032 (5), #45 | The container runs with TLS: `SHOW ssl` is `on`; every fixture connection (app, retention, migrate, and the CLI's migrate DSN) uses `sslmode=require` and `pg_stat_ssl.ssl` is true for its backend; a `sslmode=disable` connection as `bitscan_app` is refused by the server (`pg_hba` `hostssl` only for the three roles) | TLS off; `host` (non-SSL) rule left in `pg_hba` | W |
| CHK-M1-036 | CODE | REQ-032 (1) | The only superuser statements are the three listed above (static review of `conftest.py` plus a statement log: `log_statement = all` on a run, superuser lines filtered) | extra superuser statement | W |

## TASK-013 Migration runner and `db migrate` (REQ-020; TP-M1-04)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-050 | APP | REQ-020 (1) | Bootstrap only, then `bitscan-manager db migrate`: exit 0; `alembic_version.version_num` is the head revision of the shipped migrations | — | W |
| CHK-M1-051 | APP | REQ-020 (2), #41 (answered) | Every relation, index, sequence, type, function and view in `public` is owned by `bitscan_owner`; none by `bitscan_migrate` (query over `pg_class`, `pg_type`, `pg_proc`). `alembic_version` is in `public`, owned by `bitscan_owner`, and after `m0005` carries only the default blanket grants (SELECT and INSERT for `bitscan_app`, SELECT for `bitscan_retention`, nothing else) | object created without `SET ROLE`; extra grant on `alembic_version` | W |
| CHK-M1-052 | APP | REQ-020 (3) | Second run exits 0; catalog snapshot (the schema-diff helper's full dump plus row counts of seeded tables) before and after is equal | non-idempotent migration | W |
| CHK-M1-053 | CODE | REQ-020 (4) | Every module in `versions/`: calling `downgrade()` (if defined) raises; static check that no `downgrade` does work (AST: body is only `raise`). CLI: `db downgrade`, `db stamp`, `db`, `db bogus` exit non-zero and change nothing (catalog snapshot equal) | a working `downgrade()` (G22) | L (unit, AST); W (CLI) |
| CHK-M1-054 | APP | REQ-020 (5) | DSN for `bitscan_app`: exit non-zero; no object created (catalog snapshot equals Bootstrap-only) | — | W |
| CHK-M1-055 | APP | REQ-020 (6) | `BITSCAN_MIGRATE_DSN_FILE` unset: exit non-zero, stderr names the variable. Wrong password, and unreachable host (`127.0.0.1:1`), with the canary in the DSN file: exit non-zero, canary absent from stdout and stderr | DSN in error output | L (unset, unreachable); W (wrong password) |
| CHK-M1-056 | CODE | REQ-020 (7), REQ-008 (narrowed) | `test_cli.py` update: `serve`, `users create-admin x`, `bits rebuild`, `bogus`, no args: exit non-zero, read no `BITSCAN_*` key, and `psycopg`, `sqlalchemy`, `alembic` are not imported (`__import__` recorder); `--help` exit 0 | `serve` imports the db module | L |
| CHK-M1-057 | APP | REQ-020 (8) | Build the wheel (`pip wheel --no-deps --no-build-isolation manager`), install it non-editable into a fresh venv from the runtime lock; `bitscan-manager db migrate` from that venv migrates a fresh database to head; the wheel contains `bitscan_manager/db/migrations/versions/m000*.py` | migrations excluded from the wheel | W (wheel listing also L) |
| CHK-M1-058 | CODE | REQ-020 (9), G1 | `ruff check manager` with S608 active passes over `bm/db/`; a copy with `op.execute(f"...")` or `"..." % x` in a migration is red | f-string in a migration | L |
| CHK-M1-059 | CODE | m1-brief rules | Static scan of `versions/*.py`: no SQL comment containing `:`, no `:word` outside bound-parameter statements; seeds use bound parameters | colon comment in a migration | L |
| CHK-M1-060 | APP | REQ-020 (1) | `db migrate` output (stdout/stderr) on success names no DSN, password or host; exit 0 | — | W |

## TASK-014 to TASK-017 Schema parts (REQ-021 to REQ-024; TP-M1-05 to -09)

Each part: (a) diff-equal to its TS §5.2 lines (schema-diff helper, ACLs excluded here); (b) behaviour cases as `bitscan_owner`. Each behaviour case asserts the specific SQLSTATE (23514 check, 23505 unique, 23503 FK, 23502 not null, 22P02 invalid enum, 23001 restrict) or the stored value.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-070 | CODE | REQ-021 (1), REQ-027, #40 (answered) | Schema-diff helper (`tests/schema_diff.py`). Reference = the TS §5.2 SQL blocks extracted from the spec at test time (`spec_sql.py`) and applied as `bitscan_owner` to a **separate scratch database** in the same container (created for the reference only, never the database under test). Both databases are dumped with the same catalog queries (tables, columns, types, defaults, CHECKs, indexes, grants, trigger, view) and compared, excluding the monthly partitions and `alembic_version`. Unit-tested without Docker on two hand-made dumps (equal, and each difference kind reported with the object name); then the catalog objects of L638–L707 are diff-equal | — | L (unit); W |
| CHK-M1-071 | CODE | REQ-021 (2) | `enum_range(NULL::plugin_operator)` equals the 14 spec labels in order; `policy_status`, `plugin_state` labels in order | reordered label | W |
| CHK-M1-072 | CODE | REQ-021 (3) | `plugin.timeout_s` 0 and 601 rejected (23514), 1 and 600 accepted, default 60; `bit_import.mode` and `outcome` outside the sets rejected | — | W |
| CHK-M1-073 | CODE | REQ-021 (4) | Defaults: `status_overridden` false, `format_version` `'1.0'`, `version` 1, `plugin.state` `active`, `bit_import.errors` `[]` | — | W |
| CHK-M1-074 | CODE | REQ-021 (5) | Duplicate `policy_name`, `source_file`, `family_name` rejected (23505); `plugin.owner_policy_id` FK rejected (23503); deleting a policy cascades `policy_plugin` | — | W |
| CHK-M1-080 | CODE | REQ-022 (1) | Fleet and inventory objects of L709–L825 diff-equal | — | W |
| CHK-M1-081 | CODE | REQ-022 (2) | Token columns are `character(64) NOT NULL UNIQUE` and reject duplicates; catalog scan: every column whose name contains `token` ends in `token_hash` (or is `enrollment_token_id`-style FK / table name); `machine_id` `character(32) NOT NULL UNIQUE` | raw token column | W |
| CHK-M1-082 | CODE | REQ-022 (3) | `max_uses` 0 and 10001 rejected, 1 and 10000 accepted, default 1; `uses` default 0; `uses > max_uses` rejected; `auto_approve` default false; NULL `expires_at` rejected | — | W |
| CHK-M1-083 | CODE | REQ-022 (4) | `agent.status` default and label order; `enrollment_request.kind` and `decision` sets; deleting an agent with an enrollment request refused (RESTRICT); cascades for tags, IPs, `os_info`, `agent_package`, snapshots | — | W |
| CHK-M1-084 | CODE | REQ-022 (5), (6) | Duplicate (name, version, architecture) rejected; index definitions: `ix_package_name_debver` btree `(name, ((version)::debversion))`; trigram indexes GIN `gin_trgm_ops` | — | W |
| CHK-M1-090 | CODE | REQ-023 (1) | Scanning objects of L842–L938 diff-equal | — | W |
| CHK-M1-091 | CODE | REQ-023 (2) | `scan_job` CHECK cases (compliance without `scan_id`, inventory with `scan_id`, compliance without `eval_spec`, bad kind) rejected; inventory with neither accepted; `ix_job_pending` predicate `state = 'queued'` | — | W |
| CHK-M1-092 | CODE | REQ-023 (3) | `scan_result` partition key `RANGE (job_created_at)`; `scan_result_default` is its DEFAULT partition | — | W |
| CHK-M1-093 | CODE | REQ-023 (4) | Mismatched `job_created_at` rejected with exactly `scan_result.job_created_at must equal scan_job.created_at`, through the parent and directly into `scan_result_default`; matching insert accepted | — | W |
| CHK-M1-094 | CODE | REQ-023 (5) | `eval_code` 3 rejected; generated `result` 0/1/2 = PASS/FAIL/ERROR; supplying `result` rejected; NULL in each snap column rejected | — | W |
| CHK-M1-095 | CODE | REQ-023 (6), (7) | `scan.trigger` set; schedule delete sets `scan.schedule_id` NULL; scan delete cascades jobs, results and reevals; `scan_result_reeval.eval_code` 3 rejected | — | W |
| CHK-M1-096 | CODE | REQ-024 (1) | System objects (L827–L831, L835–L840, L941–L990) diff-equal; `system_schedule` and `setting` empty after migrating to `m0004` only | — | W |
| CHK-M1-097 | CODE | REQ-024 (2) | No `enabled` column on `system_schedule`; `job_kind` set; `interval_s` 59, 86401 rejected; inventory 3599 rejected, 3600 accepted; offline_sweep 60 accepted | — | W |
| CHK-M1-098 | CODE | REQ-024 (3) to (6) | `user_token` api + totp_verified rejected, session + true accepted; `token_hash` `character(64) NOT NULL UNIQUE`; `ix_user_token_active` partial; `app_user.role` default `viewer` and label order, `disabled` default false; `task.kind`/`state` sets; `audit_log.prev_hash`/`row_hash` `character(64) NOT NULL` | — | W |

## TP-M1-07 Debian version comparison (REQ-029; G21)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-100 | CODE | REQ-029 (1) | `tests/fixtures/debversion_pairs.tsv`: at least 500 rows `a<TAB>b<TAB>lt|eq|gt`; unit test (no Docker) asserts the count, the format, and the presence of each required category (epoch, `0:1.0` = `1.0`, `~` incl. `1.0~~ < 1.0~`, revisions and missing revisions, `+` and `.`, letters vs digits, leading zeros, long digit runs) | — | L |
| CHK-M1-101 | CODE | REQ-029 (2) | In the test container (Debian, `dpkg` present): `dpkg --compare-versions a lt|eq|gt b` agrees with every recorded relation | one relation flipped `lt` -> `gt` (G21) | W |
| CHK-M1-102 | CODE | REQ-029 (2) | Generator cross-check on the Windows/WSL host: the fixture was produced by `dpkg` (WSL Ubuntu `dpkg --compare-versions` gives the same relations) | — | W |
| CHK-M1-103 | CODE | REQ-029 (3) | On the migrated database, `a::debversion < = > b::debversion` gives the recorded relation for every pair; as `bitscan_owner` from TASK-015, re-run as `bitscan_app` in TASK-018 TEST | flipped relation | W |
| CHK-M1-104 | CODE | REQ-029 (4) | At least 20 pairs where the text order differs from the `debversion` order (counted in the test) | — | L (unit), W |
| CHK-M1-105 | CODE | REQ-029 (5) | `SET enable_seqscan = off`; `EXPLAIN SELECT ... FROM package WHERE name = %s AND version::debversion < %s::debversion` mentions `ix_package_name_debver` | index dropped | W |
| CHK-M1-106 | CODE | REQ-029 (6) | `package.version` is `character varying(255)` | — | W |

## TASK-018 Privileges, view, seeds, partitions, final diff (REQ-025 to REQ-027; TP-M1-10 to -12)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-130 | CODE | REQ-025 (1) | Grant probes as `bitscan_app`: SELECT and INSERT on every table; UPDATE exactly on the 15 tables listed plus the named `scan_job` and `scan` columns; DELETE exactly on the five tables listed; every other UPDATE/DELETE 42501 (matrix generated from `pg_tables`, so a new table is covered) | `GRANT DELETE ON scan` (G20) | W |
| CHK-M1-131 | CODE | REQ-025 (2) | 42501 for UPDATE, DELETE, TRUNCATE on `audit_log`, `scan_result` (parent), `scan_result_default`, a monthly partition, a partition created by `db maintain`, `scan_result_reeval`, `bit_import` | `GRANT UPDATE ON audit_log` (G20) | W |
| CHK-M1-132 | CODE | REQ-025 (3) | 42501 for DELETE on `scan`, `scan_job`, `agent`, `policy`, `system_schedule` | — | W |
| CHK-M1-133 | CODE | REQ-025 (4) | UPDATE of `scan_job.agent_id`, `scan_id`, `kind`, `payload`, `eval_spec`, `scan.policy_id`: 42501; UPDATE of the progress columns succeeds | — | W |
| CHK-M1-134 | CODE | REQ-025 (5) | `bitscan_retention`: SELECT every table; DELETE exactly the nine tables; 42501 elsewhere; INSERT into `audit_log` with `nextval('audit_log_audit_id_seq')` succeeds; INSERT elsewhere and UPDATE anywhere 42501 | — | W |
| CHK-M1-135 | CODE | REQ-025 (6) | `SELECT display_name FROM v_plugin` as `bitscan_app` = `family_name || ' - ' || plugin_name`; `v_plugin` columns include every `plugin` column | — | W |
| CHK-M1-136 | CODE | REQ-025 (7) | A table created by `bitscan_owner` after migrate gets SELECT+INSERT for app, SELECT for retention, nothing else (`aclexplode`) | — | W |
| CHK-M1-137 | CODE | REQ-025 (8) | No role but `bitscan_owner` has TRUNCATE, REFERENCES or TRIGGER on any table; `bitscan_migrate` holds no direct table privilege (`information_schema.table_privileges` + `aclexplode`) | — | W |
| CHK-M1-138 | CODE | REQ-029 (3) | CHK-M1-103 re-run as `bitscan_app` | — | W |
| CHK-M1-139 | CODE | G20 | Throwaway `m0006` in a copy, one at a time: `GRANT UPDATE ON audit_log TO bitscan_app`, `GRANT DELETE ON scan TO bitscan_app`: `test_grants.py` red | as stated | W |
| CHK-M1-140 | CODE | REQ-026 (1) | `system_schedule` = exactly the three rows | — | W |
| CHK-M1-141 | CODE | REQ-026 (2), #42 (answered) | `setting` = exactly six keys; the five numeric keys hold bare JSON numbers (`agent_token_ttl_days` 365, `job_pull_seconds` 300, `decommission_after_days` 7, `max_parallel_plugins` 2, `enrolment_alert_per_hour` 50, compared as `value::text` and as JSON type `number`), `redaction_patterns` a JSON array of five strings; every `updated_by` NULL; no `inventory_interval_s` and no key naming inventory or a switch | a value seeded as a JSON string `"365"` | W |
| CHK-M1-142 | CODE | REQ-026 (3) | `redaction_patterns` = the five TS §8.6 patterns read from the spec at test time (L1332–L1336), in order, byte-identical; each `re2.compile`s | one character changed (G22) | W (`re2` also L for the spec extraction) |
| CHK-M1-143 | CODE | REQ-026 (4), #43 (answered) | Exactly four range partitions besides the default, named `scan_result_YYYY_MM` for the current UTC month and the next three; bounds read with `TimeZone = UTC` are `FROM ('YYYY-MM-01 00:00:00+00') TO (<next month>)`; contiguous, no gap or overlap; first lower bound = first instant of the current UTC month, last upper bound = four months later | a partition missing or named by local time | W |
| CHK-M1-144 | CODE | REQ-026 (5) | Each partition owned by `bitscan_owner`; ACL = SELECT+INSERT app, SELECT retention | — | W |
| CHK-M1-145 | CODE | REQ-026 (6) | A row with `job_created_at` in the current month lands in that month's partition (`tableoid::regclass`); `scan_result_default` empty after migrate | — | W |
| CHK-M1-146 | APP | REQ-026 (7) | Migrate to `m0004` only (`alembic upgrade m0004` via the runner's test hook, or a copy without `m0005`): `system_schedule` and `setting` empty, only the default partition | — | W |
| CHK-M1-150 | CODE | REQ-027 (1), #40 (answered) | Full diff of the migrated `public` schema against the reference scratch database built from the TS §5.2 blocks (CHK-M1-070 method): extensions, types and labels, tables, columns (type, length, nullability, default, generated), constraints (PK, UNIQUE, FK + ON DELETE, CHECK), indexes (method, keys, predicate), function body, triggers, view, sequences, owners, table and column ACLs, default ACLs: no difference. The reference database is dropped afterwards and never receives `db migrate` | — | W |
| CHK-M1-151 | CODE | REQ-027 (2) | The four monthly partitions and `alembic_version` are excluded from the diff and checked by CHK-M1-143 and CHK-M1-051 (the exclusion list is exactly these) | broader exclusion | W |
| CHK-M1-152 | CODE | REQ-027 (3), G19 | Throwaway `m0006` in a copy, one at a time: drop a CHECK, change a default, add a column, add a GRANT, drop an index: `test_schema_diff.py` red each time, naming the object | as stated | W |

## TASK-019 `db maintain` (REQ-028; TP-M1-13)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-170 | CODE | REQ-028 (1) | Maintenance function with an injected clock two months ahead: creates exactly the missing partitions so current month + 3 exist, contiguous with the earlier ones | maintains only two future months (G22) | W |
| CHK-M1-171 | CODE | REQ-028 (2) | Second run: exit 0 / no change (partition set and ACLs equal) | — | W |
| CHK-M1-172 | CODE | REQ-028 (3) | New partitions owned by `bitscan_owner`, default ACL; `bitscan_app` 42501 for UPDATE, DELETE, TRUNCATE on them | — | W |
| CHK-M1-173 | CODE | REQ-028 (4), #44 (answered) | With an injected clock: a partition whose upper bound is at least 400 days before now (UTC) is dropped, whether or not its rows are gone; one at 399 days is kept; `scan_result_default` and in-retention partitions are never dropped; rows in kept partitions unchanged (count and checksum). Partitions are found by bounds, not by name (a partition renamed in a copy is still handled) | drops the default; drops at 399 days | W |
| CHK-M1-174 | CODE | REQ-028 (5) | Statement log during maintain: no `DELETE`; DDL only on `scan_result` partitions | — | W |
| CHK-M1-175 | CODE | REQ-028 (6) | Rows in `scan_result_default` inside a range it must create: exit non-zero, message names `scan_result_default`, no partition created | — | W |
| CHK-M1-176 | APP | REQ-028 (7) | `bitscan-manager db maintain` on a migrated database: exit 0, output lists each partition created or dropped, no canary; `BITSCAN_MIGRATE_DSN_FILE` unset: non-zero, names the variable | DSN in output | W (unset case also L) |
| CHK-M1-177 | CODE | REQ-028 (3) | CHK-M1-131 partition case on a partition created by `db maintain` | — | W |
| CHK-M1-178 | CODE | REQ-028 (8), G1 | Partition DDL composed with `psycopg.sql.SQL/Identifier/Literal` only (AST scan of `bm/db/maintain.py`: no f-string, `%` or `.format` reaching `execute`); ruff S608 red on a planted f-string | f-string DDL | L |
| CHK-M1-179 | CODE | REQ-020 (7) | `test_cli.py`: `db maintain` is a real command; other commands keep M0 behaviour | — | L |

### TASK-019 revision 1 (amendment to #44, 2026-10-20: clock guard, naive clock, run lock)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-180 | CODE | #44 amendment (a) | 24 older monthly partitions, clock +24 months: `drops_refused` set and names the clock (`YYYY-MM-DDTHH:MM:SS`), `drop == ()`, nothing dropped, the 4-month window created | guard (a) removed | W |
| CHK-M1-181 | CODE | #44 amendment (b) | one partition past 400 days and a row with `job_created_at` = now + 20 days: drops refused, clock named, partition kept; a row exactly at now does not refuse (CHK-M1-173 asserts `drops_refused is None`) | guard (b) removed | W |
| CHK-M1-182 | CODE | #44 amendment | clock inside the window and no future rows: the 400-day drop still happens, `drops_refused is None` | — | W |
| CHK-M1-183 | APP | #44 amendment | `bitscan-manager db maintain` with guard (b) tripped: exit 1, `drops refused` and the date on stderr, no `dropped` line, no row data (job id) in the output; unit (L): stubbed plan with `drops_refused` gives exit 1 with `created ...` on stdout and the message only on stderr; a normal drop gives exit 0, empty stderr | CLI exits 0 on refusal | L, W |
| CHK-M1-184 | CODE | #44 amendment (reviewer nit) | naive `now` refused with `ValueError` ("timezone-aware") by `plan_partitions` and `run_maintain` (before any connection) | — | L |
| CHK-M1-185 | CODE | #44 amendment (run lock) | (i) two concurrent runs at clock +2 months: no error, the 2 missing partitions created once, 7 partitions; (ii) deterministic: a session holds `pg_advisory_xact_lock(hashtext('db_maintain'))`, a run waits (ungranted advisory row in `pg_locks`, nothing created), the holder creates one window partition and commits, the run then plans afresh (`create == ()`), 6 partitions | run lock removed | W |
| CHK-M1-186 | CODE | #44 amendment (open) | Probe, not a committed test: clock +24 months, two runs a day apart. Run 2 finds the partition run 1 created, so guard (a) no longer trips; whether it then drops in-retention partitions is reported to `main` for an owner ruling (result: it did; led to guard (c)) | — | W (WSL copy only) |

### TASK-019 revision 2 (second amendment to #44, 2026-10-20: guard (c), contiguous partitions)

Text: drops are refused when the existing non-default partitions, read before the run's creates, are not contiguous (a UTC month missing between the oldest and the newest); the window is still created; exit 1; the message names the missing month(s). Earlier drop tests (CHK-M1-173, -181, -182, -183) fill every month between their old partition and the window, so they keep testing their own rule.

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-187 | CODE | #44 amendment 2 | The CHK-M1-186 scenario as a committed test: 6 in-retention months, clock +24 months, run twice: both runs refuse, run 2 names the first missing month (current + 4) and drops nothing | guard (c) removed | W |
| CHK-M1-188 | CODE | #44 amendment 2 | Contiguous set from 400+ days back to the window, correct clock: the two past-retention months are dropped, `drops_refused is None` | — | W |
| CHK-M1-189 | CODE | #44 amendment 2 | One and two middle months dropped by hand (clock +1 month): drops refused, each missing `YYYY-MM` named, past-retention partition kept, the window (the one missing month) still created | guard (c) removed | W |
| CHK-M1-190 | APP | #44 amendment 2 | CLI with a hand-made gap: exit 1, `drops refused` and the month on stderr, no `dropped` line | — | W |
| CHK-M1-191 | CODE | #44 amendment 2 | Pure: `missing_months` for none, one, unordered input across a year end, 24 contiguous months; the message lists at most 12 months then `and K more`, and names the clock | — | L |

## TASK-020 / TASK-021 Audit chain (REQ-030, REQ-031; TP-M1-14, -15; G23)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-200 | CODE | REQ-030 (8), G1, #38 (answered) | Pure hash function unit tests (no PostgreSQL) against an independent reference in the test: SHA-256, lowercase hex, over the UTF-8 bytes of `json.dumps([prev_hash, audit_id, actor, action, target, detail_text, at_text], separators=(',', ':'), ensure_ascii=False)`; a hard-coded known-answer vector; each field changes the hash; `None` target/detail differ from `''`/`'{}'`; non-ASCII kept as UTF-8; genesis = 64 × `0`; at_text `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Ruff S608 red on planted f-string SQL in `bm/repositories/audit_log.py` | field omitted from the hash; `ensure_ascii=True`; spaces in separators | L |
| CHK-M1-201 | CODE | REQ-030 (8), G5 | Coverage gate on Windows with `pg` skipped: `pytest --cov=bitscan_manager/services --cov-fail-under=85` exits 0 from the unit tests alone; a planted untested 20-statement function in `bm/services/audit/` is red | as stated | L |
| CHK-M1-202 | CODE | REQ-030 (1) | Append flow with a fake repository (unit): lock taken before reading the head, `prev_hash` = last `row_hash`, insert with the computed hash; order of calls asserted | lock after read | L |
| CHK-M1-203 | CODE | REQ-030 (1) | PostgreSQL: N appends; every `prev_hash` = previous `row_hash` by `audit_id`; first = genesis; recomputed `row_hash` = stored | — | W |
| CHK-M1-204 | CODE | REQ-030 (2) | 8 concurrent `bitscan_app` connections x 25 appends: 200 entries, one unbroken chain, no duplicate `prev_hash` | advisory-lock call removed (G23) | W |
| CHK-M1-205 | CODE | REQ-030 (3) | Held uncommitted append: second writer waits (row in `pg_locks` with `locktype = 'advisory'`, `granted = false`) until commit; after rollback, the next entry links to the last committed entry | — | W |
| CHK-M1-206 | CODE | REQ-030 (4) | Append as `bitscan_app` and as `bitscan_retention` succeeds with only their grants | — | W |
| CHK-M1-207 | CODE | REQ-030 (5) | Writers in REPEATABLE READ, SERIALIZABLE and autocommit: concurrently appending never forks (either correct append or an error before insert); chain intact after | — | W |
| CHK-M1-208 | CODE | REQ-030 (6) | `actor` 129, `action` 65, `target` 256 characters: rejected, row count unchanged; at the limits accepted | — | W (validation part L if done in Python) |
| CHK-M1-209 | CODE | REQ-030 (7) | During append: `capsys`/`caplog` empty of the entry's detail and of any output; `socket.create_connection` patched (unit) | logs the entry | L, W |
| CHK-M1-220 | CODE | REQ-031 (1), (6) | Pure verifier unit tests over row sequences: intact chain passes with count; empty passes | — | L |
| CHK-M1-221 | CODE | REQ-031 (2), (3) | Unit and PostgreSQL (as `bitscan_owner`): each hashed field of one entry changed: first bad `audit_id` = that entry; middle entry deleted: reports the entry after the gap; inserted entry with wrong `prev_hash`: reports it | verifier skips the `prev_hash` link check (G23) | L, W |
| CHK-M1-222 | CODE | REQ-031 (4) | `audit_id` gaps from rolled-back appends with intact links: passes | — | L, W |
| CHK-M1-223 | CODE | REQ-031 (5), #39 (answered) | As `bitscan_retention`: append an ordinary chained entry with `action = 'audit.checkpoint'`, `detail = {"last_deleted_id": <id>, "last_deleted_row_hash": "<hex>"}` for the last entry to delete, then delete up to that id: verifies (the oldest remaining entry's prev_hash equals last_deleted_row_hash and last_deleted_id < its id). Fails: deleting one more entry; altering the recorded hash; a checkpoint whose last_deleted_id is not lower than the oldest remaining id | — | W |
| CHK-M1-224 | CODE | REQ-031 | Verifier reads from one snapshot (REPEATABLE READ or a single query); concurrent append during verify does not cause a false failure | — | W |
| CHK-M1-226 | CODE | G5 | Coverage of `bm/services/audit/` from unit tests alone stays >= 85 % with `verify.py` added | — | L |
| CHK-M1-228 | CODE | G23 | In a copy: advisory-lock call removed from append: CHK-M1-204 red; verifier with the link check removed: CHK-M1-221 red | as stated | W (unit part L) |
| CHK-M1-230 | CODE | REQ-031 (1)–(5), TASK-021 step 2 | PostgreSQL through `verify_chain` (read as `bitscan_app`): empty and 5-entry chains verify with the count; as `bitscan_owner`, each of actor, action, target, detail, at, prev_hash, row_hash changed on one entry reports that entry; a deleted middle entry reports the next (`broken link`); an inserted entry with a wrong prev_hash reports itself; rolled-back gaps verify; as `bitscan_retention`, checkpoint then delete up to it verifies (and keeps verifying after more appends); one more delete fails at the oldest remaining; the checkpoint's recorded hash edited reports the checkpoint (`row_hash mismatch`); a connection with an open transaction is refused (AuditError); the connection is left idle after success and after an early failure | snapshot isolation dropped from the read; link check removed | W |
| CHK-M1-229 | CODE | REQ-031 (2), (3), #39 | A failure before the vouching checkpoint is reported at the failing row, not the oldest row: checkpoint for id 4, ids 1–4 deleted, actor of id 8 changed in place gives (8, `row_hash mismatch`); rehashed in place gives the next row; a deleted row before the checkpoint gives the row after the gap. A checkpoint edited without rehash reports its own id; rehashed reports the oldest row. A checkpoint whose `last_deleted_id` is not below its own id does not vouch | oldest-row result given priority | L |

## TASK-022 CI migration gate (REQ-033; TP-M1-16; G24)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-250 | CODE | REQ-033 (4) | Static parse of `manager.yml`: the migration step is its own step, no `continue-on-error`, `\|\| true`, `if:` skip; runs on `pull_request` | — | L |
| CHK-M1-251 | CODE | REQ-033 (1), (2) | Local substitute: the step's script run in scratch git repos (base commit = tree, PR commit on top): modify, delete, rename `m0001_catalog.py`: red; add two migration files: red; add zero or one: green; touching only `versions/__init__.py` the first time: green | as stated | L (scratch repos under TEMP) |
| CHK-M1-252 | CODE | REQ-033 (3) | The PostgreSQL job sets `CI=true`, runs the M1 suites (`pytest` without `-m "not pg"`, Docker on the runner) | `-m "not pg"` | L (static) |
| CHK-M1-253 | CODE | REQ-033 | The step's base ref for a PR is the PR base (fetch depth sufficient); on `push` to main it does not falsely fail | shallow checkout without base | L (static), CI |
| CHK-M1-254 | CODE | REQ-033 (1), (2); user merge decision (five stacked PRs) | Scratch clone: five stacked branches, each adding exactly one of `m0001` (plus `__init__.py`) to `m0005` on top of the previous; the gate (script extracted byte for byte from `manager.yml`) passes for each PR against its own base, and after each base merges and the next is rebased/retargeted onto `main`; a stacked PR adding two migrations fails; a PR against `main` while its parent is unmerged fails (2 added) | stack PR adds two | L (scratch repos under TEMP) |
| CHK-M1-255 | CODE | REQ-033 (4), user approval 2026-10-20 | `actionlint` at a pinned released tag at least two weeks old via `go run github.com/rhysd/actionlint/cmd/actionlint@vX.Y.Z` (sumdb verified; no GONOSUMDB, insecure or direct proxy), from a scratch directory outside the repo, over `.github/workflows/*.yml`: no findings; nothing added to the repository | — | L |
| CHK-M1-256 | CODE | REQ-033, G24 | Live: PR branches with the planted changes fail the job; a clean PR passes | as stated | CI only: NOT RUN locally (needs pushed PRs) |

## M1 gate run (G18)

| Id | Type | REQ | Check | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M1-240 | CODE | all M1 | `cd /root/bitscan/manager && CI=true /root/venv/bin/python -m pytest --cov=bitscan_manager/services --cov-fail-under=85 -rs`: every test passes, **0 skipped**, coverage >= 85 % | any of G19 to G23 | W; CI |
| CHK-M1-241 | CODE | all M1 | The same on Windows (`CI` unset): unit tests pass, `pg` tests skipped with `not run: Docker unavailable` (reported, not counted as pass), coverage gate passes | — | L |
| CHK-M1-242 | CODE | all M1, user merge decision | Per-PR-head runs: for each of the five stacked M1 PR heads, a clean WSL copy of that head runs the full suite with `CI=true` and the coverage gate (0 skipped), one head at a time. Scheduled after the lead and the user agree the PR split | — | W (one head at a time) |

## Not tested in M1

Everything the M1 coverage matrix in `work/tasks.md` marks uncovered (sink, disk queue, alerts, row retention, `/readyz`, settings API, `serve`, users CLI, rebuild). G7 to G17 are unchanged and stay green in CI.
