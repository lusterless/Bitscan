# TP-M1-02 TEST: PostgreSQL test harness (REQ-032)

Verdict: **PASS**. Tester: `tester-b`, independent of the harness author (`tester`), PD-17. Date: 2026-10-20.

## Scope and files tested
REQ-032 (1) to (5), with checks CHK-M1-031 to CHK-M1-036 from [tests/m1/test-plan.md](../../tests/m1/test-plan.md). Spec: TS §5.2 Bootstrap (L1016–L1033), TS §5.3 L1049 (TLS only), TS §8.3 Integration, testing.md L51. Final files (sha256 prefix): `manager/tests/conftest.py` 459de4d6eb46, `manager/tests/spec_sql.py` 3feac2b81cdd, `manager/tests/test_pg_harness.py` 4bb596956ac4, `manager/tests/postgres/Dockerfile` 6259f785bb25. These files include the restructure made after the 2026-10-20 ruling: the `bitscan_ref` bootstrap moved into `bootstrapped_server`, and `PgServer` no longer holds the superuser password or the container.

## Commands and counts
- L (Windows, `CI` unset): `cd manager && .venv/Scripts/python.exe -m pytest -q -rs --cov=bitscan_manager/services --cov-fail-under=85`: 263 passed, 32 skipped, all `not run: Docker unavailable`, exit 0, coverage gate reached. `ruff check .`: all checks passed. `ruff format --check .`: 26 files already formatted. `mypy --strict --config-file pyproject.toml .`: Success, 26 files. The spec extraction script (TEMP) prints OK.
- W (WSL2 Ubuntu 24.04, Docker Engine, `/root/bitscan` rsynced from the tree, `/root/venv`, `CI=true`, pinned `RYUK_CONTAINER_IMAGE`, `SSL_CERT_FILE`): `pytest -rs -v tests/test_pg_harness.py`: 19 passed. Full suite `pytest -rs -q --cov=bitscan_manager/services --cov-fail-under=85`: 295 passed, 0 skipped, exit 0. `docker ps -a` was empty within 1–2 s after every run, including all mutation runs. Only the image `bitscan-test-postgres:16` remains, by design (`clean_up=False`).
- W statement and connection log (copy with `log_statement=all`, `log_connections=on`): `pytest -m pg`: 32 passed, 6 containers. Each had 25 superuser statements, all from the plan list, and 0 after the first app-role statement. Every TCP connection used SSL.
- W mutations: 17 throwaway copies under `/root/mut/<name>` (deleted afterwards). Mutated Dockerfiles were built under their own tags, which were removed afterwards.

## Mutations (planted in throwaway copies only)
| Mutation | Change | Result |
| --- | --- | --- |
| CONTROL | none | green, 19 passed |
| PORT_DEFAULT | port mapping line removed (default bind) | red: `test_port_is_published_on_localhost_only` |
| PORT_ALL | `("0.0.0.0", None)` | red: same test, `HostIp '0.0.0.0'` |
| HBA_HOST | first `hostssl` line changed to `host` | red: `test_connection_without_tls_is_refused` (DID NOT RAISE) |
| HBA_EXTRA_HOST | extra `host bitscan bitscan_app 0.0.0.0/0` line | red: same test |
| SSL_OFF | `ssl=off` | red: 12 setup errors (server unreachable over hostssl) |
| SU_FIXTURE | `app_conn` as `postgres`, `dsn()` guard disabled | red: 5 setup errors `('postgres', True)` and 2 failures |
| SU_FIXTURE_NOASSERT | the above, plus the `_role_conn` assertion removed | red: 3 tests including `test_fixtures_are_the_app_roles_and_not_superusers` |
| SU_PW_REACHABLE | `_su_password` put back on `PgServer` | red: `test_no_superuser_credential_is_reachable` |
| SU_EXTRA_GRANT | superuser `GRANT CREATE ON SCHEMA public TO bitscan_app` | red: `test_bootstrap_database_and_schema_privileges` |
| SU_EXTRA_TABLE | superuser `CREATE TABLE public.su_extra` | red: `test_migrate_from_bootstrap_twice_and_ownership` |
| SU_EXTRA_SELECT | superuser `SELECT 1` in the bootstrap phase | committed suite green; the statement log lists it (caught by the CHK-M1-036 method only) |
| LOG_LATE | superuser `SELECT 1` in `migrated_db` after the CLI migrate | committed suite green (32 passed); log scan: 1 superuser statement after the first app-role statement (caught by the log run only) |
| FIXED_PASSWORD | fixed literal passwords | committed suite green; covered by static review only |
| SPEC_CREATEDB | spec copy: `CREATE ROLE bitscan_app LOGIN CREATEDB;` | red: `test_bootstrap_roles_and_ownership` (the spec is read at test time) |
| SPEC_SHIFT | spec copy: paragraphs inserted above the heading | green, as expected (extraction by fence, not line number) |
| SPEC_LINE (pre-restructure run) | spec copy: `GRANT USAGE … TO bitscan_app;` (retention dropped) | green: on PG16, PUBLIC keeps USAGE on schema `public`, so this line has no visible effect (observation 4) |

## Acceptance
| REQ-032 criterion | Checks | Result |
| --- | --- | --- |
| (1) Bootstrap verbatim from TS §5.2 at test time, `\c bitscan` as a reconnect; the only other superuser statements are the listed ones | [CHK-M1-031](../../tests/m1/report.md), [CHK-M1-036](../../tests/m1/report.md) FAIL, then [CHK-M1-036-r1](../../tests/m1/report.md) PASS | PASS |
| (2) `db migrate` through the CLI with `BITSCAN_MIGRATE_DSN_FILE` in a temp file | [CHK-M1-032](../../tests/m1/report.md) | PASS |
| (3) every handed-out connection is app, retention or migrate, with `rolsuper` false | [CHK-M1-033](../../tests/m1/report.md) | PASS |
| (4) port bound to 127.0.0.1 only | [CHK-M1-034](../../tests/m1/report.md) | PASS |
| (5) TLS on; `sslmode=require` connects; non-TLS is refused | [CHK-M1-035](../../tests/m1/report.md) | PASS |
| (6) skip/exit hook | CHK-M1-030 (TP-M1-01, out of scope here). The L run confirms the pg tests skip with the right reason and the other tests pass | n/a |

## CHK-M1-036: is static review acceptable?
Not on its own. A review of `conftest.py` cannot see the image entrypoint's and the Testcontainers probe's superuser statements, and it did not stop the post-Bootstrap `reference_db` statements; the log run found all of these. Static review plus the statement-log run, as done here, is acceptable for this TEST. Before the M1 gate (CHK-M1-240), the log run should become a committed `pg` test, because two plantable violations (SU_EXTRA_SELECT, LOG_LATE) leave the committed suite green. That test would assert that the superuser statements equal the plan list and that none comes after the bootstrap phase.

## Observations (not blocking)
1. No committed guard against an extra read-only or post-migrate superuser statement (see above).
2. Password randomness is not asserted by a committed test. Evidence comes from static review (`secrets.token_hex(16)` per server) and the log (18 distinct values over 6 containers).
3. Ryuk publishes its control port on `0.0.0.0` and `[::]` during a session (Testcontainers default). This is not the PostgreSQL port.
4. The TS §5.2 `GRANT USAGE ON SCHEMA public TO bitscan_app, bitscan_retention` has no visible effect on PG16, because PUBLIC keeps USAGE on `public`. This is a spec and grant-probe topic (TP-M1-10), not a harness defect.
5. Both testers share one Docker daemon, and both build the tag `bitscan-test-postgres:16`. Containers from the other tester's run appeared while my runs were going. Concurrent runs from different trees can retag the image under each other.
