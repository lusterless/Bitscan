# M0 test plan (scaffolding)

Owner: tester. Written 2026-10-20 from `work/tasks.md` (acceptance tests and the M0 gate table G1 to G17) and `work/requirements.md` (REQ-001 to REQ-017), before any implementation was read. Results go to [report.md](report.md), one row per check id.

## Conventions

- Type: every M0 check is **CODE** (static gate, unit test or script on the tree). There is no running app in M0, so there are no **APP** checks.
- Local: `yes` = runs on the Windows 11 + Git Bash dev box. `NOT RUN locally (<reason>)` = runs only in CI; the reason is copied into the report row. Docker and WSL are absent (decisions PD-15), so PostgreSQL, `systemd-analyze` and running Linux ELF binaries are NOT RUN locally.
- Every Bash command starts with the PATH line from `work/m0-brief.md` (shown here as `$P;`). `R` = repo root `/c/Users/kaiquan.koh/Documents/Bitscan`. `PY` = `$R/manager/.venv/Scripts/python.exe` (dev lock + package installed). `PY312` = `/c/Users/kaiquan.koh/AppData/Local/Programs/Python/Python312/python.exe`.
- **Planted violations** are made only in a throwaway copy `T=$(mktemp -d)` (tree copied with `tar --exclude=.venv --exclude=node_modules --exclude=bin`; `web/node_modules` copied only where a web gate needs it) and deleted afterwards. Never in the tree. Each planted check runs the gate twice: once on the unmodified copy (must be green, so the red result is caused by the plant) and once with the plant (must be red).
- The M0 files are untracked, so a local `git diff --exit-code` on them is vacuous (always 0). Locally the "no diff" gates (G6, G16) are checked by snapshotting the file, regenerating and comparing bytes with `cmp`; the `git diff` form itself is checked in CI (TASK-009).
- Re-test rounds add report rows with a suffix on the plan id: `-rN` (round N re-run or regression), `-ctl` (green controls), `-nolint` and similar. Every suffixed row traces back to the plan id it extends; the plan id itself is unique.
- "Red" means exit code non-zero **and** the expected rule or message in the output (for example `TID251`, `S608`, `forbidigo`, `fail-under`), so a red result for an unrelated reason does not count.

## Gate map (M0 gate table to checks)

| Gate | Checks |
| --- | --- |
| G1 ruff check | CHK-M0-020 to CHK-M0-026 |
| G2 ruff format | CHK-M0-027, CHK-M0-028 |
| G3 mypy --strict | CHK-M0-029 to CHK-M0-031 |
| G4 pip --require-hashes | CHK-M0-002 to CHK-M0-008, CHK-M0-013 |
| G5 pytest + coverage | CHK-M0-032 to CHK-M0-034 |
| G6 OpenAPI export diff | CHK-M0-040, CHK-M0-041 |
| G7 gofmt | CHK-M0-065, CHK-M0-066 |
| G8 golangci-lint | CHK-M0-067 to CHK-M0-076 |
| G9 go mod verify | CHK-M0-077 |
| G10 CGO_ENABLED=0 build, go version -m, no-cgo listing, go test | CHK-M0-060 to CHK-M0-064, CHK-M0-078, CHK-M0-147 |
| G11 npm ci | CHK-M0-090, CHK-M0-091 |
| G12 npm run lint | CHK-M0-094 to CHK-M0-101 |
| G13 npm run typecheck | CHK-M0-092, CHK-M0-093 |
| G14 npm run format:check | CHK-M0-102, CHK-M0-103 |
| G15 npm test | CHK-M0-104, CHK-M0-105 |
| G16 OpenAPI client regeneration diff | CHK-M0-110 to CHK-M0-113 |
| G17 systemd-analyze verify | CHK-M0-124, CHK-M0-125 |
| CI wiring (all gates) | CHK-M0-130 to CHK-M0-152 |

## TASK-001 Manager project config and hashed lock files (REQ-001 to REQ-005)

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-001 | CODE | REQ-001 (1) | `project.requires-python` admits 3.12 and rejects 3.11 and 3.13: `manager/tests/test_project_config.py` reads `pyproject.toml` with `tomllib` and checks with `packaging.specifiers.SpecifierSet` (`"3.12.0"`, `"3.12.10"` in; `"3.11.9"`, `"3.13.0"` out). | (unit test, red if the specifier is widened) | yes |
| CHK-M0-002 | CODE | REQ-002 (1), G4 | Fresh venv: `$PY312 -m venv $T/v && $T/v/Scripts/python -m pip install --require-hashes -r manager/requirements.txt`; exit 0. | see CHK-M0-005 to -007 | yes (Windows). Linux: NOT RUN locally (no Linux host); CHK-M0-013 is the local proxy, CI runs the real install |
| CHK-M0-003 | CODE | REQ-002 (1), G4 | Same as CHK-M0-002 for `manager/requirements-dev.txt` in a second fresh venv; exit 0. | see CHK-M0-005 to -007 | yes (Windows); Linux as CHK-M0-002 |
| CHK-M0-004 | CODE | REQ-002 (2) | Every requirement line of both locks is `name==version` followed by at least one `--hash=sha256:<64 hex>` (`manager/tests/test_lock_files.py`, parses continuation lines; markers after `;` allowed). Each lock starts with a comment holding the `uv pip compile --universal --generate-hashes` command (decision PD-13). | (unit test) | yes |
| CHK-M0-005 | CODE | REQ-002 (3), G4 | Copy of each lock with one `--hash=` line removed, installed as in CHK-M0-002 in a fresh venv: exit non-zero, output names a hash mismatch or missing hash. | one hash removed | yes |
| CHK-M0-006 | CODE | REQ-002 (3), G4 | Copy of each lock with one digest character altered: install exits non-zero with `THESE PACKAGES DO NOT MATCH THE HASHES`. | one digest char altered | yes |
| CHK-M0-007 | CODE | REQ-002 (3), G4 | Copy of each lock with an unpinned line (`six`) appended: install exits non-zero (pip: hashes required / not pinned with `==`). | one unpinned line | yes |
| CHK-M0-008 | CODE | REQ-002 (4) | Runtime lock contains no `pytest*`, `ruff`, `mypy`, `testcontainers`, `coverage`, `hatchling` (unit test); the dev lock contains all of `pytest`, `pytest-cov`, `ruff`, `mypy`, `testcontainers`, `httpx`, `psycopg`, `hatchling` (build backend, TASK-001 plan step 3). | (unit test) | yes |
| CHK-M0-009 | CODE | REQ-001 (2) | In the CHK-M0-002 venv: `python -c "import fastapi, pydantic, apscheduler, defusedxml, re2; assert pydantic.VERSION.startswith('2.'); assert apscheduler.__version__.startswith('3.')"`; exit 0. | (fails if any import or version is wrong) | yes |
| CHK-M0-010 | CODE | REQ-001 (3) | No out-of-scope library in either lock: none of `authlib`, `oauthlib`, `requests-oauthlib`, `python-jose`, `oic`, `pyoidc`, `fastapi-sso`, `python-keycloak`, `msal`, `okta`, `social-auth-*` (unit test over lock names). | (unit test) | yes |
| CHK-M0-011 | CODE | REQ-003, REQ-004, REQ-005 (config) | `pyproject.toml`: ruff `target-version = "py312"`; banned-api includes `xml.etree`, `xml.dom`, `xml.sax`, `xml.parsers.expat`, `lxml`, `re`; mypy `strict = true`, `python_version = "3.12"`; coverage `source` is `bitscan_manager/services` only and `fail_under = 85`; pytest `addopts` has no `--cov-fail-under`; a PostgreSQL marker is declared; console script `bitscan-manager = "bitscan_manager.cli:main"`; version `0.1.0`. Behaviour of these settings is proved by the planted checks of TASK-002. | (unit test) | yes |
| CHK-M0-012 | CODE | REQ-002 | The locks are reproducible from the recorded command: rerun the header command into `$T` and `cmp` with the committed lock. | hand-edited lock | yes, if PyPI is reachable; otherwise NOT RUN locally (no network) |
| CHK-M0-013 | CODE | REQ-002 (1), PD-14 (j) | Linux proxy: for every line of both locks whose marker applies on Linux, `pip download --no-deps --only-binary=:all: --python-version 3.12 --implementation cp --platform manylinux_2_17_x86_64` (then `manylinux_2_17_aarch64`) of `name==version` into `$T/dl`, and the downloaded file's SHA-256 is one of that line's hashes. In particular `google-re2` has a cp312 wheel for Windows amd64, Linux x86_64 and Linux aarch64. | (red if a wheel is missing or its hash is not in the lock) | yes, if PyPI is reachable |

## TASK-002 Manager package skeleton (REQ-003 to REQ-008)

Unit tests live in `manager/tests/test_app.py`, `manager/tests/test_openapi.py` and `manager/tests/test_cli.py`.

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-020 | CODE | REQ-003 (1), G1 | `$P; cd $R && $PY -m ruff check manager`; exit 0. | — | yes |
| CHK-M0-021 | CODE | REQ-003 (2), G1 | In `$T`: `import os` added unused to `manager/bitscan_manager/app.py`; `ruff check $T/manager` exits non-zero with `F401`. | unused import | yes |
| CHK-M0-022 | CODE | REQ-003 (4), G1 | In `$T`, one plant at a time in `bitscan_manager/services/_plant.py`: `import xml.etree.ElementTree`, `from xml.etree import ElementTree`, `import xml.dom.minidom`, `import xml.sax`, `import xml.parsers.expat`, `import lxml.etree`; each exits non-zero with `TID251`. | stdlib or lxml XML parser | yes |
| CHK-M0-023 | CODE | REQ-003 (4) | In `$T`: `import defusedxml.ElementTree` in the same module passes `ruff check` (exit 0). | (negative control) | yes |
| CHK-M0-024 | CODE | REQ-003 (5), G1 | In `$T`, one at a time: `cur.execute(f"SELECT * FROM agent WHERE id = {x}")`, `cur.execute("SELECT * FROM agent WHERE id = " + x)`, `cur.execute("SELECT * FROM agent WHERE id = {}".format(x))`, `cur.execute("SELECT * FROM agent WHERE id = %s" % x)`; each exits non-zero with `S608`. | string-built SQL | yes |
| CHK-M0-025 | CODE | REQ-003 (6), G1 | In `$T`, one at a time: `import re`, `from re import compile`; each exits non-zero with `TID251` (PD-14 (g) accepted). `import re2` passes. | stdlib `re` in product code | yes |
| CHK-M0-026 | CODE | REQ-003 | The bans hold in every `bitscan_manager` sub-package, not just one file: plant `import xml.sax` in `bitscan_manager/cli/_plant.py` and `bitscan_manager/_plant.py`; each red. | same, other paths | yes |
| CHK-M0-027 | CODE | REQ-003 (1), G2 | `$PY -m ruff format --check manager`; exit 0. | — | yes |
| CHK-M0-028 | CODE | REQ-003 (3), G2 | In `$T`: append `x = ( 1,2 )` to `bitscan_manager/__init__.py`; `ruff format --check $T/manager` exits non-zero naming the file. | misformatted line | yes |
| CHK-M0-029 | CODE | REQ-004 (1), G3 | `$PY -m mypy --strict --config-file manager/pyproject.toml manager` from `$R`; exit 0 with `Success`. Also record the literal CLAUDE.md form `mypy --strict manager` (PD-16). | — | yes |
| CHK-M0-030 | CODE | REQ-004 (2), G3 | In `$T`: `def f(x): return x` in `bitscan_manager/services/_plant.py`; mypy (same command against `$T`) exits non-zero with `no-untyped-def`. | unannotated product function | yes |
| CHK-M0-031 | CODE | REQ-004 (3), G3 | In `$T`: `def test_x(): assert True` in `manager/tests/test_plant.py`; mypy exits non-zero with `no-untyped-def`. | unannotated test function | yes |
| CHK-M0-032 | CODE | REQ-005 (1), G5 | `$P; cd $R/manager && $PY -m pytest --cov=bitscan_manager/services --cov-fail-under=85`; exit 0. PostgreSQL-marked tests show as skipped with "not run: Docker unavailable" (reported, not counted as pass). | — | yes (unit); PostgreSQL part NOT RUN locally (Docker unavailable) |
| CHK-M0-033 | CODE | REQ-005 (2) | Same run with `--cov-report=term`: every file listed is under `bitscan_manager/services/`; `app.py` and `cli/` are not listed. | — | yes |
| CHK-M0-034 | CODE | REQ-005 (3), G5 | In `$T`: `bitscan_manager/services/_plant.py` with 20+ statements and no test; the coverage command from `$T/manager` exits non-zero with `Required test coverage of 85% not reached` (or `fail-under`). | untested 20+ statement module | yes |
| CHK-M0-035 | CODE | REQ-006 (1) | Unit test: `TestClient(create_app())` gets 404 for `GET /docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`, `/api/v1/agent/enroll` (and `POST /api/v1/agent/enroll`: 404 or 405 is not enough, must be 404). | (red if a doc route is served) | yes |
| CHK-M0-036 | CODE | REQ-006 (2) | Unit test: no `fastapi.routing.APIRoute` in `create_app().routes`; also no `starlette.routing.Route` or `Mount` (the doc routes are plain `Route`s). | — | yes |
| CHK-M0-037 | CODE | REQ-006 (3) | Unit test: `OPTIONS /api/v1/x` with `Origin: https://evil.example`, `Access-Control-Request-Method: GET` gets no header starting `access-control-allow-` (case-insensitive); same for a plain `GET` with `Origin`; no `CORSMiddleware` in `app.user_middleware`. | (red if CORS is added) | yes |
| CHK-M0-038 | CODE | REQ-006 (4) | Unit test: `create_app() is not create_app()`, and a route added to one is absent from the other. | — | yes |
| CHK-M0-039 | CODE | REQ-006 (5), REQ-007 (5) | Unit test with every `BITSCAN_*` variable removed and `socket.socket.connect` / `socket.create_connection` / `getaddrinfo` patched to raise: importing `bitscan_manager.app` (fresh import), `create_app()` and `openapi_document()` succeed; an `os.environ` access recorder sees no `BITSCAN_` key read. | (red on env read or network) | yes |
| CHK-M0-040 | CODE | REQ-007 (1), (2), (3) | Unit test: `write_openapi()` twice into `tmp_path` gives byte-identical files; bytes decode as UTF-8, contain no `\r`, end with exactly one `\n`; `json.dumps(json.loads(b), indent=2, sort_keys=True, ensure_ascii=False) + "\n"` equals the file (sorted keys); `openapi` starts with `3.1.`; `paths == {}`; `info.version == bitscan_manager.__version__ == "0.1.0"` (SemVer). Command-line form `python -m bitscan_manager.app <path>` run twice in a subprocess, same bytes. | — | yes |
| CHK-M0-041 | CODE | REQ-007 (4), G6 | Clean: unit test asserts committed `manager/openapi.json` bytes equal a fresh export; locally also `cp manager/openapi.json $T/o && $PY -m bitscan_manager.app manager/openapi.json && cmp manager/openapi.json $T/o` (then restore). Planted in `$T`: change the FastAPI `title` in `app.py`, or add `@app.get("/x")`; the export then differs from the committed file (`cmp` non-zero). | changed title; added route | yes (the `git diff` form: CI, CHK-M0-133) |
| CHK-M0-042 | CODE | REQ-008 (1) | `manager/.venv/Scripts/bitscan-manager.exe --help` exits 0; stdout contains `usage: bitscan-manager`. Unit test: `cli.main(["--help"])` raises `SystemExit(0)` or returns 0. | — | yes |
| CHK-M0-043 | CODE | REQ-008 (2) | Console script and `cli.main` with `[]`, `["serve"]`, `["db", "migrate"]`, `["db", "maintain"]`, `["bogus"]`: exit code non-zero, stderr non-empty, stdout empty. | — | yes |
| CHK-M0-044 | CODE | REQ-008 (2) | Unit test: during `cli.main(["serve"])` and `cli.main(["db","migrate"])` no `BITSCAN_*` key is read (recorder), no socket is created (`socket.socket.__init__` patched to raise), and no `psycopg`, `sqlalchemy` or `testcontainers` module is newly imported (`sys.modules` diff). | — | yes |
| CHK-M0-045 | CODE | REQ-001, TASK-001 plan step 3 | The package installs from hashed locks only: in the CHK-M0-003 venv, `pip install --no-deps --no-build-isolation -e manager` exits 0 and `bitscan-manager --help` works there. | — | yes |

## TASK-003 PostgreSQL 16 Testcontainers harness (REQ-009, REQ-004)

Implemented by tester; its TEST step is run by a second tester instance (PD-17). Files: `manager/tests/{__init__.py,conftest.py,test_pg_harness.py,postgres/Dockerfile}`.

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-050 | CODE | REQ-009 (1) | `cd manager && pytest -m pg tests/test_pg_harness.py` on a Docker host: `SHOW server_version_num` is in 160000 to 169999; `pg_trgm`, `pgcrypto`, `debversion` are in `pg_available_extensions`. | image on PostgreSQL 15 or without `postgresql-16-debversion` | NOT RUN locally (Docker unavailable) |
| CHK-M0-051 | CODE | REQ-009 (2) | Same run: `CREATE EXTENSION debversion` succeeds; `SELECT '1.0~rc1'::debversion < '1.0'::debversion` is `true` (and `'1.0'::debversion < '1.0~rc1'::debversion` is `false`, so the type is not plain text ordering). | — | NOT RUN locally (Docker unavailable) |
| CHK-M0-052 | CODE | REQ-009 (3) | After the session, `docker ps -a --filter label=org.testcontainers=true` lists no container from the run. | fixture without teardown | NOT RUN locally (Docker unavailable) |
| CHK-M0-053 | CODE | REQ-009 (4) | Without Docker and `CI` unset: `pytest -rs` exits 0, the PostgreSQL tests are reported `SKIPPED ... not run: Docker unavailable`, and the non-PostgreSQL unit tests still run and pass. | — | yes (Docker is absent) |
| CHK-M0-054 | CODE | REQ-009 (4) | Without Docker and `CI=true`: `CI=true pytest` exits non-zero with "Docker unavailable" in the output. | — | yes (Docker is absent) |
| CHK-M0-055 | CODE | REQ-009, PD-14 (n) | `manager/tests/postgres/Dockerfile`: `FROM postgres:16...@sha256:<64 hex>`; installs `postgresql-16-debversion`; no committed password literal in `conftest.py` (the password is generated per run). | tag without digest | yes (static) |
| CHK-M0-056 | CODE | REQ-004 | ruff check, ruff format --check and mypy --strict (CHK-M0-020, -027, -029) pass with the harness files present. | — | yes |
| CHK-M0-057 | CODE | REQ-009 | The image builds: `docker build manager/tests/postgres`. | — | NOT RUN locally (Docker unavailable) |

## TASK-004 Go module, golangci-lint config, binary stubs (REQ-010 to REQ-012)

`A` = `$R/agent`. Builds write to `$T/bin/linux_<arch>/`, not to the tree.

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-060 | CODE | REQ-010 (1), G10 | `$P; cd $A && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o $T/bin/linux_amd64/ ./cmd/...`, then `GOARCH=arm64`; both exit 0; each dir holds exactly `bitscan-agent`, `bitscan-runner`, `bitscan-capread`. | — | yes (cross-compile) |
| CHK-M0-061 | CODE | REQ-010 (2), G10 | `go version -m` on all six binaries shows `build CGO_ENABLED=0`, `build GOOS=linux` and the matching `build GOARCH`; the `mod`/`path` line names `bitscan.local/agent`. | — | yes |
| CHK-M0-062 | CODE | REQ-010 (2) | Static ELF check (local proxy for `file`): a Python script reads each ELF header and program headers; machine is x86-64 / AArch64 as expected; no `PT_INTERP` and no `PT_DYNAMIC` segment. On Linux CI, `file` says `statically linked` (CHK-M0-146). | — | yes (proxy); `file`: NOT RUN locally (Linux tool, CI) |
| CHK-M0-063 | CODE | REQ-010 (3) (reworded 2026-10-20), G10 | No agent package has a cgo file: from `agent/`, for `GOARCH` amd64 and arm64, `CGO_ENABLED=1 GOOS=linux go list -f '{{if .CgoFiles}}{{.ImportPath}}: {{.CgoFiles}}{{end}}' ./...` prints nothing on the tree. Planted in `$T`: `cmd/bitscan-agent/cgo_probe.go` (`package main`, `import "C"`) next to `main.go`: the listing prints `bitscan.local/agent/cmd/bitscan-agent: [cgo_probe.go]` while the `CGO_ENABLED=0` build still exits 0; and a cgo-only package imported by `main` makes the build exit non-zero. The CI step is CHK-M0-147. | `import "C"` | yes |
| CHK-M0-064 | CODE | REQ-010 (4) | Linux: each binary exits non-zero within 1 s, stdout empty, stderr exactly one line containing `not implemented`. Local proxy: build the same `./cmd/...` for `GOOS=windows` into `$T` and run each `.exe` with a 1 s timeout; same assertions. | — | proxy: yes; Linux ELF run: NOT RUN locally (no Linux host) |
| CHK-M0-065 | CODE | REQ-011 (1), G7 | `test -z "$(gofmt -l agent)"` from `$R`; exit 0. | — | yes |
| CHK-M0-066 | CODE | REQ-011 (2), G7 | In `$T`: `cmd/bitscan-agent/fmt_plant.go` with `package main\nfunc  x( ) {}`; `gofmt -l` prints that path. | misformatted file | yes |
| CHK-M0-067 | CODE | REQ-011 (1), G8 | `cd $A && golangci-lint run ./...`; exit 0, `0 issues`. | — | yes |
| CHK-M0-068 | CODE | REQ-011 (3), G8 | In `$T`: `func plant() { os.Remove("x") }` (ignored error) in a non-test file; lint exits non-zero with `errcheck`. | ignored error | yes |
| CHK-M0-069 | CODE | REQ-011 (4), G8 | In `$T`: `return fmt.Errorf("read: %v", err)`; lint exits non-zero with `errorlint`. Variant `%s`: also red. | `%v` wrap | yes |
| CHK-M0-070 | CODE | REQ-012 (1), G8 | In `$T`, one per run, in a non-test file: `net.Listen`, `net.ListenTCP`, `net.ListenUDP`, `net.ListenUnix`, `net.ListenPacket`, plus `net.ListenUnixgram`, `net.ListenIP`, `net.ListenMulticastUDP` (TASK-004 plan); each red with `forbidigo`. | listening socket call | yes |
| CHK-M0-071 | CODE | REQ-012 (2), G8 | Same for `http.ListenAndServe` and `http.ListenAndServeTLS`; each red with `forbidigo`. | listening HTTP server | yes |
| CHK-M0-072 | CODE | REQ-012 (3), G8 | Same for `_ = &tls.Config{InsecureSkipVerify: true}`; red with `gosec` G402. | TLS verification skipped | yes |
| CHK-M0-073 | CODE | REQ-012 (1)-(3) | The guards apply in "any agent package": repeat one plant of each kind in a new non-main package `internal/plant/plant.go` (imported or not) and in `cmd/bitscan-runner/`; each red. | same, other packages | yes |
| CHK-M0-074 | CODE | REQ-012 (1) | Evasions of the same calls: aliased import (`import n "net"; n.Listen(...)`) and a function value (`f := net.Listen`); each red. | aliased use | yes |
| CHK-M0-075 | CODE | REQ-012 (4) | In `$T`: the CHK-M0-070/071 calls in `cmd/bitscan-agent/plant_test.go` (package `main`); lint exits 0. | (negative control) | yes |
| CHK-M0-076 | CODE | REQ-012 statement (in scope: `main` ruling 2026-10-20) | Other standard-library listeners, one per run in a non-test file, each red with `forbidigo` (also with `--enable-only forbidigo`): `(&net.ListenConfig{}).Listen(ctx, ...)` (and `ListenPacket`), `(&http.Server{}).ListenAndServe()`, `.ListenAndServeTLS(...)`, `.Serve(l)`, `.ServeTLS(l, ...)`, `http.Serve(l, nil)`, `http.ServeTLS(...)`, `httptest.NewServer` / `NewTLSServer` / `NewUnstartedServer`, `syscall.Listen(...)`. Green controls: the same calls in a `_test.go` file pass lint (as CHK-M0-075). Regression: CHK-M0-070 to CHK-M0-075 re-run after the config change. | other listener APIs | yes |
| CHK-M0-077 | CODE | REQ-011 (5), G9 | `cd $A && go mod verify`; exit 0, prints `all modules verified`. No planted case is possible until the first dependency (M6). `go.mod`: module `bitscan.local/agent`, `go` directive is a supported release (1.26 or 1.27). | none possible in M0 | yes |
| CHK-M0-078 | CODE | G10 (PD-5) | `cd $A && go test ./...`; exit 0. Planted in `$T`: `cmd/bitscan-agent/fail_test.go` with `t.Fatal("x")`; exits non-zero. | failing test | yes |
| CHK-M0-079 | CODE | REQ-010, REQ-012 | Stubs do nothing: each `cmd/*/main.go` imports only `fmt` and `os` (or `os` only); no flags, network, file access. `go vet` clean (part of CHK-M0-067). | — | yes (static) |

## TASK-005 Web toolchain (REQ-013, REQ-014)

`W` = `$R/web`. Planted checks run in `$T/web` (a copy including `node_modules`).

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-090 | CODE | REQ-013 (1), G11 | `cd $T/web && npm ci` (fresh copy without `node_modules`); exit 0. Then the tree's `npm ci` once. | — | yes (needs npm registry) |
| CHK-M0-091 | CODE | G11 | In `$T/web`: add `"left-pad": "1.3.0"` to `dependencies` without touching the lock; `npm ci` exits non-zero (`npm ci` can only install ... in sync). | lock out of sync | yes |
| CHK-M0-092 | CODE | REQ-013 (2), G13 | `npx tsc --showConfig -p tsconfig.json` shows `"strict": true`; `npm run typecheck` exits 0. | — | yes |
| CHK-M0-093 | CODE | REQ-013 (2), G13 | In `$T/web/src/plant.ts`, one per run: `const n: number = "x";` (TS2322); `export function f(a) { return a; }` (TS7006); each makes `npm run typecheck` exit non-zero with that code. | type error; implicit any | yes |
| CHK-M0-094 | CODE | REQ-013 (3), G12 | `npm run lint` exits 0 on the clean tree. | — | yes |
| CHK-M0-095 | CODE | REQ-013 (3), G12 | Plant `const unused = 1;` in `src/plant.ts`; lint red (`no-unused-vars`). | unused variable | yes |
| CHK-M0-096 | CODE | REQ-014 (1), G12 | Plant `export const X = () => <div dangerouslySetInnerHTML={{ __html: "x" }} />;` in `src/plant.tsx`; lint red. | `dangerouslySetInnerHTML` | yes |
| CHK-M0-097 | CODE | REQ-014 (2), G12 | One per run in `src/plant.ts`: `document.body.innerHTML = "x";`, `el.outerHTML = "x";`, `el.insertAdjacentHTML("beforeend", "x");`, `document.write("x");`; each lint red. | HTML sinks | yes |
| CHK-M0-098 | CODE | REQ-014 (3), G12 | One per run: `localStorage.setItem("t","x")`, `window.localStorage.getItem("t")`, `sessionStorage.getItem("t")`, `const c = document.cookie;`, `document.cookie = "a=b";`; each lint red. | browser storage | yes |
| CHK-M0-099 | CODE | REQ-014 (4), G12 | One per run in `src/plant.ts` and in `src/features/plant.ts`: `void fetch("/x");`, `void window.fetch("/x");`, `void globalThis.fetch("/x");`, `new XMLHttpRequest();`; each lint red. | hand-written HTTP outside `src/api/` | yes |
| CHK-M0-100 | CODE | REQ-014 (4) | Negative control: `void fetch("/x");` in `src/api/plant.ts` passes the fetch rule (lint red only for unrelated reasons is not allowed: exit 0). | (negative control) | yes |
| CHK-M0-101 | CODE | REQ-014 | The guards apply to `.tsx` as well as `.ts`: repeat one plant of each of CHK-M0-097, -098, -099 in `src/plant.tsx`; each red. | same, `.tsx` | yes |
| CHK-M0-102 | CODE | REQ-013 (4), G14 | `npm run format:check` exits 0. | — | yes |
| CHK-M0-103 | CODE | REQ-013 (4), G14 | In `$T/web`: `src/main.tsx` with an extra `   ;;` line or `const  a=1` in a new `src/plant.ts`; format:check exits non-zero naming the file. | misformatted file | yes |
| CHK-M0-104 | CODE | REQ-013 (5), G15 | `npm test` exits 0 with no test files. | — | yes |
| CHK-M0-105 | CODE | G15 | In `$T/web`: `src/plant.test.ts` with `expect(1).toBe(2)` makes `npm test` exit non-zero; with `expect(1).toBe(1)` it exits 0 and reports 1 passed (proves tests are discovered). | failing test | yes |

## TASK-006 Generated API client (REQ-015, REQ-007)

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-110 | CODE | REQ-015 (1), G16 | Snapshot `web/src/api/` to `$T/snap`; `npm run gen:api` twice; `diff -r $T/snap web/src/api` empty after each run. Run with `npm_config_offline=true`, `HTTP_PROXY`/`HTTPS_PROXY=http://127.0.0.1:9` (no network proxy). | — | yes |
| CHK-M0-111 | CODE | REQ-015 (2), G16 | In `$T/web`: append `export type Plant = 1;` to `src/api/schema.d.ts`; `npm run gen:api` removes it (file equals the snapshot). | hand edit to generated file | yes |
| CHK-M0-112 | CODE | REQ-015 (3), G16 | In `$T`: add a path `/api/v1/x` to `manager/openapi.json`; without regeneration the snapshot comparison is clean, after regeneration `schema.d.ts` differs (so the CI diff check, which regenerates, exits non-zero). | `openapi.json` changed without regeneration | yes |
| CHK-M0-113 | CODE | REQ-015 (4) | `client.ts` contains no `http://`, `https://` or `//<host>` origin (scan excluding the `import` specifiers); it imports `paths` from the generated module and calls `createClient<paths>(...)` with a relative or empty `baseUrl`; `npm run typecheck` and `npm run lint` exit 0. | absolute origin in `client.ts` | yes |
| CHK-M0-114 | CODE | REQ-015 | `gen:api` reads `../manager/openapi.json` (the committed file) and `schema.d.ts` carries the generator header. | — | yes |

## TASK-007 and TASK-008 systemd units, verbatim (REQ-016)

Script: `deploy/tests/check_units_verbatim.py` (tester-owned), which strips the fence lines from the TS blocks and compares bytes.

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-120 | CODE | REQ-016 (1) | `$PY312 deploy/tests/check_units_verbatim.py agent`: `bitscan-runner.socket` = TS L290–L301, `bitscan-runner.service` = L309–L362, `bitscan-agent.service` = L370–L407, `bitscan-capread.socket` = L438–L448, `bitscan-capread.service` = L452–L481 (fences at L289/L302, L308/L363, L369/L408, L437/L449, L451/L482), each byte-identical with LF endings and a final newline; exit 0. | one changed byte in a copy | yes |
| CHK-M0-121 | CODE | REQ-016 (1) | `$PY312 deploy/tests/check_units_verbatim.py manager`: `bitscan-manager.service` = L1353–L1400, `bitscan-manager-migrate.service` = L1406–L1434, `bitscan-manager-maintain.service` = L1440–L1466, `bitscan-manager-maintain.timer` = L1470–L1479; exit 0. | one changed byte in a copy | yes |
| CHK-M0-122 | CODE | REQ-016 (2) | No line in `deploy/systemd/*` has a `#` after a directive (only lines whose first non-blank character is `#` may contain `#`); part of the script. | end-of-line comment | yes |
| CHK-M0-123 | CODE | REQ-016 (3) | `bitscan-capread.service` has no `[Install]` section; `deploy/systemd/` holds exactly the nine unit files (no D-Bus policy in M0). | — | yes |
| CHK-M0-124 | CODE | REQ-016 (4), G17 | On Linux with stub binaries in `/usr/sbin/` and `/usr/bin/bitscan-manager`: `systemd-analyze verify deploy/systemd/*` exits 0 with no output. | — | NOT RUN locally (Git Bash has no systemd; no WSL) |
| CHK-M0-125 | CODE | REQ-016 (5), G17 | In a copy: an end-of-line comment (`ProtectSystem=strict # x`) and, separately, an unknown directive (`Bogus=1`) each make `systemd-analyze verify` report an error. | EOL comment; unknown directive | NOT RUN locally (no systemd) |

## TASK-009 CI: manager and web workflows (REQ-017)

Static checks parse `.github/workflows/manager.yml` and `web.yml` (YAML via the dev venv or Node). Live runs need a pushed PR branch, which the team may not create (never push).

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-130 | CODE | REQ-017 (1) | Both workflows trigger on `pull_request` and on `push` to `main`. | — | yes (static) |
| CHK-M0-131 | CODE | REQ-017 (1) | `manager.yml` has its own step for each of G1 (`ruff check manager`), G2 (`ruff format --check manager`), G3 (`mypy --strict --config-file manager/pyproject.toml manager`), G4 (`pip install --require-hashes` for both locks into a fresh 3.12 environment, then the package with `--no-deps --no-build-isolation`), G5 (`pytest --cov=bitscan_manager/services --cov-fail-under=85` from `manager/`), G6 (export, then `git diff --exit-code -- manager/openapi.json`). | — | yes (static) |
| CHK-M0-132 | CODE | REQ-017 (1) | `web.yml` has its own step for each of G11 (`npm ci`), G12 (`npm run lint`), G13 (`npm run typecheck`), G14 (`npm run format:check`), G15 (`npm test`), G16 (export, `npm run gen:api`, `git diff --exit-code -- manager/openapi.json web/src/api/`), all in `web/`. | — | yes (static) |
| CHK-M0-133 | CODE | REQ-017 (1) | No step or job in either file has `continue-on-error`, `|| true`, `|| :`, `set +e`, or an `if:` that can skip a gate step; no `paths-ignore` that skips the workflow for gate files. | any of these | yes (static) |
| CHK-M0-134 | CODE | REQ-017 (4) | Python jobs set up CPython `3.12`; the Node version is pinned (Active LTS, 24.x); the PostgreSQL tests run on a runner with Docker and `CI=true` (GitHub sets it; not overridden to false). | — | yes (static) |
| CHK-M0-135 | CODE | REQ-017 (7) | No `${{ secrets.* }}`, no token or credential literal (`bsa_`, `bsk_`, `bsu_`, `bse_`, `ghp_`, `AKIA`, `password:`) in either file; `permissions:` is read-only (`contents: read`). | — | yes (static) |
| CHK-M0-136 | CODE | REQ-017 (2) | Both workflows pass on a PR branch with the clean tree. | — | NOT RUN locally (needs GitHub Actions and a pushed PR branch; pushing is not authorised) |
| CHK-M0-137 | CODE | REQ-017 (3) | For each of G1 to G6 and G11 to G16, a PR carrying one planted violation from the gate table fails that job. Local substitute: the matching planted checks above (CHK-M0-021 to -034, -041, -091 to -105, -111, -112) are run with the workflow's exact `run:` command lines. | one per gate | live: NOT RUN locally (as CHK-M0-136); substitute: yes |

## TASK-010 CI: agent and units workflows (REQ-017, REQ-010, REQ-011, REQ-016)

| Id | Type | REQ | Check and command | Planted violation (must turn it red) | Local |
| --- | --- | --- | --- | --- | --- |
| CHK-M0-140 | CODE | REQ-017 (1) | `agent.yml` and `units.yml` trigger on `pull_request` and `push` to `main` (a `paths:` filter, if any, includes `agent/**`, `deploy/systemd/**`, `manager/**` and the workflow file itself). | — | yes (static) |
| CHK-M0-141 | CODE | REQ-017 (1), (5) | `agent.yml` has its own step for G7 (`test -z "$(gofmt -l ...)"` that also prints the list), G8 (`golangci-lint run ./...`, pinned v2.14.0), G9 (`go mod verify`), G10 (amd64 and arm64 `CGO_ENABLED=0` builds into `bin/linux_<arch>/`, `go version -m` check failing unless `CGO_ENABLED=0`, `file` showing `statically linked`, `go test ./...`). Go version taken from `agent/go.mod`. | — | yes (static) |
| CHK-M0-142 | CODE | REQ-017 (6) | `units.yml` installs the built stubs to `/usr/sbin/` and the manager console script (from the hashed lock, `--no-deps --no-build-isolation`) to `/usr/bin/bitscan-manager` **before** `systemd-analyze verify deploy/systemd/*`, and the step fails on a non-zero exit or any output. | — | yes (static) |
| CHK-M0-143 | CODE | REQ-017 (1), (7) | CHK-M0-133 and CHK-M0-135 applied to `agent.yml` and `units.yml`. | — | yes (static) |
| CHK-M0-144 | CODE | REQ-017 (2) | Both workflows pass on a PR branch with the clean tree. | — | NOT RUN locally (needs GitHub Actions and a pushed PR branch) |
| CHK-M0-145 | CODE | REQ-017 (3) | For each of G7 to G10 and G17, a planted violation fails that job. Local substitute: CHK-M0-063, -066, -068 to -072, -078 with the workflow's exact commands; G17 has no local substitute. | one per gate | live: NOT RUN locally; substitute: yes except G17 |
| CHK-M0-146 | CODE | REQ-010 (2), (4) | In CI: `file` reports each binary statically linked, and each binary run on the runner exits non-zero within 1 s with one `not implemented` line on stderr. | — | NOT RUN locally (Linux ELF) |
| CHK-M0-147 | CODE | REQ-010 (3), G10 | `agent.yml` has its own no-cgo step: for `GOARCH` amd64 and arm64, `out="$(CGO_ENABLED=1 GOOS=linux GOARCH=$GOARCH go list -f '{{if .CgoFiles}}{{.ImportPath}}: {{.CgoFiles}}{{end}}' ./...)"`, printing `$out` and exiting non-zero if it is non-empty (static check). Local substitute: run the step's exact script on the tree (exit 0) and on a copy with `cmd/bitscan-agent/cgo_probe.go` (`import "C"` next to `main.go`): exit non-zero naming `bitscan.local/agent/cmd/bitscan-agent`. | `import "C"` next to `main.go` | static and substitute: yes; live PR run: NOT RUN locally (as CHK-M0-144) |

## Not tested in M0

Everything the coverage matrix in `work/tasks.md` marks uncovered (M1 to M8). G9 cannot be shown red until the agent has a dependency (M6).
