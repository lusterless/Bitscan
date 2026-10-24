# Tasks

Owner: planner. Ids are never renumbered or reused. Each TASK becomes `TASK-### IMPL`, `TASK-### TEST`, `TASK-### REVIEW`, in that order. Requirements are in `work/requirements.md`; plans for risky tasks are in `work/plans/`.

Row format: `TASK-### | title | REQ links | area | owner | files expected (<= 5) | depends on | est. LOC (<= 200) | acceptance test`.

LOC counts hand-written lines only. Generated files (`manager/requirements*.txt`, `web/package-lock.json`, `manager/openapi.json`, `web/src/api/schema.d.ts`) are counted as files, not lines; the reviewer checks they are reproducible from the stated command, not line by line.

## M0 scaffolding (done)

The M0 sections below (through "M0 changes since approval") are history and stay as approved. M1 follows them.

| TASK | Title | REQ links | Area | Owner | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-001 | Manager project config and hashed lock files (plan: `work/plans/TASK-001.md`) | REQ-001, REQ-002, REQ-003, REQ-004, REQ-005 | manager | impl-manager | `manager/pyproject.toml`, `manager/requirements.txt`, `manager/requirements-dev.txt` | none | 120 (+2 generated) | In a fresh CPython 3.12 venv on Linux and on Windows, `pip install --require-hashes -r manager/requirements.txt` and the same for `manager/requirements-dev.txt` each exit 0, and each exits non-zero on a copy of the file with one `--hash` value removed or altered. |
| TASK-002 | Manager package skeleton: app factory, CLI stub, services package, OpenAPI export (plan: `work/plans/TASK-002.md`) | REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008 | manager | impl-manager | `manager/bitscan_manager/__init__.py`, `manager/bitscan_manager/app.py`, `manager/bitscan_manager/cli/__init__.py`, `manager/bitscan_manager/services/__init__.py`, `manager/openapi.json` | TASK-001 | 90 (+1 generated) | With the dev lock installed, ruff, ruff format, `mypy --strict` and the coverage command pass; a test client on `create_app()` gets 404 for `/docs`, `/redoc` and `/openapi.json` and no `Access-Control-Allow-*` header on a CORS preflight; re-running the export leaves `manager/openapi.json` byte-identical, with `openapi` starting `3.1.` and empty `paths`; and `bitscan-manager --help` exits 0 while `bitscan-manager serve` exits non-zero. |
| TASK-003 | Testcontainers PostgreSQL 16 harness with `debversion` (plan: `work/plans/TASK-003.md`) | REQ-009, REQ-004 | manager (tests) | tester | `manager/tests/__init__.py`, `manager/tests/conftest.py`, `manager/tests/test_pg_harness.py`, `manager/tests/postgres/Dockerfile` | TASK-001 | 130 | On a host with Docker, the harness test finds `server_version_num` in 160000–169999, the three extensions in `pg_available_extensions` and `'1.0~rc1'::debversion < '1.0'::debversion` true; with Docker stopped it reports "not run: Docker unavailable" locally and fails when `CI=true`. |
| TASK-004 | Go module, golangci-lint config and three binary stubs (plan: `work/plans/TASK-004.md`) | REQ-010, REQ-011, REQ-012 | agent | impl-agent | `agent/go.mod`, `agent/.golangci.yml`, `agent/cmd/bitscan-agent/main.go`, `agent/cmd/bitscan-runner/main.go`, `agent/cmd/bitscan-capread/main.go` | none | 110 | From `agent/`, `CGO_ENABLED=0` linux/amd64 and linux/arm64 builds of `./cmd/...` succeed, `go version -m` shows `CGO_ENABLED=0` on all six binaries, and the TASK-010 CgoFiles listing prints nothing; `gofmt -l agent` prints nothing; `golangci-lint run ./...` and `go mod verify` exit 0; and golangci-lint exits non-zero when a non-test file calls `net.Listen` or `http.ListenAndServe`, sets `InsecureSkipVerify: true`, ignores an error or wraps one with `%v`. |
| TASK-005 | Web toolchain: package, strict tsconfig, ESLint with security guards, Prettier | REQ-013, REQ-014 | web | impl-web | `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/eslint.config.js`, `web/src/main.tsx` | none | 150 (+1 generated) | In `web/`, `npm ci`, `npm run lint`, `npm run typecheck`, `npm run format:check` and `npm test` exit 0 on the clean tree; lint exits non-zero for a planted `dangerouslySetInnerHTML`, `.innerHTML =`, `localStorage`, `sessionStorage` or `document.cookie` use, or a `fetch(` call outside `web/src/api/`; typecheck exits non-zero for a planted implicit `any`; format:check exits non-zero for a misformatted file. |
| TASK-006 | Generated API client from `manager/openapi.json` | REQ-015, REQ-007 | web | impl-web | `web/package.json` (adds `gen:api`), `web/src/api/schema.d.ts`, `web/src/api/client.ts` | TASK-002, TASK-005 | 25 (+1 generated) | Running `npm run gen:api` twice from the committed `manager/openapi.json` leaves `git diff --exit-code -- web/src/api/` at 0; a hand edit to `schema.d.ts` is reverted by regeneration; `client.ts` has no absolute origin; and `npm run typecheck` passes. |
| TASK-007 | Agent systemd units, verbatim from TS §3.7 | REQ-016 | deploy | impl-deploy | `deploy/systemd/bitscan-agent.service`, `deploy/systemd/bitscan-runner.socket`, `deploy/systemd/bitscan-runner.service`, `deploy/systemd/bitscan-capread.socket`, `deploy/systemd/bitscan-capread.service` | none | 150 (verbatim copy) | A script that strips the fences from the TS blocks at L289–L302, L308–L363, L369–L408, L437–L449 and L451–L482 finds each byte-identical to its `deploy/systemd/` file; on Linux with stub binaries in `/usr/sbin`, `systemd-analyze verify` on the five files exits 0 with no output. |
| TASK-008 | Manager systemd units, verbatim from TS §8.7 | REQ-016, REQ-008 | deploy | impl-deploy | `deploy/systemd/bitscan-manager.service`, `deploy/systemd/bitscan-manager-migrate.service`, `deploy/systemd/bitscan-manager-maintain.service`, `deploy/systemd/bitscan-manager-maintain.timer` | none | 120 (verbatim copy) | The same fence-stripping script finds the four files byte-identical to the TS blocks at L1352–L1401, L1405–L1435, L1439–L1467 and L1469–L1480; on Linux with `/usr/bin/bitscan-manager` installed from TASK-002, `systemd-analyze verify` on the four files exits 0 with no output. |
| TASK-009 | CI workflows: manager gates, web gates, OpenAPI regeneration diff | REQ-017, REQ-002, REQ-005, REQ-007, REQ-015 | deploy (CI) | impl-deploy | `.github/workflows/manager.yml`, `.github/workflows/web.yml` | TASK-001, TASK-002, TASK-003, TASK-006 | 130 | On a PR branch both workflows pass on the clean tree, and each of their jobs fails when one planted violation from the M0 gate table for that job is pushed (rows G1–G6 and G11–G16). |
| TASK-010 | CI workflows: agent gates on a Linux runner (including the no-cgo listing and the no-nolint/no-linkname step) and systemd units verify (plan: `work/plans/TASK-010.md`) | REQ-017, REQ-010, REQ-011, REQ-012, REQ-016 | deploy (CI) | impl-deploy | `.github/workflows/agent.yml`, `.github/workflows/units.yml` | TASK-002, TASK-004, TASK-007, TASK-008 | 140 | On a PR branch both workflows pass on the clean tree, and each job fails when one planted violation from the M0 gate table for that job is pushed (rows G7–G10 and G17), including four that golangci-lint or the build alone miss: an `import "C"` file next to `main.go` in `agent/cmd/bitscan-agent/`, and a `raw_amd64.s` file there implementing a body-less func (both caught by the cgo/asm/syso listing), a `//nolint:forbidigo` comment on a `net.Listen` call in a non-test file, and a `//go:linkname` directive in a non-test file (both caught by the no-nolint/no-linkname step). |

Totals: 17 REQ, 10 TASK, 4 waves. All tasks are within 5 files and 200 hand-written lines.

### Notes on scope (trimmed from the candidate list)

- **No empty Python sub-packages** (`api/agent/`, `auth/`, `services/<area>/`, `repositories/`, `db/migrations/`, `config/`): about 20 empty `__init__.py` files add nothing testable and break the 5-file limit. Each is created by the first task that puts code in it (M1 onwards). M0 creates only `services/`, because the coverage gate must point at it, and `cli/`, because the units need `/usr/bin/bitscan-manager`.
- **No `agent/internal/*` stubs**: they add nothing testable. Each is created in M6 with its code.
- **No web bundler or build** (Vite or similar): no M0 gate needs it, and how the manager serves `web/dist` is open (#6). Deferred to M7.
- **No D-Bus policy**: no M0 gate checks it. It ships with the `.deb` in M6.
- **TASK-007 and TASK-008 are a trim candidate.** They exist only so the `systemd-analyze verify` gate can run and fail in M0. If the lead prefers, move them, and the units job in TASK-010, to M6; the M0 gate table then drops G17.
- **Nothing for `bits/` or `e2e/`** in M0.

### Owner and review notes

- TASK-003 is implemented by the tester (test infrastructure). Its TEST step cannot be the tester's own: PD-17 proposes `smoke-tester` or the lead.
- TASK-004 and TASK-007 touch agent and runner code or units, which need two approvals (TS §8.2 L1268). Until PD-3 is decided, the second approver is the user, batched per wave (decisions 2026-10-19).
- Planted violations are made in a throwaway copy or branch (for example `git worktree`), never left in the tree.
- TASK-001 owns `manager/pyproject.toml`, so any mypy or pytest override the tester needs for TASK-003 (for example for `testcontainers` typing) is requested from impl-manager, not edited by the tester.

## M0 waves and dependency spine

Spine: `TASK-001 → TASK-002 → TASK-006 → TASK-009`, with `TASK-005 → TASK-006` and `TASK-004, TASK-007, TASK-008 → TASK-010`. The graph is acyclic.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-001, TASK-004, TASK-005, TASK-007, TASK-008 | `manager/pyproject.toml`, `manager/requirements*.txt` · `agent/go.mod`, `agent/.golangci.yml`, `agent/cmd/*/main.go` · `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/eslint.config.js`, `web/src/main.tsx` · `deploy/systemd/bitscan-{agent,runner,capread}.*` · `deploy/systemd/bitscan-manager*` |
| W2 | TASK-002, TASK-003 | `manager/bitscan_manager/{__init__.py,app.py,cli/__init__.py,services/__init__.py}`, `manager/openapi.json` · `manager/tests/{__init__.py,conftest.py,test_pg_harness.py,postgres/Dockerfile}` |
| W3 | TASK-006, TASK-010 | `web/package.json`, `web/src/api/{schema.d.ts,client.ts}` · `.github/workflows/{agent,units}.yml` |
| W4 | TASK-009 | `.github/workflows/{manager,web}.yml` |

TASK-007 and TASK-008 have the same owner (impl-deploy), so they run one after the other within W1; their files are disjoint, so the order does not matter.

## M0 gate

The M0 exit gate: on a clean tree every command below is green, and each turns red on its planted violation. Commands run from the repository root unless a working directory is given. The working directory for the Python commands depends on PD-16; the test and coverage commands are PD-5 placeholders until the user decides.

"Local" means the Windows 11 + Git Bash dev box. Under the PD-5 convention, anything that cannot run there is reported as "not run locally: <reason>" and runs in CI (or WSL2, if the user confirms one exists).

| Gate | Command | Planted violation that must turn it red | Local |
| --- | --- | --- | --- |
| G1 | `ruff check manager` | unused import; `import xml.etree.ElementTree` in `bitscan_manager/`; f-string SQL passed to `execute()` | yes |
| G2 | `ruff format --check manager` | one misformatted line | yes |
| G3 | `mypy --strict manager` (config discovery: PD-16) | function with no annotations in `bitscan_manager/` or `manager/tests/` | yes |
| G4 | `pip install --require-hashes -r manager/requirements.txt` in a fresh 3.12 venv (and the dev lock, PD-13) | one hash removed or altered; one unpinned line | yes, if the lock resolves for Windows too (PD-13); otherwise not run locally: platform-specific lock |
| G5 | `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` (PD-5 placeholder) | untested module of 20+ statements under `services/` | yes for unit tests; PostgreSQL tests need Docker (PD-15), otherwise not run locally: Docker unavailable |
| G6 | export the OpenAPI document to `manager/openapi.json` (command fixed in TASK-002), then `git diff --exit-code -- manager/openapi.json` | app title changed or route added without re-export | yes |
| G7 | `test -z "$(gofmt -l agent)"` | one misformatted `.go` file | yes |
| G8 | `cd agent && golangci-lint run ./...` on a **Linux** runner (authoritative: on the Windows dev box `GOOS=windows`, so `_linux.go` files are not linted); then the **no-nolint/no-linkname step**: `if grep -rnE --include='*.go' --exclude='*_test.go' '//[[:space:]]*(nolint\|go:linkname)' .; then echo "nolint or go:linkname in non-test agent code"; exit 1; fi` (from `agent/`; same result as the reviewer's reference `grep -rnE '//[[:space:]]*nolint' --include='*.go' agent \| grep -vE '_test\.go:'` must print nothing) | ignored error; `%v` error wrap; `net.Listen` or `http.ListenAndServe` in a non-test file; `InsecureSkipVerify: true`; **a `//nolint:forbidigo` comment on a `net.Listen` call in a non-test file** (golangci-lint passes, so the step must fail); **a `//go:linkname` directive in a non-test file** (for example `//go:linkname listen net.Listen` above a body-less `func listen(network, address string) (net.Listener, error)` in `agent/cmd/bitscan-agent/`; the step must fail) | lint: yes, but it misses `_linux.go` files, so CI on Linux is authoritative. No-nolint step: yes (Git Bash `grep`) |
| G9 | `cd agent && go mod verify` | none possible until the first dependency (M6): with no dependencies it always prints "all modules verified" | yes |
| G10 | `cd agent && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o <out> ./cmd/...`, then the same with `GOARCH=arm64`; `go version -m` shows `CGO_ENABLED=0`; **no-cgo/asm/syso listing:** for `GOARCH` in amd64 and arm64, `out="$(CGO_ENABLED=1 GOOS=linux GOARCH=$GOARCH go list -f '{{if or .CgoFiles .SFiles .SysoFiles}}{{.ImportPath}}: cgo={{.CgoFiles}} s={{.SFiles}} syso={{.SysoFiles}}{{end}}' ./...)"`, failing if `$out` is non-empty (and printing it); `go test ./...` (PD-5) | (a) a package whose only file has `import "C"`: the build fails; (b) a file with `import "C"` next to `main.go` in `agent/cmd/bitscan-agent/`: the build still exits 0, so the **listing** must print the package and fail the step; (c) `raw_amd64.s` next to `agent/cmd/bitscan-agent/main.go`, implementing a body-less func declared there: the listing for amd64 must print `s=[raw_amd64.s]` and fail the step; (d) a `.syso` file in an agent package: the listing must fail the step | build, `go version -m` and the listing: yes (cross-compile; `go list` compiles nothing, so it needs no C compiler, which impl-deploy confirms in the TASK-010 report). Running the ELF stubs and the `file` static check: not run locally: Linux binaries |
| G11 | `cd web && npm ci` | committed lock file out of sync with `package.json` | yes |
| G12 | `cd web && npm run lint` | unused variable; `dangerouslySetInnerHTML`; `.innerHTML =`; `localStorage`, `sessionStorage` or `document.cookie`; `fetch(` outside `web/src/api/` | yes |
| G13 | `cd web && npm run typecheck` | `const n: number = "x"`; an implicit `any` parameter | yes |
| G14 | `cd web && npm run format:check` (Prettier `--check`) | one misformatted file | yes |
| G15 | `cd web && npm test` (PD-5 placeholder) | a failing test (tester's check) | yes |
| G16 | G6, then `cd web && npm run gen:api`, then `git diff --exit-code -- manager/openapi.json web/src/api/` | hand edit to `web/src/api/schema.d.ts`; `manager/openapi.json` changed without regeneration | yes |
| G17 | `systemd-analyze verify deploy/systemd/*`, with the built binaries installed at `/usr/sbin/` and `/usr/bin/bitscan-manager` | end-of-line comment or unknown directive in a unit copy | not run locally: Git Bash has no systemd (WSL2 with systemd only if the user confirms it, PD-15) |

Not M0 gates (later milestones): migrations forward-only and schema diff (M1), contract fixtures (M4/M6), agent and sandbox suites on Ubuntu 22.04, 24.04, Debian 12 and arm64 hardware (M6, Linux VMs only), lintian, reproducible builds and SBOM (M6), end-to-end and load (M8).

## Open items for M0

Recorded in `work/open-questions.md`. Blocking means a task cannot start or finish without the answer.

| Item | Blocks | Summary |
| --- | --- | --- |
| PD-5 | TASK-009, TASK-010 (and G5, G10, G15) | Test and coverage commands and the "not run locally" convention; who adds them to CLAUDE.md "Commands" |
| PD-9 | TASK-010 | Build output path for Go binaries (suggested `agent/bin/linux_<arch>/`, already in `.gitignore`) |
| PD-13 (new) | TASK-001 | How hashed lock files are produced so they install on both Windows and Linux; runtime/dev split |
| PD-14 (new) | TASK-001 to TASK-006 | Tool choices the spec leaves open (module path, Go and Node versions, generator, lint versions, OpenAPI file location, `re` ban, build backend, driver, RE2 binding, APScheduler major, initial version, Postgres image); can be approved together |
| PD-15 (new) | TASK-003, G5, G17 | Is Docker (and WSL2 with systemd) on the dev box; missing Docker is "not run" locally and a failure in CI |
| PD-16 (new) | TASK-001, TASK-009 (G3, G5) | `mypy --strict manager` run from the root does not read `manager/pyproject.toml`; choose how the config is found |
| PD-17 (new) | TASK-003 TEST | Who runs the TEST step of a tester-implemented task |
| #34 (new, proposed) | none (M0 takes the no-route reading) | Is the OpenAPI document served at runtime, and how is it authenticated |
| PD-2, PD-3 | every REVIEW | Review baseline; second approver for TASK-004 and TASK-007 |
| PD-11, PD-12 | TASK-004; reviewers of TASK-001 and TASK-004 | Go version in the user's memory file; no rule loads for `pyproject.toml`, `go.mod`, `.golangci.yml` |
| #6 | none in M0 | How the manager is installed. M0 only provides the console script so the units can be verified; the CI symlink to `/usr/bin` is test scaffolding, not the install method |
| #5 | none in M0 | `/healthz` and `/readyz` prefix and auth; M0 adds no health route |
| PD-18 (new, M1 note) | M1 breakdown | The TS §5.2 DDL (L637–L1014, about 380 lines) cannot fit the 200-line task limit, and the rules require the *first* migration to seed `system_schedule` and settings and create partitions |

## Coverage matrix (M0)

| Spec section | Covered by | Status in M0 |
| --- | --- | --- |
| TS §2.1 Components (stack facts) | REQ-001, REQ-006, REQ-009, REQ-010, REQ-013 / TASK-001, -002, -003, -004, -005 | Covered for the stack (Python 3.12, FastAPI, Pydantic v2, APScheduler pinned, PostgreSQL 16 with extensions in tests, Go static binaries, React + TypeScript). Component behaviour (scheduler, importer, evaluator, agent) is uncovered: M1 to M6 |
| TS §2.2 Design principles (pull, not push) | REQ-012 / TASK-004, TASK-010 (no-nolint step) | Lint guard only; runtime behaviour M4/M6 |
| TS §2.3 Data flows and tokens | REQ-006 (no unauthenticated default routes) / TASK-002 | Partial; token handling M3 |
| TS §3.1 Packaging and install | REQ-010, REQ-016 / TASK-004, -007 | Binary names and units only; `.deb`, debconf, maintainer scripts, D-Bus policy M6 |
| TS §3.7 Privilege model (unit files) | REQ-016 / TASK-007 | Unit files only; sandbox suites M6 |
| TS §6 intro (OpenAPI 3.1 from code) | REQ-006, REQ-007, REQ-015 / TASK-002, -006 | Covered for an empty API; routes M3 to M5 |
| TS §6.3 Conventions (no CORS, plain text, CSP) | REQ-006, REQ-014 / TASK-002, -005 | No-CORS check and lint guards only; headers middleware M3, UI M7 |
| TS §8.1 Security controls | REQ-002, REQ-003, REQ-012, REQ-014 | Supply chain (hashed deps), XML and SQL lint guards, no listener, XSS sinks. Other rows uncovered: M1 to M8 |
| TS §8.2 Coding standards | REQ-001 to REQ-005, REQ-010, REQ-011, REQ-013, REQ-015 / TASK-001 to -006 | Repo layout, Python, Go, TypeScript covered. Commits, semver and reviews are process (no task). Configuration rule uncovered: M3 (config-and-cli) |
| TS §8.3 Testing | REQ-005, REQ-009, REQ-016, REQ-017 / TASK-001, -003, -007 to -010 | Unit coverage gate, integration harness base and the units verify gate. **Uncovered:** property/fuzz (M2), contract (M4/M6), integration content (M1 onwards), agent (M6), sandbox suites (M6), end-to-end and load (M8), security (M2 to M6) |
| TS §8.6 Manager configuration | (none) | **Uncovered**: start-up config and settings are M1/M3. M0 uses it only for stack facts |
| TS §8.7 Manager deployment | REQ-008, REQ-016 / TASK-002, -008 | Unit files and CLI entry point only. Install method (#6), folders, migrate and maintain commands: M1 and later |
| TS §1, §3.2 to §3.6, §4, §5, §6.1, §6.2, §6.4, §6.5, §7, §8.4, §8.5; SR (all) | (none) | **Uncovered in M0 by design**: M1 to M8 |

## M0 changes since approval

| Date | Change | Why |
| --- | --- | --- |
| 2026-10-20 | **No-cgo check.** REQ-010 (3) and the TASK-004 plan no longer say a `CGO_ENABLED=0` build fails on any `import "C"` file. TASK-010 (row and plan) and gate G10 gain a CI step: `CGO_ENABLED=1 GOOS=linux go list -f '{{if .CgoFiles}}{{.ImportPath}}: {{.CgoFiles}}{{end}}' ./...` for amd64 and arm64, failing on any output. Its planted violation is an `import "C"` file next to `main.go` in `agent/cmd/bitscan-agent/`. TASK-010 stays at 2 files; its estimate goes from 120 to 130 lines. TASK-004 itself is unchanged; its acceptance test now also names the listing. | impl-agent found (`work/reports/TASK-004-impl.md`) that with `CGO_ENABLED=0` such a file is silently left out of the build. The build then exits 0 unless the file is the package's only one, so the build alone could not prove "no CGO" (TS §8.2 L1265). |
| 2026-10-20 | **No-nolint step and Linux lint runner.** TASK-010 (row, plan) and gate G8 gain a CI step in `agent.yml`. It fails when any non-test `.go` file under `agent/` contains a `//nolint` directive (`grep -rnE --include='*.go' --exclude='*_test.go' '//[[:space:]]*nolint'`). Its planted violation is `//nolint:forbidigo` on a `net.Listen` call. M0 has no allow-list; any future exception needs a reviewed allow-list added by its own two-approval task. Agent lint is stated to run on a Linux runner, because `_linux.go` files are not linted on the Windows dev box. TASK-010 adds REQ-012 to its links, stays at 2 files, and goes from 130 to 140 lines. | Reviewer finding on TASK-004: `//nolint:all` or `//nolint:forbidigo,gosec` silences the listener and TLS guards (REQ-012, TS §2.2, §8.1), and golangci-lint cannot forbid that itself. |
| 2026-10-20 | **`//go:linkname` added to the same step.** The TASK-010 step (row, plan step 7) and gate G8 now also fail on `//go:linkname` in any non-test `.go` file under `agent/` (pattern `'//[[:space:]]*(nolint\|go:linkname)'`). Planted violation: `//go:linkname listen net.Listen` in `agent/cmd/bitscan-agent/`. The plan states the step's result equals the reviewer's reference command for the nolint part, and why it uses the `if grep …` form rather than a pipeline (with `bash -e`/`pipefail`, a grep that finds nothing would kill the step). TASK-010 stays at 2 files and about 140 lines. | Reviewer request: `//go:linkname` can reach unexported standard-library listener internals that `forbidigo` does not name (REQ-012, TS §2.2). |
| 2026-10-20 | **Assembly and object files.** REQ-010 (3) and REQ-012 are widened, and the TASK-010 listing (row, plan step 6) and gate G10 now use `{{if or .CgoFiles .SFiles .SysoFiles}}…{{end}}`. They fail on cgo, hand-written assembly (`.s`) or prebuilt object (`.syso`) files in any agent package. New planted violations: `raw_amd64.s` next to `agent/cmd/bitscan-agent/main.go`, implementing a body-less func, and a `.syso` file. No size change (TASK-010: 2 files, about 140 lines). | Reviewer finding on TASK-010: `.s` and `.syso` files bypass every agent gate (gofmt, golangci-lint, the grep step and the REQ-012 guards). |

## M1 database and audit core

Scope as confirmed by the user on 2026-10-20 (`work/decisions.md`: milestone reorder, PD-18 answer, M1 scope); requirements REQ-018 to REQ-033 in `work/requirements.md`. Branch `m1-db-audit-core`. Path prefix `manager/bitscan_manager/` is written `bm/` in this section only, to keep rows short; `versions/` means `bm/db/migrations/versions/`.

Every PostgreSQL test runs the TS §5.2 Bootstrap and then `bitscan-manager db migrate` (REQ-032). These tests run in WSL2 (Ubuntu 24.04, Docker Engine) or CI with `CI=true`. On the Windows dev box they are reported "not run: Docker unavailable" (decisions 2026-10-20, container runtime row).

### M1 tasks

| TASK | Title | REQ links | Area | Owner | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-011 | Runtime database dependencies: Alembic, SQLAlchemy and psycopg 3 (moved from dev to runtime) in `pyproject.toml` and both hashed locks | REQ-018 | manager | impl-manager | `manager/pyproject.toml`, `manager/requirements.txt`, `manager/requirements-dev.txt` | none | 15 (+2 generated) | In fresh CPython 3.12 venvs on Windows and Linux, `pip install --require-hashes` of each lock exits 0 and `python -c "import alembic, sqlalchemy, psycopg"` exits 0; the runtime lock names none of pytest, ruff, mypy or testcontainers; and rerunning the recorded lock command reproduces both locks byte for byte. |
| TASK-012 | Start-up configuration loader, serve and db profiles (plan: `work/plans/TASK-012.md`) | REQ-019 | manager | impl-manager | `bm/config/__init__.py`, `bm/config/startup.py` | TASK-011; #45 for the `sslmode` set and the retention and migrate DSNs | 160 | Calling the serve and db loaders with an environment mapping and temporary credential files for each REQ-019 case gives the stated configuration, or an error naming the variable; and no canary secret appears in any `repr`, message, exception chain or captured output. |
| TASK-013 | Alembic environment, migration runner and the `db migrate` command (plan: `work/plans/TASK-013.md`). Its TEST step also delivers REQ-032 through TP-M1-01 and TP-M1-02 (tester-built harness) | REQ-020, REQ-032 | manager | impl-manager | `bm/db/__init__.py`, `bm/db/migrations/__init__.py`, `bm/db/migrations/env.py`, `versions/__init__.py`, `bm/cli/__init__.py` | TASK-011, TASK-012; #41 | 170 | On a container prepared by only the TS §5.2 Bootstrap, `bitscan-manager db migrate` with a `bitscan_migrate` DSN file exits 0 twice in a row and leaves only Alembic's version table, owned by `bitscan_owner`. A `bitscan_app` DSN, a missing variable and a wrong password each exit non-zero without the DSN canary in the output. `serve` still imports no database module. |
| TASK-014 | Migration `m0001`: extensions, catalog types and tables, TS §5.2 L638–L707 (plan for TASK-014 to TASK-018: `work/plans/TASK-014.md`) | REQ-021, REQ-020 | manager | impl-manager | `versions/m0001_catalog.py` | TASK-013 | 95 | After Bootstrap and `db migrate`, the three types and five catalog tables are diff-equal to TS §5.2 L638–L707, and each REQ-021 CHECK, default, uniqueness and cascade case behaves as stated. |
| TASK-015 | Migration `m0002`: fleet and inventory, L709–L825, including `ix_package_name_debver` | REQ-022, REQ-029 | manager | impl-manager | `versions/m0002_fleet_inventory.py` | TASK-014 | 140 | After `db migrate`, `agent_status`, the nine fleet and inventory tables and the five indexes are diff-equal to TS §5.2 L709–L825, and each REQ-022 case behaves as stated. The 500-pair `debversion` suite (TP-M1-07) agrees with `dpkg` for every pair, and `EXPLAIN` shows `ix_package_name_debver`. |
| TASK-016 | Migration `m0003`: scanning, L842–L938 (partitioned `scan_result`, default partition, trigger) | REQ-023 | manager | impl-manager | `versions/m0003_scanning.py` | TASK-015 | 120 | After `db migrate`, the two scanning types, five tables, `scan_result_default`, the function and the trigger are diff-equal to TS §5.2 L842–L938. Each REQ-023 case behaves as stated, including the trigger rejection both through the parent and directly into `scan_result_default`. |
| TASK-017 | Migration `m0004`: system tables, L827–L831, L835–L840 and L941–L990 | REQ-024 | manager | impl-manager | `versions/m0004_system.py` | TASK-016 | 80 | After `db migrate`, `system_schedule`, `setting`, `task`, `user_role`, `app_user`, `user_token` and `audit_log` are diff-equal to TS §5.2, `system_schedule` and `setting` are empty, and each REQ-024 case behaves as stated. |
| TASK-018 | Migration `m0005`: privileges, `v_plugin`, seeds and the initial partitions (L992–L1013, L1037–L1042, L832–L833, TS §8.6 L1317–L1336, TS §5.3 L1046) | REQ-025, REQ-026, REQ-027 | manager | impl-manager | `versions/m0005_privileges_seeds.py` | TASK-017; #42, #43 | 130 | On a freshly migrated database, every REQ-025 grant probe gives the stated success or 42501, the seeds and the four monthly partitions match REQ-026, and the full schema diff against TS §5.2 (REQ-027) shows no difference and turns red for each planted change. |
| TASK-019 | `db maintain`: monthly partition maintenance (plan: `work/plans/TASK-019.md`) | REQ-028 | manager | impl-manager | `bm/db/maintain.py`, `bm/cli/__init__.py` | TASK-018; #43; #44 for the drop half | 160 | With the clock moved forward, the maintenance function creates exactly the missing monthly partitions with the default ACL, is a no-op on a second run, drops only partitions past retention under #44, and refuses when the default partition holds rows in a range it must create. `bitscan-manager db maintain` exits 0 on a migrated database with no DSN canary in its output. |
| TASK-020 | Audit chain append: pure hash function, advisory lock and insert (plan: `work/plans/TASK-020.md`) | REQ-030 | manager | impl-manager | `bm/services/audit/__init__.py`, `bm/services/audit/chain.py`, `bm/repositories/__init__.py`, `bm/repositories/audit_log.py` | TASK-018; #38 | 150 | Unit tests on the hash function, and on the append flow with a fake repository, pass without PostgreSQL. On PostgreSQL, eight concurrent `bitscan_app` writers produce one unbroken chain of 200 entries, and a held, uncommitted append blocks the next writer on the advisory lock. |
| TASK-021 | Audit chain verifier, including checkpoints (plan: `work/plans/TASK-020.md`) | REQ-031 | manager | impl-manager | `bm/services/audit/verify.py`, `bm/repositories/audit_log.py` | TASK-020; #39 | 110 | The verifier passes an intact chain and an empty log, and reports the first bad `audit_id` for each REQ-031 tampering case done as `bitscan_owner`. It still passes after `bitscan_retention` writes an `audit.checkpoint` entry and deletes the entries it covers. |
| TASK-022 | CI: forward-only, one-migration-per-PR gate in the manager workflow | REQ-033 | deploy (CI) | impl-deploy | `.github/workflows/manager.yml` | TASK-014 | 40 | On PR branches, the manager workflow passes with zero or one added migration file. It fails for a PR that modifies, deletes or renames `m0001_catalog.py`, or adds two migration files. Its PostgreSQL job runs with `CI=true`. |

Totals: 16 REQ (REQ-018 to REQ-033), 12 TASK (TASK-011 to TASK-022), 17 test-plan items, 10 waves. Every task is within 5 files and 200 hand-written lines. LOC counts hand-written lines only, as in M0.

REQ to TASK: REQ-018 TASK-011; REQ-019 TASK-012; REQ-020 TASK-013, TASK-014; REQ-021 TASK-014; REQ-022 TASK-015; REQ-023 TASK-016; REQ-024 TASK-017; REQ-025, REQ-026 and REQ-027 TASK-018; REQ-028 TASK-019; REQ-029 TASK-015; REQ-030 TASK-020; REQ-031 TASK-021; REQ-032 TASK-013 (TEST step, TP-M1-01 and TP-M1-02); REQ-033 TASK-022. Every M1 REQ has at least one TASK, and every TASK has at least one REQ.

### M1 test-plan items (tester)

Tests and fixtures are tester-owned. They are not IMPL tasks: each item is drafted from the acceptance criteria at phase start, and run in the TEST step of the task named under "Runs in". Check ids in `tests/m1/test-plan.md` use `CHK-M1-###`. Constraint tests in TP-M1-05 to TP-M1-09 run as `bitscan_owner` (a `bitscan_migrate` connection with `SET ROLE bitscan_owner`), because `bitscan_app` has no table privileges until `m0005`. Grant behaviour is tested only in TP-M1-10. Per-domain schema diffs leave out ACLs, which are compared once, in TP-M1-12.

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M1-00 | Phase test plan, and the index row for M1 | all M1 | phase start; report at the M1 gate | `tests/m1/test-plan.md`, `tests/test-plan.md` (report files via `main`, decisions 2026-10-20) | none |
| TP-M1-01 | Pytester tests of the conftest skip/exit hook (M0 carry-over) | REQ-032 (6), REQ-009 (4) | TASK-013 TEST | `manager/tests/test_conftest_hook.py` | none (drafted in W1) |
| TP-M1-02 | Harness switch: Bootstrap extracted verbatim from TS §5.2 L1018–L1033 (`\c bitscan` as a reconnect); test-only role passwords; container TLS (#45); port bound to `127.0.0.1`; a `migrated_db` fixture that runs the CLI `db migrate`; `app_conn`, `retention_conn` and `owner_conn` fixtures, each asserting `rolsuper` is false. A second tester instance (`tester-b`) runs its checks (PD-17 precedent) | REQ-032 | TASK-013 TEST | `manager/tests/conftest.py`, `manager/tests/postgres/Dockerfile`, `manager/tests/spec_sql.py`, `manager/tests/test_pg_harness.py` | TASK-013 IMPL (drafted from W2) |
| TP-M1-03 | Configuration loader cases | REQ-019 | TASK-012 TEST | `manager/tests/test_config.py` | TASK-012 IMPL |
| TP-M1-04 | `db migrate` behaviour, and the `test_cli.py` update for REQ-008 (narrowed) | REQ-020 | TASK-013 TEST | `manager/tests/test_db_migrate.py`, `manager/tests/test_cli.py` | TP-M1-02 |
| TP-M1-05 | Schema-diff helper (method #40) and the catalog checks | REQ-021, REQ-027 | TASK-014 TEST | `manager/tests/schema_diff.py`, `manager/tests/test_schema_catalog.py` | TP-M1-02; #40 |
| TP-M1-06 | Fleet and inventory checks | REQ-022 | TASK-015 TEST | `manager/tests/test_schema_fleet.py` | TP-M1-05 |
| TP-M1-07 | Debian version comparison, at least 500 pairs against `dpkg --compare-versions` in the test container, plus `EXPLAIN` on `ix_package_name_debver`. Re-run as `bitscan_app` in TASK-018 TEST | REQ-029 | TASK-015 TEST, TASK-018 TEST | `manager/tests/fixtures/debversion_pairs.tsv`, `manager/tests/test_debversion.py` | TP-M1-02 |
| TP-M1-08 | Scanning checks | REQ-023 | TASK-016 TEST | `manager/tests/test_schema_scanning.py` | TP-M1-05 |
| TP-M1-09 | System-table checks | REQ-024 | TASK-017 TEST | `manager/tests/test_schema_system.py` | TP-M1-05 |
| TP-M1-10 | Grant probes, including a partition created after the migration | REQ-025 | TASK-018 TEST (the `db maintain` partition case in TASK-019 TEST) | `manager/tests/test_grants.py` | TP-M1-02 |
| TP-M1-11 | Seeds and initial partitions | REQ-026 | TASK-018 TEST | `manager/tests/test_seeds_partitions.py` | TP-M1-02; #42, #43 |
| TP-M1-12 | Final schema diff against TS §5.2, with the five planted changes | REQ-027 | TASK-018 TEST | `manager/tests/test_schema_diff.py` | TP-M1-05 |
| TP-M1-13 | `db maintain` | REQ-028 | TASK-019 TEST | `manager/tests/test_db_maintain.py` | TP-M1-02; #44 |
| TP-M1-14 | Audit append: unit (hash, fake repository) and PostgreSQL (concurrency, lock wait, roles, isolation and autocommit cases) | REQ-030 | TASK-020 TEST | `manager/tests/test_audit_chain.py`, `manager/tests/test_audit_append_pg.py` | TP-M1-02; #38 |
| TP-M1-15 | Audit verifier: unit and PostgreSQL, including the checkpoint case | REQ-031 | TASK-021 TEST | `manager/tests/test_audit_verify.py` | TP-M1-14; #39 |
| TP-M1-16 | CI migration gate: planted PRs on throwaway branches | REQ-033 | TASK-022 TEST | none in the tree (report evidence only) | TASK-022 IMPL |

### M1 owner and review notes

- TASK-012 and TASK-020/021 are not in the TS §8.2 two-approval list (importer, auth, agent, runner); one approval each. The lead may still want a second look at the audit core, since TS §8.1 names the hash-chained audit log as a control against manager compromise.
- `bm/cli/__init__.py` is touched by TASK-013 and then TASK-019, never in the same wave. `bm/repositories/audit_log.py` is touched by TASK-020 and then TASK-021.
- TASK-019 and TASK-020 are both impl-manager's work in W9. They run in parallel only if the lead spawns a second impl-manager instance; otherwise they run one after the other, in either order.
- The IMPL of TASK-015 to TASK-018 may be drafted early, because the files are disjoint. They are tested, reviewed and merged in chain order, because each migration's `down_revision` is the one before (one migration per PR, REQ-033).
- `manager/pyproject.toml` stays with impl-manager (TASK-011). Any mypy override the tester needs, for example for `testcontainers`, is asked of impl-manager.
- Planted violations are made in a throwaway copy or branch, never left in the tree.

### M1 waves and dependency spine

Spine: `TASK-011 → TASK-012 → TASK-013 → TASK-014 → TASK-015 → TASK-016 → TASK-017 → TASK-018 → TASK-019` and `TASK-018 → TASK-020 → TASK-021`, plus `TASK-014 → TASK-022`. The graph is acyclic. Interface-first: the configuration contract (TASK-012) comes before its consumers (TASK-013, TASK-019); the schema (TASK-014 to TASK-018) comes before the code that writes to it (TASK-019 to TASK-021); and the audit hash contract (#38, TASK-020) comes before the verifier (TASK-021).

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-011; tester TP-M1-00, TP-M1-01 (draft) | `manager/pyproject.toml`, `manager/requirements*.txt` · `tests/m1/test-plan.md`, `tests/test-plan.md`, `manager/tests/test_conftest_hook.py` |
| W2 | TASK-012; tester drafts TP-M1-02, TP-M1-03 | `bm/config/{__init__,startup}.py` · `manager/tests/{conftest.py,postgres/Dockerfile,spec_sql.py,test_pg_harness.py,test_config.py}` |
| W3 | TASK-013 | `bm/db/__init__.py`, `bm/db/migrations/{__init__,env}.py`, `versions/__init__.py`, `bm/cli/__init__.py` · tester: `manager/tests/{test_db_migrate.py,test_cli.py}` |
| W4 | TASK-014 | `versions/m0001_catalog.py` · tester: `manager/tests/{schema_diff.py,test_schema_catalog.py}` |
| W5 | TASK-015, TASK-022 | `versions/m0002_fleet_inventory.py` · `.github/workflows/manager.yml` · tester: `manager/tests/{test_schema_fleet.py,test_debversion.py,fixtures/debversion_pairs.tsv}` |
| W6 | TASK-016 | `versions/m0003_scanning.py` · tester: `manager/tests/test_schema_scanning.py` |
| W7 | TASK-017 | `versions/m0004_system.py` · tester: `manager/tests/test_schema_system.py` |
| W8 | TASK-018 | `versions/m0005_privileges_seeds.py` · tester: `manager/tests/{test_grants.py,test_seeds_partitions.py,test_schema_diff.py}` |
| W9 | TASK-019, TASK-020 | `bm/db/maintain.py`, `bm/cli/__init__.py` · `bm/services/audit/{__init__,chain}.py`, `bm/repositories/{__init__,audit_log}.py` · tester: `manager/tests/{test_db_maintain.py,test_audit_chain.py,test_audit_append_pg.py}` |
| W10 | TASK-021 | `bm/services/audit/verify.py`, `bm/repositories/audit_log.py` · tester: `manager/tests/test_audit_verify.py` |

The questions can be answered while the waves run. #45 is needed by the end of W2. #41 and #40 are needed by W3 and W4. #42 and #43 are needed by W8. #38, #39 and #44 are needed by W9 and W10.

### M1 gate

The M1 exit gate: on a clean tree every command below is green, and each new gate turns red on its planted violation. Python commands use the forms fixed in M0 (PD-5, PD-16). "Local" is the Windows 11 + Git Bash dev box. "WSL" is WSL2 Ubuntu 24.04 with Docker Engine and the project copy at `/root/bitscan`, refreshed from the working tree before the run (decisions 2026-10-20). G7 to G17 (agent, web, units) are unchanged from M0 and must stay green in CI.

| Gate | Command | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1 | `ruff check manager` | f-string SQL passed to `execute()` in `bm/repositories/audit_log.py` or `bm/db/maintain.py` (S608); `import re` in `bm/config/startup.py` | local |
| G2 | `ruff format --check manager` | one misformatted line in a migration | local |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` | an unannotated `upgrade()` in a migration; an untyped function in `bm/config/startup.py` | local |
| G4 | `pip install --require-hashes -r manager/requirements.txt`, and the same for `manager/requirements-dev.txt`, in a fresh CPython 3.12 venv | one altered `alembic` hash | local (Windows) and CI (Linux) |
| G5 | `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | an untested function of 20 or more statements in `bm/services/audit/` | local. The `pg` tests are NOT RUN here ("not run: Docker unavailable"), so the 85 % must come from the unit tests of the pure audit code (REQ-030 (8), REQ-031 (6)) |
| G6 | OpenAPI export, then `git diff --exit-code -- manager/openapi.json` (M1 adds no route) | a route added without re-export | local |
| G18 | `cd /root/bitscan/manager && CI=true python3.12 -m pytest --cov=bitscan_manager/services --cov-fail-under=85` (dev lock installed there): every test passes, 0 skipped | any of G19 to G23 | WSL; CI |
| G19 | `cd /root/bitscan/manager && CI=true python3.12 -m pytest -m pg tests/test_schema_diff.py` | a throwaway `m0006` that drops a CHECK, changes a default, adds a column, adds a GRANT or drops an index (one at a time) | WSL; CI |
| G20 | `… pytest -m pg tests/test_grants.py` | a throwaway `m0006` with `GRANT UPDATE ON audit_log TO bitscan_app`, or `GRANT DELETE ON scan TO bitscan_app` | WSL; CI |
| G21 | `… pytest -m pg tests/test_debversion.py` | one fixture relation flipped (`lt` → `gt`) | WSL; CI |
| G22 | `… pytest -m pg tests/test_db_migrate.py tests/test_db_maintain.py tests/test_seeds_partitions.py` | a migration with a working `downgrade()`; `db maintain` that creates only two future months; a seed pattern with one character changed | WSL; CI |
| G23 | `cd manager && pytest tests/test_audit_chain.py tests/test_audit_verify.py` (unit part) and `… CI=true python3.12 -m pytest -m pg tests/test_audit_append_pg.py tests/test_audit_verify.py` (PostgreSQL part) | the advisory-lock call removed from append (the concurrency test must go red); a verifier that skips the `prev_hash` link check | unit part local; PostgreSQL part WSL and CI |
| G24 | The REQ-033 step in `.github/workflows/manager.yml` on a pull request | a PR that edits `m0001_catalog.py`; a PR adding two migration files | GitHub CI only (needs a PR) |

### Open items for M1

All are in `work/open-questions.md`. "Blocks" means the task cannot finish, or its acceptance cannot be fixed, without the answer. Each blocking answer is needed only by the wave named above.

| Item | Blocks | Summary |
| --- | --- | --- |
| #38 (new) | TASK-020, and TASK-021 through it | The exact `row_hash` input: fields, serialisation, timestamp and JSON forms, hex case, and the genesis `prev_hash` |
| #39 (new) | TASK-021 (checkpoint part) | The `audit.checkpoint` `detail` keys, and the rule for verifying from a checkpoint |
| #40 (new) | TP-M1-05, TP-M1-12 (REQ-027) | How the schema-diff test gets its TS §5.2 reference, given testing.md "never apply the raw spec DDL"; what is compared |
| #41 (new) | TASK-013, REQ-027 (2) | Alembic's `alembic_version` table: schema, owner, grants, and whether the diff excludes it |
| #42 (new) | TASK-018 | The JSON shape of each seeded `setting.value` |
| #43 (new) | TASK-018, TASK-019 | `scan_result` partition names, and the time zone of month boundaries |
| #44 (new) | TASK-019 (drop half) | Which partitions are "past retention", and who reports rows in the default partition (no alert in M1) |
| #45 (new) | TASK-012 (one rule), TP-M1-02 (TLS in the container) | Which `sslmode` values count as "TLS required"; whether the retention and migrate DSNs get the same check |
| #46 (new) | none in M1 | How operators get the Bootstrap block (a verbatim runbook copy under `deploy/`?), and how the LOGIN roles authenticate; tied to #6 |
| #24 | none (marker handled) | The loader keeps `BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF` and `BITSCAN_AUDIT_SINK` as opaque non-empty strings and contacts neither the vault nor the sink. The audit core has no sink hook in M1 |
| #5 | none (M1 adds no route) | `/readyz` ("migrations current, `system_schedule` rows present") is M2/M3; M1 provides only the tables and Alembic revision it will read |
| #6 | none in M1 | M1 creates no system user, folder or install step; the Bootstrap delivery is #46 |
| #7 | none (`users create-admin` stays a stub) | Initial-password handling waits for M2 |
| #4 | not applicable | It is about the agent's `agent.yaml`; the manager loader does not read it |
| PD-3, PD-17 | TASK-013 TEST (harness) | The second approver; who runs the TEST checks of the tester-built harness (`tester-b`, PD-17 precedent) |

### Coverage matrix (M1)

| Spec section | Covered by | Status in M1 |
| --- | --- | --- |
| TS §5.1 Table map | REQ-021 to REQ-024 / TASK-014 to TASK-017 | Covered: every table in the map is created. The map omits `agent_ip_seen` and `task` (spec inconsistency, open-questions part 5); both are created from TS §5.2 |
| TS §5.2 DDL, types and tables (L637–L990) | REQ-021 to REQ-024, REQ-027 / TASK-014 to TASK-018 | Covered |
| TS §5.2 privileges (L992–L1013) | REQ-025 / TASK-018 | Covered |
| TS §5.2 Bootstrap (L1016–L1033) | REQ-032 / TP-M1-02 (tests run it verbatim from the spec) | Covered for tests. Operator delivery is **uncovered** (#46, #6) |
| TS §5.2 display-name view (L1035–L1042) | REQ-025 (6) / TASK-018 | Covered |
| TS §5.3 Migrations | REQ-020, REQ-026, REQ-033 / TASK-013, TASK-018, TASK-022 | Covered ("first migration" read as the initial set, PD-18) |
| TS §5.3 Retention | REQ-028 / TASK-019 | Partition creation and the drop of whole partitions (`db maintain`) are covered; the drop rule is #44. **Uncovered:** row deletes by the retention task (scans after 400 days, snapshots 180 days, enrolment requests and user tokens 90 days, audit log 3 years, inventory jobs 30 days, unreferenced packages): M11. The default-partition alert is M2 or later (#44) |
| TS §5.3 Backups | (none) | **Uncovered**: operational, monthly restore test, not CI (testing.md) |
| TS §5.3 Database roles | REQ-025, REQ-020 (2), REQ-032 / TASK-018, TASK-013 | Covered for grants and ownership. "PostgreSQL accepts connections only from the manager host, over TLS" is server configuration: **uncovered** (deploy, #46). The client-side TLS check is REQ-019 (5) |
| TS §5.3 Users never deleted | REQ-025 (1) (no DELETE on `app_user` for the app) | Partly covered; the user service is M2 |
| TS §5.3 Audit log integrity | REQ-030, REQ-031 / TASK-020, TASK-021 | Chain, advisory lock and checkpoint verification are covered. **Uncovered:** writing checkpoints during retention (M11); the sink, disk queue, outage alert and 15-minute refusal (M2) |
| TS §5.3 No results in logs | REQ-019 (8), REQ-020 (6), REQ-030 (7) | Covered for the M1 code (no DSN, token or audit detail in output). Plugin output is M9 to M11 |
| TS §7.2 Version comparison | REQ-022 (6), REQ-029 / TASK-015, TP-M1-07 | Covered. `version_op` in package search is M5 |
| TS §8.1 SQL injection | REQ-020 (9), REQ-028 (8), REQ-030 / G1 | Covered for M1 code |
| TS §8.1 least-privilege DB roles; hash-chained audit log (Manager compromise, Privilege misuse, Tampering rows) | REQ-025, REQ-030, REQ-031 | Covered for roles and the chain. External shipping is M2 |
| TS §8.1 Secrets in config | REQ-019 | Covered |
| TS §8.1 Install and supply chain (hashed Python dependencies) | REQ-018 | Covered for the new dependencies |
| TS §8.1 other rows | (none) | **Uncovered in M1**: M2 to M11 |
| TS §8.4 Logs | REQ-019 (8), REQ-020 (6) (negative: no secrets) | Structured JSON logs with `request_id`, `agent_id` and `job_id` are **uncovered**: M2 (app plumbing) |
| TS §8.4 Metrics, alerts, health endpoints | (none) | **Uncovered**: M2/M3 (alert delivery through `detail.alert = true` needs the M2 sink; health is #5) |
| TS §8.6 Start-up configuration | REQ-019 / TASK-012 | Covered as a library; wired to `serve` in M2 |
| TS §8.6 Runtime settings and default redaction patterns | REQ-026 (2), (3) / TASK-018 | The seeds are covered. **Uncovered:** `/settings`, range validation and RE2 validation on save, audit and alerts on change: M2/M3 |
| TS §8.7 Service (`serve`, SIGHUP) | (none) | **Uncovered**: `serve` stays a stub until M2 |
| TS §8.7 Folders | (none) | **Uncovered**: install (#6) |
| TS §8.7 Configuration and secrets (`LoadCredential=`, `%d`, migrate credential only in the two units) | REQ-019 (1), (6), (7) | Covered on the reading side; the unit files exist since M0 (REQ-016) |
| TS §8.7 Database (migrate and maintain units) | REQ-020, REQ-028 / TASK-013, TASK-019 | Covered |
| TS §8.7 Server CLI (`users …`, `bits rebuild`, `app.dsn`) | (none) | **Uncovered**: M2 (users) and M7 (rebuild) |
| TS §8.7 Upgrade order | REQ-020 (3) (re-run is a no-op) | Partly covered; the runbook is #6 |

TS §8.3 rows touched in M1: Unit (version compare via TP-M1-07, plus the pure audit code), and Integration (partition maintenance, grant probes, including on a new partition). The others are unchanged from the M0 matrix.

### M1 changes to M0 items

| Date | Change | Why |
| --- | --- | --- |
| 2026-10-20 | REQ-008 (2) narrowed: `db migrate` (TASK-013) and `db maintain` (TASK-019) become real commands. `manager/tests/test_cli.py` is updated in TP-M1-04 | M1 scope (user, 2026-10-20) |
| 2026-10-20 | The M0 note "No empty Python sub-packages" is honoured. `bm/config/`, `bm/db/`, `bm/repositories/` and `bm/services/audit/` are created by the first task that puts code in them | M0 scope notes |

## M2 auth core and API plumbing

Scope: `work/m2-brief.md` and the requirements REQ-034 to REQ-059 in `work/requirements.md`. Branch `m2-auth-core`. As in M1, `bm/` means `manager/bitscan_manager/` in this section only.

**No migration in M2.** The TS §5.2 DDL already has every column M2 uses (`app_user`, `user_token`, `audit_log`, `system_schedule`, plus Alembic's version table, #41), so REQ-033 (one migration per PR) is not exercised and no `versions/` file is touched. The recommended defaults of #7 and #49 need no column; any answer that does is a spec change for the owner.

Design rules every M2 task follows (so the G5 coverage gate holds on the Windows box, where PostgreSQL tests do not run):
- `services/` code (audit sink, alerts, users) takes repository and transport objects through `Protocol`s, as `services/audit/chain.py` already does, so its unit tests need no database or network.
- Every time-based rule (session idle and maximum, back-off, TOTP steps, rate-limit windows, the 15-minute outage) reads the `Clock` from TASK-025, so tests use a fake clock.
- Route handlers only validate, authorise and call `auth/` or `services/` functions (`api → services → repositories`).
- Every task that adds or changes a route re-exports `manager/openapi.json` in the same task, so G6 stays green per task. Regenerating `web/src/api/schema.d.ts` is TASK-047 (impl-web), so G16 is checked only at the M2 gate (PD-20).

### M2 tasks

| TASK | Title | REQ links | Area | Owner | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-023 | Runtime dependencies for M2 (PD-19): ASGI server, Argon2id, HTTP client, psycopg pool, Prometheus client; both hashed locks regenerated | REQ-034 | manager | impl-manager | `manager/pyproject.toml`, `manager/requirements.txt`, `manager/requirements-dev.txt` | none; PD-19 | 15 (+2 generated) | In fresh CPython 3.12 venvs on Windows and Linux, `pip install --require-hashes` of each lock exits 0, each new package imports, the runtime lock names no test or lint tool and no OpenTelemetry SDK or exporter, and the recorded lock command reproduces both files byte for byte. |
| TASK-024 | `create_app()` hardening: telemetry off, security headers on every response, 1 MB body cap with 413, still no docs routes or CORS | REQ-035, REQ-036, REQ-037 | manager | impl-manager | `bm/app.py` | none; #57 | 140 | With the OTel variables set and a local listener on the OTLP endpoint, requests make no connection to it; every response status the tester can provoke (200 to 503, including an unhandled exception) carries the four headers exactly once with the spec CSP; a body one byte over the cap gets 413 whether sent with `Content-Length` or chunked; `/docs`, `/redoc`, `/openapi.json` get 404 and a CORS preflight gets no `Access-Control-Allow-*`. |
| TASK-025 | Runtime contract and the app database pool: `Runtime` (clock, database, TOTP cipher, sink gate, rate limits, lifecycle) with `Protocol`s; psycopg pool for `bitscan_app`, READ COMMITTED transactions with on-commit hooks (plan: `work/plans/TASK-025.md`) | REQ-044, REQ-055, REQ-056 | manager | impl-manager | `bm/runtime.py`, `bm/db/pool.py` | TASK-023 | 150 | Unit: a `Runtime` built from fakes passes `mypy --strict`, and on-commit hooks run after commit and never after a rollback. PostgreSQL: a pool from a `bitscan_app` DSN gives connections whose `session_user` is `bitscan_app` in READ COMMITTED, an `audit_log` append inside its transaction helper commits, and a DSN canary never appears in errors when the database is unreachable. |
| TASK-026 | Problem details for every error and the cursor pagination helper (`{items, next_cursor}`) | REQ-038 | manager | impl-manager | `bm/api/__init__.py`, `bm/api/problems.py`, `bm/api/pagination.py`, `bm/app.py` | TASK-024; #48, #52 | 160 | Every error the tester provokes (validation, unknown path, wrong method, 413, unhandled exception) returns `application/problem+json` with exactly the five RFC 9457 keys and no canary; paging N + 1 rows with `limit=N` returns each row once and a null `next_cursor` at the end; `limit` 0 or 501 and a tampered cursor are refused with the #48 status. |
| TASK-027 | JSON logging with `request_id`, `agent_id` and `job_id`; access records without query strings or headers | REQ-039 | manager | impl-manager | `bm/api/request_log.py`, `bm/app.py` | TASK-026 | 110 | Each request yields JSON records that share one `request_id` (different between requests) and have `agent_id` and `job_id` keys; an `Authorization` header, a query string and a request body planted with canaries never appear in any record, also when the handler raises. |
| TASK-028 | Token and password primitives: `bsu_`/`bsk_` generation, SHA-256 hashing, prefix parsing; Argon2id hash and verify with the 12-character minimum and a dummy verify (plan: `work/plans/TASK-041.md`) | REQ-040, REQ-041 | manager | impl-manager | `bm/auth/tokens.py`, `bm/auth/passwords.py` | TASK-023, TASK-029 (creates `bm/auth/__init__.py`); #56 | 120 | 10,000 tokens of each kind are distinct, prefixed and decode to 32 bytes; their stored hash is the lowercase SHA-256 hex; prefix parsing rejects `bsa_`, `bse_` and unknown prefixes; password hashes start `$argon2id$`, differ per call, verify only the exact password, and an 11-character password is refused while 12 is accepted. |
| TASK-029 | TOTP core (RFC 6238): secret generation, provisioning URI, code check returning the matched time step (plan: `work/plans/TASK-038.md`) | REQ-042 | manager | impl-manager | `bm/auth/__init__.py`, `bm/auth/totp.py` | none; #49 | 90 | The RFC 6238 Appendix B vectors for the #49 algorithm give the stated codes; with a fake clock a code inside the #49 window returns its step, a code outside it, of the wrong length or with non-digits returns none, and comparison uses `hmac.compare_digest`. |
| TASK-030 | Vault cipher for TOTP seeds (#24 product and API), behind the `TotpCipher` protocol of TASK-025 | REQ-043 | manager | impl-manager | `bm/auth/vault.py` | TASK-023, TASK-025; #24, #58 | 140 | Against a local fake vault over HTTPS, encrypt then decrypt round-trips a seed and the ciphertext holds no form of the seed; an untrusted vault certificate, a 403, a 5xx and a malformed reply each raise the #58 error with no seed, vault token or vault response body in the message, chain, `repr` or logs. |
| TASK-031 | Repositories for `app_user` and `user_token` (parameterised SQL only): lookups, atomic back-off and TOTP-step updates, token insert, revoke by user and kind, admin-row locking | REQ-044, REQ-048, REQ-051, REQ-052 | manager | impl-manager | `bm/repositories/users.py`, `bm/repositories/user_tokens.py` | none (M1 schema) | 190 | PostgreSQL as `bitscan_app`: every function works with only the TS §5.2 grants; the TOTP-step update succeeds for exactly one of two concurrent callers with the same step; the back-off update is atomic under 10 concurrent failures; token lookup is by `token_hash` only; ruff S608 passes. |
| TASK-032 | Audit sink transports (#24): syslog over TLS and HTTPS, built from `BITSCAN_AUDIT_SINK`, plain transports refused (plan: `work/plans/TASK-034.md`) | REQ-053 | manager | impl-manager | `bm/services/audit/sink_transport.py` | TASK-023; #24, #51 | 160 | Against local fake syslog-TLS and HTTPS sinks, a delivered entry carries every `audit_log` column in the #24 format; an untrusted sink certificate fails the send; `udp://`, plain `tcp://` and `http://` sink values are refused when the transport is built; a send to a closed port raises a delivery error within the configured timeout. |
| TASK-033 | Audit disk queue: append-only, fsynced records in the queue folder, ordered read, acknowledge, detection of a cut-off last record, 0700/0600 permissions, outage state file (plan: `work/plans/TASK-034.md`) | REQ-054 | manager | impl-manager | `bm/services/audit/disk_queue.py` | none | 140 | In a temporary folder, records come back in append order after the queue object is recreated; acknowledged records are not returned again; a file truncated mid-record returns every earlier record and never the cut-off one; on Linux the folder is 0700 and files 0600. |
| TASK-034 | Sink shipper and outage gate: tail committed `audit_log` entries by `audit_id`, queue on disk while the sink is down, outage start persisted, one alert per outage, `SinkGate.refusing()` after 15 minutes until drained (plan: `work/plans/TASK-034.md`) | REQ-053, REQ-054 | manager | impl-manager | `bm/services/audit/shipper.py`, `bm/repositories/audit_log.py` | TASK-025, TASK-032, TASK-033, TASK-035; #51 | 180 | Unit, with a fake repository, fake transport and fake clock: entries are sent in `audit_id` order; with the sink down they are queued, one outage alert is raised, `refusing()` is false at 14 min 59 s and true at 15 min, stays true across a shipper restart, and turns false only when the sink is back and the queue is empty. PostgreSQL: a rolled-back entry is never sent, and a CLI-written entry is sent. |
| TASK-035 | Alerts: `raise_alert()` writes an audit entry with `detail.alert = true` and the #50 kind, and increments `bitscan_alerts_total{kind}` on commit | REQ-055 | manager | impl-manager | `bm/services/audit/alerts.py`, `bm/services/audit/metrics.py`, `bm/services/audit/__init__.py` | TASK-023, TASK-025 (on-commit hooks); #50 | 90 | Unit with a fake repository: an alert writes exactly one entry with `detail.alert` true and its kind; the counter rises by one when the on-commit hook runs and not when the transaction rolls back; the counter is in a registry object a later route can serve. |
| TASK-036 | Rate limiter and failed-token-check aggregator (in memory): per-IP sign-in, per-user, per-IP failed checks counting failures only, one aggregated audit entry per IP per minute | REQ-047 | manager | impl-manager | `bm/api/ratelimit.py` | TASK-025; #54, #55 | 140 | With a fake clock, the 11th sign-in from one IP, the 601st request of one user and the 21st failed check from one IP in a minute are refused while other keys pass; valid-token requests are never counted as failures; the aggregator emits exactly one entry per IP per minute with failures, and none for minutes without; keys are dropped after their window. |
| TASK-037 | Auth dependencies: bearer parsing, token resolution (prefix and kind, revoked, expired, 8 h idle, disabled user), current role, failed-check counting, per-user limit, `require_role`, `require_session`, `require_totp_session` (with the sink gate), restricted admin session (plan: `work/plans/TASK-037.md`) | REQ-044, REQ-045, REQ-046, REQ-047 | manager | impl-manager | `bm/auth/principal.py`, `bm/auth/dependencies.py` | TASK-025, TASK-026, TASK-028, TASK-031, TASK-036; #48 | 190 | On a test app with one route per dependency and PostgreSQL behind it, the full matrix (no header, wrong scheme, `bsa_`, `bse_`, unknown, revoked, expired, idle 8 h, 24 h old, disabled user, kind/prefix mismatch, each role, `bsk_` vs session, verified vs unverified, admin without TOTP, sink gate refusing) gives exactly the REQ-044 to REQ-046 outcomes, and every failure counts as a failed check while valid tokens never do. |
| TASK-038 | Sign-in and sign-out: `POST /auth/login` (same response for every failure, dummy verify, back-off, admin TOTP code used once, restricted session, per-IP limit, repeated-failure alert) and `POST /auth/logout`; user router mounted at `/api/v1` (plan: `work/plans/TASK-038.md`) | REQ-048, REQ-042, REQ-047, REQ-035 | manager | impl-manager | `bm/auth/login.py`, `bm/api/user/__init__.py`, `bm/api/user/auth.py`, `bm/app.py`, `manager/openapi.json` | TASK-027, TASK-029, TASK-030, TASK-035, TASK-036, TASK-037, TASK-044; #47, #48, #49, #50, #54, #55 | 200 (+1 generated) | Through the API on PostgreSQL with a fake vault and fake clock: every failure case returns byte-identical 401 bodies; back-off follows 1, 2, 4 … 900 s and resets on success; an admin with TOTP gets a verified session only with a fresh code, a reused code fails, and two concurrent sign-ins with one code give one session; an admin without TOTP gets a restricted session; logout revokes only the presenting session and refuses a `bsk_` token. |
| TASK-039 | TOTP enrolment and replacement: `POST /auth/totp/enrol` (#49 protocol), current password and code for replacement, seed stored via the vault cipher, session re-issued as verified, alerts (plan: `work/plans/TASK-038.md`) | REQ-049, REQ-043 | manager | impl-manager | `bm/auth/totp_enrol.py`, `bm/api/user/auth.py`, `manager/openapi.json` | TASK-038; #49 | 170 (+1 generated) | A restricted admin enrols and gets a new verified token while the old one is refused; replacement without or with a wrong password or code leaves the stored seed unchanged; a wrong confirmation code keeps the old seed working; `bsk_` is refused; each enrolment and replacement writes one alert entry; `totp_secret_enc` never holds the seed. |
| TASK-040 | Change own password: `POST /auth/password` (session only, current password, REQ-041 rules, sessions ended per #53, audit entry) | REQ-050 | manager | impl-manager | `bm/auth/password_change.py`, `bm/api/user/auth.py`, `manager/openapi.json` | TASK-039; #53 | 90 (+1 generated) | With a session, a correct current password and a 12-character new one, the new password signs in, the old one fails, other sessions are refused (presenting session per #53) and API tokens still work; a `bsk_` token, a wrong current password or an 11-character new password change nothing. |
| TASK-041 | API tokens: create (session only, TOTP session for admins, 90 days default, 365 max, shown once, alert), list own, revoke own; service reused by the CLI (plan: `work/plans/TASK-041.md`) | REQ-051, REQ-040, REQ-046 | manager | impl-manager | `bm/auth/api_tokens.py`, `bm/api/user/api_tokens.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-035, TASK-037, TASK-040; #8, #47, #52 | 180 (+1 generated) | A viewer session creates a token that works on its next request and is never listed again in clear; lifetimes 365 and default 90 are accepted and 366 or 0 refused; a `bsk_` token and an unverified admin session cannot create; a user cannot list or revoke another user's token; a revoked token is refused; each creation writes one alert. |
| TASK-042 | Users service: create, list, read, role change (promotion needs TOTP; sessions ended; demotion revokes API tokens), disable (all tokens revoked), TOTP reset by another admin, revoke a user's tokens, last-active-admin guard under concurrency, audit and alerts (plan: `work/plans/TASK-042.md`) | REQ-052, REQ-041, REQ-055 | manager | impl-manager | `bm/services/users/__init__.py`, `bm/services/users/accounts.py` | TASK-028, TASK-031, TASK-035; #7, #50, #53, #56 | 200 | Unit with fake repositories covers every REQ-052 rule and alert; PostgreSQL: two connections demoting the two remaining admins at once leave one active admin, and a forced rollback after a change leaves neither the change nor its audit entry. |
| TASK-043 | `/users` routes (admin, TOTP session, sink gate): CRUD with delete meaning disable, plus the #47 sub-actions | REQ-052, REQ-046, REQ-054 | manager | impl-manager | `bm/api/user/users.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-041, TASK-042; #47, #52, #53 | 150 (+1 generated) | Through the API, an admin TOTP session performs each REQ-052 action with the stated effects; an admin `bsk_` token, an unverified admin session and operator or viewer sessions are refused on every method; with the sink gate refusing, every `/users` method is refused and changes nothing; no response contains a hash or seed. |
| TASK-044 | Health routes: `/healthz` (no database) and `/readyz` (database, packaged Alembic head, three `system_schedule` rows), prefix and auth per #5; `create_app(runtime)` with the lifecycle lifespan (TASK-025 plan) | REQ-056, REQ-036 | manager | impl-manager | `bm/api/health.py`, `bm/repositories/health.py`, `bm/app.py`, `manager/openapi.json` | TASK-025, TASK-027; #5 | 110 (+1 generated) | On a migrated database `/readyz` is 200; it is 503 with a problem body naming the check when the database is down, the stored revision is not the head, or any one of the three rows is deleted as `bitscan_owner`; `/healthz` stays 200 with the database down; neither route writes, and both carry the security headers. |
| TASK-045 | `bitscan-manager serve`: serve profile, runtime wiring, HTTPS only with TLS 1.2+, `SIGHUP` certificate reload, no proxy headers, no access log with secrets, shipper and aggregator lifecycle; README "Starting the app" (plan: `work/plans/TASK-045.md`) | REQ-057, REQ-039, REQ-047, REQ-053 | manager | impl-manager | `bm/cli/serve.py`, `bm/cli/__init__.py`, `README.md` | TASK-030, TASK-034, TASK-036, TASK-044 | 190 | On Linux with a test certificate and a migrated database, `serve` answers `/healthz` over TLS 1.2 and 1.3 with the security headers, refuses TLS 1.1 and plain HTTP, presents a replaced certificate after `SIGHUP` without changing its PID or socket, keeps the old certificate after a `SIGHUP` with a broken pair, exits non-zero naming the variable when one is missing, and flushes failed-check counts on `SIGTERM`. |
| TASK-046 | Server CLI `users create-admin`, `users create-api-token`, `users reset-totp`: DSN from `/etc/bitscan/secrets/app.dsn`, password per #7, audit and alerts; README "Users" section | REQ-058 | manager | impl-manager | `bm/cli/users.py`, `bm/cli/__init__.py`, `README.md` | TASK-041, TASK-042, TASK-045; #7, #47, #50, #51 | 170 | With the DSN path pointed at a temporary file, `create-admin` creates an admin without TOTP whose first sign-in is restricted, `create-api-token` prints one working token and stores only its hash, `reset-totp` clears TOTP and ends sessions, each writes its alert, a password is never taken from argv or the environment, and a missing or non-TLS DSN file exits non-zero without a canary. |
| TASK-047 | Web: regenerate `schema.d.ts` from the M2 `manager/openapi.json`; recheck `baseUrl ""` against the `/api/v1` paths | REQ-059 | web | impl-web | `web/src/api/schema.d.ts`, `web/src/api/client.ts` | TASK-043, TASK-044; #5; PD-20 | 10 (+1 generated) | After `npm run gen:api`, G16 shows no diff, every M2 user path in `schema.d.ts` starts with `/api/v1/`, `client.ts` has no absolute origin, and `npm run typecheck` passes with a type-level call to the sign-in path. |

Totals: 26 REQ (REQ-034 to REQ-059), 25 TASK (TASK-023 to TASK-047), 26 test-plan items, 10 waves. Every task is within 5 files and about 200 hand-written lines (TASK-038 and TASK-042 are at the limit; if either grows, split TASK-038 into login and logout, and TASK-042 into create/read and change/disable).

REQ to TASK: REQ-034 TASK-023; REQ-035 TASK-024, TASK-038; REQ-036 TASK-024, TASK-044; REQ-037 TASK-024; REQ-038 TASK-026; REQ-039 TASK-027, TASK-045; REQ-040 TASK-028, TASK-041; REQ-041 TASK-028, TASK-042; REQ-042 TASK-029, TASK-038; REQ-043 TASK-030, TASK-039; REQ-044 TASK-025, TASK-031, TASK-037; REQ-045 TASK-037; REQ-046 TASK-037, TASK-041, TASK-043; REQ-047 TASK-036, TASK-037, TASK-038, TASK-045; REQ-048 TASK-031, TASK-038; REQ-049 TASK-039; REQ-050 TASK-040; REQ-051 TASK-031, TASK-041; REQ-052 TASK-031, TASK-042, TASK-043; REQ-053 TASK-032, TASK-034, TASK-045; REQ-054 TASK-033, TASK-034, TASK-043; REQ-055 TASK-025, TASK-035, TASK-042; REQ-056 TASK-025, TASK-044; REQ-057 TASK-045; REQ-058 TASK-046; REQ-059 TASK-047. Every M2 REQ has at least one TASK, and every TASK has at least one REQ.

### M2 owner and review notes

- **Two approvals (TS §8.2 L1268, "auth"):** TASK-028, TASK-029, TASK-030, TASK-031, TASK-037, TASK-038, TASK-039, TASK-040, TASK-041, TASK-042, TASK-043 and TASK-046. Until PD-3 is decided, the second approver is the user, batched per wave (decisions 2026-10-19).
- **Recommended second look (not on the TS §8.2 list):** TASK-034 (the 15-minute refusal is the control TS §8.1 L1256 names for a sink outage, and the sink is the only defence against a full chain rewrite, `work/m2-brief.md`), TASK-036 (failed-token-check limits) and TASK-045 (TLS set-up).
- impl-manager owns every M2 task except TASK-047 (impl-web). No impl-deploy task is planned: the CI workflows already run the whole pytest suite with `CI=true` on every PR, which includes the TS §8.3 Security tests for auth. If the tester wants a separate `security` marker step in CI, that is a small impl-deploy follow-up, and the marker itself goes in `manager/pyproject.toml` (impl-manager).
- `bm/app.py` is touched by TASK-024, TASK-026, TASK-027, TASK-044 and TASK-038, in that order and never in the same wave. `bm/api/user/auth.py` by TASK-038, TASK-039, TASK-040; `bm/api/user/__init__.py` by TASK-038, TASK-041, TASK-043; `bm/cli/__init__.py` and `README.md` by TASK-045 then TASK-046; `bm/repositories/audit_log.py` only by TASK-034. `manager/openapi.json` is regenerated by TASK-044, TASK-038, TASK-039, TASK-040, TASK-041 and TASK-043, one wave each.
- CLAUDE.md puts middleware in `app.py`; TASK-024 keeps the header and size middleware there. The rate limiter is a plain module (`bm/api/ratelimit.py`) used from the auth dependencies and the sign-in route, not middleware.
- Waves list possible parallelism. With one impl-manager instance, tasks inside a wave run one after the other in any order; the lead may spawn a second instance for W1 to W4, where the files are disjoint.
- Planted violations are made in a throwaway copy or branch, never left in the tree.

### M2 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m2/test-plan.md`, check ids `CHK-M2-###`), run in the TEST step named. PostgreSQL items run in WSL or CI with `CI=true`; on the Windows box they are reported "not run: Docker unavailable". Files are the tester's suggestion.

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M2-00 | Phase test plan and the M2 index row | all M2 | phase start; report at the M2 gate | `tests/m2/test-plan.md`, `tests/test-plan.md` (report files via `main`) | none |
| TP-M2-01 | Lock install, imports, no SDK or test tools in the runtime lock, reproducible locks | REQ-034 | TASK-023 TEST | none in the tree (evidence) | TASK-023 IMPL |
| TP-M2-02 | Telemetry off with OTel variables and a local listener; headers on every status; body cap with `Content-Length` and chunked; docs routes and CORS | REQ-035, REQ-036, REQ-037 | TASK-024 TEST (headers re-run in TASK-044 and TASK-045 TEST) | `manager/tests/test_app_hardening.py` | TASK-024 IMPL |
| TP-M2-03 | Runtime fakes, on-commit hooks; pool roles and isolation (PostgreSQL) | REQ-044, REQ-055, REQ-056 | TASK-025 TEST | `manager/tests/test_runtime.py`, `manager/tests/test_db_pool_pg.py` | TASK-025 IMPL |
| TP-M2-04 | Problem details for every error class; pagination walk and cursor tampering | REQ-038 | TASK-026 TEST | `manager/tests/test_problems.py`, `manager/tests/test_pagination.py` | TASK-026 IMPL; #48 |
| TP-M2-05 | JSON logs, `request_id`; the M2-wide canary sweep (fixture reused by later items) | REQ-039 | TASK-027 TEST; full sweep at the M2 gate | `manager/tests/test_request_log.py`, `manager/tests/canary.py` | TASK-027 IMPL |
| TP-M2-06 | Token generation and hashing; Argon2id and length rules | REQ-040, REQ-041 | TASK-028 TEST | `manager/tests/test_tokens.py`, `manager/tests/test_passwords.py` | TASK-028 IMPL; #56 |
| TP-M2-07 | TOTP: RFC 6238 vectors, window, malformed codes | REQ-042 | TASK-029 TEST | `manager/tests/test_totp.py` | TASK-029 IMPL; #49 |
| TP-M2-08 | Vault cipher against a local fake HTTPS vault (good, untrusted certificate, 403, 5xx, malformed); canary | REQ-043 | TASK-030 TEST | `manager/tests/fake_vault.py`, `manager/tests/test_vault.py` | TASK-030 IMPL; #24, #58 |
| TP-M2-09 | Repositories on PostgreSQL as `bitscan_app`: grants suffice, concurrent TOTP step, concurrent back-off | REQ-044, REQ-048, REQ-051, REQ-052 | TASK-031 TEST | `manager/tests/test_user_repos_pg.py` | TASK-031 IMPL |
| TP-M2-10 | Sink transports against local fake syslog-TLS and HTTPS sinks; plain transports refused | REQ-053 | TASK-032 TEST | `manager/tests/fake_sink.py`, `manager/tests/test_sink_transport.py` | TASK-032 IMPL; #24 |
| TP-M2-11 | Disk queue order, restart, acknowledge, cut-off record, permissions | REQ-054 | TASK-033 TEST | `manager/tests/test_disk_queue.py` | TASK-033 IMPL |
| TP-M2-12 | Shipper and gate: order, outage queueing, one alert, 15-minute boundary, restart, drain; rolled-back and CLI entries (PostgreSQL) | REQ-053, REQ-054 | TASK-034 TEST | `manager/tests/test_shipper.py`, `manager/tests/test_shipper_pg.py` | TP-M2-10, TP-M2-11; #51 |
| TP-M2-13 | Alerts: one entry with `detail.alert`, counter on commit only | REQ-055 | TASK-035 TEST | `manager/tests/test_alerts.py` | TASK-035 IMPL; #50 |
| TP-M2-14 | Rate limits and the failed-check aggregator with a fake clock | REQ-047 | TASK-036 TEST | `manager/tests/test_ratelimit.py` | TASK-036 IMPL; #54, #55 |
| TP-M2-15 | Auth dependency matrix (TS §8.3 Security: tokens on the wrong route group, API tokens on TOTP-session and session-only routes), restricted admin session | REQ-044, REQ-045, REQ-046 | TASK-037 TEST | `manager/tests/test_auth_dependencies.py` | TP-M2-03, TP-M2-09; #48 |
| TP-M2-16 | Sign-in and sign-out: identical failures, dummy verify, back-off sequence, TOTP single use under concurrency, restricted session, per-IP limit, alert | REQ-048, REQ-042, REQ-047 | TASK-038 TEST | `manager/tests/test_login.py`, `manager/tests/test_login_pg.py` | TP-M2-15; #47, #54, #55 |
| TP-M2-17 | TOTP enrolment and replacement | REQ-049, REQ-043 | TASK-039 TEST | `manager/tests/test_totp_enrol.py` | TP-M2-16; #49 |
| TP-M2-18 | Password change | REQ-050 | TASK-040 TEST | `manager/tests/test_password_change.py` | TP-M2-16; #53 |
| TP-M2-19 | API tokens: lifetimes, shown once, ownership, revocation, alert, `bsk_` refusals | REQ-051 | TASK-041 TEST | `manager/tests/test_api_tokens.py` | TP-M2-15; #8 |
| TP-M2-20 | Users service (unit) and `/users` routes (PostgreSQL), last-admin race, rollback, sink-gate refusal on `/users` | REQ-052, REQ-046, REQ-054 | TASK-042 TEST (unit), TASK-043 TEST (API) | `manager/tests/test_users_service.py`, `manager/tests/test_users_api_pg.py` | TP-M2-15; #7, #53 |
| TP-M2-21 | Health routes, including `/readyz` with the `inventory` row missing (TS §8.3 Integration) | REQ-056 | TASK-044 TEST | `manager/tests/test_health_pg.py` | TP-M2-03; #5 |
| TP-M2-22 | `serve` on Linux: TLS versions, plain HTTP, `SIGHUP` reload (good and broken pair), missing variable, `SIGTERM` flush, proxy headers ignored | REQ-057 | TASK-045 TEST | `manager/tests/test_serve_linux.py`, `manager/tests/certs.py` | TP-M2-21 |
| TP-M2-23 | CLI `users` commands, including the password-input rules of #7 | REQ-058 | TASK-046 TEST | `manager/tests/test_cli_users_pg.py`, `manager/tests/test_cli.py` (update for REQ-008) | TP-M2-19, TP-M2-20; #7 |
| TP-M2-24 | Web regeneration and `baseUrl` recheck (G16, path prefix, type-level call) | REQ-059 | TASK-047 TEST | `web/src/api/client.test.ts` | TASK-047 IMPL |
| TP-M2-25 | M2 Security suite consolidated (TS §8.3 Security row, auth part): wrong route group; API tokens refused for sensitive actions, token creation and TOTP changes; plus the full canary sweep and the end-to-end chain create-admin → sign-in (restricted) → enrol → TOTP sign-in → create user → create API token → sink receives every entry | REQ-044 to REQ-058 | M2 gate | `manager/tests/test_security_m2.py` | all above |

### M2 waves and dependency spine

Spine: `TASK-023 → TASK-025 → TASK-036 → TASK-037 → TASK-038 → TASK-039 → TASK-040 → TASK-041 → TASK-043 → TASK-047`, with `TASK-024 → TASK-026 → TASK-027 → TASK-044 → TASK-038`; `TASK-029 → TASK-028 → TASK-037`; `TASK-031 → TASK-037`, `TASK-031 → TASK-042 → TASK-043`; `TASK-032, TASK-033, TASK-035 → TASK-034 → TASK-045 → TASK-046`; `TASK-030 → TASK-038`, `TASK-030 → TASK-045`; `TASK-041 → TASK-046`. The graph is acyclic.

Interface first: the runtime contract (TASK-025: `Clock`, `Database`, `TotpCipher`, `SinkGate`, on-commit hooks), the credential primitives (TASK-028, TASK-029), the repositories (TASK-031) and the problem types (TASK-026) all come before their consumers, so TASK-037 and the route tasks are written and tested against fixed signatures. The sink gate is consumed (TASK-037) through the TASK-025 protocol, so TASK-034 and TASK-037 run side by side in W4. `TASK-025 → TASK-035` (on-commit hooks) is why the alerts land in W3.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-023, TASK-024, TASK-029, TASK-031, TASK-033; tester TP-M2-00 | `manager/pyproject.toml`, `manager/requirements*.txt` · `bm/app.py` · `bm/auth/{__init__,totp}.py` · `bm/repositories/{users,user_tokens}.py` · `bm/services/audit/disk_queue.py` · `tests/m2/test-plan.md`, `tests/test-plan.md` |
| W2 | TASK-025, TASK-026, TASK-028, TASK-032 | `bm/runtime.py`, `bm/db/pool.py` · `bm/api/{__init__,problems,pagination}.py`, `bm/app.py` · `bm/auth/{tokens,passwords}.py` · `bm/services/audit/sink_transport.py` |
| W3 | TASK-027, TASK-030, TASK-035, TASK-036 | `bm/api/request_log.py`, `bm/app.py` · `bm/auth/vault.py` · `bm/services/audit/{alerts,metrics,__init__}.py` · `bm/api/ratelimit.py` |
| W4 | TASK-034, TASK-037, TASK-042, TASK-044 | `bm/services/audit/shipper.py`, `bm/repositories/audit_log.py` · `bm/auth/{principal,dependencies}.py` · `bm/services/users/{__init__,accounts}.py` · `bm/api/health.py`, `bm/repositories/health.py`, `bm/app.py`, `manager/openapi.json` |
| W5 | TASK-038, TASK-045 | `bm/auth/login.py`, `bm/api/user/{__init__,auth}.py`, `bm/app.py`, `manager/openapi.json` · `bm/cli/{serve,__init__}.py`, `README.md` |
| W6 | TASK-039 | `bm/auth/totp_enrol.py`, `bm/api/user/auth.py`, `manager/openapi.json` |
| W7 | TASK-040 | `bm/auth/password_change.py`, `bm/api/user/auth.py`, `manager/openapi.json` |
| W8 | TASK-041 | `bm/auth/api_tokens.py`, `bm/api/user/{api_tokens,__init__}.py`, `manager/openapi.json` |
| W9 | TASK-043, TASK-046 | `bm/api/user/{users,__init__}.py`, `manager/openapi.json` · `bm/cli/{users,__init__}.py`, `README.md` |
| W10 | TASK-047; tester TP-M2-25 and the M2 gate | `web/src/api/{schema.d.ts,client.ts}` |

Tester files follow the TP table; they are disjoint from the impl files of every wave.

### M2 gate

On a clean tree every command below is green, and each new gate turns red on its planted violation. "Local" is the Windows 11 + Git Bash box; "WSL" is WSL2 Ubuntu 24.04 with Docker, as in M1. G7 to G17 (agent, web, units) are unchanged and must stay green in CI; G16 must be green at the M2 head after TASK-047.

| Gate | Command | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1 | `ruff check manager` | f-string SQL in `bm/repositories/users.py` (S608); `import re` in `bm/auth/totp.py` | local |
| G2 | `ruff format --check manager` | one misformatted line in `bm/auth/dependencies.py` | local |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` | an untyped function in `bm/auth/login.py` | local |
| G4 | `pip install --require-hashes` of both locks in a fresh 3.12 venv | one altered hash of the Argon2id package | local and CI |
| G5 | `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | an untested 20-statement function in `bm/services/users/accounts.py` | local (unit tests of `services/audit` and `services/users` must reach 85 % without PostgreSQL) |
| G6 | OpenAPI export, then `git diff --exit-code -- manager/openapi.json` plus the untracked-file check | a route added in `bm/api/user/users.py` without re-export | local |
| G16 | G6, then `cd web && npm run gen:api`, then the diff and untracked check on `manager/openapi.json web/src/api/` | `manager/openapi.json` changed without regenerating the client | local and CI |
| G18 | `cd /root/bitscan/manager && CI=true python3.12 -m pytest --cov=bitscan_manager/services --cov-fail-under=85`: all pass, 0 skipped | any of G25 to G29 | WSL; CI |
| G25 | `… pytest tests/test_auth_dependencies.py tests/test_security_m2.py` (TS §8.3 Security, auth part) | the TOTP-session dependency removed from one `/users` method; `bsa_` accepted on user routes; the prefix-kind check removed | WSL; CI |
| G26 | `… pytest tests/test_shipper.py tests/test_shipper_pg.py` | the 15-minute check removed from `refusing()`; the shipper acknowledging a record before the sink accepted it | local (unit) and WSL (PostgreSQL) |
| G27 | `… pytest tests/test_serve_linux.py` | the TLS minimum lowered to 1.0; the `SIGHUP` handler removed | WSL; CI (Linux only: `SIGHUP` does not exist on Windows) |
| G28 | `… pytest tests/test_security_m2.py -k canary` | a log call that writes the `Authorization` header in `bm/api/request_log.py` | WSL; CI |
| G29 | `… pytest tests/test_app_hardening.py -k telemetry` | the telemetry settings removed from `create_app()` | local |

### Open items for M2

All are in `work/open-questions.md`. "Needed by" is the start of the wave whose task cannot be finished, or whose acceptance cannot be fixed, without the answer. Recommended defaults are given there; the lead may approve them in a batch.

| Item | Blocks | Needed by |
| --- | --- | --- |
| PD-19 (new): new runtime packages | TASK-023 | W1 |
| #57 (new): HSTS value; the byte value of "MB" | TASK-024 | W1 |
| #49 (new): TOTP algorithm, digits, period, window; enrolment protocol; non-admin codes at sign-in | TASK-029 (parameters, W1); TASK-038, TASK-039 (protocol) | W1 (parameters), W5 (protocol) |
| #24 (re-checked): vault product and API; sink wire format and authentication | TASK-032 (W2), TASK-030 (W3), TASK-034 | W2 |
| #48 (new): status codes and problem `type` values for user-route refusals | TASK-026, TASK-037 and every route task | W2 |
| #50 (new): audit actions, actor format, alert kinds and `detail` keys; which sign-in events are audited | TASK-035 and every task that audits | W3 |
| #52 (new): JSON form of BIGSERIAL ids | TASK-026, TASK-041, TASK-043 | W2 |
| #56 (new): token padding; password upper bound and normalisation; Argon2id parameters; username case | TASK-028 (W2), TASK-031 lookups (W1, adjustable), TASK-042 | W2 |
| #51 (new): sink delivery model (tail of committed rows; CLI and retention entries; outage clock across restarts; "drained"; delivery bound) | TASK-034, TASK-046 (alerts reaching the sink); shapes TASK-032 | W2 (TASK-032 record shape), W4 (TASK-034) |
| #54 (new; the lead's "alert thresholds", replaces two own-question markers): repeated sign-in failures; repeated 401s; floods of 409s (M3) | alert parts of TASK-036 and TASK-038 | W3 |
| #55 (new): back-off and rate-limit details; source IP is the TCP peer | TASK-036, TASK-038, TASK-045 | W3 |
| #58 (new): behaviour when the vault is unreachable | TASK-030 | W3 |
| #5 (re-checked): health route prefix and authentication; the metrics route | TASK-044 (W4), TASK-047 | W4 |
| #7 (re-checked): initial password for `create-admin` and `POST /users`; the forced change cannot be stored | TASK-042 (W4), TASK-046 (W9) | W4 |
| #53 (new): session and token effects of password change, self TOTP replacement, promotion, revoke-tokens; admins created directly; re-enable; self-disable; admin API tokens while the admin has no TOTP | TASK-037 (last point), TASK-040, TASK-042, TASK-043 | W4 |
| #47 (new): user-route request and response bodies and the `/users` sub-action and `DELETE /api-tokens` shapes; CLI options | TASK-038 onwards | W5 |
| #34 (re-checked): OpenAPI document not served | none (M0 reading kept); confirm before the first route | W5 |
| PD-20 (new): G16 checked at the gate, not per route task | TASK-038 to TASK-047 TEST steps | W5 |
| #8 (re-checked): may a `bsk_` token call `DELETE /api-tokens` | TASK-041, criterion REQ-051 (6) | W8 |
| #1 | none in M2: TASK-037's TOTP-session dependency is reused by `DELETE /policies/{id}` in M7, where #1 decides whether the sink gate applies | M7 |
| #6 | none: `serve` is reached through the M0 console script; how the UI is served stays M5 | M5 |
| PD-3 | second approval of the twelve auth tasks | each wave's REVIEW |

### Coverage matrix (M2)

| Spec section | Covered by | Status in M2 |
| --- | --- | --- |
| TS §2.3 Data flows and tokens | REQ-040, REQ-044 / TASK-028, TASK-037 | `bsu_` and `bsk_` covered; user tokens refused on agent routes is **uncovered** until M3 builds the agent router (M2 covers the user side: `bsa_`/`bse_` refused on user routes) |
| TS §5.3 Audit log integrity (sink, disk queue, 15-minute refusal) | REQ-053, REQ-054 / TASK-032 to TASK-034, TASK-043 | Covered; the delivery model is #51 |
| TS §5.3 Users never deleted; no results in logs | REQ-052 (2), REQ-039 | Covered |
| TS §6 intro (one API at `/api/v1`, separate routers per token group) | REQ-035 (5), REQ-044 | User router covered; the agent router is M3 |
| TS §6.2 token table and rules (L1076–L1091) | REQ-040 to REQ-052 | Covered |
| TS §6.2 routes `/auth/*`, `/api-tokens`, `/users` | REQ-048 to REQ-052 / TASK-038 to TASK-043 | Covered |
| TS §6.2 routes `GET`, `PATCH /settings` and `GET /audit-log` | (none) | **Uncovered**: not in the lead's M2 list; proposed for M3 (the settings feed the heartbeat). `PATCH /settings` will reuse the TASK-037 TOTP-session dependency |
| TS §6.2 other routes (policies, tasks, imports, agents, enrolment, packages, scans, schedules) | (none) | **Uncovered**: M3, M5, M7, M9, M11 per the reorder |
| TS §6.3 errors, pagination, timestamps and ids | REQ-038 / TASK-026 | Covered; BIGSERIAL id form is #52 |
| TS §6.3 rate limits | REQ-047 / TASK-036 to TASK-038 | Sign-in, per-user and failed-token limits covered. **Uncovered:** 30/min per agent and 10/min on `/agent/enroll` (M3) |
| TS §6.3 size limits | REQ-037 / TASK-024 | The mechanism and the 1 MB default are covered; the inventory and result caps are M3 and the `.bit` cap M7 |
| TS §6.3 headers, no CORS | REQ-035, REQ-036 / TASK-024 | Covered |
| TS §6.3 plain-text rendering, CSV escaping, `Idempotency-Key`, multipart import | (none) | **Uncovered**: M5 (UI, CSV), M9 (`POST /scans`), M7 (import) |
| TS §8.1 Privilege misuse; Stolen admin credentials (TOTP, API-token limits); Audit sink outage; Secrets in config; SQL injection | REQ-042 to REQ-054 | Covered for M2 code. The "every import, delete and settings change alerts" half of Stolen admin credentials is M3 (settings) and M7 (imports, deletes) |
| TS §8.1 Stolen web session (XSS) | REQ-036 (CSP), REQ-040 (bearer only, no cookies) | Server half covered; the UI half (in-memory token, plain text) is M5 |
| TS §8.2 Reviews (two approvals for auth) | owner notes above | Process: twelve tasks marked |
| TS §8.3 Security row (auth part) | TP-M2-15, TP-M2-25 / G25 | Covered for user routes. Job, runner, importer and certificate items are M3 to M10 |
| TS §8.3 Integration (every endpoint; `/readyz` with the `inventory` row missing) | TP-M2-09 to TP-M2-23 | Covered for every M2 endpoint |
| TS §8.4 Logs | REQ-039 / TASK-027 | Covered |
| TS §8.4 Metrics | REQ-055 (3) | Only `bitscan_alerts_total{kind}` exists, unexposed. **Uncovered:** the metrics route (#5) and the other metrics (agents by status, heartbeat latency, jobs, import failures, plugin ERROR rate): M3 onwards |
| TS §8.4 Alerts | REQ-055 / TASK-035 and the raising tasks | M2 events covered (API token created; TOTP enrolled, replaced, reset; user created, role granted, admin created; audit sink unreachable; repeated sign-in failures and 401s per #54). **Uncovered:** every other immediate and threshold alert (M3 to M11), including **clock skew > 5 min**, which needs the M3 heartbeat. The `db maintain` residual risk that relies on it (decisions 2026-10-20, gap check) therefore stays open until M3 |
| TS §8.4 Health endpoints | REQ-056 / TASK-044 | Covered; prefix and authentication #5 |
| TS §8.6 Start-up configuration | REQ-019 (M1), REQ-043, REQ-053, REQ-057 | Covered; vault and sink formats #24 |
| TS §8.6 Runtime settings | (none) | **Uncovered**: M3 with `/settings` |
| TS §8.7 Service (`serve`, HTTPS, `SIGHUP`) | REQ-057 / TASK-045 | Covered |
| TS §8.7 Server CLI | REQ-058 / TASK-046 | `users create-admin`, `create-api-token`, `reset-totp` covered; `bits rebuild` is M7 |
| TS §8.7 Folders and install | REQ-054 (the queue path is used as given) | **Uncovered**: creating the folders and the `bitscan-manager` user is the install method (#6) |
| TS §1.2 / CLAUDE.md out of scope (OIDC, client certificates) | REQ-034 (5) | Nothing planned; no OIDC library |

## M3 agent API and scheduler (inventory only)

Scope: the lead's M3 request (2026-10-22) and REQ-060 to REQ-090 in `work/requirements.md`. Branch `m3-agent-api`. As in M1 and M2, `bm/` means `manager/bitscan_manager/` in this section only.

**No migration in M3.** Every table and grant M3 uses is in TS §5.2 (see the requirements section), so REQ-033 is not exercised.

Design rules every M3 task follows (in addition to the M2 rules, which still hold):
- Services take repository objects through `Protocol`s, so their unit tests run without PostgreSQL and the G5 gate holds on the Windows box.
- Every time-based rule (token expiry, rotation window and overlap, rate windows, the 10-minute inventory limit, status thresholds, `pickup_by`, the 30-minute inventory failure, alert windows) reads the `Clock`.
- Route handlers only validate, authorise and call services. Agent route handlers never read the database directly.
- Threshold windows and rate counters live in memory (one manager instance, TS §2.1 L103) and reset on restart, unless #65 is answered otherwise.
- Every task that adds or changes a route re-exports `manager/openapi.json` in the same task (G6 per task). `web/src/api/schema.d.ts` is regenerated once, in TASK-081 (PD-20, kept for M3).
- No task adds a route, setting or parameter that queues a command or disables inventory (REQ-088); the route-walk test of TP-M3-35 is re-run in every route task's TEST step.

### M3 tasks

| TASK | Title | REQ links | Area | Owner | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-048 | Agent wire contract: Pydantic models for the six agent routes (TS §6.5), both Job variants, Results, Inventory, Rotate; agent problem `type` constants (plan: `work/plans/TASK-048.md`) | REQ-060, REQ-088 | manager | impl-manager | `bm/api/agent/__init__.py`, `bm/api/agent/schemas.py` | none; #59, #60 | 190 | Every valid TP-M3-01 fixture parses with its model and every invalid one is refused; the job-pull response's `model_json_schema()` has the two Job variants with exactly the TS §6.5 keys, `additionalProperties: false` and no `operator`, `expected_result` or `eval_spec` property; the heartbeat response schema has exactly its three keys. |
| TASK-049 | Body caps matched by path template, with an after-auth mode for the inventory and results routes (plan: `work/plans/TASK-049.md`) | REQ-066 | manager | impl-manager | `bm/app.py` | none | 90 | With test routes at the inventory and results templates, a body one byte over the template's cap on a concrete path gets 413 in normal mode, or in after-auth mode reaches the route through a reader that refuses past cap + 1 bytes (with `Content-Length` and chunked); other paths keep 1 MiB; a duplicate template or a cap over its class raises at app creation. |
| TASK-050 | `bsa_` and `bse_` token generation and parsing next to the user tokens | REQ-063 | manager | impl-manager | `bm/auth/tokens.py` | none; #56 (a) | 45 | 10,000 tokens of each kind are distinct, 47 characters, prefixed and decode to 32 bytes; the agent parser accepts only a well-formed token of the asked prefix, and the user parser still refuses both. |
| TASK-051 | Agent repository: lookups by token hash, previous-token hash and machine-id; insert; status, token, rotation and heartbeat updates; `agent_ip_seen` upsert and last-seen lookup; tag replace; list, detail and sweep selects | REQ-064, REQ-070, REQ-071, REQ-078, REQ-081, REQ-082 | manager | impl-manager | `bm/repositories/agents.py` | none (M1 schema) | 190 | PostgreSQL as `bitscan_app`: every function works with only the TS §5.2 grants, an unknown hash returns none, the `agent_ip_seen` upsert keeps `first_seen_at`, a tag replace is all-or-nothing, the status update touches only agents in the statuses it names, and ruff S608 passes. |
| TASK-052 | Enrolment repository: `enrollment_token` insert, atomic use (`UPDATE … WHERE uses < max_uses … RETURNING`, with expiry, revocation and CIDR in the same statement), revoke, pages; `enrollment_request` insert, lookup by `new_token_hash`, pages by state, decide with `FOR UPDATE`, same-hostname or machine-id matches (plan: `work/plans/TASK-067.md`) | REQ-067, REQ-068, REQ-069 | manager | impl-manager | `bm/repositories/enrolment.py` | none | 180 | PostgreSQL as `bitscan_app`: 20 concurrent uses of a `max_uses` 5 token succeed exactly 5 times; an expired, revoked or out-of-CIDR use returns none without incrementing `uses`; two concurrent decisions on one request succeed once; matches list every other agent sharing the hostname or machine-id. |
| TASK-053 | Inventory repository: `os_info` upsert; `package` insert-or-select in batches, reporting which rows are new; `agent_package` upsert and delete-not-listed; `inventory_snapshot` insert and latest; one agent's package page | REQ-075, REQ-081 | manager | impl-manager | `bm/repositories/inventory.py` | none | 190 | PostgreSQL as `bitscan_app`: 50,000 packages insert in batches using only INSERT on `package`, a second call reports no new rows, two concurrent inserts of one new package give one row, the `agent_package` upsert keeps `first_seen_at`, and delete-not-listed removes exactly the missing rows. |
| TASK-054 | Job repository: insert an inventory job with its payload in one statement; pull-and-dispatch (row lock, own agent, `queued`, `pickup_by` in the future, kind inventory in M3, at most 10, oldest first); lookup for an agent; complete; fail; expire past `pickup_by`; fail stale dispatched inventory; open-job check; oldest queued age for online agents | REQ-072, REQ-076, REQ-077, REQ-078, REQ-079 | manager | impl-manager | `bm/repositories/jobs.py` | none | 170 | PostgreSQL as `bitscan_app`: the payload's `job_id` equals the row's id; two concurrent pulls never return one job; every update uses only the TS §5.2 progress columns (a probe changing `agent_id` or `payload` is refused by the grants); the expire and stale-inventory updates touch exactly the rows past their bound for a given `now`. |
| TASK-055 | Runtime settings: repository for `setting` and `system_schedule`; typed `Settings` read; whole-patch range validation (pure); no key that disables inventory | REQ-083, REQ-088 | manager | impl-manager | `bm/repositories/settings.py`, `bm/services/settings/__init__.py`, `bm/services/settings/store.py` | none; #42 | 150 | On a migrated database the read returns the seeded defaults with `inventory_interval_s` from `system_schedule`; unit: every key at its minimum and maximum validates, one beyond, a wrong type and an unknown key (including `inventory_enabled`) fail, and a patch with one bad key fails as a whole. |
| TASK-056 | M3 alert kinds (#71); in-memory threshold windows (sliding count, once-per-period, re-arm); metric definitions (agents by status, heartbeat latency, jobs queued, jobs expired) in the existing registry | REQ-065, REQ-070, REQ-073, REQ-075, REQ-079, REQ-086 | manager | impl-manager | `bm/services/audit/alerts.py`, `bm/services/audit/thresholds.py`, `bm/services/audit/metrics.py`, `bm/services/audit/__init__.py` | none; #65, #71 | 150 | Unit with a fake clock: a window raises once when its count first exceeds the threshold, not again inside the period, again after it; a re-arm window raises again only after the value went back to or below the threshold; every #71 kind is accepted by `raise_alert` and exported from zero; the new metrics have bounded labels only. |
| TASK-057 | Agent rate limits: 30 per minute per agent, 10 per minute per IP on enrol, one unscheduled inventory upload per agent per 10 minutes; `RateLimits` protocol extended | REQ-065, REQ-076 | manager | impl-manager | `bm/api/ratelimit.py`, `bm/runtime.py` | none; #72 | 90 | With a fake clock, the 31st request of one agent, the 11th enrol from one IP and a second unscheduled upload within 10 minutes are refused while other keys pass, the retry-after value is the seconds to that window's end, and keys are dropped after their window. |
| TASK-058 | Dev-only test libraries for the contract and fuzz suites (PD-21): `jsonschema`, `hypothesis`; dev lock regenerated with the recorded command | REQ-061, REQ-074 | manager | impl-manager | `manager/pyproject.toml`, `manager/requirements-dev.txt` | none; PD-21 | 6 (+1 generated) | `pip install --require-hashes -r manager/requirements-dev.txt` exits 0 in fresh Windows and Linux venvs, both packages import, `manager/requirements.txt` is byte-identical to before, and the recorded lock command reproduces the dev lock byte for byte. |
| TASK-059 | Agent token check service: resolve a `bsa_` through the current, previous and pending-request hashes; outcomes in #59 order; mismatch revokes and alerts; first use of a rotated token starts the overlap; old-token reuse revokes both and alerts (plan: `work/plans/TASK-059.md`) | REQ-064, REQ-071 | manager | impl-manager | `bm/services/enrolment/__init__.py`, `bm/services/enrolment/token_check.py` | TASK-050, TASK-051, TASK-052, TASK-056; #25, #26, #59, #62, #63 | 190 | Unit with fake repositories and a fake clock: every row of the plan's outcome table (unknown, revoked, expired, mismatch, missing header, pending new, pending re-enrolment, rejected new, rejected re-enrolment, overlap before and after first use, reuse after the overlap, decommissioned) gives its outcome and writes exactly the stated revoke and alert, and no pending outcome is counted as a failed check. |
| TASK-060 | Inventory decoder: streaming gunzip with a 64 MiB cap (`gunzip_capped`, also used by the results route), JSON parse, 50,000-row and field limits, `raw` ≤ 256 KiB, `list_sha256` recomputed (#33); a complete `DecodedInventory` or one refusal (plan: `work/plans/TASK-060.md`) | REQ-074 | manager | impl-manager | `bm/services/inventory/__init__.py`, `bm/services/inventory/decode.py` | TASK-048; #33, #60, #72 | 170 | Unit and property tests: the TP-M3-01 inventory fixtures decode exactly; 64 MiB + 1 decompressed, a gzip bomb, 50,001 rows, each over-length field, a 256 KiB + 1 `raw`, duplicates and a hash mismatch each give their #72 refusal within the read and memory bounds; random or truncated input never raises anything else. |
| TASK-061 | Inventory queueing: eligible agents with no open inventory job get one (payload, `pickup_by` + 24 h) per run; `queue_first_inventory(agent_id)` for #36; runs serialised (plan: `work/plans/TASK-061.md`) | REQ-077, REQ-088 | manager | impl-manager | `bm/services/scheduler/__init__.py`, `bm/services/scheduler/inventory.py` | TASK-054, TASK-055; #36, #67 | 110 | PostgreSQL with a fake clock: one run queues exactly one job per `enrolled`, `online`, `stale` and `offline` agent and none for the others; a second run adds nothing while jobs are open; two simultaneous runs still give one job per agent; `queue_first_inventory` queues one job unless one is open. |
| TASK-062 | `GET` and `PATCH /api/v1/settings`: admin read; admin TOTP session and sink gate for PATCH; atomic apply with one audit entry and one `settings_changed` alert; `inventory_interval_s` written to `system_schedule` | REQ-083, REQ-088 | manager | impl-manager | `bm/api/user/settings.py`, `bm/services/settings/store.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-055, TASK-056; #68, #71 | 150 (+1 generated) | Through the API on PostgreSQL: GET returns the defaults; a PATCH of every key at its bounds succeeds with one audit and one alert entry; out-of-range, wrong-type, unknown-key (`inventory_enabled`) and mixed bodies change nothing; an admin `bsk_`, an unverified session and a session during a sink outage are refused on PATCH. |
| TASK-063 | Agent router and `bsa_` dependency: bearer and `X-Bitscan-Machine-Id`, token check, `{id}` match, failed-check counting, 30-per-minute agent limit, IP recording, `agent_id` and `job_id` log context, capped body reader for the after-auth routes; router mounted at `/api/v1/agent` (plan: `work/plans/TASK-059.md`) | REQ-062, REQ-064, REQ-065, REQ-066, REQ-087 | manager | impl-manager | `bm/api/agent/__init__.py`, `bm/api/agent/dependencies.py`, `bm/api/agent/bodies.py`, `bm/app.py` | TASK-048, TASK-049, TASK-057, TASK-059; #59, #63 | 190 | On a test app with one `bsa_` route and PostgreSQL behind it, the full matrix (no header, wrong scheme, `bsu_`, `bsk_`, `bse_`, unknown, revoked, expired, mismatch, missing machine-id header, pending, rejected, foreign `{id}`, the 31st request in a minute, an IP over the failed limit presenting a valid token) gives exactly the #59 outcomes; failures count toward the IP limit and valid tokens never do; records carry the `agent_id`. |
| TASK-064 | Inventory ingestion: one transaction replacing `os_info`, setting `last_inventory_at`, and on a changed `list_sha256` inserting packages, upserting and deleting `agent_package` and writing the snapshot (#69); new-package burst alert (plan: `work/plans/TASK-060.md`) | REQ-075 | manager | impl-manager | `bm/services/inventory/ingest.py` | TASK-053, TASK-056, TASK-060; #65, #69 | 180 | Unit with fake repositories, and PostgreSQL as `bitscan_app`: the first upload, the same list, an upgrade plus a removal and a forced mid-transaction failure each leave exactly the REQ-075 rows; two agents with one new package make one `package` row; more than 1,000 new packages in the #65 window alert once. |
| TASK-065 | `offline_sweep` core: status from heartbeat age (#25 base), decommission with token revoke, expire past `pickup_by`, fail inventory jobs dispatched over 30 minutes, jobs-expired metric; each step its own transaction (plan: `work/plans/TASK-061.md`) | REQ-078 | manager | impl-manager | `bm/services/scheduler/sweep.py` | TASK-051, TASK-054, TASK-055, TASK-056, TASK-061; #25, #73 | 170 | PostgreSQL with a fake clock at the REQ-078 boundaries: statuses, decommission (7 days and 0), expiry and inventory failure come out exactly as REQ-078 states, no job row is created, a step forced to fail leaves the other steps applied, and audit entries follow #73. |
| TASK-066 | Enrolment tokens: CRUD `/api/v1/enrollment-tokens` (admin, TOTP session, sink gate), token shown once, revoke by delete, risky-token alert, audit entries (plan: `work/plans/TASK-067.md`) | REQ-067, REQ-063 | manager | impl-manager | `bm/services/enrolment/enrolment_tokens.py`, `bm/api/user/enrolment.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-050, TASK-052, TASK-056, TASK-059, TASK-062; #68, #71 | 170 (+1 generated) | Through the API on PostgreSQL: defaults, ranges, CIDR validation and the once-only token behave as REQ-067; `auto_approve` or 101 uses writes one alert entry; delete sets `revoked_at` and keeps the row; every method refuses an admin `bsk_`, an unverified session, operators, viewers and any session while the sink gate refuses. |
| TASK-067 | `POST /api/v1/agent/enroll`: `bse_` check with atomic use and CIDR, new or re-enrolment, auto-approve, rows and response, per-IP limit, enrolments-per-hour alert, audit entry, #36 first inventory job (plan: `work/plans/TASK-067.md`) | REQ-068, REQ-065, REQ-077 | manager | impl-manager | `bm/services/enrolment/enrol.py`, `bm/api/agent/enrol.py`, `bm/api/agent/__init__.py`, `manager/openapi.json` | TASK-052, TASK-055, TASK-056, TASK-057, TASK-061, TASK-063, TASK-066; #36, #59, #60, #61, #64 | 200 (+1 generated) | Through the API on PostgreSQL: every refusal case changes nothing; 20 concurrent enrolments on a 5-use token give 5 successes; the new auto-approved, new held and re-enrolment outcomes write exactly the REQ-068 rows and responses (a re-enrolment with an auto-approve token stays held); the 11th attempt from one IP gets 429; the #61 alert fires on the enrolment after the threshold. |
| TASK-068 | Fleet threshold alerts run by the sweep: offline share, queue age (#66), stale inventory, default-partition rows (plan: `work/plans/TASK-061.md`) | REQ-079 | manager | impl-manager | `bm/services/scheduler/fleet_alerts.py` | TASK-056, TASK-065; #44, #65, #66 | 140 | PostgreSQL with a fake clock: 5 of 100 agents offline raise nothing and 6 raise one alert entry, repeats follow #65, the queue-age and stale-inventory boundaries of REQ-079 hold, and a row planted as owner in `scan_result_default` raises one alert entry. |
| TASK-069 | Redaction-pattern setting: RE2 compile of each pattern, at most 50, default-removed alert (PD-23 may move this task to M10) | REQ-084 | manager | impl-manager | `bm/services/settings/redaction.py`, `bm/services/settings/store.py` | TASK-062; PD-23 | 90 | Through `PATCH /settings` on PostgreSQL: 50 valid patterns are stored; 51, an invalid RE2 pattern and a non-string are refused with no change; removing a default writes the extra `redaction_default_removed` alert entry; the defaults round-trip byte for byte. |
| TASK-070 | Enrolment requests: `GET /api/v1/enrollment-requests` with matching agents; approve and reject (admin, TOTP session, sink gate) with the new, re-enrolment and rejection effects, the re-enrolment alert and the #36 first job (plan: `work/plans/TASK-067.md`) | REQ-069, REQ-077 | manager | impl-manager | `bm/services/enrolment/requests.py`, `bm/api/user/enrolment.py`, `manager/openapi.json` | TASK-052, TASK-056, TASK-061, TASK-066, TASK-067; #26, #36, #64, #68, #71 | 190 (+1 generated) | Through the API on PostgreSQL: the list shows hostname, source IP, OS and matching agents; approving new and re-enrolment requests and rejecting both kinds leave exactly the REQ-069 and #26 states (old token refused after a re-link, history kept, one alert entry); a second or concurrent decision gets 409 once; the refusals of REQ-069 (6) hold. |
| TASK-071 | Scheduler wiring in `serve`: APScheduler jobs for the inventory run and `offline_sweep` (intervals from `system_schedule`, one instance each, failures logged by type), started and stopped by the lifecycle; OpenTelemetry recheck (plan: `work/plans/TASK-061.md`) | REQ-080 | manager | impl-manager | `bm/services/scheduler/runner.py`, `bm/cli/serve.py` | TASK-061, TASK-065, TASK-068 | 120 | On Linux, `serve` with a short interval set as owner runs both jobs repeatedly, a run that raises is logged by type and the next one runs, overlapping runs never execute at once, `SIGTERM` exits 0 with no run after the pool closed, and G29 stays green. |
| TASK-072 | Heartbeat: `POST /api/v1/agent/{id}/heartbeat` storing heartbeat time, IP, version and helpers (change audit and alert), status per #73, #25 fields, clock-skew alert, latency metric, configuration-only response | REQ-070, REQ-086, REQ-088 | manager | impl-manager | `bm/services/agents/__init__.py`, `bm/services/agents/heartbeat.py`, `bm/api/agent/heartbeat.py`, `bm/api/agent/__init__.py`, `manager/openapi.json` | TASK-051, TASK-055, TASK-056, TASK-063; #25, #65, #73 | 170 (+1 generated) | Through the API on PostgreSQL with a fake clock: the response has exactly the three keys with the current settings; a helper change and a 5 min 1 s skew each write one alert entry while exactly 5 min and an unchanged list write none; no job row changes; `last_error` follows #25. |
| TASK-073 | Job pull and the M3 results route: `GET /jobs` (at most 10, own, `queued`, before `pickup_by`, inventory only, dispatched once); `POST /jobs/{job_id}/results` validating the frozen Results body with the 1.5 MiB caps and gzip, then 409 `job_not_acceptable`, audit entry, 409-flood alert | REQ-072, REQ-073, REQ-087, REQ-088 | manager | impl-manager | `bm/services/jobs/__init__.py`, `bm/services/jobs/pull.py`, `bm/api/agent/jobs.py`, `bm/api/agent/__init__.py`, `manager/openapi.json` | TASK-054, TASK-056, TASK-060, TASK-063; #54 (c), #65 | 190 (+1 generated) | Through the API on PostgreSQL: 12 queued jobs come back as 10 then 2, each dispatched once; concurrent pulls never share a job; other agents' jobs, past-`pickup_by` jobs and a compliance row planted as owner are never returned; every well-formed results post gets 409 with one audit entry and no stored row; a gzip body over 1.5 MiB decompressed gets 413; the 21st 409 in 10 minutes alerts once. |
| TASK-074 | `PUT /api/v1/agent/{id}/inventory`: after-auth caps, decode and ingest, the #72 `job_id` cases, the 10-minute unscheduled limit, refused uploads audit-logged and their job failed, 204 (plan: `work/plans/TASK-060.md`) | REQ-076, REQ-066 | manager | impl-manager | `bm/services/inventory/upload.py`, `bm/api/agent/inventory.py`, `bm/api/agent/__init__.py`, `manager/openapi.json` | TASK-054, TASK-057, TASK-060, TASK-063, TASK-064; #72 | 170 (+1 generated) | Through the API on PostgreSQL with a fake clock: a dispatched job's upload completes it; a failed job's upload is stored and the job stays failed; each other #72 `job_id` case gets its answer; a second unscheduled upload within 10 minutes gets 429; an over-cap or 422 upload naming a dispatched job fails it with one audit entry. |
| TASK-075 | Token rotation: `POST /api/v1/agent/{id}/token/rotate` with the window, the 24 h rule, the lost-response retry, reuse, and the outside-window and new-IP alerts (plan: `work/plans/TASK-059.md`) | REQ-071 | manager | impl-manager | `bm/services/enrolment/rotation.py`, `bm/api/agent/rotate.py`, `bm/api/agent/__init__.py`, `manager/openapi.json` | TASK-051, TASK-055, TASK-056, TASK-059, TASK-063; #62 | 170 (+1 generated) | Through the API on PostgreSQL with a fake clock: every REQ-071 criterion holds (window edges for TTL 365 and 60, lost-response retry, overlap and reuse per #62, the 24 h rule, the new-IP alert at 8 days and not at 6, `token_expired` after `expires_at`). |
| TASK-076 | Fleet read routes: `GET /api/v1/agents`, `/agents/{id}` (with `os_info` and the latest snapshot, #69), `/agents/{id}/packages` (viewer, paginated) | REQ-081 | manager | impl-manager | `bm/services/agents/fleet.py`, `bm/api/user/agents.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-051, TASK-053, TASK-072; #68, #69 | 190 (+1 generated) | Through the API on PostgreSQL: a viewer `bsk_` reads the three routes with exactly the #68 fields; paging returns each item once; an unknown id gets 404; `<script>` values come back verbatim; no response holds a token hash. |
| TASK-077 | Tags and revoke: `PUT /api/v1/agents/{id}/tags` (operator) and `POST /api/v1/agents/{id}/revoke` (admin, TOTP session, sink gate), audit entries | REQ-082 | manager | impl-manager | `bm/services/agents/admin.py`, `bm/api/user/agents.py`, `manager/openapi.json` | TASK-051, TASK-056, TASK-076; #68, #71 | 130 (+1 generated) | Through the API on PostgreSQL: an operator replaces and clears tags and a viewer is refused; after revoke the current and the previous token get 401 `token_revoked`; revoke refuses an admin `bsk_`, an unverified session and any session while the sink gate refuses; each change writes one audit entry. |
| TASK-078 | `GET /api/v1/audit-log` (admin, session or API token): paginated read of the chain | REQ-085 | manager | impl-manager | `bm/repositories/audit_log.py`, `bm/api/user/audit_log.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-077 (OpenAPI order only); #68 | 110 (+1 generated) | Through the API on PostgreSQL: an admin `bsk_` pages through every entry once in the #68 order, the returned items re-verify with `compute_row_hash`, an operator is refused, and the route writes nothing. |
| TASK-079 | Metrics route (#70) serving the existing registry, with agents by status and jobs queued collected at scrape time | REQ-086 | manager | impl-manager | `bm/services/audit/metrics.py`, `bm/api/user/metrics.py`, `bm/api/user/__init__.py`, `manager/openapi.json` (if #70 picks a root path: `bm/api/metrics.py` and `bm/app.py` instead of the two `api/user` files) | TASK-056, TASK-078; #70 | 120 (+1 generated) | Through the API on PostgreSQL: the #70 route returns Prometheus text with the REQ-086 metrics, the gauges equal database counts, the histogram and the expired counter move as REQ-086 (2) states, the #70 authentication holds, and no label has an unbounded value. |
| TASK-080 | README: enrolment tokens and approvals through the API with a TOTP session (#37), the agent API and its limits, settings, metrics, the scheduler | REQ-090 | manager | impl-manager | `README.md` | TASK-079 | 160 (docs) | The reviewer follows every documented request against a test manager and each behaves as written; the README holds no real secret, task id or process note. |
| TASK-081 | Web: regenerate `schema.d.ts` from the M3 `manager/openapi.json`; recheck `baseUrl ""` and `HealthPath` (#70) | REQ-089 | web | impl-web | `web/src/api/schema.d.ts`, `web/src/api/client.ts` | TASK-079, TASK-083; #70; PD-20 | 10 (+1 generated) | After `npm run gen:api`, G16 shows no diff, the `UserPathsArePrefixed` guard passes and fails on a planted unprefixed path, and `npm run typecheck` passes with a type-level call to `GET /api/v1/agents`. |
| TASK-082 | Every attempt counts: `POST /api/v1/agent/enroll` and `POST /api/v1/auth/login` read the raw body and validate it after the per-IP limit, so malformed attempts count too (TS §6.3 L1136, #55 (c); user-ordered follow-up, decisions 2026-10-23 "TASK-067 second approval given"). **Two approvals (auth, enrolment).** | REQ-065, REQ-068, REQ-047 | manager | impl-manager | `bm/api/agent/enrol.py`, `bm/api/user/auth.py` (plus one shared helper module if needed), `manager/openapi.json` | TASK-067, TASK-070 (OpenAPI order) | 80 (+1 generated) | On each route, 11 non-JSON or malformed-JSON attempts from one IP within a minute give 10 × 400 and then 429 `rate_limited`; valid behaviour and problem bodies are otherwise unchanged, and the OpenAPI document still documents each request schema and lists no 422. |
| TASK-083 | Token before body on `bsa_` JSON routes: the token check runs before body parsing on every `bsa_` route that declares a JSON body (today the heartbeat; results, inventory and rotate already read their body after it), reusing the TASK-082 route-class pattern; the `Count64` comment fixed (user-ordered follow-up, decisions 2026-10-23 "TASK-072 and TASK-048 revision 2 second approvals given"). **Two approvals (agent routes).** | REQ-065, REQ-062 | manager | impl-manager | `bm/api/agent/heartbeat.py`, `bm/api/attempt_limits.py` (or a sibling route class), `bm/api/agent/schemas.py` (the `Count64` comment only), `manager/openapi.json` | TASK-072, TASK-082, TASK-079 (export order) | 60 (+1 generated) | On `POST /api/v1/agent/{id}/heartbeat`, a non-JSON or malformed body with a bad or missing token gets 401 and counts as a failed check (the 21st such attempt from one IP in a minute gets 429), and with a valid token it still gets 400; valid behaviour, problem bodies and the OpenAPI document are otherwise unchanged (no 422). |
| TASK-084 | Break the `services.inventory` ↔ `api.agent` import cycle at its smallest point, keeping the contract models in `api/agent/schemas.py` (lead ruling, decisions 2026-10-23 "Import cycle fixed in M3"). Not on the two-approval list unless the fix touches agent-route behaviour. | REQ-062, REQ-074 | manager | impl-manager | `bm/api/agent/__init__.py`, a new small constants module, `bm/services/inventory/ingest.py`, `bm/services/jobs/pull.py` (as needed) | TASK-083 | 30 | Every `bitscan_manager` module imports on its own in a fresh interpreter; behaviour and `manager/openapi.json` are unchanged. |

Totals: 31 REQ (REQ-060 to REQ-090), 37 TASK (TASK-048 to TASK-084), 39 test-plan items (TP-M3-00 to TP-M3-38), 14 waves. Every task is within 5 files and about 200 hand-written lines; TASK-067 is at the limit (if it grows, split the response building and audit from the `bse_` check). Test files are not counted, as in M2.

REQ to TASK: REQ-060 TASK-048; REQ-061 TASK-058 (fixtures are TP-M3-01, tester); REQ-062 TASK-063; REQ-063 TASK-050, TASK-066; REQ-064 TASK-051, TASK-059, TASK-063; REQ-065 TASK-056, TASK-057, TASK-063, TASK-067; REQ-066 TASK-049, TASK-063, TASK-074; REQ-067 TASK-052, TASK-066; REQ-068 TASK-052, TASK-067; REQ-069 TASK-052, TASK-070; REQ-070 TASK-051, TASK-056, TASK-072; REQ-071 TASK-051, TASK-059, TASK-075; REQ-072 TASK-054, TASK-073; REQ-073 TASK-056, TASK-073; REQ-074 TASK-058, TASK-060; REQ-075 TASK-053, TASK-056, TASK-064; REQ-076 TASK-054, TASK-057, TASK-074; REQ-077 TASK-054, TASK-061, TASK-067, TASK-070; REQ-078 TASK-051, TASK-054, TASK-065; REQ-079 TASK-054, TASK-056, TASK-068; REQ-080 TASK-071; REQ-081 TASK-051, TASK-053, TASK-076; REQ-082 TASK-051, TASK-077; REQ-083 TASK-055, TASK-062; REQ-084 TASK-069; REQ-085 TASK-078; REQ-086 TASK-056, TASK-072, TASK-079; REQ-087 TASK-063, TASK-073; REQ-088 TASK-048, TASK-055, TASK-061, TASK-062, TASK-072, TASK-073; REQ-089 TASK-081; REQ-090 TASK-080. Every M3 REQ has at least one TASK, and every TASK has at least one REQ.

### M3 owner and review notes

- **Two approvals (TS §8.2 L1268; `work/decisions.md` 2026-10-20: "enrolment and agent routes (M3)"):** TASK-048 (agent contract), TASK-050 (agent token primitives), TASK-059 (agent token check), TASK-063 (agent router and dependency), TASK-066 (enrolment tokens), TASK-067 (enrol), TASK-070 (approve and reject), TASK-072 (heartbeat), TASK-073 (job pull and results), TASK-074 (inventory route), TASK-075 (rotation), TASK-077 (revoke), TASK-082 (every attempt counts on enrol and sign-in), TASK-083 (token before body on `bsa_` JSON routes). Until PD-3 is decided, the second approver is the user, batched per wave.
- **Recommended second look (not on the TS §8.2 list):** TASK-049 (caps that guard every agent route), TASK-057 (agent rate limits), TASK-060 and TASK-064 (decoder and ingestion: TS §8.1 L1250 decompression bombs, L1257 flooding), TASK-062 (`PATCH /settings` is a sensitive action), TASK-071 (`serve` lifecycle).
- impl-manager owns every M3 task except TASK-081 (impl-web). No impl-deploy task is planned: the CI workflows run the whole pytest suite with `CI=true`, which picks up the new contract, fuzz and security files. If the tester wants the fuzz suite on a longer budget than PR CI allows, that is a small impl-deploy follow-up (a nightly job), not M3 scope.
- Shared files, never in the same wave: `bm/app.py` (TASK-049 then TASK-063, and TASK-079 only if #70 picks a root path); `bm/api/agent/__init__.py` (TASK-048 creates it; TASK-063, 067, 072, 073, 074, 075 add one router line each); `bm/api/user/__init__.py` (TASK-062, 066, 076, 078, 079); `bm/api/user/enrolment.py` (TASK-066, TASK-070); `bm/api/user/agents.py` (TASK-076, TASK-077); `bm/services/settings/store.py` (TASK-055, 062, 069); `manager/openapi.json` (TASK-062, 066, 067, 070, 072, 073, 074, 075, 076, 077, 078, 079, one per wave, PD-24).
- `bm/runtime.py` changes once (TASK-057, the `RateLimits` protocol). `bm/cli/serve.py` changes once (TASK-071).
- Planted violations are made in a throwaway copy or branch, never left in the tree.
- **G5 plant (M2 gate review "Planning" carry-over):** the plant is an untested function in `bm/services/inventory/ingest.py` with more than `covered / 0.85 − S` statements, where `S` and `covered` come from the clean run's coverage report; the tester computes the size at the gate, so the plant turns G5 red whatever the coverage then is. The 85 % threshold is unchanged.

### M3 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m3/test-plan.md`, check ids `CHK-M3-###`) and run in the TEST step named. PostgreSQL items run in WSL or CI with `CI=true`; Linux-only items also run as the non-root WSL user `bstester` (decisions 2026-10-22). Files are the tester's suggestion; the fixture location follows PD-22.

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M3-00 | Phase test plan and the M3 index row | all M3 | phase start; report at the M3 gate | `tests/m3/test-plan.md`, `tests/test-plan.md` (report files via `main`) | none |
| TP-M3-01 | Contract fixtures written from TS §6.5 and #60, valid and invalid, for every request and response of the six routes | REQ-061 | W1, before TASK-048 TEST | `manager/tests/contract/fixtures/` (PD-22) | #60, PD-22 |
| TP-M3-02 | Contract test (G30): fixtures against the models and against the `manager/openapi.json` component schemas | REQ-060, REQ-061 | TASK-048 TEST (models); re-run in every agent route task's TEST (document) | `manager/tests/test_contract_agent.py` | TP-M3-01, TASK-058 |
| TP-M3-03 | Templated and after-auth body caps | REQ-066 | TASK-049 TEST | `manager/tests/test_body_caps.py` | TASK-049 IMPL |
| TP-M3-04 | Agent token primitives | REQ-063 | TASK-050 TEST | `manager/tests/test_tokens.py` (extend) | TASK-050 IMPL |
| TP-M3-05 | Agent repository on PostgreSQL | REQ-064, REQ-070, REQ-071, REQ-078, REQ-081, REQ-082 | TASK-051 TEST | `manager/tests/test_agent_repo_pg.py` | TASK-051 IMPL |
| TP-M3-06 | Enrolment repository: concurrent `max_uses`, CIDR, concurrent decisions | REQ-067, REQ-068, REQ-069 | TASK-052 TEST | `manager/tests/test_enrolment_repo_pg.py` | TASK-052 IMPL |
| TP-M3-07 | Inventory repository: batches, concurrency, grants only | REQ-075, REQ-081 | TASK-053 TEST | `manager/tests/test_inventory_repo_pg.py` | TASK-053 IMPL |
| TP-M3-08 | Job repository: row locks, progress-column grant probes, bounds for a given `now` | REQ-072, REQ-076, REQ-077, REQ-078 | TASK-054 TEST | `manager/tests/test_jobs_repo_pg.py` | TASK-054 IMPL |
| TP-M3-09 | Settings read and validation | REQ-083 | TASK-055 TEST | `manager/tests/test_settings_service.py`, `manager/tests/test_settings_pg.py` | TASK-055 IMPL |
| TP-M3-10 | Threshold windows, alert kinds, metric definitions | REQ-079, REQ-086 | TASK-056 TEST | `manager/tests/test_thresholds.py` | TASK-056 IMPL |
| TP-M3-11 | Agent rate limits | REQ-065, REQ-076 | TASK-057 TEST | `manager/tests/test_ratelimit.py` (extend) | TASK-057 IMPL |
| TP-M3-12 | Dev lock install and reproducibility | REQ-061, REQ-074 | TASK-058 TEST | none in the tree (evidence) | TASK-058 IMPL |
| TP-M3-13 | Token check outcome table | REQ-064, REQ-071 | TASK-059 TEST | `manager/tests/test_token_check.py` | TASK-059 IMPL; #59, #62, #63 |
| TP-M3-14 | Decoder unit, property and fuzz tests incl. gzip bombs (G32) | REQ-074 | TASK-060 TEST | `manager/tests/test_inventory_decode.py`, `manager/tests/test_inventory_fuzz.py` | TP-M3-01, TASK-058 |
| TP-M3-15 | Inventory queueing | REQ-077 | TASK-061 TEST | `manager/tests/test_inventory_queue_pg.py` | TASK-061 IMPL; #67 |
| TP-M3-16 | Settings routes | REQ-083, REQ-088 | TASK-062 TEST | `manager/tests/test_settings_api_pg.py` | TP-M3-09 |
| TP-M3-17 | Agent dependency matrix (TS §8.3 Security: tokens on the wrong route group) | REQ-062, REQ-064, REQ-065, REQ-066, REQ-087 | TASK-063 TEST | `manager/tests/test_agent_auth_pg.py` | TP-M3-13 |
| TP-M3-18 | Ingestion | REQ-075 | TASK-064 TEST | `manager/tests/test_inventory_ingest.py`, `manager/tests/test_inventory_ingest_pg.py` | TP-M3-07, TP-M3-14 |
| TP-M3-19 | Sweep with clock control (G33) | REQ-078 | TASK-065 TEST | `manager/tests/test_sweep_pg.py` | TP-M3-05, TP-M3-08 |
| TP-M3-20 | Enrolment tokens API | REQ-067, REQ-063 | TASK-066 TEST | `manager/tests/test_enrolment_tokens_api_pg.py` | TP-M3-06 |
| TP-M3-21 | Enrolment API: refusals, concurrency, CIDR, auto-approve, re-enrolment, per-IP limit, #61 alert | REQ-068, REQ-065 | TASK-067 TEST | `manager/tests/test_enrol_api_pg.py` | TP-M3-17, TP-M3-20 |
| TP-M3-22 | Fleet threshold alerts | REQ-079 | TASK-068 TEST | `manager/tests/test_fleet_alerts_pg.py` | TP-M3-19 |
| TP-M3-23 | Redaction-pattern setting | REQ-084 | TASK-069 TEST | `manager/tests/test_settings_redaction_pg.py` | TP-M3-16 |
| TP-M3-24 | Approve and reject | REQ-069, REQ-077 | TASK-070 TEST | `manager/tests/test_enrolment_requests_api_pg.py` | TP-M3-21 |
| TP-M3-25 | Scheduler inside `serve` on Linux (also G27, G29) | REQ-080 | TASK-071 TEST | `manager/tests/test_serve_scheduler_linux.py` | TP-M3-19, TP-M3-22 |
| TP-M3-26 | Heartbeat | REQ-070, REQ-086 | TASK-072 TEST | `manager/tests/test_heartbeat_api_pg.py` | TP-M3-17 |
| TP-M3-27 | Job pull and results | REQ-072, REQ-073 | TASK-073 TEST | `manager/tests/test_jobs_api_pg.py` | TP-M3-17, TP-M3-08 |
| TP-M3-28 | Inventory upload route | REQ-076, REQ-066 | TASK-074 TEST | `manager/tests/test_inventory_api_pg.py` | TP-M3-18, TP-M3-27 |
| TP-M3-29 | Rotation with clock control | REQ-071 | TASK-075 TEST | `manager/tests/test_rotation_api_pg.py` | TP-M3-17 |
| TP-M3-30 | Fleet read routes | REQ-081 | TASK-076 TEST | `manager/tests/test_agents_api_pg.py` | TP-M3-28 |
| TP-M3-31 | Tags and revoke | REQ-082 | TASK-077 TEST | `manager/tests/test_agents_admin_api_pg.py` | TP-M3-30 |
| TP-M3-32 | Audit-log route | REQ-085 | TASK-078 TEST | `manager/tests/test_audit_log_api_pg.py` | TASK-078 IMPL |
| TP-M3-33 | Metrics route | REQ-086 | TASK-079 TEST | `manager/tests/test_metrics_api_pg.py` | TP-M3-26 |
| TP-M3-34 | Web regeneration and `HealthPath` recheck (G16) | REQ-089 | TASK-081 TEST | `web/src/api/client.test.ts` (extend) | TASK-081 IMPL |
| TP-M3-35 | M3 security and invariants suite (G31, G34): the route walk (no ad-hoc command, no inventory switch), the static no-client check, the canary sweep with `bsa_`, `bse_`, stdout and package-name canaries, the at-rest token scan, the API chain (create `bse_` → enrol held → approve → heartbeat → pull the inventory job → upload → `GET /agents/{id}` shows `os_info` and the snapshot → rotate → revoke), and the mutation table below | REQ-060 to REQ-088 | M3 gate (route walk and canary re-run in every route task) | `manager/tests/test_security_m3.py`, `manager/tests/test_invariants_m3.py` | all above |
| TP-M3-36 | Every attempt counts on enrol and sign-in: 11 non-JSON or malformed-JSON attempts from one IP within a minute give 10 × 400 then 429 on each route; valid requests, problem bodies and the OpenAPI document (request schema documented, no 422) unchanged; M2 sign-in tests re-run | REQ-065, REQ-068, REQ-047 | TASK-082 TEST | `manager/tests/test_attempt_limits_pg.py`, `manager/tests/test_login.py` (re-run) | TP-M3-21, TP-M3-24 |
| TP-M3-37 | Token before body on the heartbeat: a non-JSON or malformed body with a bad or missing token gets 401 and counts as a failed check (the 21st from one IP in a minute gets 429); with a valid token it gets 400; valid behaviour, problem bodies and the OpenAPI document (no 422) unchanged; heartbeat tests re-run | REQ-065, REQ-062 | TASK-083 TEST | `manager/tests/test_attempt_limits_pg.py` (extend), `manager/tests/test_heartbeat_api_pg.py` (re-run) | TP-M3-26, TP-M3-36 |
| TP-M3-38 | Import isolation: each `bitscan_manager` module imports on its own in a fresh interpreter (no import cycle); G6 export byte-identical; full suite re-run on the fixed tree | REQ-062, REQ-074 | TASK-084 TEST; the M3 gate re-runs on the fixed tree | `manager/tests/test_module_imports.py` | TASK-084 IMPL |

### M3 waves and dependency spine

Spine (data): `TASK-050, TASK-051, TASK-052, TASK-056 → TASK-059 → TASK-063 → TASK-067 → TASK-070`; `TASK-048 → TASK-060 → TASK-064 → TASK-074`; `TASK-053 → TASK-064`; `TASK-054, TASK-055 → TASK-061 → TASK-065 → TASK-068 → TASK-071`; `TASK-049, TASK-057 → TASK-063`; `TASK-059 → TASK-075`; `TASK-072 → TASK-076 → TASK-077`.
Spine (OpenAPI order, PD-24): `TASK-062 → TASK-066 → TASK-067 → TASK-070 → TASK-082 → TASK-072 → TASK-073 → TASK-074 → TASK-075 → TASK-076 → TASK-077 → TASK-078 → TASK-079 → TASK-083 → TASK-080, TASK-081`. The graph is acyclic.

Interface first: the wire contract (TASK-048, fixed by #60 and checked against the tester's fixtures TP-M3-01), the token primitives (TASK-050), the four repositories (TASK-051 to TASK-054), the settings read (TASK-055), the alert kinds, windows and metric names (TASK-056) and the rate-limit protocol (TASK-057) all land in W1, so every service and route task is written and tested against fixed signatures.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-048, 049, 050, 051, 052, 053, 054, 055, 056, 057, 058; tester TP-M3-00, TP-M3-01 | `bm/api/agent/{__init__,schemas}.py` · `bm/app.py` · `bm/auth/tokens.py` · `bm/repositories/agents.py` · `bm/repositories/enrolment.py` · `bm/repositories/inventory.py` · `bm/repositories/jobs.py` · `bm/repositories/settings.py`, `bm/services/settings/{__init__,store}.py` · `bm/services/audit/{alerts,thresholds,metrics,__init__}.py` · `bm/api/ratelimit.py`, `bm/runtime.py` · `manager/pyproject.toml`, `manager/requirements-dev.txt` · `tests/m3/test-plan.md`, `tests/test-plan.md`, `manager/tests/contract/fixtures/` |
| W2 | TASK-059, 060, 061, 062 | `bm/services/enrolment/{__init__,token_check}.py` · `bm/services/inventory/{__init__,decode}.py` · `bm/services/scheduler/{__init__,inventory}.py` · `bm/api/user/settings.py`, `bm/services/settings/store.py`, `bm/api/user/__init__.py`, `manager/openapi.json` |
| W3 | TASK-063, 064, 065, 066 | `bm/api/agent/{__init__,dependencies,bodies}.py`, `bm/app.py` · `bm/services/inventory/ingest.py` · `bm/services/scheduler/sweep.py` · `bm/services/enrolment/enrolment_tokens.py`, `bm/api/user/enrolment.py`, `bm/api/user/__init__.py`, `manager/openapi.json` |
| W4 | TASK-067, 068, 069 | `bm/services/enrolment/enrol.py`, `bm/api/agent/{enrol,__init__}.py`, `manager/openapi.json` · `bm/services/scheduler/fleet_alerts.py` · `bm/services/settings/{redaction,store}.py` |
| W5 | TASK-070, 071 | `bm/services/enrolment/requests.py`, `bm/api/user/enrolment.py`, `manager/openapi.json` · `bm/services/scheduler/runner.py`, `bm/cli/serve.py` |
| W5b | TASK-082 | `bm/api/agent/enrol.py`, `bm/api/user/auth.py` (plus a shared helper if needed), `manager/openapi.json` |
| W6 | TASK-072 | `bm/services/agents/{__init__,heartbeat}.py`, `bm/api/agent/{heartbeat,__init__}.py`, `manager/openapi.json` |
| W7 | TASK-073 | `bm/services/jobs/{__init__,pull}.py`, `bm/api/agent/{jobs,__init__}.py`, `manager/openapi.json` |
| W8 | TASK-074 | `bm/services/inventory/upload.py`, `bm/api/agent/{inventory,__init__}.py`, `manager/openapi.json` |
| W9 | TASK-075 | `bm/services/enrolment/rotation.py`, `bm/api/agent/{rotate,__init__}.py`, `manager/openapi.json` |
| W10 | TASK-076 | `bm/services/agents/fleet.py`, `bm/api/user/{agents,__init__}.py`, `manager/openapi.json` |
| W11 | TASK-077 | `bm/services/agents/admin.py`, `bm/api/user/agents.py`, `manager/openapi.json` |
| W12 | TASK-078 | `bm/repositories/audit_log.py`, `bm/api/user/{audit_log,__init__}.py`, `manager/openapi.json` |
| W13 | TASK-079 | `bm/services/audit/metrics.py`, `bm/api/user/{metrics,__init__}.py`, `manager/openapi.json` |
| W14 | TASK-083, TASK-080, TASK-081; tester TP-M3-35 and the M3 gate (TASK-083 before TASK-081, OpenAPI order) | `bm/api/agent/heartbeat.py`, `bm/api/attempt_limits.py`, `bm/api/agent/schemas.py`, `manager/openapi.json` · `README.md` · `web/src/api/{schema.d.ts,client.ts}` |
| W14b | TASK-084 (after TASK-083, before the M3 gate) | `bm/api/agent/__init__.py`, a new small constants module, `bm/services/inventory/ingest.py`, `bm/services/jobs/pull.py` (as needed) |

Waves W6 to W13 hold one route task each only because every route task re-exports `manager/openapi.json` and edits a router `__init__.py` (PD-24 (a)). All non-route work is finished by W5, so with one impl-manager instance this costs no time; with PD-24 (b) the lead could merge W6 to W13 into about three waves. Tester files follow the TP table and are disjoint from every wave's impl files.

### M3 gate

On a clean tree every command below is green, and each gate turns red on its planted violation. "Local" is the Windows 11 + Git Bash box; "WSL" is WSL2 Ubuntu 24.04 with Docker, as in M1 and M2. G7 to G15 and G17 are unchanged since M0 and must stay green in CI; G16 must be green at the M3 head after TASK-081.

| Gate | Command | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1 | `ruff check manager` | f-string SQL in `bm/repositories/agents.py` (S608); `import re` in `bm/services/settings/redaction.py` | local |
| G2 | `ruff format --check manager` | one misformatted line in `bm/api/agent/dependencies.py` | local |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` | an untyped function in `bm/services/inventory/decode.py` | local |
| G4 | `pip install --require-hashes` of both locks in a fresh 3.12 venv | every `hypothesis` hash altered in the dev lock (one altered hash stays green: 78 wheel hashes, pip falls back to another allowed wheel; CHK-M3-002, decisions 2026-10-23) | local and CI |
| G5 | `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | an untested function in `bm/services/inventory/ingest.py` sized from the clean report (owner notes) | local |
| G6 | OpenAPI export, then `git diff --exit-code -- manager/openapi.json` plus the untracked-file check | an agent route added in `bm/api/agent/heartbeat.py` without re-export | local |
| G16 | G6, then `cd web && npm run gen:api`, then the diff and untracked check on `manager/openapi.json web/src/api/` | `manager/openapi.json` changed without regenerating the client | local and CI |
| G18 | `cd /root/bitscan/manager && CI=true python3.12 -m pytest --cov=bitscan_manager/services --cov-fail-under=85`: all pass, 0 skipped | any of G25 to G34 | WSL; CI |
| G25 | M2 security suite re-run (`tests/test_auth_dependencies.py tests/test_security_m2.py`) | the M2 plants (agent tokens now real rows: `bsa_` accepted on user routes) | WSL; CI |
| G26 | M2 shipper suite re-run, unchanged | the M2 plants | local and WSL |
| G27 | `… pytest tests/test_serve_linux.py tests/test_serve_scheduler_linux.py` | the pool closed before the scheduler stops (a run after close) | WSL as `bstester`; CI |
| G28 | `… pytest tests/test_security_m3.py -k canary` (with the M2 canary tests) | the `Authorization` header or the inventory body logged in `bm/api/agent/dependencies.py` | WSL; CI |
| G29 | `… pytest tests/test_app_hardening.py -k telemetry` | `telemetry=` removed from `create_app()` after the scheduler wiring | local |
| G30 | `… pytest tests/test_contract_agent.py` (new) | `operator` added to the compliance Job variant; `extra="forbid"` removed from the heartbeat request model; a field renamed in `schemas.py` | local |
| G31 | `… pytest tests/test_agent_auth_pg.py tests/test_security_m3.py` (new; TS §8.3 Security, agent part) | the security mutation table rows marked G31 | WSL; CI |
| G32 | `… pytest tests/test_inventory_fuzz.py tests/test_inventory_decode.py` (new; TS §8.3 Property/fuzz) | the decompressed cap removed (whole-body `zlib.decompress`); packages returned before the row-count check | local |
| G33 | `… pytest tests/test_sweep_pg.py tests/test_inventory_queue_pg.py tests/test_fleet_alerts_pg.py` (new) | the 30-minute inventory failure changed to 30 hours; the inventory run skipping `offline` agents | WSL; CI |
| G34 | `… pytest tests/test_invariants_m3.py` (new) | `POST /api/v1/agents/{id}/run` added; a setting `inventory_enabled` accepted; an `httpx` call in `bm/services/agents/heartbeat.py` | local |

### M3 security mutation table (tester; CHK-M3-320 onwards)

Each row is planted in a throwaway copy, must turn the named gate red, and is re-planted against the final tree at the gate (as CHK-M2-320-349-gate).

| CHK | Plant | Red in | Code owned by |
| --- | --- | --- | --- |
| CHK-M3-320 | the agent dependency accepts `bse_` as well as `bsa_` (heartbeat answers 200 to a `bse_`) | G31 | TASK-063 |
| CHK-M3-321 | the agent dependency uses the user-token parser (`bsu_`/`bsk_` accepted on agent routes) | G31 | TASK-063 |
| CHK-M3-322 | `POST /agent/enroll` accepts a `bsa_` token | G31 | TASK-067 |
| CHK-M3-323 | the M2 prefix-kind check removed, with real agent rows present (`bsa_` accepted on user routes) | G25 | M2 TASK-037 |
| CHK-M3-324 | enrolment stores the raw `bsa_` token in `agent.token_hash` | G31 (at-rest scan) | TASK-067 |
| CHK-M3-325 | the raw `bse_` token stored in `enrollment_token.token_hash` | G31 | TASK-066 |
| CHK-M3-326 | approve guarded by `require_role("admin")` instead of the TOTP-session dependency (admin `bsk_` approves) | G31 | TASK-070 |
| CHK-M3-327 | the TOTP-verified check skipped on approve and reject (unverified session decides) | G31 | TASK-070 |
| CHK-M3-328 | `sink_gate=False` on approve, reject, revoke, enrolment tokens or `PATCH /settings` | G31 | TASK-062, 066, 070, 077 |
| CHK-M3-329 | an admin `bsk_` token creates an enrolment token | G31 | TASK-066 |
| CHK-M3-330 | an admin `bsk_` token revokes an agent | G31 | TASK-077 |
| CHK-M3-331 | an admin `bsk_` token patches settings | G31 | TASK-062 |
| CHK-M3-332 | `AND uses < max_uses` removed from the atomic use (6 of 20 concurrent enrolments on a 5-use token succeed) | G31 | TASK-052 |
| CHK-M3-333 | the expiry condition removed (an expired `bse_` enrols) | G31 | TASK-052 |
| CHK-M3-334 | the revocation condition removed (a revoked `bse_` enrols) | G31 | TASK-052 |
| CHK-M3-335 | the `allowed_cidrs` condition removed | G31 | TASK-052 |
| CHK-M3-336 | `auto_approve` defaults to true in the create model | G31 | TASK-066 |
| CHK-M3-337 | a re-enrolment with an `auto_approve` token is approved at once | G31 | TASK-067 |
| CHK-M3-338 | the `{id}` match removed (agent A's token works on agent B's path) | G31 | TASK-063 |
| CHK-M3-339 | an `awaiting_approval` agent's token gets 200 on `GET /jobs` | G31 | TASK-059 |
| CHK-M3-340 | a machine-id mismatch answers 401 without revoking the token | G31 | TASK-059 |
| CHK-M3-341 | a missing `X-Bitscan-Machine-Id` header is accepted (#63) | G31 | TASK-059, TASK-063 |
| CHK-M3-342 | the expiry check moved one day late (an expired `bsa_` works, rotate included) | G31 | TASK-059 |
| CHK-M3-343 | the rotation window check removed (rotate on day 1 succeeds) | G31 | TASK-075 |
| CHK-M3-344 | old-token use after the overlap accepted without revoking both (#62) | G31 | TASK-059 |
| CHK-M3-345 | the heartbeat response gains a `jobs` key | G30, G34 | TASK-048, TASK-072 |
| CHK-M3-346 | the job payload gains `operator`, or `eval_spec` is copied into a pull response | G30, G31 | TASK-048, TASK-073 |
| CHK-M3-347 | the agent filter removed from the pull (another agent's job returned) | G31 | TASK-054 |
| CHK-M3-348 | the pull limit raised to 11 | G31 | TASK-054 |
| CHK-M3-349 | the `pickup_by` or `state = 'queued'` condition removed from the pull | G31 | TASK-054 |
| CHK-M3-350 | the row lock and the state re-check removed (two concurrent pulls dispatch one job twice) | G31 | TASK-054 |
| CHK-M3-351 | the M3 kind filter removed (a compliance row planted as owner is returned) | G31 | TASK-054 |
| CHK-M3-352 | a setting `inventory_enabled` honoured by the inventory run, or accepted by `PATCH /settings` | G34 | TASK-055, TASK-061 |
| CHK-M3-353 | a route that queues an ad-hoc command (`POST /api/v1/agents/{id}/run`) | G34 | any route task |
| CHK-M3-354 | the `inventory_interval_s` range check removed from the service (3,599 reaches the database CHECK and answers 500, not 400) | G31 | TASK-055 |
| CHK-M3-355 | the decoder decompresses the whole body without a cap | G32 | TASK-060 |
| CHK-M3-356 | the 50,000-row check removed | G32 | TASK-060 |
| CHK-M3-357 | the agent's `list_sha256` trusted instead of recomputed (#33) | G32 | TASK-060 |
| CHK-M3-358 | the 10-minute unscheduled-upload limit removed | G31 | TASK-057, TASK-074 |
| CHK-M3-359 | the results route answers 200 or stores a row in M3 | G31 | TASK-073 |
| CHK-M3-360 | template matching removed from the cap registry (a valid 2 MiB inventory upload gets 413) | G31 | TASK-049 |
| CHK-M3-361 | the after-auth mode removed (an over-cap inventory upload with a valid token writes no audit entry and leaves its job `dispatched`) | G31 | TASK-049, TASK-074 |
| CHK-M3-362 | failed `bsa_` checks not counted toward the per-IP limit | G31 | TASK-063 |
| CHK-M3-363 | a valid `bsa_` from an IP over the failed-check limit gets 429 | G31 | TASK-063 |
| CHK-M3-364 | the 30-per-minute agent limit removed | G31 | TASK-057, TASK-063 |
| CHK-M3-365 | the 10-per-minute enrol limit removed | G31 | TASK-057, TASK-067 |
| CHK-M3-366 | a `bsa_` or `bse_` token, or a results stdout, written to a log record | G28 | TASK-063, TASK-073 |
| CHK-M3-367 | the clock-skew alert removed | G31 | TASK-072 |
| CHK-M3-368 | a `runner_helpers` change stored without audit entry or alert | G31 | TASK-072 |
| CHK-M3-369 | the sweep never decommissions, or decommissions without revoking the token | G33 | TASK-065 |
| CHK-M3-370 | rejecting a new enrolment leaves the agent `awaiting_approval` | G31 | TASK-070 |
| CHK-M3-371 | approve allowed for an operator session | G31 | TASK-070 |
| CHK-M3-372 | a viewer allowed on `PUT /agents/{id}/tags` | G31 | TASK-077 |
| CHK-M3-373 | the sweep creates a retry row for a failed inventory job | G33 | TASK-065 |
| CHK-M3-374 | an HTTP client call added in a service (a manager-to-agent connection) | G34 | any service task |

### Open items for M3

All are in `work/open-questions.md`. "Needed by" is the start of the wave whose task cannot be finished, or whose acceptance cannot be fixed, without the answer. Every item has a recommended answer there; the lead may approve them in a batch.

| Item | Blocks | Needed by |
| --- | --- | --- |
| #60 (new): agent wire-contract field constraints | TASK-048, TP-M3-01 (the frozen contract and the shared fixtures) | W1 |
| #59 (new): agent-route statuses and `type` values outside the TS §6.5 list; token-check order | TASK-048 (constants), TASK-059, TASK-063, TASK-067 | W1 |
| #71 (new): M3 audit actions, actor, alert kinds | TASK-056 and every auditing task | W1 |
| #65 (new): threshold-alert windows, denominators and repeats | TASK-056 (window shapes, W1); TASK-064, 068, 072, 073 | W1 |
| PD-21 (new): `jsonschema` and `hypothesis` in the dev lock | TASK-058, TP-M3-02, TP-M3-14 | W1 |
| PD-22 (new): where the shared fixtures live | TP-M3-01 | W1 |
| PD-24 (new): one route task per wave, or several | wave plan W6 to W13 | W2 |
| #33 (re-checked): recompute `list_sha256`; sort order; mismatch status | TASK-060 | W2 |
| #72 (new): inventory upload details, including the late-`job_id` marker | TASK-057 (window rule, W1, adjustable), TASK-060 (W2), TASK-074 | W2 |
| #36 (re-checked) and #67 (new): first inventory job; cadence across restarts and interval changes | TASK-061 | W2 |
| #68 (new): M3 user-route bodies | TASK-062 (settings shape, W2); TASK-066 (W3); TASK-070, 076, 077, 078 | W2 |
| PD-23 (new): redaction setting in M3 or M10 | TASK-069 | W4 |
| #62 (new): rotation overlap, reuse and refusal statuses | TASK-059 (W2), TASK-075 | W2 |
| #63 (new): missing machine-id header; mismatch on a pending re-enrolment token | TASK-059 | W2 |
| #25 (re-checked): heartbeat fields; `agent_ip_seen` writer; age of a never-seen agent | TASK-059, TASK-063 (IP recording, W2 to W3), TASK-065 (W3), TASK-072 | W2 |
| #73 (new): heartbeat status, decommission base, revoke and status audit | TASK-065 (W3), TASK-072 | W3 |
| #66 (new): queue-age alert versus offline hosts | TASK-068 | W4 |
| #61 (new): enrolments-per-hour counting | TASK-067 | W4 |
| #64 (new): re-enrolment details | TASK-067 (W4), TASK-070 | W4 |
| #26 (re-checked): rejected re-enrolment | TASK-059 (outcome, W2), TASK-070 | W2 |
| #54 (c) (answered in M2: more than 20 409s from one agent in 10 minutes) | TASK-073 (repeat rule is #65 (f)) | W7 |
| #69 (new): snapshot shape, `collected_at`, the route that shows it | TASK-064 (W3), TASK-076 | W3 |
| #70 (new; the open half of #5): metrics route path, auth, role | TASK-079, TASK-081 | W13 |
| #37 (re-checked): first `bse_` token through the API before the UI | TASK-080 (README), TP-M3-35 chain | W14 |
| #4 | none in M3: the manager's `job_pull_seconds` and `max_parallel_plugins` ranges already equal the agent's clamps (TS §3.3 L206); the rest is M4 | M4 |
| CLAUDE.md N / N−1 marker | none in M3; the contract frozen here is the first agent contract, and N−1 support starts with the first supported agent release | before the first supported release |
| PD-3 | second approval of the twelve agent, enrolment and token tasks | each wave's REVIEW |

**W1 rulings recorded in `work/decisions.md` (2026-10-23, "M3 W1 rulings"),** which later tasks must follow:
- **TASK-048 revision 1 (agent contract):**
  - nullable fields are required keys whose value may be null; a missing key is 400;
  - every agent-sent string refuses U+0000 and lone surrogates with 400 `invalid_request`, including keys and values inside `os_info.raw`;
  - the one exception is Results `stdout` and `stderr`, whose NUL rule is decided in M9 when results are stored;
  - `JobsResponse.jobs` has `maxItems` 10 (TS §6.1 L1064, §3.3 L214);
  - UUIDs are accepted only in the hyphenated RFC 9562 form and are returned lowercase.
- **TASK-051 (and TASK-065) age base:** the `offline_sweep` age base is GREATEST(`last_heartbeat_at`, `enrolled_at`, latest approved `decided_at`), not the literal COALESCE of #25 (c). An approved re-enrolment of a host with an old heartbeat is therefore not decommissioned by the next sweep. It is identical to #25 (c) for agents that never heartbeat.
- **TASK-069:** the RE2 compile of redaction patterns already lives in `bm/services/settings/store.py`. TASK-069 must not add a second one; it keeps the `redaction_default_removed` alert.

### Coverage matrix (M3)

| Spec section | Covered by | Status in M3 |
| --- | --- | --- |
| TS §2.2 Pull, not push (L111); idempotent jobs (L112) | REQ-072, REQ-088 / TASK-054, TASK-073, TP-M3-35 | Pull-only covered. "First result per plugin wins" needs result intake: **M9/M11** |
| TS §2.3 tokens and flows A, B, C, E (L118–L148) | REQ-062 to REQ-071, REQ-077 | Covered. Flows 1 to 7 (compliance scan) are M7 to M11 |
| TS §3.1 State and logs (L162–L163) | REQ-087 (manager side) | Agent side is **M4** |
| TS §3.2 steps 1–9, transport (L181–L194) | REQ-063, REQ-064, REQ-067 to REQ-069, REQ-071 | Covered; steps 4, 8, 9 and the transport paragraph are agent behaviour (**M4**), whose manager side (401 types, cloned-image listing) is covered |
| TS §3.3 loops, pull-only rules, idle, status, decommission (L198–L220) | REQ-070, REQ-072, REQ-078, REQ-088 | Covered for the manager. Idle cost and agent-side job checks are **M4**. L222 (start notice, deadline) is **M9** |
| TS §3.3 responses to posts, network failure (L224–L226) | REQ-073, REQ-076 (manager statuses) | Agent behaviour is **M4** |
| TS §3.4 inventory (L230–L244) | REQ-074 to REQ-079 | Covered, except L243 (pruning unreferenced `package` rows): **M11** retention |
| TS §3.5 job execution (L248–L253) | REQ-060 (Job and Results schemas only) | Execution is **M10**; job building **M9** |
| TS §3.6 `agent.yaml` | none | **M4** (#4); no manager effect |
| TS §3.7 helper reporting (L484) | REQ-070 (3) | Covered; everything else in §3.7 is **M4/M10** |
| TS §4 compliance engine | none | **M7 to M11** |
| TS §5.2 fleet and inventory tables, `system_schedule`, `setting`, `scan_job` (inventory) | REQ-064 to REQ-083 | Used as written, no migration |
| TS §5.3 retention (L1047) | none | **M11** (inventory jobs 30 days, snapshots 180 days, decided requests 90 days, packages daily). The default-partition alert is REQ-079 (4) |
| TS §5.3 audit integrity (L1051) | REQ-067, REQ-069, REQ-082, REQ-083 (sink gate on the M3 TOTP routes) | Covered by the M2 machinery |
| TS §6 intro, route groups (L1056) | REQ-062 | Covered |
| TS §6.1 agent endpoints (L1060–L1072) | REQ-062 to REQ-076 | All six routes covered; result acceptance rules (L1071) other than "anything else returns 409" are **M9/M11** |
| TS §6.2 `/agents`, `/agents/{id}`, `/agents/{id}/packages`, tags, revoke (L1108–L1113) | REQ-081, REQ-082 | Covered. **Uncovered:** `GET /agents/{id}/scans` (L1111): **M9**, no scans exist and its item is the `/scans` item |
| TS §6.2 `/enrollment-requests`, `/enrollment-tokens` (L1114–L1116) | REQ-067, REQ-069 | Covered |
| TS §6.2 `/settings`, `/audit-log` (L1126–L1127) | REQ-083 to REQ-085 | Covered (REQ-084 per PD-23) |
| TS §6.2 L1129 (no inventory switch, no ad-hoc command) | REQ-088 | Covered |
| TS §6.2 policies, tasks, imports, packages, scans, schedules | none | **M5** (packages), **M7** (policies, tasks, imports), **M9** (scans, schedules) |
| TS §6.3 rate limits (L1136) | REQ-065, REQ-076 | Agent and enrol limits covered (user limits M2) |
| TS §6.3 size limits (L1138) | REQ-066, REQ-074 | Inventory and result caps covered; `.bit` is **M7** |
| TS §6.3 errors, pagination, timestamps, ids, headers | REQ-060, REQ-081, REQ-085 (M2 machinery) | Covered |
| TS §6.3 CSV, `Idempotency-Key`, multipart | none | **M5**, **M9**, **M7** |
| TS §6.5 wire contract (L1159–L1190) | REQ-060, REQ-061 | Covered and frozen, including the compliance Job and Results |
| TS §7 package search | none | **M5** (REQ-081's per-host package list is the only package read in M3) |
| TS §8.1 rogue or hijacked agent; oversized input; flooding from one agent; SQL injection | REQ-064 to REQ-076 | Covered for M3 code |
| TS §8.2 two approvals (agent routes) | owner notes | Twelve tasks marked |
| TS §8.3 Unit (redaction fixtures) | none | **M10** |
| TS §8.3 Property/fuzz, inventory decoder | REQ-074 / G32 | Covered |
| TS §8.3 Contract | REQ-060, REQ-061 / G30 | Manager side covered; Go side **M4** |
| TS §8.3 Integration (every endpoint) | TP-M3-16 to TP-M3-33 | Covered for every M3 endpoint |
| TS §8.3 Security (tokens on the wrong route group; API tokens refused for sensitive actions) | REQ-062, REQ-067, REQ-069, REQ-082, REQ-083 / G31 | Covered for M3 routes; job, runner and certificate items are **M4/M10** |
| TS §8.3 End-to-end, Load | TP-M3-35 (API chain only) | VMs and 10,000-agent load are **M6** |
| TS §8.4 logs | REQ-087 | Covered |
| TS §8.4 metrics | REQ-086 | Agents by status, heartbeat latency, jobs queued and expired covered. **Uncovered:** import failures (**M7**), plugin ERROR rate (**M11**) |
| TS §8.4 immediate alerts | REQ-067, REQ-069, REQ-064, REQ-070, REQ-071, REQ-079, REQ-083, REQ-084 | M3 events covered. **Uncovered:** policy imported, rebuilt, deleted, re-enabled (**M7**); all-hosts scan with an API token (**M9**) |
| TS §8.4 threshold alerts | REQ-065, REQ-068, REQ-070, REQ-073, REQ-075, REQ-079 | M3 thresholds covered, clock skew included (the M2 carry-over). **Uncovered:** `.bit` import rejected, catalog integrity (**M7**) |
| TS §8.4 health | M2 REQ-056 | Unchanged |
| TS §8.6 runtime settings (L1317–L1339) | REQ-083, REQ-084 | Covered |
| TS §8.7 | REQ-080 (`serve` runs the scheduler) | No other change |
| CLAUDE.md out of scope; decisions "Not to be added" | REQ-088 | Nothing planned: no `bse_` CLI, no "collect now" or deregister route, no signing, no client certificates |

## M4 Go agent and pre-release `.deb`

Scope: REQ-091 to REQ-112 in `work/requirements.md`. Built against the frozen agent contract: TS §6.5, the agent operations and components of `manager/openapi.json`, and the shared fixtures in `manager/tests/contract/fixtures/` (manifest `schema_gaps`: the Go test asserts nothing for `lone surrogate` and `nan_inf` entries, decisions 2026-10-23). In this section `ag/` means `agent/` and `bm/` means `manager/bitscan_manager/`.

**amd64 only (decisions 2026-10-24, "arm64 dropped from v1").** No M4 task builds, packages, tests or emulates arm64; TASK-097 removes the existing arm64 steps from `.github/workflows/agent.yml`.

**No migration and no manager behaviour change in M4.** The only manager task is TASK-085 (M3 carry-overs: a refactor with unchanged behaviour, and two README sentences).

Rules every M4 task follows (user rules of 2026-10-24 and the agent rules):
- **Tests per task:** the tester runs only the affected tests (the changed Go packages and what imports them, or the affected Python suites); the whole `go test ./...`, the package tests and the full manager suite run at the end of each wave, at the M4 gate and in CI.
- **Linux only:** Go tests run on Linux (WSL Ubuntu 24.04 locally, CI per PD-27); Python tests run on Linux with `CI=true`. Lint and format may still run on Windows, but G8 counts only on Linux (the `_linux.go` files).
- **Rigor by area:** full rigor (every mutation row, boundary and race cases, a second review round if needed) for every agent task and for the maintainer scripts (TASK-100); one review round for packaging metadata, CI, the runbook and TASK-085.
- **Per-wave user approval:** the user's TS §8.2 second approval is asked once per wave, for every two-approval task in it.
- Agent code passes a cancellable `context.Context` through every loop and call, wraps errors with `%w`, uses only the clock it is given (tests use a fake clock), never logs a token, a request body or plugin output, opens no listening socket and runs no command except the #35 list.
- Implementers check `work/reviews/builder-checklist.md` before every hand-off.

### M4 tasks

| TASK | Title | REQ links | Area | Owner | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-085 | M3 carry-overs: `upload.py` takes its stores through a `stores(tx)` factory with `Protocol` types (no behaviour change); README sentences on the re-linked old token (401 `unauthorized`) and an operator calling approve (403 `totp_session_required`) | REQ-112 | manager | impl-manager | `bm/services/inventory/upload.py`, `README.md` | TASK-084 and the M3 gate verdict | 90 | On Linux the TASK-074 inventory route suites pass unchanged, new unit tests with fake stores cover every `upload.py` branch without a database, `manager/openapi.json` is byte-identical, and both README sentences match the M3 route tests. |
| TASK-086 | Agent wire types for the six routes, with strict response decoding (unknown and missing keys refused, bounds, hyphenated UUIDs, RFC 3339 with fractions) and problem-body parsing (plan: `work/plans/TASK-086.md`) | REQ-091 | agent | impl-agent | `ag/internal/agent/wire/wire.go`, `ag/internal/agent/wire/decode.go` | none; #59, #60 (as agreed) | 190 | The Go contract test decodes every valid response fixture and re-encodes every valid request fixture to equivalent JSON, refuses every invalid fixture except the manifest's `schema_gap` entries, and every encoded request validates against its `manager/openapi.json` component schema; no contract field uses `omitempty`. |
| TASK-087 | `agent.yaml` loader with the #4 rules and strict keys; first Go dependencies pinned in `go.sum` (PD-25) | REQ-092, REQ-105 | agent | impl-agent | `ag/internal/agent/config/config.go`, `ag/go.mod`, `ag/go.sum` | none; #4, PD-25 | 140 | The TS §3.6 example loads exactly; an `http://` URL, a missing URL, an unknown key such as `inventory: false`, out-of-range values and malformed YAML are each refused with one line naming the key; `go mod verify` passes and fails on an altered `go.sum` hash. |
| TASK-088 | State directory: atomic write (temporary file, fsync, rename) of `agent_id`, `token` and the token times; delete `enroll.token`; seen job ids kept 7 days | REQ-093 | agent | impl-agent | `ag/internal/agent/state/state.go`, `ag/internal/agent/state/seen.go` | none | 170 | In a temporary directory, writes give mode 0600 for `token` and 0644 for `agent_id`, a crash injected between any two write steps leaves the old or the new complete state, seen ids survive a reload and expire after 7 days on a fake clock, and nothing is written outside the directory. |
| TASK-089 | TLS configuration: TLS 1.2 minimum, system store or `ca_file`, host-name check, optional SPKI pin of the leaf (#79), no client certificate (plan: `work/plans/TASK-093.md`) | REQ-094 | agent | impl-agent | `ag/internal/agent/transport/tls.go` | none; #79 | 90 | Against test servers: an untrusted CA, a wrong host name, an expired certificate, a TLS 1.1-only server and a wrong pin are refused, the right pin and an unpinned trusted chain succeed, and the client never presents a certificate. |
| TASK-090 | Back-off (10 s doubling to 5 min, jitter, reset on success) and jittered intervals (300 s ± 30 s, `job_pull_seconds` ± 30 s with clamping) on an injected clock | REQ-095, REQ-097, REQ-098 | agent | impl-agent | `ag/internal/agent/schedule/backoff.go`, `ag/internal/agent/schedule/interval.go` | none | 80 | With a fake clock and seeded randomness, successive failures give 10, 20, 40 … s capped at 300 s within the jitter bound, a success resets to 10 s, 1,000 heartbeat intervals all fall in 270–330 s, and pull intervals clamp to 60–3,600 s ± 30 s. |
| TASK-091 | dpkg watcher: inotify on `/var/lib/dpkg/` for `IN_MOVED_TO` and `IN_CLOSE_WRITE` on `status` (stdlib `syscall`), debounce per #80, injectable path and clock (plan: `work/plans/TASK-104.md`) | REQ-102 | agent | impl-agent | `ag/internal/inventory/watch.go`, `ag/internal/inventory/watch_linux.go` | none; #80 | 150 | On Linux in a temporary directory: a rename onto `status` and a close-after-write each signal once after the #80 delay, 50 changes in 10 minutes signal once plus once after the hold-off, signals are never closer than 10 minutes, other file names signal nothing, and a failed watch returns an error the caller can log. |
| TASK-092 | D-Bus policy verbatim; package metadata (`control`, `rules` with the `dh_installsystemd` flags, `changelog` 0.x, `copyright`) (plan: `work/plans/TASK-100.md`) | REQ-106 | deploy | impl-deploy | `deploy/dbus/bitscan-runner.conf`, `deploy/debian/control`, `deploy/debian/rules`, `deploy/debian/changelog`, `deploy/debian/copyright` | none; PD-26 | 120 | The policy compares byte-identical to TS §3.7 L412–L431 (extended verbatim check), and `rules` passes `--no-enable` for `bitscan-runner.service` and `--no-enable --no-start` for both capread units. |
| TASK-093 | HTTP client: request builder (bearer and `X-Bitscan-Machine-Id` on every call, `bse_` on enrol only), time limits, response size cap, no redirects or proxy (#75), problem parsing, and the TS §3.3 L224 response classes (plan: `work/plans/TASK-093.md`) | REQ-094, REQ-095 | agent | impl-agent | `ag/internal/agent/transport/client.go`, `ag/internal/agent/transport/classify.go` | TASK-086, TASK-089; #59, #75 | 170 | Against a fake manager, every request carries exactly the required headers, a 3xx is not followed, an oversized body is refused early, and a table over every contract status and `type` gives exactly the classes drop, stop, wait or retry. |
| TASK-094 | `os_info` collector and the fixed command runner: `/etc/os-release`, `/proc/meminfo`, `/proc/uptime`, `uname`, `nproc`, `hostnamectl`, `ip -j addr`, `dpkg-query` from absolute paths, no shell, minimal environment, time limits; derivation and `raw` per #77 (plan: `work/plans/TASK-104.md`) | REQ-100 | agent | impl-agent | `ag/internal/inventory/osinfo.go`, `ag/internal/inventory/command.go` | TASK-086; #35, #77 | 190 | On Ubuntu 22.04, 24.04 and Debian 12 the result validates against `InventoryBody.os_info` and matches the files and commands read independently as #77 defines; a hanging command is killed at its limit and the collection still returns; a static test finds only the #35 commands and no shell. |
| TASK-095 | dpkg list parser (the TS §3.4 format), `list_sha256` (lines sorted by UTF-8 bytes) and the gzip inventory body | REQ-100, REQ-101 | agent | impl-agent | `ag/internal/inventory/dpkg.go`, `ag/internal/inventory/body.go` | TASK-086; #72, #77 | 150 | Parsing real `dpkg-query` output from the three distributions gives one item per line with empty `Source` as null and empty `Installed-Size` as null; `list_sha256` equals the manager decoder's value on the shared inventory fixtures; the gzip body decompresses to JSON that validates against `InventoryBody`. |
| TASK-096 | Debconf templates (`password` type for the token) and `config` script; `bitscan-agent.install`; `source/format` (plan: `work/plans/TASK-100.md`) | REQ-107, REQ-106 | deploy | impl-deploy | `deploy/debian/templates`, `deploy/debian/config`, `deploy/debian/bitscan-agent.install`, `deploy/debian/source/format` | TASK-092 | 90 | A preseeded non-interactive configure sets all four questions, `bitscan/enrol_token` is stored only in `passwords.dat`, and the install file maps the three binaries to `/usr/sbin` and the policy to `/etc/dbus-1/system.d/`. |
| TASK-097 | Agent CI: `go test` on linux/amd64 (PD-27), the Go contract test, the stub step limited to runner and capread; remove the existing arm64 build loop (`agent.yml` L58) and the arm64 half of the cgo listing (L107), so nothing builds or tests arm64 (decisions 2026-10-24, "arm64 dropped from v1") | REQ-111, REQ-105 | deploy | impl-deploy | `.github/workflows/agent.yml` | TASK-087; PD-27 | 80 | On a PR, `go test ./...` runs on linux/amd64, the contract test reads the shared fixtures, `bitscan-runner` and `bitscan-capread` still pass the stub check, `grep -n arm64 .github/workflows/agent.yml` finds nothing, and each planted failure (a failing test, an altered `go.sum`) turns the job red. |
| TASK-098 | Enrolment: read `enroll.token`, collect the enrol fields, call enrol, persist, delete `enroll.token`; start-up and re-enrolment rules (#81); lost response (#76) (plan: `work/plans/TASK-099.md`) | REQ-096 | agent | impl-agent | `ag/internal/agent/enrol/enrol.go` | TASK-086, TASK-088, TASK-093, TASK-094; #76, #81 | 150 | Against a fake manager: `enrolled` and `awaiting_approval` answers persist the files and remove `enroll.token`; a 401 keeps `enroll.token`, writes nothing and reports "stop"; a bad `/etc/machine-id` and a missing token and enrol token are refused; the #76 and #81 cases behave as answered. |
| TASK-099 | Token holder (one current token for every loop) and rotation: window from the token's own TTL, one call at a time, persist before use, lost-response retry, 429, 403 and 401 handling (plan: `work/plans/TASK-099.md`) | REQ-099 | agent | impl-agent | `ag/internal/agent/token/holder.go`, `ag/internal/agent/token/rotate.go` | TASK-086, TASK-088, TASK-093; #62 | 180 | Fake clock and fake manager: no rotate before day 335 of a 365-day token and one on the first check after; a dropped response is retried with the old token; a crash before the state write keeps the old token; two concurrent triggers make one call (race test with `-race` where available); 429 and 403 wait as REQ-099 says; 401 reports "stop". |
| TASK-100 | Maintainer scripts: `postinst` (users, `agent.yaml`, `enroll.token`, `install.env`, debconf token cleared, enable and start, upgrade path, #81 re-enrolment) and `postrm` (remove; purge per #82), idempotent (plan: `work/plans/TASK-100.md`) | REQ-108, REQ-107 | deploy | impl-deploy | `deploy/debian/postinst`, `deploy/debian/postrm` | TASK-092, TASK-096; #81, #82 | 170 | On Ubuntu 24.04 with systemd: install, reinstall, upgrade and purge each run twice without error; modes and owners are exactly REQ-108 (1); a missing URL or token fails with one clear line and leaves the package unconfigured; the debconf token is empty afterwards; purge leaves a planted `/etc/bitscan/manager.env`. |
| TASK-101 | Agent run state (stop on 401, `last_error`, intervals from the heartbeat, current job) and the heartbeat loop with #78 fields and #30 helper detection (plan: `work/plans/TASK-101.md`) | REQ-097, REQ-095, REQ-103 | agent | impl-agent | `ag/internal/agent/loops/run.go`, `ag/internal/agent/loops/heartbeat.go` | TASK-088, TASK-090, TASK-093, TASK-099; #30, #78, #81 | 190 | Fake clock and fake manager: heartbeats every 270–330 s with a body matching #78, `runner_helpers` follows the presence of a planted `capread.sock`, a new `job_pull_seconds` changes the pull interval, a 401 stops every loop within one second, and a heartbeat response never triggers any other call. |
| TASK-102 | `.deb` build script: staging tree from `deploy/`, prebuilt static binaries, fixed version, `SOURCE_DATE_EPOCH`, reproducible Go flags, SBOM and SHA-256 file (plan: `work/plans/TASK-100.md`) | REQ-106, REQ-109 | deploy | impl-deploy | `deploy/debian/build-deb.sh` | TASK-092, TASK-096, TASK-100; PD-26 | 120 | Two amd64 runs in fresh environments give identical SHA-256 values for the three binaries and the `.deb`, no arm64 artifact is built, `dpkg-deb -c` lists exactly the REQ-106 files, `lintian` is clean, and the SBOM lists every module of `go version -m`. |
| TASK-103 | Job pull, job checks (own `agent_id`, `pickup_by` in the future and ≤ 25 h, unseen in 7 days) and dispatch: inventory at once, compliance per #74 (plan: `work/plans/TASK-101.md`) | REQ-098, REQ-104 | agent | impl-agent | `ag/internal/agent/loops/pull.go`, `ag/internal/agent/loops/jobs.go` | TASK-088, TASK-090, TASK-101; #74 | 190 | Fake clock and fake manager: pulls every `job_pull_seconds` ± 30 s with nothing else on an empty answer; a foreign, an expired, a more-than-25-h and a replayed job (also after a restart) are refused and not run; an inventory job is handed to the inventory runner once; a compliance job produces exactly the #74 calls and no process execution. |
| TASK-104 | Inventory jobs and watcher uploads: collect, build the body, upload with or without `job_id`, retry 429, 5xx and network errors with back-off, drop and report 409, 413 and 422, at most one unscheduled upload per 10 minutes (plan: `work/plans/TASK-104.md`) | REQ-101, REQ-102, REQ-100 | agent | impl-agent | `ag/internal/agent/loops/inventory.go` | TASK-091, TASK-094, TASK-095, TASK-101; #72, #80 | 170 | Fake clock and fake manager: a job upload carries `?job_id=` and gzip, a 503 is retried and then succeeds, a 422 becomes `last_error` with no retry, watcher signals lead to unscheduled uploads never closer than 10 minutes, and a 429 is retried with back-off. |
| TASK-105 | Package CI (amd64 only): build the `.deb`, `lintian`, install, reinstall, upgrade and purge tests on the PD-27 platforms, the reproducibility double build, the SBOM and SHA-256 artifacts, the D-Bus verbatim and `systemd-analyze verify` checks | REQ-111, REQ-109, REQ-106 | deploy | impl-deploy | `.github/workflows/package.yml` | TASK-102; PD-26, PD-27 | 150 | On a PR, every listed step runs and each planted failure (a lintian error, a timestamp in the build, an altered unit, a failing install test, a module missing from the SBOM) turns the job red. |
| TASK-106 | `bitscan-agent` main: load config and state, enrol when #81 says, start the loops, `SIGTERM` handling, stderr logging without secrets, version from the build | REQ-103, REQ-096 | agent | impl-agent | `ag/cmd/bitscan-agent/main.go` | TASK-087, TASK-098, TASK-101, TASK-103, TASK-104 | 140 | Against a fake manager the binary enrols, heartbeats, pulls and uploads; `SIGTERM` during each exits 0 within 5 s with no partial state file; a canary sweep finds no token in stdout or stderr; under the verbatim unit (WSL systemd) the same run succeeds and writes only the state directory. |
| TASK-107 | Agent install runbook (TS §3.1 steps, NTP, cloned images, pinning and private CA, re-enrolment per #81, uninstall and purge, 0.x status) | REQ-110 | deploy | impl-deploy | `deploy/runbooks/agent-install.md` | TASK-100, TASK-106; #81 | 150 (docs) | The tester follows every step on a clean Ubuntu 24.04 against the real manager and each behaves as written; the runbook holds no real secret and no process notes. |

Totals: 22 REQ (REQ-091 to REQ-112), 23 TASK (TASK-085 to TASK-107), 25 test-plan items (TP-M4-00 to TP-M4-24), 6 waves plus the gate. Every task is within 5 files and about 200 hand-written lines; test files are not counted.

REQ to TASK: REQ-091 TASK-086; REQ-092 TASK-087; REQ-093 TASK-088; REQ-094 TASK-089, TASK-093; REQ-095 TASK-090, TASK-093, TASK-101; REQ-096 TASK-098, TASK-106; REQ-097 TASK-090, TASK-101; REQ-098 TASK-090, TASK-103; REQ-099 TASK-099; REQ-100 TASK-094, TASK-095, TASK-104; REQ-101 TASK-095, TASK-104; REQ-102 TASK-091, TASK-104; REQ-103 TASK-101, TASK-106; REQ-104 TASK-103; REQ-105 TASK-087, TASK-097; REQ-106 TASK-092, TASK-096, TASK-102, TASK-105; REQ-107 TASK-096, TASK-100; REQ-108 TASK-100; REQ-109 TASK-102, TASK-105; REQ-110 TASK-107; REQ-111 TASK-097, TASK-105; REQ-112 TASK-085. Every M4 REQ has at least one TASK, and every TASK has at least one REQ.

### M4 owner and review notes

- **Two approvals (TS §8.2 L1268, "agent"):** every agent task: TASK-086, 087, 088, 089, 090, 091, 093, 094, 095, 098, 099, 101, 103, 104, 106. Recommended also for TASK-100 (maintainer scripts run as root on every host and handle the `bse_` token). TASK-085 is not on the list unless its refactor changes behaviour (as the TASK-084 ruling). The second approval is asked once per wave (user rule 4).
- **Owners:** impl-agent (a new `implementer` instance for `agent/`) for the agent tasks; impl-deploy for `deploy/` and `.github/workflows/`; impl-manager for TASK-085. The tester owns every `*_test.go`, `deploy/tests/`, `e2e/` and `tests/m4/`.
- **Parallel with M3's closing:** every W1 task except TASK-085 touches only `agent/` or `deploy/`, so W1 (TASK-086 to TASK-092) and the tester's TP-M4-00 and TP-M4-01 can start now, while the M3 gate and TASK-084 finish. TASK-085 changes approved M3 manager code, so it starts only after the M3 gate verdict (the gate must run on a fixed tree). TASK-097 edits `.github/workflows/agent.yml`, which the M3 PR does not touch; it can also run alongside. Suggested branch: `m4-agent` from the current `m3-agent-api` head, rebased onto main after the M3 merge (agent and deploy files do not conflict with M3).
- Shared files, never in the same wave: `ag/go.mod` and `ag/go.sum` (TASK-087 only; a later task needing a new module asks the lead first, PD-25); `ag/internal/agent/loops/` (TASK-101 creates `run.go`; TASK-103 and TASK-104 add their own files in W5 and only call the interfaces `run.go` defines); `deploy/debian/` files are each owned by one task.
- The runner and capread binaries stay as #74 says; no task changes `ag/cmd/bitscan-runner/` or `ag/cmd/bitscan-capread/` in M4 under the recommended answer.
- Planted violations are made in a throwaway copy or branch, never left in the tree.

### M4 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m4/test-plan.md`, check ids `CHK-M4-###`). Go tests run in WSL (`GOOS=linux`) or CI; package tests need systemd (WSL Ubuntu 24.04 or CI runners); Linux-only tests also run as the non-root WSL user `bstester` where file modes matter.

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M4-00 | Phase test plan and the M4 index row | all M4 | phase start; report at the gate | `tests/m4/test-plan.md`, `tests/test-plan.md` | none |
| TP-M4-01 | Go contract test (G35): the shared fixtures through the Go types and the `openapi.json` schemas; `schema_gap` entries skipped | REQ-091 | TASK-086 TEST; re-run in every agent task that touches `wire` | `ag/internal/agent/wire/contract_test.go` | PD-25 |
| TP-M4-02 | Config loading and refusals | REQ-092 | TASK-087 TEST | `ag/internal/agent/config/config_test.go` | TASK-087 IMPL |
| TP-M4-03 | State writes: modes, crash injection, seen-id expiry | REQ-093 | TASK-088 TEST | `ag/internal/agent/state/state_test.go` | TASK-088 IMPL |
| TP-M4-04 | TLS matrix with a test CA (G36 part) | REQ-094 | TASK-089 TEST | `ag/internal/agent/transport/tls_test.go` | TASK-089 IMPL |
| TP-M4-05 | Back-off and interval bounds | REQ-095, REQ-097, REQ-098 | TASK-090 TEST | `ag/internal/agent/schedule/schedule_test.go` | TASK-090 IMPL |
| TP-M4-06 | Watcher on Linux (rename, close-write, storms, hold-off) | REQ-102 | TASK-091 TEST | `ag/internal/inventory/watch_linux_test.go` | TASK-091 IMPL |
| TP-M4-07 | D-Bus policy verbatim (extend the unit check), `rules` flags | REQ-106 | TASK-092 TEST | `deploy/tests/check_units_verbatim.py` (extend) | TASK-092 IMPL |
| TP-M4-08 | Client headers, redirects, size cap, classification table | REQ-094, REQ-095 | TASK-093 TEST | `ag/internal/agent/transport/client_test.go` | TP-M4-04 |
| TP-M4-09 | `os_info` on Ubuntu 22.04, 24.04 and Debian 12 (containers or runners, PD-27); command-list static check | REQ-100 | TASK-094 TEST | `ag/internal/inventory/osinfo_test.go` | TASK-094 IMPL |
| TP-M4-10 | dpkg parsing on real outputs; `list_sha256` cross-check with the manager decoder | REQ-100, REQ-101 | TASK-095 TEST | `ag/internal/inventory/dpkg_test.go` | TP-M4-01 |
| TP-M4-11 | Debconf preseed and `passwords.dat` | REQ-107 | TASK-096 TEST | `deploy/tests/test_debconf.sh` | TASK-096 IMPL |
| TP-M4-12 | Agent CI plants | REQ-111, REQ-105 | TASK-097 TEST | none in the tree (evidence) | TASK-097 IMPL |
| TP-M4-13 | Enrolment against the fake manager, #76 and #81 cases | REQ-096 | TASK-098 TEST | `ag/internal/agent/enrol/enrol_test.go` | TP-M4-08 |
| TP-M4-14 | Rotation: window, lost response, crash, race | REQ-099 | TASK-099 TEST | `ag/internal/agent/token/rotate_test.go` | TP-M4-08 |
| TP-M4-15 | Maintainer scripts: install, reinstall, upgrade, purge twice each (G38), failure on missing inputs, #82 purge | REQ-108, REQ-107 | TASK-100 TEST | `deploy/tests/test_maintainer_scripts.sh` | TP-M4-11 |
| TP-M4-16 | Heartbeat loop, stop on 401, helper detection | REQ-097, REQ-095 | TASK-101 TEST | `ag/internal/agent/loops/heartbeat_test.go` | TP-M4-14 |
| TP-M4-17 | Reproducibility double build (G39), SBOM (G40), contents, lintian (G37) | REQ-106, REQ-109 | TASK-102 TEST | `deploy/tests/test_build_deb.sh` | TP-M4-15 |
| TP-M4-18 | Pull and job checks (TS §8.3 Security: expired, foreign, replayed jobs; G36), 0.x compliance handling | REQ-098, REQ-104 | TASK-103 TEST | `ag/internal/agent/loops/pull_test.go` | TP-M4-16 |
| TP-M4-19 | Inventory jobs and watcher uploads | REQ-101, REQ-102 | TASK-104 TEST | `ag/internal/agent/loops/inventory_test.go` | TP-M4-16 |
| TP-M4-20 | Package CI plants | REQ-111, REQ-109 | TASK-105 TEST | none in the tree (evidence) | TASK-105 IMPL |
| TP-M4-21 | Binary-level run: `SIGTERM`, canary sweep, under the verbatim unit, no listening socket | REQ-103, REQ-096 | TASK-106 TEST | `ag/cmd/bitscan-agent/main_test.go`, `e2e/agent_unit.sh` | TP-M4-18, TP-M4-19 |
| TP-M4-22 | Runbook walk-through on a clean Ubuntu 24.04 | REQ-110 | TASK-107 TEST | none in the tree (evidence) | TP-M4-21 |
| TP-M4-23 | M4 gate: the installed `.deb` against the real M3 manager in WSL (G41): create a `bse_` token with a TOTP session → install with preseed → enrol held → approve → heartbeat → inventory job → upload → `GET /api/v1/agents/{id}` shows `os_info` and the snapshot → `dpkg` change → unscheduled upload → revoke → 401 stops the loops; the security suite and the mutation table; idle CPU and RSS recorded (no gate) | REQ-091 to REQ-111 | M4 gate | `e2e/agent_manager.sh`, `ag/internal/agent/security_test.go` | all above |
| TP-M4-24 | Manager carry-over: `upload.py` unit tests with fake stores; TASK-074 suites targeted | REQ-112 | TASK-085 TEST | `manager/tests/test_inventory_upload_unit.py` | TASK-085 IMPL |

### M4 waves and dependency spine

Spine: `TASK-086, TASK-089 → TASK-093 → TASK-099 → TASK-101 → TASK-103, TASK-104 → TASK-106 → TASK-107`; `TASK-086 → TASK-094, TASK-095 → TASK-104`; `TASK-088 → TASK-098, TASK-099`; `TASK-093, TASK-094 → TASK-098 → TASK-106`; `TASK-090 → TASK-101`; `TASK-091 → TASK-104`; `TASK-087 → TASK-097`, `TASK-087 → TASK-106`; `TASK-092 → TASK-096 → TASK-100 → TASK-102 → TASK-105`. TASK-085 depends only on the M3 gate. The graph is acyclic.

Interface first: the wire types (TASK-086, checked against the shared fixtures by TP-M4-01), the config (TASK-087), the state store (TASK-088), TLS (TASK-089), the schedules (TASK-090) and the package metadata (TASK-092) land in W1; `run.go` (TASK-101) fixes the loop interfaces before TASK-103 and TASK-104.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) | Alongside M3 closing? |
| --- | --- | --- | --- |
| W1 | TASK-085 (after the M3 gate verdict), 086, 087, 088, 089, 090, 091, 092; tester TP-M4-00, TP-M4-01 | `bm/services/inventory/upload.py`, `README.md` · `ag/internal/agent/wire/{wire,decode}.go` · `ag/internal/agent/config/config.go`, `ag/go.{mod,sum}` · `ag/internal/agent/state/{state,seen}.go` · `ag/internal/agent/transport/tls.go` · `ag/internal/agent/schedule/{backoff,interval}.go` · `ag/internal/inventory/{watch,watch_linux}.go` · `deploy/dbus/bitscan-runner.conf`, `deploy/debian/{control,rules,changelog,copyright}` | yes, except TASK-085 |
| W2 | TASK-093, 094, 095, 096, 097 | `ag/internal/agent/transport/{client,classify}.go` · `ag/internal/inventory/{osinfo,command}.go` · `ag/internal/inventory/{dpkg,body}.go` · `deploy/debian/{templates,config,bitscan-agent.install,source/format}` · `.github/workflows/agent.yml` | yes |
| W3 | TASK-098, 099, 100 | `ag/internal/agent/enrol/enrol.go` · `ag/internal/agent/token/{holder,rotate}.go` · `deploy/debian/{postinst,postrm}` | yes |
| W4 | TASK-101, 102 | `ag/internal/agent/loops/{run,heartbeat}.go` · `deploy/debian/build-deb.sh` | yes |
| W5 | TASK-103, 104, 105 | `ag/internal/agent/loops/{pull,jobs}.go` · `ag/internal/agent/loops/inventory.go` · `.github/workflows/package.yml` | yes |
| W6 | TASK-106, 107; tester TP-M4-23 and the M4 gate | `ag/cmd/bitscan-agent/main.go` · `deploy/runbooks/agent-install.md` | the gate needs the M3 manager as approved (G41 runs against it) |

Tester files follow the TP table and are disjoint from every wave's impl files.

### M4 gate

On a clean tree every command below is green, and each gate turns red on its planted violation. "WSL" is WSL2 Ubuntu 24.04 (systemd on, Docker for the manager's PostgreSQL); "CI" per PD-27. Go gates run on Linux.

| Gate | Command | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G7 | `gofmt -l agent` prints nothing | one misformatted line in `ag/internal/agent/loops/run.go` | WSL; CI |
| G8 | `cd agent && golangci-lint run ./...` plus the nolint grep | `net.Listen` in `ag/internal/agent/loops/run.go`; `InsecureSkipVerify` in `ag/internal/agent/transport/tls.go`; a `//nolint` | WSL; CI |
| G9 | `cd agent && go mod verify` | an altered hash line in `ag/go.sum`; a modified file in the module cache | WSL; CI |
| G10 | `CGO_ENABLED=0` build for linux/amd64, static check, cgo listing (no arm64 build: decisions 2026-10-24) | a non-test file with `import "C"` | CI |
| G11 | `cd agent && go test ./...` on linux/amd64 | any planted test failure | WSL; CI |
| G17 | units and D-Bus policy verbatim check, then `systemd-analyze verify deploy/systemd/*` | one character changed in the D-Bus policy; `ProtectHome=yes` removed from the agent unit | CI |
| G35 | `go test ./internal/agent/wire/ -run Contract` | `omitempty` on `current_job_id`; strict decoding off; a fixture field renamed in `wire.go` | WSL; CI |
| G36 | `go test ./internal/agent/... -run 'Security|TLS|Job'` (TS §8.3 Security, agent part) | the mutation-table rows marked G36 | WSL; CI |
| G37 | `lintian` on the amd64 `.deb`: no error or warning | a unit file at mode 0755; a missing `copyright` | CI |
| G38 | `deploy/tests/test_maintainer_scripts.sh` (install, reinstall, upgrade, purge, twice each) | `set -e` removed and a failing step ignored; purge of all of `/etc/bitscan` (#82) | WSL; CI |
| G39 | two clean amd64 builds, `sha256sum` of the three binaries and the `.deb` identical | a build timestamp in the version string; an absolute path in a binary (`-trimpath` removed) | CI |
| G40 | SBOM lists every module of `go version -m` for each binary | a module dropped from the SBOM step | CI |
| G41 | `e2e/agent_manager.sh`: the `.deb` against the real M3 manager in WSL (TP-M4-23) | the agent sending `list_sha256` unsorted (the manager answers 422 and the chain stops) | WSL |
| G1–G6, G18 | manager gates, for TASK-085 only (targeted suites per task; the full suite in CI) | the M3 plants for `upload.py` | WSL; CI |

### M4 security mutation table (tester; CHK-M4-320 onwards)

Each row is planted in a throwaway copy, must turn the named gate red, and is re-planted against the final tree at the gate only if its target code changed after it was last proven red (user rule, decisions 2026-10-23 "Targeted test runs").

| CHK | Plant | Red in | Code owned by |
| --- | --- | --- | --- |
| CHK-M4-320 | an `http://` `manager_url` accepted | G36 | TASK-087 |
| CHK-M4-321 | `InsecureSkipVerify: true` | G8 | TASK-089 |
| CHK-M4-322 | the pin check skipped when `manager_spki_sha256` is set | G36 | TASK-089 |
| CHK-M4-323 | the pin matched against any chain certificate instead of the leaf (#79) | G36 | TASK-089 |
| CHK-M4-324 | `ca_file` ignored (system store used instead) | G36 | TASK-089 |
| CHK-M4-325 | host-name verification skipped in a custom verify callback | G36 | TASK-089 |
| CHK-M4-326 | TLS minimum lowered to 1.0 | G36 | TASK-089 |
| CHK-M4-327 | a 3xx redirect followed (#75) | G36 | TASK-093 |
| CHK-M4-328 | the proxy taken from the environment (#75) | G36 | TASK-093 |
| CHK-M4-329 | `X-Bitscan-Machine-Id` omitted on one route | G36 | TASK-093 |
| CHK-M4-330 | a job with another `agent_id` accepted | G36 | TASK-103 |
| CHK-M4-331 | a job with `pickup_by` in the past accepted | G36 | TASK-103 |
| CHK-M4-332 | a job with `pickup_by` more than 25 h ahead accepted | G36 | TASK-103 |
| CHK-M4-333 | seen job ids kept only in memory (a replay after restart is accepted) | G36 | TASK-088, TASK-103 |
| CHK-M4-334 | seen job ids expired after less than 7 days | G36 | TASK-088 |
| CHK-M4-335 | a 401 that does not stop the other loop | G36 | TASK-101 |
| CHK-M4-336 | 403 `pending_approval` dropped instead of waited on | G11 | TASK-093 |
| CHK-M4-337 | a 409 retried | G11 | TASK-093 |
| CHK-M4-338 | the back-off cap removed, or no back-off on 503 | G11 | TASK-090 |
| CHK-M4-339 | the `Authorization` header logged at debug level | G36 (canary) | TASK-093 |
| CHK-M4-340 | `token` written with mode 0644 | G36 | TASK-088 |
| CHK-M4-341 | `enroll.token` kept after a successful enrolment | G36 | TASK-098 |
| CHK-M4-342 | the agent writes `agent.yaml` | G36 | TASK-087 |
| CHK-M4-343 | an unknown `agent.yaml` key (`inventory: false`) accepted | G36 | TASK-087 |
| CHK-M4-344 | an inventory command run through `sh -c` | G36 (static check) | TASK-094 |
| CHK-M4-345 | a command argument taken from a job or heartbeat field | G36 | TASK-094, TASK-103 |
| CHK-M4-346 | a listening socket opened (`net.Listen`) | G8 | any agent task |
| CHK-M4-347 | rotation without the single-flight guard (two concurrent rotate calls) | G36 (race) | TASK-099 |
| CHK-M4-348 | rotation before the window | G36 | TASK-099 |
| CHK-M4-349 | the new token used before it is persisted | G36 (crash test) | TASK-099 |
| CHK-M4-350 | `list_sha256` lines unsorted or in another format | G35, G41 | TASK-095 |
| CHK-M4-351 | `Content-Encoding: gzip` missing on the upload | G41 | TASK-104 |
| CHK-M4-352 | the watcher debounce removed (one upload per event) | G11 | TASK-091, TASK-104 |
| CHK-M4-353 | `omitempty` on a nullable contract field | G35 | TASK-086 |
| CHK-M4-354 | unknown keys accepted in a response | G35 | TASK-086 |
| CHK-M4-355 | a heartbeat response triggering a pull or an upload | G11 | TASK-101 |
| CHK-M4-356 | a compliance job's `execute` run by the agent | G36 (exec counter) | TASK-103 |
| CHK-M4-357 | `postinst` writes the enrolment token into `agent.yaml` | G38 | TASK-100 |
| CHK-M4-358 | the debconf token not cleared | G38 | TASK-100 |
| CHK-M4-359 | an install input read from a command-line environment variable | G38 | TASK-100 |
| CHK-M4-360 | purge removes all of `/etc/bitscan` (a planted `manager.env` is lost, #82) | G38 | TASK-100 |
| CHK-M4-361 | `bitscan-runner.service` enabled, or a capread unit enabled or started | G38 | TASK-092 |
| CHK-M4-362 | one character of the D-Bus policy or an agent unit changed | G17 | TASK-092 |
| CHK-M4-363 | a build timestamp or absolute path in a binary | G39 | TASK-102 |
| CHK-M4-364 | a module missing from the SBOM | G40 | TASK-102 |
| CHK-M4-365 | an altered `go.sum` line | G9 | TASK-087 |
| CHK-M4-366 | an `upload.py` branch changed during the refactor (a `failed`-job upload answered 409) | G18 (targeted TASK-074 suites) | TASK-085 |

### Open items for M4

All are in `work/open-questions.md`. "Needed by" is the start of the wave whose task cannot be finished without the answer.

| Item | Blocks | Needed by |
| --- | --- | --- |
| PD-25 (new): Go dependencies (YAML library; JSON Schema validator for tests only; hand-written wire types) | TASK-086, TASK-087, TP-M4-01 | W1 |
| PD-26 (new): packaging toolchain, SBOM tool, version scheme | TASK-092, TASK-102 | W1 |
| PD-27 (agreed, user 2026-10-24: CI runners plus containers; amd64 only): test platforms for Ubuntu 22.04, 24.04 and Debian 12 | TASK-097 (W2), TASK-105, TP-M4-09 | W2 |
| #4 (re-checked): `agent.yaml` keys and ranges | TASK-087 | W1 |
| #79 (new): SPKI pin format and scope | TASK-089 | W1 |
| #80 (new): watcher debounce | TASK-091 | W1 |
| #35 (re-checked): the agent runs its inventory commands | TASK-094 | W2 |
| #77 (new): `os_info` derivation, `raw` contents, values outside the contract | TASK-094, TASK-095 | W2 |
| #75 (new): proxies and redirects | TASK-093 | W2 |
| #76 (new): lost enrolment response | TASK-098 | W3 |
| #81 (new): start-up, 401 behaviour, re-enrolment on the host | TASK-098, TASK-100 (W3), TASK-101 | W3 |
| #82 (new): purge versus a manager on the same host | TASK-100 | W3 |
| #30 (re-checked): helper detection | TASK-101 | W4 |
| #78 (new): heartbeat field meanings | TASK-101 | W4 |
| #74 (new; touches #28): 0.x runner, capread and compliance jobs | TASK-103 | W5 |
| #28 (re-checked) | none in 0.x beyond #74; answer before the first supported release | M6 |
| #6 | none in M4: only the manager install method; the agent package is fully specified | M5 |
| CLAUDE.md N / N−1 marker | none: 0.x is not supported as N−1 (decisions 2026-10-20) | before the first supported release |
| PD-3 | second approval of the agent tasks, once per wave | each wave's REVIEW |

### Coverage matrix (M4)

| Spec section | Covered by | Status in M4 |
| --- | --- | --- |
| TS §2.2 pull, not push; no listening port; agent identity by token | REQ-094, REQ-103 | Covered |
| TS §3 intro (two binaries plus capread; `runner_unavailable`) | REQ-104, REQ-106 | Package covered; the runner itself is **M10** |
| TS §3.1 binaries, units, config, D-Bus policy, state, logs, install inputs, install, uninstall, postinst, distribution | REQ-093, REQ-103, REQ-106 to REQ-110 | Covered; publishing on a release page from another origin is the **M6** release step |
| TS §3.2 steps 2–4, 6–9 and Transport (agent side) | REQ-094, REQ-096, REQ-099 | Covered; manager side done in M3 |
| TS §3.3 loops, pull-only rules, job checks, idle, responses to posts, network failure | REQ-095, REQ-097, REQ-098 | Covered. The result spool and `spool_overflow` are **M10**; the idle-cost target is measured, no gate (testing.md question) |
| TS §3.3 L222 start notice and one-at-a-time compliance jobs | REQ-104 (#74) | 0.x handling only; real execution **M10** |
| TS §3.4 collection, watcher, upload (agent side) | REQ-100 to REQ-102 | Covered |
| TS §3.5 job execution, redaction, batches | none | **M10** (results batches appear in M4 only as #74 allows) |
| TS §3.6 `agent.yaml` | REQ-092 | Covered per #4 |
| TS §3.7 units, socket, D-Bus policy, file ownership | REQ-106, REQ-108 | Shipped verbatim; runner and capread behaviour **M10** |
| TS §6.1, §6.5 (client side) | REQ-091, REQ-094 to REQ-101 | Covered for every route |
| TS §8.1 tampered job in transit; bug in the agent's network code; install and supply chain; local user (enrolment token in debconf) | REQ-094, REQ-103, REQ-105, REQ-107, REQ-109 | Covered |
| TS §8.2 Go standards, two approvals for agent changes | REQ-103, REQ-105; owner notes | Covered |
| TS §8.3 Contract | REQ-091 / G35 | Go half covered |
| TS §8.3 Agent (back-off on 22.04, 24.04, Debian 12, amd64 and arm64) | REQ-095, REQ-111 / PD-27 | amd64 only: arm64 is **dropped from v1** (owner deviation, decisions 2026-10-24), so it is uncovered by decision, not deferred. Back-off covered; runner timeouts, output caps, redaction and spool overflow are **M10** |
| TS §8.3 Security (agent part: expired, foreign, replayed jobs; certificate or pin failure) | REQ-094, REQ-098 / G36 | Covered for the agent; the runner half is **M10** |
| TS §8.3 Sandbox | REQ-106 (units verbatim, `systemd-analyze verify`) | The plugin-cannot list is **M10** |
| TS §8.3 Packaging and release (testing.md) | REQ-106, REQ-108, REQ-109 / G37 to G40 | Covered |
| TS §8.3 End-to-end, Load | TP-M4-23 (one host in WSL) | 3 VMs and 10,000 agents are **M6** |
| TS §8.7 | none | Manager deployment unchanged; #6 is **M5** |
| CLAUDE.md out of scope | none | Nothing planned: no signed APT repository, no client certificates, no job or `.bit` signing |
