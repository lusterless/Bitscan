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

## M5 minimal host UI and package search

Planned 2026-10-24 (planner); consistency pass done (every TASK links a REQ and every REQ has a TASK, waves file-disjoint, at most 5 files and about 200 lines per task, the spine acyclic, no gate lowered, M3-file work after the M3 gate verdict, TASK-128 after M4's TASK-085). Plans: `work/plans/TASK-110.md` (TASK-109, 110), `TASK-112.md`, `TASK-113.md` (TASK-113, 114), `TASK-116.md`. Awaiting the lead's review and the user's approval.

Scope: REQ-113 to REQ-136 in `work/requirements.md`. Planned 2026-10-24 alongside M4 (speed rule 7) in the worktree `Bitscan-m4` (branch `m4-agent`). In this section `bm/` means `manager/bitscan_manager/` and `w/` means `web/`.

**M5 needs only the M3 manager API, not the Go agent.** No M5 task depends on an M4 task, except that TASK-128 (README) follows M4's TASK-085, which also edits `README.md`. Every UI screen is built and tested against the M3 contract in `manager/openapi.json` with component tests; nothing waits for a real agent.

**When each task may start (M3 gate).** Tasks that edit files the M3 PR changes (`bm/api/user/*.py`, `bm/app.py`, `bm/cli/serve.py`, `manager/openapi.json`, `w/src/api/schema.d.ts`) start only after the M3 gate verdict, as TASK-085 does, so the gate runs on a fixed tree and the later rebase onto main has no conflicts: TASK-108, 112, 113 (and the tasks after them on the same files: 114, 122, 124). Two smaller edits wait for the same verdict: the tester's TP-M5-05 allow-list change in `manager/tests/test_invariants_m3.py` (an M3 test file), and TASK-115's one `.gitignore` line (the M3 tree has an uncommitted `.gitignore` change; until the line lands the build folder shows as untracked, and nobody commits); the rest of TASK-115 does not wait. Every other M5 task touches new files, or files M3 did not change (`w/package.json`, `.github/workflows/web.yml`), and **can start now**: TASK-109, 110, 111, 115 (without the `.gitignore` line), 116, 117, 118 to 121, 127, and tester TP-M5-00.

**No migration, no new index.** Rules every M5 task follows:
- **Tests per task (speed rule 1):** the tester runs only the affected tests (for a manager task its own suites plus what imports the changed modules; for a web task `vitest run <files>` plus lint and typecheck); the full manager suite, the whole web suite and the build run at the end of each wave, at the M5 gate and in CI.
- **Linux only for Python (speed rule 2):** pytest runs in WSL with `CI=true`; web lint, typecheck, tests and the build may run on Windows and also run in CI on Ubuntu.
- **Rigor (speed rule 6):** UI and package search get **one review round**. No M5 task changes manager auth, the importer, the agent or the runner, so none is on the TS §8.2 two-approval list; PD-30 asks whether the user also wants a second look at the web session and sign-in tasks.
- **Per-wave second approval (speed rule 4):** asked once per wave only if PD-30 adds tasks to the list.
- Manager: `api → services → repositories`; SQL only through `psycopg.sql` composition of fixed fragments with bound values (ruff S608); RE2 for any pattern on input; every route task re-exports `manager/openapi.json` (G6).
- Web: call the API only through `w/src/api/client.ts`; the `bsu_` token in memory only; render API data as text; no new runtime dependency outside PD-28; screens are standalone components that TASK-126 wires into the routes, so screen tasks share no file.
- No task adds a route, setting or parameter that queues a command or disables inventory (REQ-088); the M3 route walk (G34) is re-run in every manager route task's TEST.
- Implementers check `work/reviews/builder-checklist.md` before every hand-off.

### M5 tasks

| TASK | Title | REQ links | Area | Owner | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-108 | Status and kind enums in the user-route models: `AgentItem`, `AgentDetailItem` and `MatchItem` `status` as the six-value `agent_status`; `RequestItem.kind` and `decision` (PD-29); re-export | REQ-117 | manager | impl-manager | `bm/api/user/agents.py`, `bm/api/user/enrolment.py`, `manager/openapi.json` | M3 gate verdict; PD-29 | 30 (+1 generated) | The exported document gives exactly the six `agent_status` values (TS §5.2 L710) to the three `status` properties and the PD-29 values to `kind` and `decision`, and the M3 agents and enrolment-request route suites pass unchanged. |
| TASK-109 | Package search query: `GroupBy`, `SearchQuery` (wrapping TASK-110's `SearchFilter`, with `cursor_scope()`), `InvalidSearch` and `parse_search(params) -> SearchQuery` with every REQ-113 rule (pure; plain ASCII character checks for `os`, `agent_id` and the Debian version, no regular expression) (plan: `work/plans/TASK-110.md`) | REQ-113 | manager | impl-manager | `bm/services/packages/__init__.py`, `bm/services/packages/query.py` | TASK-110 (the `SearchFilter` and `VersionOp` types only: built in parallel against the plan's signatures, TESTed after TASK-110 IMPL); #83, #88 | 140 | Unit: each REQ-113 (1) case gives its 400 `invalid_request` naming the parameter (never the value), and every valid combination returns a `SearchQuery` with the #83 (a), (c), (d) and (f) normalised fields. |
| TASK-110 | Package search repository: the `SearchFilter`, `VersionOp` and row types, rows, `group_by=package` and `group_by=host` queries with all filters, Debian-order `version_op`, the #83 (e) agent scope, escaped `LIKE`, keyset paging in the #83 (b) order from id anchors (`AnchorGone`) (plan: `work/plans/TASK-110.md`) | REQ-114, REQ-115 | manager | impl-manager | `bm/repositories/packages.py` | none; #83, #87 | 200 | PostgreSQL as `bitscan_app` on a fixture fleet: each filter alone, every pair and one five-filter combination give exactly the independently computed sets for all three shapes; `version_op` agrees with `dpkg --compare-versions` on 50 fixture pairs; paging with `limit=N` returns each item once, including `1.0` versus `1.0-0`; `q=%_` matches literally; ruff S608 passes. |
| TASK-111 | CSV writer with TS §6.3 formula escaping (one shared function for every export) and RFC 4180 quoting, header row (#84) | REQ-116 | manager | impl-manager | `bm/services/packages/csv_export.py` | TASK-109 (creates the package's `__init__.py`; TASK-111 is built in parallel and TESTed after TASK-109 IMPL); #84 | 70 | Unit: every trigger and every #84 (d) whitespace-then-trigger form gets exactly one leading `'`, non-trigger cells are unchanged, and commas, quotes, CR and LF are quoted after the prefix, so `=HYPERLINK("http://x")` becomes `"'=HYPERLINK(""http://x"")"`. |
| TASK-112 | Serve the built UI: `GET /` and `GET /assets/{name}` from the PD-28 folder, files fixed at app creation, fixed content types, no token, not in the document, problem 404 otherwise; `serve` logs when the UI is not built (plan: `work/plans/TASK-112.md`) | REQ-118 | manager | impl-manager | `bm/api/webui.py`, `bm/app.py`, `bm/cli/serve.py` | M3 gate verdict; #6 (M5 half), PD-28 | 120 | With a fixture build folder, `/` and each asset answer 200 with their content type and exactly the TS §6.3 headers; every REQ-118 (2) traversal, encoded, late-added, sub-folder and unknown-extension request answers 404 with no file content; no response has an `Access-Control-Allow-*` header; `manager/openapi.json` is byte-identical; with no folder `/` is 404 and the API suites pass. |
| TASK-113 | Package search service and `GET /api/v1/packages/search` (viewer): query parameters, the three response shapes, cursor scope bound to the filters and `group_by`, invalid-version mapping to 400; router registration; re-export (plan: `work/plans/TASK-113.md`) | REQ-113, REQ-114, REQ-115 | manager | impl-manager | `bm/services/packages/search.py`, `bm/api/user/packages.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-108 (OpenAPI order), TASK-109, TASK-110; #83 | 170 (+1 generated) | Through the API on PostgreSQL: REQ-113 refusals answer 400 problem+json; the three shapes return exactly their keys and the fixture-fleet sets; a cursor reused with other filters is refused; no token, `bsa_` and `bse_` get 401 and a viewer `bsk_` 200; hostile names come back verbatim; nothing is written. |
| TASK-114 | `GET /api/v1/packages/search.csv` (viewer): the same filters, the whole result set in one REPEATABLE READ, READ ONLY transaction up to the #84 cap (repository `read_only_snapshot`, `count_capped`, `stream`), refused over it before any byte, the #84 headers; documented as `text/csv`; re-export (plan: `work/plans/TASK-113.md`) | REQ-116, REQ-115 | manager | impl-manager | `bm/api/user/packages.py`, `bm/services/packages/search.py`, `bm/repositories/packages.py`, `manager/openapi.json` | TASK-110, TASK-111, TASK-113; #84 | 140 (+1 generated) | Through the API on PostgreSQL: the CSV's data rows equal the JSON items of every page for the same filters in all three shapes, with the header row and escaped hostile cells; a result one row over the cap answers 400 with no CSV body; `Content-Type` and `Content-Disposition` follow #84; no token and agent tokens get 401. |
| TASK-115 | Web toolchain: Vite pinned as a direct dev dependency, `build` script into the PD-28 folder, `w/index.html`, `w/vite.config.ts` (also the Vitest jsdom environment), jsdom and Testing Library dev-only, any PD-28 runtime addition; lock regenerated | REQ-119 | web | impl-web | `w/package.json`, `w/package-lock.json` (generated), `w/vite.config.ts`, `w/index.html`, `.gitignore` (one line, only under PD-28 (b); the lead names its owner) | none; PD-28 | 60 (+1 generated) | `npm ci --ignore-scripts && npm run build` exits 0 and writes `index.html` with external assets only; the G42 check passes and turns red on each planted inline script, style element, `style=` attribute and `https://` link; `npm ls --omit=dev --all` lists only React, React DOM, `openapi-fetch` and the PD-28 additions; lint, typecheck, format and test still pass. |
| TASK-116 | Web session core: in-memory session store with `useSession()`, the bearer and 401 middleware registered on the generated client (no change to `client.ts`), problem reading and the REQ-126 message map, the hash router and `Route` type (plan: `work/plans/TASK-116.md`) | REQ-120, REQ-126 | web | impl-web | `w/src/app/session.ts`, `w/src/app/problems.ts`, `w/src/app/router.ts` | none (its DOM tests run once TASK-115 is in) | 170 | Unit: after `setSession` every client request carries `Authorization: Bearer <token>` and none before it; a 401 from any route clears the session; no storage API, cookie or console receives the token (spies); each REQ-126 problem `type` maps to its message; every `Route` round-trips through `formatHash` and `parseHash`, and a malformed hash or a non-UUID host id parses to the host list. |
| TASK-117 | Shared display components: cursor `Pager` (next and previous from returned cursors), `ProblemBanner` (REQ-126 messages and `detail` as text), the time format ("never" for null), a confirm dialog | REQ-126, REQ-127, REQ-132 | web | impl-web | `w/src/components/Pager.tsx`, `w/src/components/ProblemBanner.tsx`, `w/src/components/Confirm.tsx`, `w/src/format.ts` | TASK-115, TASK-116 | 150 | UI test: the pager walks N + 1 items with page size N forwards and back showing each once; `ProblemBanner` shows hostile `detail` text literally and the REQ-126 message per `type`; `Confirm` calls its action only after confirmation; a null time renders "never". |
| TASK-118 | Sign-in screen (REQ-121), including the `Retry-After` wait and the next-screen choice from the response | REQ-121, REQ-120, REQ-132 | web | impl-web | `w/src/screens/SignIn.tsx` | TASK-116, TASK-117; #85 (e) | 130 | UI test: the body is exactly `{username, password, totp_code}` (null when empty); two different 401s show one message; a 429 with `Retry-After: 7` disables the button for 7 s; the fields are cleared after each attempt; success calls `setSession` and reports the REQ-133 next screen. |
| TASK-119 | Account screens: TOTP enrolment (start, secret and URI as text, PD-28 QR, confirm, session swap), replacement (current password and code), the first-sign-in offer for non-admins, and password change (REQ-123) | REQ-122, REQ-123, REQ-132 | web | impl-web | `w/src/screens/TotpEnrol.tsx`, `w/src/screens/PasswordChange.tsx`, `w/src/components/QrCode.tsx` (only under PD-28 (e)) | TASK-116, TASK-117; #85 (a); PD-28 | 190 | UI test: start shows the secret and URI as text; a good confirm swaps the token for the next request; 403 and 409 behave as REQ-122 (3); replacement sends `{current_password, current_code}` first; the secret is gone from the DOM, storage and console after leaving; a mismatched or short new password sends nothing and a 204 clears the session. |
| TASK-120 | Enrolment tokens screen (REQ-124): create form with defaults and the TS §3.2 hint and alert notes, token shown once with copy, paginated list, revoke with confirmation | REQ-124, REQ-126, REQ-132 | web | impl-web | `w/src/screens/EnrolmentTokens.tsx` | TASK-116, TASK-117 | 180 | UI test: an untouched form posts the REQ-124 (1) defaults; the hint is shown; the token is in the DOM only on the creation result and in no storage; revoke calls `DELETE` once after confirmation; a `totp_session_required` answer shows the sign-in-again prompt and no token field. |
| TASK-121 | Enrolment approval screen (REQ-125): pending and decided lists with matching agents flagged, approve and reject with confirmation, 409 handling | REQ-125, REQ-126, REQ-132 | web | impl-web | `w/src/screens/EnrolmentRequests.tsx` | TASK-116, TASK-117 | 170 | UI test: a request with two matches shows both; hostile hostnames, match hostnames and OS names render as text; approve calls the route once and the item leaves the pending list; 409 shows "already decided"; `totp_session_required` and `audit_sink_unavailable` show their REQ-126 messages. |
| TASK-122 | Regenerate `schema.d.ts` (status enums); host list screen (REQ-127) with an exhaustive status-label map | REQ-127, REQ-136, REQ-117, REQ-132 | web | impl-web | `w/src/api/schema.d.ts` (generated), `w/src/screens/Hosts.tsx`, `w/src/components/StatusBadge.tsx` | TASK-108, TASK-117 | 140 (+1 generated) | After `npm run gen:api` G16 shows no diff against the tree at that time; UI test: paging shows each host once, each of the six statuses has its label (removing one fails typecheck), hostile hostnames and tags render as text, and a null heartbeat shows "never". |
| TASK-123 | Host detail screen (REQ-128): identity and token times, tags and helpers, every `os_info` field with `raw` as JSON text, "Added / removed since last snapshot", paginated packages | REQ-128, REQ-132 | web | impl-web | `w/src/screens/HostDetail.tsx` | TASK-117, TASK-122 | 190 | UI test: every REQ-128 field is shown; null `os_info` and null `last_snapshot` show their empty states; the added and removed lists equal the snapshot's items; a hostile `raw` key and value show as text; a 404 shows "Host not found"; package paging shows each package once. |
| TASK-124 | Regenerate `schema.d.ts` (package routes); package search screen (REQ-129): form, grouped results, click-through to hosts and host detail, per-host view | REQ-129, REQ-136, REQ-132 | web | impl-web | `w/src/api/schema.d.ts` (generated), `w/src/screens/PackageSearch.tsx` | TASK-113, TASK-114, TASK-117, TASK-122 (generated-file order); #86 | 190 (+1 generated) | G16 shows no diff and `UserPathsArePrefixed` passes with both package paths; UI test: the form sends exactly the filled parameters, a `group_by=package` answer renders name → version → host count, a version click requests `name`, `version`, `arch` without `group_by`, a host click opens `#/hosts/<agent_id>`, and hostile names render as text. |
| TASK-125 | Type-ahead (REQ-130, per #32) and the CSV download (REQ-131) | REQ-130, REQ-131 | web | impl-web | `w/src/components/TypeAhead.tsx`, `w/src/screens/PackageSearch.tsx`, `w/src/app/download.ts` | TASK-124; #32, #84 | 130 | UI test with fake timers: 2 characters send nothing, a quick 5-character burst sends one request, at most 10 distinct names show, a stale response is ignored, choosing sets `name` and clears `q`; Export sends the visible filters without `limit` or `cursor`, saves the body unchanged and revokes the Blob URL; a 400 shows its `detail`. |
| TASK-126 | App shell: route table for every M5 screen, navigation by role, restricted-admin and first-sign-in gating, sign-out, a "not available for your role" page | REQ-133, REQ-120, REQ-122 | web | impl-web | `w/src/main.tsx`, `w/src/app/App.tsx`, `w/src/app/routes.tsx` | TASK-118 to TASK-125 | 160 | UI test per role: the navigation shows exactly the REQ-133 entries; a viewer opening an admin route sees the role page and no request is sent to it; an admin with `totp_enrolled: false` reaches only TOTP and sign-out; sign-out clears the session even when logout fails; a reload (fresh module state) starts at sign-in. |
| TASK-127 | Web CI: `npm run build` and the G42 bundle check after the existing web steps | REQ-134 | deploy | impl-deploy | `.github/workflows/web.yml` | TASK-115; PD-28 | 40 | On a PR the build and check run, and a failing build and each G42 plant (inline script, style element, `style=` attribute, `https://` link in `index.html`) turn the job red; every action stays pinned. |
| TASK-128 | README: building and opening the UI, sign-in and TOTP, enrolment tokens and approvals in the UI (API path kept), host pages, package search parameters, CSV export and escaping | REQ-135 | manager | impl-manager | `README.md` | TASK-112, TASK-114, TASK-126, M4 TASK-085 (same file) | 120 (docs) | The tester follows every new section against a WSL manager serving the built UI and each step behaves as written; the README holds no real secret, task id or process note. |

Totals: 24 REQ (REQ-113 to REQ-136), 21 TASK (TASK-108 to TASK-128), 23 test-plan items (TP-M5-00 to TP-M5-22), 7 waves plus the gate. Every task is within 5 files and about 200 hand-written lines; generated files and test files are not counted.

REQ to TASK: REQ-113 TASK-109, TASK-113; REQ-114 TASK-110, TASK-113; REQ-115 TASK-110, TASK-113, TASK-114; REQ-116 TASK-111, TASK-114; REQ-117 TASK-108, TASK-122; REQ-118 TASK-112; REQ-119 TASK-115; REQ-120 TASK-116, TASK-118, TASK-126; REQ-121 TASK-118; REQ-122 TASK-119, TASK-126; REQ-123 TASK-119; REQ-124 TASK-120; REQ-125 TASK-121; REQ-126 TASK-116, TASK-117, TASK-120, TASK-121; REQ-127 TASK-117, TASK-122; REQ-128 TASK-123; REQ-129 TASK-124; REQ-130 TASK-125; REQ-131 TASK-125; REQ-132 TASK-117 to TASK-124 (every screen's UI tests); REQ-133 TASK-126; REQ-134 TASK-127; REQ-135 TASK-128; REQ-136 TASK-122, TASK-124. Every M5 REQ has at least one TASK, and every TASK has at least one REQ.

### M5 owner and review notes

- **Owners:** impl-manager: TASK-108 to TASK-114 and TASK-128. impl-web: TASK-115 to TASK-126. impl-deploy: TASK-127 (impl-deploy also carries the M4 packaging tasks; TASK-127 is about 40 lines and has no deadline before the M5 gate). The tester owns every test file (`manager/tests/`, `w/src/**/*.test.ts(x)`), the fixture build folder for TASK-112, and `tests/m5/`.
- **Two approvals (TS §8.2 L1268):** none required. No M5 task changes manager auth, the importer, the agent or the runner. TASK-108 changes only response types in two M3 route files (as the TASK-084 ruling: not on the list unless behaviour changes). **PD-30** asks whether the user wants the second look anyway for TASK-116 (session token handling), TASK-118 (sign-in) and TASK-119 (TOTP and password), which handle `bsu_` tokens, passwords and TOTP secrets in the browser.
- **Recommended second look (reviewer's choice):** TASK-110 and TASK-113 (the only new SQL that takes user input), TASK-112 (unauthenticated file serving).
- **One review round** for every M5 task (speed rule 6); a security-invariant finding is still blocking.
- **Shared files, never in the same wave:** `manager/openapi.json` (TASK-108 W1, 113 W2, 114 W3); `bm/api/user/packages.py` and `bm/services/packages/search.py` (TASK-113 W2, 114 W3); `bm/repositories/packages.py` (TASK-110 W1, 114 W3); `w/src/api/schema.d.ts` (TASK-122 W3, 124 W4); `w/src/screens/PackageSearch.tsx` (TASK-124 W4, 125 W5); `README.md` (M4 TASK-085, then TASK-128 W7). `bm/app.py` and `bm/cli/serve.py` change once (TASK-112). `bm/services/packages/__init__.py` is created by TASK-109 only; TASK-111 adds a sibling module and does not edit it.
- **G16 between regenerations:** `manager/openapi.json` changes in W1 to W3 while `schema.d.ts` is regenerated in W3 (TASK-122) and W4 (TASK-124); G16 is checked in those two TESTs and at the gate, as PD-20 allowed in M3.
- **Built-key lint nit (TASK-005, carried to M5):** the rule stays as written; screens use a `Map` or a variable key, never a template-literal or concatenated computed key. Changing the rule needs the lead.
- Planted violations are made in a throwaway copy or branch, never left in the tree.

### M5 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m5/test-plan.md`, check ids `CHK-M5-###`). Python items run in WSL with `CI=true`; web items run with Vitest (jsdom) on Windows or Linux and in CI.

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M5-00 | Phase test plan and the M5 index row | all M5 | phase start; report at the gate | `tests/m5/test-plan.md`, `tests/test-plan.md` | none |
| TP-M5-01 | Enum types in the document; M3 agents and enrolment-request suites targeted | REQ-117 | TASK-108 TEST | `manager/tests/test_user_enums.py` | TASK-108 IMPL |
| TP-M5-02 | Query parsing, one case per rule and limit (U+0000 and empty values per #88; every M1 corpus version accepted) | REQ-113 | TASK-109 TEST | `manager/tests/test_package_query.py` | #83; TASK-109 IMPL, TASK-110 IMPL |
| TP-M5-03 | Fixture fleet and repository queries on PostgreSQL; `dpkg` corpus pairs; keyset paging from id anchors; literal wildcards; the #87 probe (reported as a finding) | REQ-114, REQ-115 | TASK-110 TEST | `manager/tests/test_package_repo_pg.py`, `manager/tests/package_fleet.py` (fixture builder) | TASK-110 IMPL |
| TP-M5-04 | CSV escaping and quoting, one case per trigger (TS §8.3 Unit) | REQ-116 | TASK-111 TEST | `manager/tests/test_csv_export.py` | #84 |
| TP-M5-05 | Static UI serving with a fixture build folder; traversal and encoding probes; headers; no CORS; G6; route walk (G34) updated for the two static routes | REQ-118 | TASK-112 TEST | `manager/tests/test_webui_serving.py`, `manager/tests/test_invariants_m3.py` (allow-list update) | TASK-112 IMPL |
| TP-M5-06 | Search route integration (TS §8.3 Integration: every endpoint) and token groups | REQ-113, REQ-114, REQ-115 | TASK-113 TEST | `manager/tests/test_package_search_pg.py` | TP-M5-03 |
| TP-M5-07 | CSV route integration: JSON equivalence, cap, headers | REQ-116, REQ-115 | TASK-114 TEST | `manager/tests/test_package_search_csv_pg.py` | TP-M5-04, TP-M5-06 |
| TP-M5-08 | Build, G42 plants, dependency list | REQ-119 | TASK-115 TEST | none in the tree (evidence) | TASK-115 IMPL |
| TP-M5-09 | Session store, middleware, problem map, router | REQ-120, REQ-126 | TASK-116 TEST | `w/src/app/session.test.ts`, `w/src/app/problems.test.ts`, `w/src/app/router.test.ts` | TASK-115 IMPL |
| TP-M5-10 | Shared components | REQ-126, REQ-127, REQ-132 | TASK-117 TEST | `w/src/components/components.test.tsx` | TP-M5-09 |
| TP-M5-11 | Sign-in | REQ-121, REQ-120 | TASK-118 TEST | `w/src/screens/SignIn.test.tsx` | TP-M5-10 |
| TP-M5-12 | TOTP enrolment, replacement, offer; password change | REQ-122, REQ-123 | TASK-119 TEST | `w/src/screens/Account.test.tsx` | TP-M5-10 |
| TP-M5-13 | Enrolment tokens | REQ-124, REQ-126 | TASK-120 TEST | `w/src/screens/EnrolmentTokens.test.tsx` | TP-M5-10 |
| TP-M5-14 | Enrolment approval | REQ-125, REQ-126 | TASK-121 TEST | `w/src/screens/EnrolmentRequests.test.tsx` | TP-M5-10 |
| TP-M5-15 | Host list; G16 at that time | REQ-127, REQ-136 | TASK-122 TEST | `w/src/screens/Hosts.test.tsx` | TP-M5-10, TP-M5-01 |
| TP-M5-16 | Host detail | REQ-128 | TASK-123 TEST | `w/src/screens/HostDetail.test.tsx` | TP-M5-15 |
| TP-M5-17 | Package search screen; G16 | REQ-129, REQ-136 | TASK-124 TEST | `w/src/screens/PackageSearch.test.tsx` | TP-M5-07, TP-M5-15 |
| TP-M5-18 | Type-ahead and CSV download | REQ-130, REQ-131 | TASK-125 TEST | `w/src/components/TypeAhead.test.tsx`, `w/src/app/download.test.ts` | TP-M5-17 |
| TP-M5-19 | Shell: navigation per role, gating, sign-out, reload | REQ-133, REQ-120, REQ-122 | TASK-126 TEST | `w/src/app/App.test.tsx` | TP-M5-11 to TP-M5-18 |
| TP-M5-20 | Web CI plants | REQ-134 | TASK-127 TEST | none in the tree (evidence) | TASK-127 IMPL |
| TP-M5-21 | README walk-through against a WSL manager serving the built UI | REQ-135 | TASK-128 TEST | none in the tree (evidence) | TASK-128 IMPL |
| TP-M5-22 | M5 security and invariants suite (G46): route walk with the package and static routes, token groups on both package routes, canary sweep (no hostile package name, CSV cell or token in any log), served-bundle check against a real `serve` in WSL (every asset `index.html` references answers 200 with headers), the mutation table below, and the user's PD-28 (f) browser walk-through recorded | REQ-113 to REQ-136 | M5 gate | `manager/tests/test_security_m5.py` | all above |

### M5 waves and dependency spine

Spine (manager): `TASK-110 → TASK-109 → TASK-113 → TASK-114` (TASK-109 needs only TASK-110's types, so both are built in W1); `TASK-109 → TASK-111` (package `__init__.py`); `TASK-111 → TASK-114`; `TASK-108 → TASK-113` (OpenAPI order); `TASK-108 → TASK-122`; `TASK-112 → TASK-128`.
Spine (web): `TASK-115, TASK-116 → TASK-117 → TASK-118, 119, 120, 121, 122`; `TASK-122 → TASK-123`; `TASK-113, TASK-114, TASK-122 → TASK-124 → TASK-125`; `TASK-118 to TASK-125 → TASK-126 → TASK-128`; `TASK-115 → TASK-127`. The graph is acyclic.

Interface first: the filter and row types (TASK-110) and the query type (TASK-109), both fixed in `work/plans/TASK-110.md` so the two are written in parallel (repositories never import services, so the filter type lives in the repository), the CSV function (TASK-111), the enums (TASK-108), the static-serving contract (TASK-112, fixed by #6 and PD-28) and the web session, problem and route interfaces (TASK-116, fixed in `work/plans/TASK-116.md`) all land in W1, before any route or screen consumes them.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) | Can start before M4 finishes? |
| --- | --- | --- | --- |
| W1 | TASK-108\*, 109, 110, 111, 112\*, 115, 116; tester TP-M5-00 | `bm/api/user/{agents,enrolment}.py`, `manager/openapi.json` · `bm/services/packages/{__init__,query}.py` · `bm/repositories/packages.py` · `bm/services/packages/csv_export.py` · `bm/api/webui.py`, `bm/app.py`, `bm/cli/serve.py` · `w/{package.json,package-lock.json,vite.config.ts,index.html}` (+ `.gitignore` under PD-28 (b)) · `w/src/app/{session,problems,router}.ts` | yes; \* after the M3 gate verdict |
| W2 | TASK-113\*, 117, 127 | `bm/services/packages/search.py`, `bm/api/user/{packages,__init__}.py`, `manager/openapi.json` · `w/src/components/{Pager,ProblemBanner,Confirm}.tsx`, `w/src/format.ts` · `.github/workflows/web.yml` | yes; \* after the M3 gate verdict |
| W3 | TASK-114, 118, 119, 120, 121, 122 | `bm/api/user/packages.py`, `bm/services/packages/search.py`, `bm/repositories/packages.py`, `manager/openapi.json` · `w/src/screens/SignIn.tsx` · `w/src/screens/{TotpEnrol,PasswordChange}.tsx`, `w/src/components/QrCode.tsx` · `w/src/screens/EnrolmentTokens.tsx` · `w/src/screens/EnrolmentRequests.tsx` · `w/src/api/schema.d.ts`, `w/src/screens/Hosts.tsx`, `w/src/components/StatusBadge.tsx` | yes |
| W4 | TASK-123, 124 | `w/src/screens/HostDetail.tsx` · `w/src/api/schema.d.ts`, `w/src/screens/PackageSearch.tsx` | yes |
| W5 | TASK-125 | `w/src/components/TypeAhead.tsx`, `w/src/screens/PackageSearch.tsx`, `w/src/app/download.ts` | yes |
| W6 | TASK-126 | `w/src/main.tsx`, `w/src/app/{App,routes}.tsx` | yes |
| W7 | TASK-128; tester TP-M5-22 and the M5 gate | `README.md` | after M4's TASK-085 (same file); the gate needs nothing from M4 |

With one impl-web instance the web column is sequential in practice (W1 to W6 hold 12 web tasks); the waves show what a second impl-web instance could take in parallel without a file clash (for example TASK-118 to TASK-122 in W3).

### M5 gate

On a clean tree every command below is green, and each gate turns red on its planted violation. G7 to G11, G17 and G35 to G41 belong to M4 and are not re-run for M5 unless an M5 task touches their files (none does). "Local" is Windows 11 + Git Bash; "WSL" is WSL2 Ubuntu 24.04 with Docker.

| Gate | Command | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1 | `ruff check manager` | an f-string query in `bm/repositories/packages.py` (S608); `import re` in `bm/services/packages/query.py` | local |
| G2 | `ruff format --check manager` | one misformatted line in `bm/api/webui.py` | local |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` | an untyped function in `bm/services/packages/csv_export.py` | local |
| G4 | `pip install --require-hashes` of both locks | every hash of one dev package altered (M3 G4 rule) | local and CI |
| G5 | coverage of `bm/services` at 85 % or more, measured by the Linux run (speed rule 2) | an untested function in `bm/services/packages/search.py` sized from the clean report | WSL; CI |
| G6 | OpenAPI export, then `git diff --exit-code -- manager/openapi.json` plus the untracked check | the static routes included in the schema; `status` reverted to `str` without re-export | local |
| G12 | `cd web && npm run lint` | `dangerouslySetInnerHTML` in `Hosts.tsx`; `sessionStorage.setItem` in `session.ts`; a `fetch(` in `download.ts` | local and CI |
| G13 | `cd web && npm run typecheck` | a status label removed from `StatusBadge.tsx` (exhaustive map) | local and CI |
| G14 | `cd web && npm run format:check` | one misformatted line in `PackageSearch.tsx` | local and CI |
| G15 | `cd web && npm test` (every M5 UI suite) | the web rows of the mutation table | local and CI |
| G16 | G6, then `cd web && npm run gen:api`, then the diff and untracked check on `manager/openapi.json web/src/api/` | `manager/openapi.json` changed without regenerating the client | local and CI |
| G18 | `cd /root/bitscan/manager && CI=true python3.12 -m pytest -n auto --cov=bitscan_manager/services --cov-fail-under=85`: all pass, 0 skipped | any of G43 to G46 | WSL; CI |
| G42 | `cd web && npm run build`, then the bundle check on the built `index.html` (no `<script>` without `src`, no `<style>`, no `style=`, no URL with a scheme or `//`) | each REQ-119 (2) plant | local and CI |
| G43 | `… pytest tests/test_package_query.py tests/test_package_repo_pg.py tests/test_package_search_pg.py` | the G43 rows of the mutation table | WSL; CI |
| G44 | `… pytest tests/test_csv_export.py tests/test_package_search_csv_pg.py` | the G44 rows | WSL; CI |
| G45 | `… pytest tests/test_webui_serving.py` | the G45 rows | WSL; CI |
| G46 | `… pytest tests/test_security_m5.py tests/test_invariants_m3.py` | the G46 rows; the M3 G34 plants | WSL; CI |

No performance gate: the TS §7 "< 1 s" target has no TS §8.3 gate (testing.md open question), and the user deferred every load and long-running test until after M6 (2026-10-24).

### M5 mutation table (tester; CHK-M5-320 onwards)

Each row is planted in a throwaway copy and must turn the named gate red; at the gate it is re-planted only if its target code changed after it was last proven red (decisions 2026-10-23, "Targeted test runs").

| CHK | Plant | Red in | Code owned by |
| --- | --- | --- | --- |
| CHK-M5-320 | `version_op` compared as text (`p.version < %s`) | G43 | TASK-110 |
| CHK-M5-321 | `status` defaults to `any` | G43 | TASK-109 |
| CHK-M5-322 | `q` with `name` accepted | G43 | TASK-109 |
| CHK-M5-323 | `version_op` without `version` accepted | G43 | TASK-109 |
| CHK-M5-324 | a 2-character `q` accepted | G43 | TASK-109 |
| CHK-M5-325 | `%` and `_` in `q` not escaped | G43 | TASK-110 |
| CHK-M5-326 | `%` and `_` in `host` not escaped | G43 | TASK-110 |
| CHK-M5-327 | the text tie-breaker dropped from the order (`1.0` and `1.0-0` repeat or vanish across pages) | G43 | TASK-110 |
| CHK-M5-328 | the cursor scope ignores the filters (a cursor from another query is accepted) | G43 | TASK-113 |
| CHK-M5-329 | the #83 (e) agent scope removed | G43 | TASK-110 |
| CHK-M5-330 | an invalid `version` reaches the cast and answers 500 | G43 | TASK-109, TASK-113 |
| CHK-M5-331 | the `-` trigger removed from the CSV escape | G44 | TASK-111 |
| CHK-M5-332 | whitespace followed by a trigger not escaped | G44 | TASK-111 |
| CHK-M5-333 | the CSV route writes cells without the shared escape | G44 | TASK-114 |
| CHK-M5-334 | the CSV cap removed, or checked after streaming started | G44 | TASK-114 |
| CHK-M5-335 | `/packages/search` needs no role (any valid token) or accepts no token | G46 | TASK-113 |
| CHK-M5-336 | `bsa_` accepted on `/packages/search.csv` | G46 | TASK-114 |
| CHK-M5-337 | `/assets/{name}` resolves `..` or an encoded slash and serves a file outside the build | G45 | TASK-112 |
| CHK-M5-338 | a static route answered without the security headers (mounted outside the middleware) | G45 | TASK-112 |
| CHK-M5-339 | a catch-all returns `index.html` for unknown paths, including `/api/v1/unknown` | G45 | TASK-112 |
| CHK-M5-340 | an `Access-Control-Allow-Origin` header added to static responses | G45 | TASK-112 |
| CHK-M5-341 | the static routes included in the OpenAPI document | G6 | TASK-112 |
| CHK-M5-342 | the session token kept in `sessionStorage` (variable key, so lint stays green) | G15 | TASK-116 |
| CHK-M5-343 | the bearer header omitted on one route | G15 | TASK-116 |
| CHK-M5-344 | a 401 that does not clear the session | G15 | TASK-116 |
| CHK-M5-345 | a hostname rendered through `dangerouslySetInnerHTML` | G12, G15 | TASK-122 |
| CHK-M5-346 | the created `bse_` token kept in state after the result is closed | G15 | TASK-120 |
| CHK-M5-347 | `totp_session_required` answered with an API-token prompt | G15 | TASK-116, TASK-120 |
| CHK-M5-348 | the TOTP secret logged to the console | G15 | TASK-119 |
| CHK-M5-349 | an admin without TOTP can open the host list | G15 | TASK-126 |
| CHK-M5-350 | an inline `<script>` in `w/index.html` | G42 | TASK-115 |
| CHK-M5-351 | the CSV download built as a link to `/packages/search.csv` without the bearer header | G15 | TASK-125 |
| CHK-M5-352 | the search cursor carries the sort values instead of the id anchors (a 255-character non-ASCII package name on a page boundary makes the next page answer 400) | G43 | TASK-113 |
| CHK-M5-353 | a U+0000 in `q` (or any text parameter) reaches the database and answers 500 | G43 | TASK-109 |
| CHK-M5-354 | a 401 for a request sent with an older token clears the current session | G15 | TASK-116 |

### Open items for M5

All are in `work/open-questions.md`. "Needed by" is the start of the wave whose task cannot be finished without the answer.

| Item | Blocks | Needed by |
| --- | --- | --- |
| #83 (new): package search semantics (matching, order and cursor, `os`, `host`, agent scope, `hold ok installed`, version validity, lengths) | TASK-109, TASK-110, TP-M5-02, TP-M5-03 | W1 |
| #84 (new): CSV format, cap and headers | TASK-111 (escaping and quoting, W1), TASK-114 | W1 |
| #87 (new): stored versions the `debversion` comparison may refuse (the M3 decoder stores any storable text) | TASK-110 edge handling (none until answered); a possible M3 decoder follow-up | W1 (the TP-M5-03 probe answers the factual half) |
| #88 (new): empty search values and U+0000 | TASK-109, TP-M5-02 | W1 |
| #89 (new): M3 cursors can exceed the 512-character cursor limit | none in M5 (the search cursors use id anchors); an M3 follow-up for `/agents` and `/agents/{id}/packages` | after M5 (lead to schedule) |
| #6 (re-checked, M5 half): how the manager serves the UI; static files without a token | TASK-112 | W1 |
| PD-28 (new): web build, output folder, test and QR libraries, no browser automation | TASK-112, TASK-115, TASK-119 | W1 |
| PD-29 (new): which enums go into the contract | TASK-108 | W1 |
| #85 (new): sign-in and TOTP behaviours the spec leaves open | TASK-118, TASK-119 (W3), TASK-116 problem map (W1, adjustable) | W3 |
| #86 (new): package search UI reading (click-through, grouping) | TASK-124 | W4 |
| #32 (re-checked): type-ahead | TASK-125 | W5 |
| PD-30 (new): extra screens in M5; a second look at the web auth tasks | wave plan (W3 to W6 if screens are added); REVIEW of TASK-116, 118, 119 | W1 |
| testing.md performance-gate marker (re-checked) | none in M5: no gate, measurement after M6 (user, 2026-10-24) | after M6 |

### Coverage matrix (M5)

| Spec section | Covered by | Status in M5 |
| --- | --- | --- |
| TS §1.1 G3 (fleet-wide package search) | REQ-113 to REQ-116, REQ-129 to REQ-131 | Covered |
| TS §2.1 Web UI component (L101) | REQ-118 to REQ-133 | Hosts and package search covered; profiles, scans and results are **M7 to M11** |
| TS §2.3 every call carries a bearer token (L118) | REQ-118 (#6 (f) exception for the static files), REQ-120 | Covered, with the static-file exception for the owner (#6 (f)) |
| TS §3.2 step 1 (enrolment token in the UI, L181) and step 5 (approval screen, L185) and step 9 (cloned images, L192) | REQ-124, REQ-125 | Covered |
| TS §3.7 helper changes shown (L484) | REQ-127, REQ-128 (current `runner_helpers`) | Current list shown; the change history needs an audit-log screen (PD-30) |
| TS §5.2 inventory tables and indexes | REQ-114 | Read only, no migration |
| TS §6.2 sessions, TOTP, password (L1080–L1090, L1096–L1097) | REQ-120 to REQ-123, REQ-126, REQ-133 | Covered in the UI (routes are M2) |
| TS §6.2 `/packages/search`, `/packages/search.csv` (L1117) | REQ-113 to REQ-116 | Covered |
| TS §6.2 `/agents`, `/agents/{id}`, `/agents/{id}/packages`, `/enrollment-requests`, `/enrollment-tokens` (UI) | REQ-124, REQ-125, REQ-127, REQ-128 | Covered |
| TS §6.2 `/agents/{id}/tags`, `/agents/{id}/revoke`, `/api-tokens`, `/users`, `/settings`, `/audit-log` (UI) | none | **Uncovered in M5 by scope** (PD-30); routes exist since M2 and M3 |
| TS §6.2 `/agents/{id}/scans` and every policy, task, import, scan and schedule route | none | **M7 to M11** |
| TS §6.3 errors, pagination, rate limits, timestamps | REQ-113, REQ-115 (M2 machinery) | Covered for the new routes |
| TS §6.3 headers, CSP, no CORS (L1140) | REQ-118, REQ-119, REQ-134 | Covered, including the served UI |
| TS §6.3 plain text (L1141) | REQ-115 (4), REQ-132 | Covered |
| TS §6.3 CSV escaping (L1142) | REQ-116 | Covered for the only M5 export; the shared function is reused by M11 `results.csv` |
| TS §7 performance target (L1194) | none | **No gate** (testing.md open question); any timing at 20 M rows is after M6 (user, 2026-10-24) |
| TS §7.1 parameters and shapes | REQ-113, REQ-114 | Covered, with #83 |
| TS §7.2 version comparison | REQ-114 (2) | Covered through `debversion`; the ≥ 500-pair dpkg test is M1's |
| TS §7.3 UI (type-ahead, grouping, click-through, CSV, host page added/removed) | REQ-128 to REQ-131 | Covered, type-ahead per #32 |
| TS §7.4 v2 CVE matching | none | Out of scope (CLAUDE.md) |
| TS §8.1 stolen web session (XSS), SQL injection | REQ-115, REQ-120, REQ-132 | Covered |
| TS §8.2 TypeScript standards, generated client, reviews | REQ-119, REQ-136; owner notes | Covered; no two-approval task (PD-30) |
| TS §8.3 Unit (CSV escaping) | REQ-116 / G44 | Covered |
| TS §8.3 Integration (every endpoint) | TP-M5-06, TP-M5-07 | Covered for both package routes |
| TS §8.3 Security (tokens on the wrong route group) | REQ-115 / G46 | Covered for the new routes |
| TS §8.3 End-to-end, Load | none | 3-VM end-to-end is **M6**; the 10,000-agent load test is **after M6** (user, 2026-10-24) |
| TS §8.7 manager deployment (install method) | none | **M6** (#6 install half) |
| CLAUDE.md out of scope | none | Nothing planned: no policy editor, no CVE data, no signing, no OIDC |

**M6 items this user decision moves (2026-10-24, load and long-running tests deferred until after M6).** From the M6 scope in `work/decisions.md` (2026-10-20 reorder: "enrol, approve, heartbeat, inventory on 3 VMs, heartbeat load test, inventory alerts"), these leave M6 and run after it:
1. The TS §8.3 Load test: 10,000 simulated agents heartbeating, p95 under 200 ms.
2. The cost checks tied to that test (decisions 2026-10-23, W3 ruling (3)): the `inventory_snapshot` latest-snapshot lookup without an `agent_id` index (TASK-064) and the decoder's 64 MiB `bytes(out)` copy (TASK-060 review nit, also in `work/status.md` W2 "one memory nit carried to M6").
3. Any long-running agent idle or soak measurement beyond the single M4 recording (REQ-103 (6)).
4. Any timing of the TS §7 search target at 10,000 hosts × 2,000 packages (never gated; testing.md open question).

Staying in M6: the 3-VM end-to-end (enrol, approve, heartbeat, inventory) on amd64 Ubuntu 22.04 and 24.04 VMs (Hyper-V on the dev PC; Debian 12 was dropped from v1 on 2026-10-24, so PD-27's "real Debian 12 host in the M6 gate" no longer applies), the inventory alerts on real hosts, the release step (SHA-256 on a page from another origin), #28 and the N / N−1 marker before the first supported release, and the #6 install half.

## M6 first-release gate

Planned 2026-10-26 (planner-m6) in the worktree `Bitscan-m6` (branch `m6-release`, from main `8ad50eb`). Consistency pass done: every TASK links a REQ and every REQ has a TASK; waves are file-disjoint; every task is within 5 files and about 200 hand-written lines; the spine is acyclic; no gate is lowered. Plans: `work/plans/M6-e2e.md`, `work/plans/TASK-131.md`, `work/plans/TASK-133.md`, `work/plans/TASK-135.md`.

Scope: REQ-137 to REQ-149 in `work/requirements.md`. In this section `bm/` means `manager/bitscan_manager/`.

**Overnight approval (user, 2026-10-26).** This breakdown adds **no new spec deviation**, and every open question it raises or re-checks (#90–#96, #6, #28, #46, #89, the two `.claude/` own-question markers, PD-31, PD-32) carries a recommended answer in `work/open-questions.md`. The deviations it relies on are the recorded ones only: Debian 12 and arm64 dropped (decisions 2026-10-24), #82 purge, the D-Bus lintian overrides, the #6 static-file exception (TS §2.3 L118), and the trailing-slash 404 (decisions 2026-10-25).

**Wave 0 is the VM network check (TP-M6-01), and it gates the end-to-end items only.** It runs first. It proves with a real TLS listener on TCP 8443 that each VM reaches the manager address the end-to-end run will use, and that the tester reaches each VM. If it fails, TP-M6-10 to TP-M6-13 and gates G50 to G52 stop and wait for the user: no SSH tunnel, port forward, firewall, `.wslconfig` or admin change (decisions 2026-10-26 (4)); the tester records what failed and the options in `work/plans/M6-e2e.md` §6, and messages `main`. **No TASK needs VM → manager reachability**: W1 to W3 start at once, alongside W0, and so do TP-M6-00, -02 to -09 and the WSL rows of the gate (G41 included).

Rules every M6 task follows:
- **Testing by risk (user, 2026-10-25).** Low-risk tasks (docs, runbooks, CI workflows, packaging metadata, the manager paging fix) are tested and reviewed **per wave**: one test run and one review round for the wave's batch; planted faults only for security checks. **High-risk** tasks (here only TASK-132, agent) get full rigor per task: every plant, two review rounds if needed, and the TS §8.2 second approval. The milestone gate keeps its full plant table. Every change is still tested and reviewed before merge.
- **Speed rules (2026-10-24):** targeted tests per task or batch; the full manager suite (G18), `go test ./...` and the package tests at the gate and in CI; Python tests in WSL with `CI=true`; results as `passed/total`; a failure is re-run by its node id after the fix.
- No task adds a route, setting, flag or code path that queues a command, pushes to an agent, opens a listening socket on the agent, disables inventory, signs anything, or changes host settings from the manager (security invariants). Runbooks put no secret on a command line or in a plain environment variable.
- Implementers check `work/reviews/builder-checklist.md` before every hand-off. Manager code keeps `api → services → repositories` and parameterised SQL.
- Nobody pushes, merges or edits `.claude/` (decisions 2026-10-26 (5)).

### M6 tasks

| TASK | Title | REQ links | Area | Owner | Risk | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-129 | Manager wheel: the built UI (`bm/webui/**`, git-ignored, as hatch build artifacts), every migration file, no tests; version 0.1.0 | REQ-137, REQ-140 | manager | impl-manager | low (packaging metadata) | `manager/pyproject.toml` | none; #6 (M6 re-check) | 25 | After `npm run build`, `pip wheel --no-deps --no-build-isolation` of `manager/` (hatchling from the hashed dev lock) gives `bitscan_manager-0.1.0-py3-none-any.whl` listing `webui/index.html`, every asset and every migration file and no `tests/` path; installed with `--no-deps` into a fresh venv over the hashed runtime lock, it runs `db migrate` to head and serves the built `index.html` byte for byte at `/`. |
| TASK-130 | Agent 0.1.0-1: changelog entry on top; agent runbook for the first release (0.1.0 status, compliance answered `runner_unavailable` per #28, `SHA256SUMS` from the release page, upgrade order, compatibility) | REQ-142 | deploy | impl-deploy | low (packaging metadata, docs) | `deploy/debian/changelog`, `deploy/runbooks/agent-install.md` | none; #28, #90 | 50 (docs) | `build-deb.sh` produces `bitscan-agent_0.1.0-1_amd64.deb` whose agent reports 0.1.0-1; G37, G38 (with an upgrade from `0.1.0~pre1-1` keeping `agent_id`, `token` and `agent.yaml` byte-identical), G39 and G40 pass on it; the changed runbook sections behave as written on a VM. |
| TASK-131 | `/agents` and `/agents/{id}/packages` cursors carry only ids; the anchor's sort values are read in the same query; a vanished or foreign anchor is 400 (#89) (plan: `work/plans/TASK-131.md`) | REQ-143 | manager | impl-manager | low (paging; SQL plants only) | `bm/api/user/agents.py`, `bm/services/agents/fleet.py`, `bm/repositories/agents.py`, `bm/repositories/inventory.py` | none; #89 | 130 | Through the API on PostgreSQL, a 255-character non-ASCII hostname and package name on page boundaries page with every item once in the unchanged order, every returned cursor is at most 512 characters, a tampered, foreign-agent or vanished-anchor cursor answers 400, the M3 and M5 route suites pass, and `manager/openapi.json` is byte-identical. |
| TASK-132 | Agent lint: forbidigo also forbids `fcgi.Serve`, `net.FileConn` and `net.FilePacketConn` in non-test agent code (reviewer TASK-004 residuals) | REQ-144 | agent | impl-agent | **high** (agent; two approvals) | `agent/.golangci.yml` | none | 12 | G8 passes on the tree and goes red, with the configured message, on each of the three calls planted in a non-test file under `agent/internal/agent/`; no existing rule is removed or narrowed; the nolint grep and G36 pass. |
| TASK-133 | Manager install runbook: release-file check, PostgreSQL 16 and TLS-only roles, the TS §5.2 Bootstrap copied byte for byte, user, folders, `manager.env`, secrets, venv and `/usr/bin/bitscan-manager`, units copied unchanged, migrate, maintain timer, start, `/readyz`, first admin and TOTP (plan: `work/plans/TASK-133.md`) | REQ-138, REQ-140 | deploy | impl-deploy | low (docs; walk-tested) | `deploy/runbooks/manager-install.md` | TASK-129; #6, #46, #93 | 200 (docs) | The tester follows it on a fresh systemd-enabled Ubuntu 24.04 manager host (#93) and every step behaves as written, ending with a host that meets REQ-140 (verbatim units, `systemd-analyze verify` clean, migrate, maintain and serve under their units, no capabilities, writes only in the two `ReadWritePaths`, `migrate.dsn` unreadable to the manager user), with a Bootstrap block byte-identical to TS §5.2 and no secret on any command line. |
| TASK-134 | Manager upgrade and operations runbook: upgrade order, compatibility rule, certificate replacement (#96), OpenBao token replacement, backups and the monthly restore test, removal (layout from `work/plans/TASK-133.md`) | REQ-139 | deploy | impl-deploy | low (docs) | `deploy/runbooks/manager-operations.md` | TASK-129; TASK-133's plan (written in parallel against it; TESTed after TASK-133 IMPL); #96 | 130 (docs) | On the TASK-133 host, the upgrade section (the same wheel re-installed) leaves the head unchanged, restarts the service and keeps an enrolled agent heartbeating without re-enrolment; the certificate step the #96 fact check selects makes new connections present the new certificate; a backup taken as written restores into a scratch database at head. |
| TASK-135 | Release workflow: version agreement (tag, changelog, `pyproject.toml`), double `.deb` build and compare, UI build and wheel with a UI check, runtime lock copy, the four manager unit files, `SHA256SUMS`, draft GitHub release with the sums in its notes; pinned actions, least privilege (plan: `work/plans/TASK-135.md`) | REQ-141 | deploy | impl-deploy | low (CI; security plants only) | `.github/workflows/release.yml` | TASK-129, TASK-130; #90, #91 | 160 | actionlint is clean, every action is pinned by commit, only the publish job can write and the release is a draft; the build job's commands run locally produce the plan's file list, `sha256sum -c SHA256SUMS` passes and the two `.deb` builds are identical; a tag/changelog mismatch, a wheel without the UI, a file changed after `SHA256SUMS` and a tag-pinned action each turn it red. |
| TASK-136 | Release workflow: manager SBOMs (CycloneDX from the hashed runtime lock; `npm sbom` for the bundled UI runtime packages), added to `SHA256SUMS` (#92) | REQ-141 | deploy | impl-deploy | low (CI) | `.github/workflows/release.yml` | TASK-135; #92 | 60 | The two SBOMs list every `requirements.txt` package with version and hash and every bundled UI runtime package with its version, both are in `SHA256SUMS`, and a package dropped from either SBOM turns the completeness check red. |
| TASK-137 | README for the first release: 0.1.0 status, links to the three runbooks, release verification, versions and the compatibility rule; remove the "no production install method" and "agent does not run" lines | REQ-145 | manager | impl-manager | low (docs) | `README.md` | TASK-133, TASK-134, TASK-135 | 70 (docs) | The tester follows every changed section against the TASK-133 host; every link resolves and each step behaves as written; no statement contradicts a runbook or the spec; no secret, task id or process note. |

Totals: 13 REQ (REQ-137 to REQ-149), 9 TASK (TASK-129 to TASK-137), 15 test-plan items (TP-M6-00 to TP-M6-14), 5 waves (W0 to W4) plus the gate. One high-risk task (TASK-132). No task needs VM → manager reachability.

REQ to TASK: REQ-137 TASK-129; REQ-138 TASK-133; REQ-139 TASK-134; REQ-140 TASK-129, TASK-133; REQ-141 TASK-135, TASK-136; REQ-142 TASK-130; REQ-143 TASK-131; REQ-144 TASK-132; REQ-145 TASK-137; REQ-146 TASK-130, TASK-133, TASK-135 (the release candidate and the installed manager it accepts); REQ-147 TASK-133 (the installed manager with its sink; the alert code is M3's, unchanged); REQ-148 TASK-130, TASK-133; REQ-149 TASK-130. REQ-146 to REQ-149 are acceptance requirements: they change no code and are proven by TP-M6-10 to TP-M6-13 on the files those tasks deliver. Every M6 REQ has at least one TASK, and every TASK has at least one REQ.

### M6 owner and review notes

- **Owners:** impl-manager: TASK-129, 131, 137. impl-deploy: TASK-130, 133, 134, 135, 136 (sequential in practice; TASK-133 first in W2, because the end-to-end run needs the installed manager). impl-agent: TASK-132. impl-web: no M6 task (no web file changes; the wheel carries the existing build). The tester owns every test file and fixture (`manager/tests/`, `deploy/tests/`, `e2e/m6/`, `tests/m6/`), the manager-host container image, the test CA and the test doubles.
- **Two approvals (TS §8.2 L1268):** TASK-132 (agent). No M6 task touches auth, the importer or the runner. TASK-130 changes only the version line the build injects, not agent code (the TASK-092 rule). If the end-to-end run finds a defect whose fix touches the agent or auth, that fix task joins this list. The user's second approval applies under the overnight rule only on a clean TEST PASS plus "APPROVED, no open blocking or should-fix findings" (decisions 2026-10-26 (3)).
- **Second look (PD-32, recommended none):** TASK-133 handles secrets and database roles in prose only and is walk-tested; the reviewer checks every path, owner and mode against TS §8.7 L1344–L1345 line by line.
- **Shared files, never in the same wave:** `.github/workflows/release.yml` (TASK-135 W2, TASK-136 W3); `README.md` (TASK-137 only); `deploy/runbooks/agent-install.md` (TASK-130 only). TASK-131's four files are touched by no other M6 task.
- **No new folders (PD-31):** release helpers stay inline in `release.yml` (as TASK-127 did in `web.yml`); the runbooks are files in `deploy/runbooks/`. The `.claude/` marker updates that follow the answers (#6 in `packaging-and-units.md`, the N / N−1 line in `CLAUDE.md`, the performance marker in `testing.md`) are left for the user.
- Planted violations are made in a throwaway copy, a throwaway image or a throwaway VM state, never left in the tree; every VM is restored to `clean` afterwards.

### M6 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m6/test-plan.md`, check ids `CHK-M6-###`; suggested ranges: 001–019 network check, 020–039 wheel, 040–079 install walk and REQ-140, 080–099 operations, 100–119 package and release, 120–139 cursors, 140–149 lint, 150–159 README, 200–259 end-to-end, 260–279 alerts and metrics, 280–299 security subset, 300–309 idle cost, 310–319 gate rows, 320 on the mutation table). "WSL" is WSL2 Ubuntu 24.04 (mirrored networking, systemd, Docker); "VM" is a Hyper-V VM reached from Windows `ssh`/`scp` (or `ssh.exe` through WSL interop; WSL itself has no route to the VMs).

| TP | What | REQ | Runs in | Needs VM → manager | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| TP-M6-00 | Phase test plan and the M6 index row | all M6 | phase start; report at the gate | no | `tests/m6/test-plan.md`, `tests/test-plan.md` | none |
| TP-M6-01 | **Wave 0 network check** (`work/plans/M6-e2e.md` §2): restore `clean`, IPs by MAC, tester → VM (SSH, `scp`, checksum), a TLS listener on WSL `0.0.0.0:8443` and one published from a container on 8443, each reached from both VMs by name (handshake and one GET), a control port, VM → Ubuntu archive | REQ-146 (0) | W0 | **it is the check** | `e2e/m6/netcheck.sh` | none |
| TP-M6-02 | Wheel build, contents, fresh-venv install, `db migrate`, `serve` of `/` (G47) | REQ-137 | TASK-129 TEST | no | `deploy/tests/test_manager_wheel.sh` | TASK-129 IMPL |
| TP-M6-03 | Manager install walk on a fresh manager host and the REQ-140 checks (G48): verbatim manager units, `systemd-analyze verify`, unit runs, capabilities, write sweep, credential isolation; the Bootstrap byte check | REQ-138, REQ-140 | TASK-133 TEST | no | `e2e/m6/manager-host.Dockerfile`, `deploy/tests/check_manager_host.sh`, `deploy/tests/check_runbook_bootstrap.py` | TP-M6-02 |
| TP-M6-04 | Operations walk: upgrade, certificate reload, backup and restore | REQ-139 | TASK-134 TEST | no | none in the tree (evidence) | TP-M6-03 |
| TP-M6-05 | 0.1.0-1 package gates G37–G40, G38 upgrade from `0.1.0~pre1-1`; runbook sections (walked on a VM in TP-M6-10) | REQ-142 | TASK-130 TEST | no (runbook walk: yes, in TP-M6-10) | `deploy/tests/test_maintainer_scripts.sh` (extend: upgrade from a named older `.deb`) | TASK-130 IMPL |
| TP-M6-06 | Release workflow: actionlint, pin and permission checks, the build job's commands run locally, `SHA256SUMS`, plants (G49) | REQ-141 | TASK-135 and TASK-136 TEST | no | `deploy/tests/check_release_workflow.py` | TASK-135 IMPL |
| TP-M6-07 | Cursor suite on PostgreSQL (G53): boundary rows, cursor length, refusals, the M3 and M5 route suites | REQ-143 | TASK-131 TEST | no | `manager/tests/test_agent_cursors_pg.py` | TASK-131 IMPL |
| TP-M6-08 | Lint plants (G8) and G36 | REQ-144 | TASK-132 TEST | no | none in the tree (evidence) | TASK-132 IMPL |
| TP-M6-09 | README walk against the TP-M6-03 host | REQ-145 | TASK-137 TEST | no | none in the tree (evidence) | TP-M6-03 |
| TP-M6-10 | **End-to-end gate on both VMs** (G50), phase A and the revoke and purge of `work/plans/M6-e2e.md` §4 | REQ-146 | W4 | **yes** | `e2e/m6/e2e_vms.py`, `e2e/m6/vm.sh` | TP-M6-01 PASS, TP-M6-03 PASS, TP-M6-05 |
| TP-M6-11 | Alerts and metrics on real hosts (G51), phase B | REQ-147 | W4 | **yes** | `e2e/m6/e2e_vms.py` | TP-M6-10 phase A |
| TP-M6-12 | Security subset on real hosts (G52) | REQ-148 | W4 | **yes** | `e2e/m6/e2e_vms.py` | TP-M6-10 phase A |
| TP-M6-13 | Agent idle cost on u2404 (#95; recorded, no gate) | REQ-149 | W4 | **yes** | `e2e/m6/idle_cost.sh` | TP-M6-10 phase A |
| TP-M6-14 | M6 gate: the gate table below, the mutation table, G41 on the RC `.deb`, and the check that the RC `.deb` tested on the VMs has the SHA-256 the release build produces | REQ-137 to REQ-149 | M6 gate | G50–G52 rows only | as above | all above |

### M6 waves and dependency spine

Spine: `TASK-129 → TASK-133 → TASK-134`; `TASK-129, TASK-130 → TASK-135 → TASK-136`; `TASK-133, TASK-134, TASK-135 → TASK-137`; `TP-M6-01 PASS + TASK-129 + TASK-130 + TASK-133 (TEST PASS) → TP-M6-10 → TP-M6-11, -12, -13 → gate`. TASK-131 and TASK-132 depend on nothing. The graph is acyclic.

Interface first: TASK-129 fixes the wheel's name and contents (W1) before the runbooks and the release workflow consume them; `work/plans/TASK-133.md` fixes the host layout (paths, owners, modes, unit location, venv) before TASK-134 and TASK-137; `work/plans/TASK-135.md` fixes the release file names before TASK-136, TASK-137 and the end-to-end run.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) | Needs VM → manager? |
| --- | --- | --- | --- |
| W0 | tester TP-M6-00, **TP-M6-01 (network check)** | `tests/m6/test-plan.md`, `tests/test-plan.md`, `e2e/m6/netcheck.sh` | it is the check |
| W1 (starts with W0) | TASK-129, 130, 131, 132 | `manager/pyproject.toml` · `deploy/debian/changelog`, `deploy/runbooks/agent-install.md` · `bm/api/user/agents.py`, `bm/services/agents/fleet.py`, `bm/repositories/agents.py`, `bm/repositories/inventory.py` · `agent/.golangci.yml` | no |
| W2 | TASK-133 (first), 134, 135 | `deploy/runbooks/manager-install.md` · `deploy/runbooks/manager-operations.md` · `.github/workflows/release.yml` | no |
| W3 | TASK-136, 137 | `.github/workflows/release.yml` · `README.md` | no |
| W4 | tester TP-M6-10 to TP-M6-13 (may start once TASK-133 is TEST PASS; it does not wait for W3) | `e2e/m6/{e2e_vms.py,vm.sh,idle_cost.sh}` | **yes** (stops if W0 failed) |
| Gate | tester TP-M6-14; reviewer's M6 closing review | tester files only | G50–G52 rows only |

Per-wave batches under testing by risk: W1 low-risk batch = TASK-129, 130, 131 (one test run, one review round); TASK-132 alone with full rigor. W2 batch = TASK-133, 134, 135. W3 batch = TASK-136, 137.

### M6 gate

On a clean tree every command is green, and each gate turns red on its planted violation. Gates for areas M6 does not touch (G12–G16 web) are not re-run, as in M5; G42 runs on the `index.html` inside the wheel (part of G47).

| Gate | Command (summary) | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1–G4 | ruff, ruff format, `mypy --strict`, hashed locks (for TASK-129 and TASK-131) | an f-string query in `bm/repositories/agents.py` (S608) | local; CI |
| G5 | services coverage ≥ 85 % (Linux run, `precision = 2`) | an untested function sized from the clean report | WSL; CI |
| G6 | OpenAPI export byte-identical | a cursor field added to a response model | local; CI |
| G7–G11 | gofmt, golangci-lint + nolint grep, `go mod download` + `verify`, static amd64 build, `go test -race ./...` | the CHK-M6-337..339 rows (G8); M4 plants stand (agent code unchanged) | WSL; CI |
| G17 | units and D-Bus verbatim; `systemd-analyze verify` on the agent units and, new in M6, on the manager units with the real binary installed (no "not executable" lines) | one character changed in `bitscan-manager.service` | WSL; CI |
| G18 | full manager suite, 0 skipped | any of G53's rows | WSL; CI |
| G35, G36 | Go contract and agent security subset (re-run once: TASK-132 touches agent lint) | M4 rows stand (agent code unchanged) | WSL; CI |
| G37–G40 | lintian, maintainer scripts (with the pre1 → 0.1.0-1 upgrade), reproducible double build, SBOM, on 0.1.0-1 | the M4 rows, re-planted only where `changelog` or a script changed | WSL; CI |
| G41 | `e2e/agent_manager.sh` on the 0.1.0-1 `.deb` against the manager in WSL (regression; needs no VM) | the reverse-order `list_sha256` `.deb` | WSL |
| G47 | wheel: build, contents, fresh-venv install, `db migrate`, `serve` of `/`, G42 on the wheel's `index.html` | CHK-M6-320..322 | WSL |
| G48 | manager install walk and REQ-140 checks on a fresh manager host | CHK-M6-323..326 | WSL (container) |
| G49 | release workflow checks and the local build of the release files | CHK-M6-327..332 | WSL; CI on push (NOT RUN until pushed) |
| G50 | end-to-end on both VMs (TP-M6-10) | CHK-M6-340 | VMs + WSL |
| G51 | alerts and metrics on real hosts (TP-M6-11) | CHK-M6-342, -343 | VMs + WSL |
| G52 | security subset on real hosts (TP-M6-12) | CHK-M6-341, -344, -345 | VMs + WSL |
| G53 | `pytest tests/test_agent_cursors_pg.py` plus the M3 and M5 `/agents` suites | CHK-M6-333..336 | WSL; CI |
| — | idle cost (TP-M6-13): recorded against the TS §3.3 target, **no gate** (testing.md own question, #95) | none | VM |

**No gate is lowered.** NOT RUN, with reasons, at the gate: the 10,000-agent load test, soak tests, the TASK-060 and TASK-064 cost checks, the CSV memory check and the TS §7 search timing (deferred until after M6 by the user, 2026-10-24); `new_packages_burst` on a real host (#94: proven at integration level in M3; over 1,000 package installs on a 2 GB VM is a long-running step); the GitHub runs of every workflow and the release publication (no push authorised overnight); the user's optional browser approval (#93 (f)); Debian 12 and arm64 (dropped from v1). If W0 fails, G50–G52 and the idle measurement are NOT RUN (waiting for the user), and the gate cannot pass until they are run.

### M6 mutation table (tester; CHK-M6-320 onwards)

Each row is planted in a throwaway copy, image or VM state and must turn the named gate red. Real-host rows (340–345) run as targeted mini-runs on one VM, only the rows they target.

| CHK | Plant | Red in | Target |
| --- | --- | --- | --- |
| CHK-M6-320 | the UI dropped from the wheel (the artifacts line removed) | G47 (`/` answers 404) | TASK-129 |
| CHK-M6-321 | migration files dropped from the wheel | G47 (`db migrate` fails) | TASK-129 |
| CHK-M6-322 | `tests/` packed into the wheel | G47 | TASK-129 |
| CHK-M6-323 | one character of the runbook's Bootstrap block changed | G48 | TASK-133 |
| CHK-M6-324 | the runbook makes `/etc/bitscan/secrets` 0755 or `manager.env` 0644 | G48 (mode rows) | TASK-133 |
| CHK-M6-325 | `LoadCredential=migrate_dsn:…` added to the installed `bitscan-manager.service` | G48 (verbatim and credential rows) | TASK-133 |
| CHK-M6-326 | `ReadWritePaths` widened to `/var/lib/bitscan` in the installed unit | G48 (verbatim and write-sweep rows) | TASK-133 |
| CHK-M6-327 | the tag/changelog/pyproject agreement check removed | G49 | TASK-135 |
| CHK-M6-328 | one action pinned by tag instead of commit | G49 | TASK-135 |
| CHK-M6-329 | the release created without `--draft`, or `contents: write` at workflow level | G49 | TASK-135 |
| CHK-M6-330 | `SHA256SUMS` written before the last file (a released file missing from it) | G49 (completeness) | TASK-135 |
| CHK-M6-331 | a wheel without `webui/index.html` accepted | G49 | TASK-135 |
| CHK-M6-332 | a `requirements.txt` package missing from the manager SBOM | G49 | TASK-136 |
| CHK-M6-333 | the `/agents` cursor carries the hostname again | G53 (255-character non-ASCII boundary) | TASK-131 |
| CHK-M6-334 | the anchor lookup built with an f-string | G1 (S608) | TASK-131 |
| CHK-M6-335 | a vanished package anchor answers 500 (no refusal) | G53 | TASK-131 |
| CHK-M6-336 | a package cursor accepted for another agent's list | G53 | TASK-131 |
| CHK-M6-337 | `fcgi.Serve` in a non-test agent file | G8 | TASK-132 |
| CHK-M6-338 | `net.FileConn` in a non-test agent file | G8 | TASK-132 |
| CHK-M6-339 | `net.FilePacketConn` in a non-test agent file | G8 | TASK-132 |
| CHK-M6-340 | the RC agent built with `list_sha256` lines in reverse order | G50 (422 `hash_mismatch`; the chain stops at the snapshot row) | E2E harness |
| CHK-M6-341 | the RC agent built with the pin check skipped | G52 (wrong-pin row: requests reach the manager) | E2E harness |
| CHK-M6-342 | the installed manager's clock-skew threshold raised to 10 minutes | G51 (no `clock_skew` entry at +6 minutes) | E2E harness |
| CHK-M6-343 | the installed manager writes the runner-helper alert without `detail.alert` | G51 (sink and metric rows) | E2E harness |
| CHK-M6-344 | the installed manager accepts a `bsa_` token on a user route | G52 (route-group row) | E2E harness |
| CHK-M6-345 | the RC agent logs its token at start-up | G52 (journal canary) | E2E harness |

### Open items for M6

All are in `work/open-questions.md`, each with a recommended answer. "Needed by" is the start of the wave whose task or test cannot finish without the answer.

| Item | Blocks | Needed by |
| --- | --- | --- |
| #6 (M6 re-check, install half): wheel, venv under `/opt`, `/usr/bin` link, units under `/etc/systemd/system`, Ubuntu 24.04 manager host | TASK-129, TASK-133, TASK-134 | W1 |
| #46 (M6 re-check): the Bootstrap copy and role authentication | TASK-133 | W2 |
| #90 (new): the M6 release is the first supported release, 0.1.0 | TASK-130, TASK-135, TASK-137 | W1 |
| #91 (new): release page and download origin; who publishes | TASK-135 | W2 |
| #92 (new): manager SBOM | TASK-136 | W3 |
| #93 (new): end-to-end environment (manager host, test doubles, CA and names, approval through the API) | TASK-133 walk, TP-M6-01, TP-M6-03, TP-M6-10 | W0 |
| #94 (new): which alerts are proven on real hosts | TP-M6-11 | W4 |
| #95 (new): idle-cost method and no gate | TP-M6-13 | W4 |
| #96 (new): does `systemctl reload` refresh `LoadCredential=` copies (certificate replacement)? Fact first | TASK-134, TP-M6-04 | W2 |
| #28 (M6 re-check): runner unavailable, before the first supported release | TASK-130 (runbook text) | W1 |
| CLAUDE.md N / N−1 marker (M6 re-check) | TASK-130, TASK-134, TASK-137 (compatibility text) | W1 |
| testing.md performance marker (M6 re-check) | TP-M6-13 | W4 |
| #89 (scheduled in M6) | TASK-131 | W1 |
| PD-31 (new): no new folders; `.claude/` edits left for the user | TASK-135, TASK-136 | W2 |
| PD-32 (new): second looks | REVIEW of TASK-133 | W2 |

### Coverage matrix (M6)

| Spec section | Covered by | Status in M6 |
| --- | --- | --- |
| TS §1.1 G1, G2, G3 on real hosts | REQ-146, REQ-147, REQ-148 | Covered (inventory half) |
| TS §1.2 L25 (no signed APT repository; `.deb` with a published SHA-256) | REQ-141 | Covered; no APT repository planned |
| TS §2.2 (pull only, no listening port) | REQ-144, REQ-148 (5) | Covered |
| TS §2.3 L118 (bearer token on every call) | REQ-148 (3) | Covered on the real manager; the static UI files keep the recorded #6 (f) exception |
| TS §3 intro L152 (cgroup v2; `runner_unavailable`) | REQ-146 (1), REQ-142 (#28 text) | Hosts checked for cgroup v2; the runner itself is **M10** |
| TS §3.1 install, distribution, uninstall | REQ-141, REQ-142, REQ-146 (2), (3), (10) | Covered |
| TS §3.2 enrolment, approval, machine-id, cloned images, transport | REQ-146 (4), (5), REQ-147 (3), REQ-148 (1), (2) | Covered on real hosts; rotation stays proven by M3/M4 tests (a 335-day wait) |
| TS §3.3 loops, status, clock skew, idle | REQ-146 (5), (11), REQ-147 (1), REQ-149 | Covered; idle recorded, no gate |
| TS §3.4 inventory, watcher, alerts | REQ-146 (6), (8), REQ-147 (4) | Covered; `new_packages_burst` on real hosts NOT RUN (#94) |
| TS §3.5, §3.6, §3.7 runner, capread, sandbox behaviour | REQ-147 (2) (helper detection only) | **M10** |
| TS §4 compliance engine | none | **M7 to M11** |
| TS §5.2 Bootstrap; §5.3 roles over TLS, backups | REQ-138 (3), (4), REQ-139 (3) | Covered |
| TS §6.2 `/agents`, `/agents/{id}/packages` paging (L1108, L1110), §6.3 L1134 | REQ-143 | Covered (#89) |
| TS §7 performance target (L1194) | none | NOT RUN: deferred with the load tests (user, 2026-10-24) |
| TS §8.1 supply chain (L1258), tampered job in transit (L1247), secrets in config (L1259) | REQ-141, REQ-148, REQ-138 (5) | Covered |
| TS §8.2 semantic versioning, N / N−1 (L1267), two approvals (L1268) | REQ-141, REQ-142, REQ-145; owner notes | Covered; the N / N−1 test itself has nothing to run until a second supported release (M6 re-check) |
| TS §8.3 End-to-end (L1281) | REQ-146 | Inventory half on 3 VMs (the WSL2 manager VM and the two agent VMs); nightly scheduling and import → scan → results are **M11** |
| TS §8.3 Load (L1282) | none | NOT RUN: deferred until after M6 (user, 2026-10-24) |
| TS §8.3 Security (L1283) | REQ-148, REQ-144 | Agent and route-group subset on real hosts; runner half **M10**, importer half **M7** |
| TS §8.3 Sandbox (L1280) | REQ-140 (2), G17 | Unit verification only (manager units now with the real binary); the plugin-cannot list is **M10** |
| TS §8.3 Packaging and release | REQ-141, REQ-142 / G37–G40, G49 | Covered |
| TS §8.4 alerts, metrics, health | REQ-147, REQ-140 (4) | Covered for the inventory-era alerts; compliance alerts are **M7 to M11** |
| TS §8.6 start-up configuration | REQ-138 | Covered |
| TS §8.7 deployment, units, CLI, upgrade order | REQ-137 to REQ-140, REQ-139 | Covered (#6 install half) |
| CLAUDE.md out of scope | none | Nothing planned: no signed APT repository, no signing, no client certificates, no OIDC, no policy editor |
## M7 compliance catalog (`.bit` importer and validator)

Planned 2026-10-27 (planner-m7) in the worktree `Bitscan-m7` (branch `m7-catalog`, from main `8ad50eb`). Numbering continues after M6 (TASK-138, G53, `Bitscan-m6`, not merged). Consistency pass done: every TASK links a REQ and every REQ has a TASK; waves are file-disjoint; every task is within 5 files and about 200 hand-written lines; the spine is acyclic; no gate is lowered. Summary for the user: `work/plans/M7-breakdown.md`.

Scope: REQ-150 to REQ-185 in `work/requirements.md`. In this section `bm/` means `manager/bitscan_manager/`.

**No new spec deviation.** Every open item (#98 to #111 new; #1, #2, #9, #10, #11, #13 to #17, #20, #21, #23, #27 re-checked; PD-33 to PD-36) carries a recommended answer in `work/open-questions.md` ("M7"). **No migration and no agent change.**

Rules every M7 task follows:
- **Testing by risk (user, 2026-10-25).** The importer is a high-risk area: every importer task gets full rigor per task (every plant, a second review round if needed) and the TS §8.2 second approval, batched once per wave (speed rule). Low-risk tasks (the profile reads, the import history route, README, web screens, samples) are tested and reviewed per wave as one batch, with planted faults only for security checks (RBAC, route group, plain-text rendering, BIT102 in samples).
- **Time-skewing (user, 2026-10-26):** tests never wait out a timer; they use the `Clock` fake or a backdated row in the throwaway database. No product code gains a test mode.
- Services take repositories and the catalog session through `Protocol`s, so the parser, validators, lexer and alert builders are unit-tested without PostgreSQL (the G5 gate on Windows), and every time-based rule reads the `Clock`.
- `api → services → repositories`; route handlers only validate, authorise and call `CatalogService` or `profiles`. Parameterised SQL only (ruff S608). `defusedxml` only (ruff bans `xml.*`, `lxml`); RE2 only (ruff bans `re`).
- Every route task re-exports `manager/openapi.json` in the same task (G6); `web/src/api/schema.d.ts` is regenerated once, in TASK-168 (PD-20). One route task per wave (PD-24 option (a)).
- No task adds a route, setting or code path that queues or runs a command, edits plugins or commands, signs anything, adds an approval step, or changes host settings. Catalog code never touches `agent`, inventory or results tables; the only scan-side writes are the TS §4.3 delete effects (REQ-167).
- Implementers check `work/reviews/builder-checklist.md` before every hand-off.

### M7 design notes (for the five tasks with real design risk)

The planner writes these out as `work/plans/TASK-141.md`, `TASK-145.md`, `TASK-151.md`, `TASK-154.md` and `TASK-162.md` once the breakdown is approved (PD-36); the notes below fix their interfaces now.
- **D1 parser (TASK-141).** One pass over the read buffer: refuse a UTF-16 or UTF-32 BOM, a declared encoding other than UTF-8 and invalid UTF-8 (strict decode, line of the first bad byte), all BIT001, before XML parsing. Then `defusedxml.ElementTree.DefusedXMLParser(target=<collector>, forbid_dtd=True, forbid_entities=True, forbid_external=True)` fed the buffer once; the collector builds `Node`s with the expat `CurrentLineNumber` at each start tag, keeps comments out, records processing instructions and text for TASK-143, and stops at the #105 element and depth caps. `DTDForbidden`, `EntitiesForbidden`, `ExternalReferenceForbidden`, `ParseError` and the caps all become one BIT001 finding with the line when known. No other XML library is imported.
- **D2 lexer (TASK-145).** A hand-written state machine after POSIX XCU §2.3 (token recognition) and §2.6.3 (command substitution); `shlex` is not used (it handles neither `$( )`, backticks nor here-documents). Output: a list of simple commands, each with assignments, words (as parts: literal, single-quoted, double-quoted, substitution holding a nested script), redirections (descriptor, operator, target word) and the operator that ends it; reserved words (`if`, `then`, `do`, `case`, `{` …) are kept so TASK-146 knows the command position. Unquoted here-document bodies are scanned for substitutions; quoted ones are data. Anything unexpected raises one fail-closed error that TASK-146 reports as BIT102.
- **D3 store (TASK-151).** Inside the caller's transaction: lock the candidate rows (`SELECT … FOR UPDATE` by name and by `source_file`), decide the case (update, rename in place, #106 collision, revival, insert, BIT007, server-folder move), run BIT015 for all ids in one query, and return findings without writing if any Reject. Writes: `family` by `INSERT … ON CONFLICT DO NOTHING` then `SELECT`; `policy` with `policy_status = CASE WHEN status_overridden THEN policy_status ELSE <file value> END` in the UPDATE itself, so a concurrent PATCH is never lost; plugins by `INSERT … ON CONFLICT (plugin_uuid) DO UPDATE … WHERE (…) IS DISTINCT FROM (…)` so `plugins_updated` counts only real changes (#21); `policy_plugin` DELETE and INSERT; one retire UPDATE.
- **D4 lock and transactions (TASK-147, TASK-154).** Parse, structure, validate and BIT102 run before the lock (pure, bounded). Then one pinned session: `pg_advisory_lock` → transaction 1 (DB rules, store, the success alert; for an upload the temp-file write just before commit) → commit → upload rename or file deletion → transaction 2 (`bit_import`, and for a rejection its alert; the failure counter on commit) → `pg_advisory_unlock` in a `finally`. An internal error (database or disk) is not a rejection (#98 (j)).
- **D5 multipart (TASK-162).** The route takes the raw `Request`; the body is already in memory and capped by `BodyLimit` (the `bit` class, #99 allowance); python-multipart's low-level `MultipartParser` runs over those bytes with callbacks, so nothing is spooled to disk. Exactly one part, named `file`; its bytes go to `CatalogService.upload`. The OpenAPI request body (`multipart/form-data`, `file`: binary) is declared through `openapi_extra`.

### M7 tasks

| TASK | Title | REQ links | Area | Owner | Risk | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-139 | Runtime dependencies for M7 (PD-33): `python-multipart` for in-memory multipart parsing; both hashed locks regenerated with the recorded command | REQ-185 | manager | impl-manager | low (dependency; second look, PD-35) | `manager/pyproject.toml`, `manager/requirements.txt`, `manager/requirements-dev.txt` | none; PD-33 | 10 (+2 generated) | In fresh CPython 3.12 venvs on Windows and Linux, `pip install --require-hashes` of each lock exits 0, `import python_multipart` works (the module name since python-multipart 0.0.13; the `multipart` alias is deprecated and not used), the runtime lock names no test or lint tool, and the recorded lock command reproduces both files byte for byte. |
| TASK-140 | Importer model: `Finding` (`line`, `element`, `code`, `message`, severity), the code table (BIT001–BIT017, BIT101–BIT103 with their SR severities; retired codes absent), the SR §2 limits, `Node`, `ParsedPolicy`, `ParsedPlugin` | REQ-152, REQ-155 | manager | impl-manager | **high** (importer; two approvals) | `bm/services/importer/__init__.py`, `bm/services/importer/model.py` | none | 140 | Unit: every SR §4.1 code has its SR severity, BIT006, BIT009 and BIT018–BIT020 are absent, each limit equals its SR §2 value, a `Finding` serialises to exactly `{line, element, code, message}`, and the module passes `mypy --strict` with frozen dataclasses. |
| TASK-141 | Safe parser (BIT001) per design note D1: UTF-8 checks, `defusedxml` with DTD, entities and external references forbidden, 5 MiB, #105 caps, start-tag lines, `Node` tree out | REQ-150, REQ-176, REQ-180 | manager | impl-manager | **high** | `bm/services/importer/parse.py` | TASK-140; #57, #105 | 170 | Every BIT001 fixture (external entity by file and by URL, parameter entity, billion laughs, quadratic blow-up, DTD only, UTF-16, ISO-8859-1, invalid UTF-8, not well-formed, empty, 5 MiB + 1 byte) gives exactly one BIT001 finding with no file or network access and under 64 MiB peak memory; a valid 5 MiB file parses; the SR §1.1 example gives a `Node` tree whose lines match the file; 10,000 random inputs raise nothing. |
| TASK-142 | Value helpers shared with M8: XML-whitespace trimming (#17), the #13 number grammar, the RE2 compile helper for BIT013 (the evaluator's form, no error logging), the #109 UUID check, `control_ref` (ASCII digits) | REQ-152, REQ-153, REQ-154 | manager | impl-manager | **high** | `bm/services/importer/values.py` | TASK-140; #13, #17, #109 | 110 | Unit tables: the #13 accept and reject lists; `(?=x)` and `(a)\1` refused while `^MaxAuthTries\s+[1-4]$` compiles; the #109 forms; `control_ref` for every REQ-154 (1) case; trimming removes only space, tab, CR and LF (a U+00A0 stays); a 4,000-character pattern within 1 s; nothing on stderr. |
| TASK-143 | Structure check (BIT002, BIT016) over the `Node` tree: canonical names and order, one `Family` (#10), empty `PluginsGroups` (#16), a missing `Operator` or `ExpectedResult` left to BIT010 and BIT011 (#2), attributes, text and processing instructions (#105); builds `ParsedPolicy` | REQ-151, REQ-176 | manager | impl-manager | **high** | `bm/services/importer/structure.py` | TASK-140; #2, #10, #16, #105 | 170 | Each REQ-151 (2) fixture tree gets BIT002 at the right line and path and no `ParsedPolicy`; `formatVersion` `1.1` gets BIT016; the SR §1.1 tree gives a `ParsedPolicy` holding the raw values and their lines; a missing `Operator` gives a `ParsedPolicy` with that field marked missing and no BIT002. |
| TASK-144 | Content validators over `ParsedPolicy`: BIT003, BIT004, BIT005, BIT008, BIT010–BIT014, BIT017, BIT101, BIT103; every failing rule reported in document order; warnings per #110; builds the store's `RuleKeys` (with one `RuleId(plugin_uuid, line, index)` per valid, distinct id, `index` the 1-based plugin position) whenever the structure passed, and its `Candidate` when no Reject finding remains (`work/plans/TASK-151.md` §2) | REQ-152, REQ-153, REQ-154, REQ-155, REQ-180 | manager | impl-manager | **high** | `bm/services/importer/validate.py` | TASK-140, TASK-142, TASK-151 (types); #2, #13, #16, #17, #109, #110 | 190 | One fixture per code gets exactly that code with its line and path; the SR §1.1 example gets no finding and a `Candidate` equal to the expected normalised values; a file with three faults gets all three in line order and no `Candidate`; the REQ-152 (1) bound table passes; warnings have Warn severity and never reject. |
| TASK-145 | POSIX `sh` lexer for BIT102 per design note D2 (quoting, operators, redirections, comments, assignments, `$( )`, backticks, `<( )`, `$(( ))`, here-documents; nested scripts; fail closed on unterminated input or depth over 8) | REQ-156 | manager | impl-manager | **high** | `bm/services/importer/shlex_model.py` (types), `bm/services/importer/shlex_grammar.py` (grouping), `bm/services/importer/shlex_posix.py` (`lex`; re-exports the model); imports one way, model → grammar → posix (user ruling 2026-10-27: one task id in three files) | TASK-140 (package); #108 (h) | about 514 (accepted over the 200 limit by the user, decisions 2026-10-27) | The REQ-156 (1) table of at least 60 inputs gives the expected tokens; unterminated quotes or substitutions and 9-deep nesting raise the fail-closed error; random strings up to 16,384 characters raise nothing else and finish within 100 ms each; the module imports nothing that executes. |
| TASK-146 | BIT102 rules over the lexer output: the SR §4.2 lists of words, options, verbs, redirections and code-running forms; every simple command anywhere (pipelines, lists, subshells, substitutions, `-c` scripts); #108 matching (paths, `mkfs.*`, wrappers, assignments) | REQ-157, REQ-177, REQ-180 | manager | impl-manager | **high** | `bm/services/importer/bit102.py` | TASK-145; #108 | 170 | Every case of the REQ-157 (1) must-reject corpus gets BIT102 with the offending token in its message, and no case of the must-pass corpus (the SR §1.1 `Execute` included) gets one. |
| TASK-147 | Catalog lock on a pinned session (design note D4): `AppDatabase.session()` holding one connection for several transactions, behind a `Protocol` in `runtime.py`; `catalog_lock(session)` taking and releasing `pg_advisory_lock(hashtext('catalog'))` | REQ-161, REQ-178 | manager | impl-manager | **high** | `bm/db/pool.py`, `bm/runtime.py`, `bm/repositories/catalog_lock.py` | none | 110 | PostgreSQL: of two sessions the second waits until the first releases; two transactions inside one session keep the lock throughout; the lock is released on an exception and when the connection closes; the existing pool tests pass; a `Runtime` built from fakes still passes `mypy --strict`. |
| TASK-148 | Catalog repository for imports (parameterised SQL): family upsert and select; policy by name, source file and id (`FOR UPDATE`); policy insert and update; plugin owner lookups for BIT015; plugin upsert reporting added or updated (#21); `policy_plugin` replace; retire unreferenced (#104) | REQ-158, REQ-159 | manager | impl-manager | **high** | `bm/repositories/catalog.py`, `bm/repositories/catalog_plugins.py` (split by the builder in W1 to stay within 200 lines; signatures in `work/plans/TASK-151.md` §4) | none (M1 schema) | 200 | PostgreSQL as `bitscan_app`: every function works with only the TS §5.2 grants; the plugin upsert reports added and updated exactly as #21 counts them; retire returns the plugins it changed and skips those a non-deleted policy lists; ruff S608 passes, and a planted f-string is red. **Revision for #100 (a) widened (user, 2026-10-27):** add `catalog_plugins.retired_among(conn, uuids) -> frozenset[UUID]` (the given ids whose `state` is `retired`; one parameterised SELECT; `current_plugins` unchanged); test: retired, active and unknown ids give exactly the retired ones. |
| TASK-149 | Import record and task repository: `bit_import` insert and newest-first page (cursor by `import_id`); `task` insert, finish, get, mark running ones failed | REQ-160, REQ-166, REQ-173 | manager | impl-manager | **high** | `bm/repositories/imports.py` | none | 110 | PostgreSQL as `bitscan_app`: an insert in its own transaction survives a sibling transaction's rollback; N + 1 rows page once each, newest first; mark-failed changes only `running` rows and sets `finished_at`; ruff S608 passes. |
| TASK-150 | Catalog admin repository: profile list (filter, `family_name`, plugin count, cursor) and detail (plugins in `sort_order` from `v_plugin`); status update; soft-delete effects (`deleted_at`, `deleted/<id>`, cancel queued compliance jobs, disable schedules, retire owned plugins); integrity reads | REQ-165, REQ-167, REQ-168, REQ-169 | manager | impl-manager | **high** | `bm/repositories/catalog_admin.py`, `bm/repositories/catalog_integrity.py` (the #103 integrity reads `integrity_rows`, `rejected_files`, `IntegrityRow`, split out in W1 by the lead; used by TASK-158) | none | 190 | PostgreSQL as `bitscan_app` with owner-written scans, jobs and schedules: the soft delete changes exactly the REQ-167 (1) rows and sends no DELETE for `policy`; list and detail return the #98 fields in order; the status update follows REQ-168 (1); ruff S608 passes. |
| TASK-151 | Store algorithm (SR §3.6) per design note D3, inside the caller's transaction: family; policy (natural key, rename in place, #106 collisions, server-folder move, override, version, #14 revival); plugins with the BIT015 and BIT007 checks (#15); `policy_plugin`; retire; returns counts, changed Executes and moved or deleted policies | REQ-158, REQ-159, REQ-177 | manager | impl-manager | **high** | `bm/services/importer/store.py` (types, `apply`), `bm/services/importer/store_decide.py` (`decide`, `check_ownership`, `is_unchanged`; plan §7 split, accepted by main 2026-10-27) | TASK-140, TASK-148, TASK-150; #14, #15, #21, #104, #106 | 200 | PostgreSQL, with `ParsedPolicy` objects built directly by the test: REQ-158 (1)–(6) and REQ-159 (1)–(6) hold; BIT007 and BIT015 come back as findings naming the other policy; a raised error leaves nothing changed after the caller's rollback. **Revision for #100 (a) widened (user, 2026-10-27):** `ChangedExecute` gains `reason` (`new` \| `changed` \| `reactivated`); `apply` reads `current_plugins` and `retired_among` before its step 1 (plan §3.4 steps 0 and 4); test: plan §6 row 4 (reactivation, revival, the #106 takeover not listed). Depends also on the TASK-148 revision. **r3 (Crash window, reviewer-m7 note; needed by TASK-156):** (1) `is_unchanged` also holds for an upload target whose decision is `update`, the policy not deleted and `old.source_sha256 == target.file_sha256` (TASK-156 has already checked that the file is that policy's `source_file`); (2) `Target("server", …)` raises `ValueError` for a `source_file` holding `/` (so `uploaded/…` and `deleted/…` can never be server targets). Tests: an unchanged upload target is unchanged and a changed one is not; `Target("server", "uploaded/policy-1.bit", …)` raises. |
| TASK-152 | Delete service: the REQ-167 effects through the repository under the catalog lock, the uploaded file removed after commit, 409 for server-folder policies (route path), audit entry and `policy_deleted` alert; a no-lock core that store, folders and rebuild reuse | REQ-167 | manager | impl-manager | **high** | `bm/services/importer/delete.py` | TASK-147, TASK-150, TASK-153; #14, #104 | 140 | PostgreSQL with a temporary bits folder: REQ-167 (1), (2), (5) and (6) hold; a fault before commit leaves the row and the file; each delete writes one `policy_deleted` alert; the core called inside another transaction rolls back with it. |
| TASK-153 | M7 alert kinds and the import-failure counter in `services/audit` (#101); importer alert builders: `policy_imported` with every changed `Execute` and the flagged words (#100), and the rejected, deleted, moved, rebuilt, re-enabled and integrity details | REQ-162, REQ-165, REQ-166, REQ-167, REQ-168 | manager | impl-manager | **high** | `bm/services/audit/alerts.py`, `bm/services/audit/metrics.py`, `bm/services/importer/alerts.py` | TASK-140; #100, #101 | 150 | Unit: every M7 kind is exported from zero; the builders give the #100 and #101 detail shapes; the six flag words match case-insensitively and a plain command matches none; `raise_alert` still refuses an unknown kind. **Revision 3 (#100 (a) widened, user 2026-10-27):** the `ChangedExecute` protocol gains a `reason` property (`new`, `changed`, `reactivated`), and each `changed_executes` entry in the `policy_imported` detail gains `"reason"`; no other change to `imported()`'s signature. Test: each reason is carried through to the detail, and an entry without `reason` fails `mypy --strict` (the protocol requires it). r2 stays APPROVED for its own change; r3 gets its own test and review. **Revision 4 (Crash window, lead 2026-10-27):** `rebuilt()` takes a new keyword `removed_leftovers: Sequence[str]` (the relative paths a rebuild removed as leftovers of interrupted deletes), and the `policy_rebuilt` detail carries `"removed_leftovers"`, empty when none, so an admin sees them in the alert. Test: two paths come through in order; none gives `[]`. Own test, review and second approval. |
| TASK-154 | Import pipeline `import_one` per design note D4: read-once buffer, hash, parse, structure, validate, BIT102, store with the DB rules, the `auto` skip, transaction 1 with the success alert, transaction 2 with the record, rejected alert and metric; the caller holds the lock | REQ-150, REQ-155, REQ-157, REQ-160, REQ-162, REQ-176 | manager | impl-manager | **high** | `bm/services/importer/pipeline.py` | TASK-141, TASK-143, TASK-144, TASK-146, TASK-147, TASK-149, TASK-151, TASK-153; #23, #98 (j), #99, #110 | 200 | PostgreSQL: the SR §1.1 example imports with one `success` row and one `policy_imported` alert; each BIT fixture is rejected with its `rejected` row and alert and no catalog change; an unchanged file in `auto` mode writes only a `skipped` row; 500 generated files leave the catalog complete or unchanged; a rolled-back import writes no success alert. |
| TASK-155 | Uploads: 409 `policy_managed_on_server`; temp file `O_WRONLY \| O_CREAT \| O_EXCL \| O_NOFOLLOW` written and flushed before commit; rename after commit; delete on rollback; the #99 client-name form; finishing interrupted uploads at start-up | REQ-163, REQ-165 | manager | impl-manager | **high** | `bm/services/importer/uploads.py` | TASK-154; #99 | 170 | Temporary folder plus PostgreSQL: REQ-163 (1)–(6) and REQ-165 (1) hold, including a symlink planted at the temp path and faults before commit and between commit and rename. |
| TASK-156 | Folders: discovery (`*.bit` regular files only; no symlinks, hidden files or subfolders; #102 name rules); reconcile in `auto` mode; removed files deleted; server folder wins over `uploaded/` with the move audit-logged; BIT007 order on first import (#15) | REQ-159, REQ-164 | manager | impl-manager | **high** | `bm/services/importer/folders.py` | TASK-152, TASK-154, TASK-151 r3; #15, #102, #103 | 180 | Temporary folders plus PostgreSQL: REQ-164 (2), REQ-159 (2), (3) and (6) and REQ-165 (3) hold; an unstorable file name is logged and skipped as #102 says; reconciling an unchanged folder writes only `skipped` rows. **How files reach `decide()`** (reviewer-m7; user "Crash window" ruling, decisions 2026-10-27): a file directly in the server folder becomes `Target("server", "<name>.bit", sha)`; a file under `uploaded/` is **never** a server target, and is classified first, under the catalog lock, by one function shared by the reconcile and the rebuild (TASK-157): **(a)** `uploaded/policy-<n>.bit` (`n` the decimal id, no leading zeros) whose policy is live (`deleted_at` NULL) and whose `source_file` is that path → the normal pipeline with `Target("upload", None, sha)` (in `auto` mode it is `skipped` when its hash equals `source_sha256`, TASK-151 r3); **(b)** `uploaded/policy-<n>.bit` whose policy has `deleted_at` set → a **leftover of an interrupted delete**: the file is removed, nothing is imported, no `bit_import` row is written, the policy stays deleted, one log line is written, and it is returned as a #103 difference (`check` = "leftover of an interrupted delete"); **(c)** any other `uploaded/` file (no such policy id, a live policy whose `source_file` is elsewhere, another name) → the normal pipeline as an upload target, so the usual answers apply (for example a server-folder policy's old copy is refused and logged), and the integrity check reports what stays. Extra tests: (i) a live policy's unchanged upload file gives one `skipped` row and no alert, and a changed one gives `success`; (ii) the leftover case removes the file, writes no row, keeps `deleted_at`, and is returned as a difference; (iii) the leftover rule never fires for a live policy, including one whose upload file has another hash; (iv) a spy on the pipeline sees no `Target("server", "uploaded/…")`. |
| TASK-157 | Rebuild service: `task` row, catalog lock, every file in both folders in `rebuild` mode with a savepoint each, gone files deleted, retire, `task.result` and state (#20), the `policy_rebuilt` alert and the #23 per-policy alerts | REQ-166 | manager | impl-manager | **high** | `bm/services/importer/rebuild.py` | TASK-149, TASK-152, TASK-154, TASK-156; #20, #23 | 180 | PostgreSQL with temporary folders: REQ-166 (1)–(6) hold, including the corrupted-catalog restore with every id unchanged and the agent, inventory, scan and audit rows untouched. `uploaded/` files go through TASK-156's classification, so a leftover of an interrupted delete is removed and listed in `task.result` (`removed_leftovers`), never revived (user "Crash window" ruling, 2026-10-27: a deleted policy never comes back by itself; the lead confirmed the rebuild extension on 2026-10-27, since upload is the only way back). The same list goes into the `bits.rebuild` entry, which is the `policy_rebuilt` alert (TASK-153 r4 `removed_leftovers`), so an admin sees it. Extra test: a rebuild with such a leftover keeps the policy deleted, removes the file, lists it in `task.result` and in the alert's `removed_leftovers`, and writes no `bit_import` row for it. Depends also on TASK-153 r4. |
| TASK-158 | Integrity check (#103) and the start-up sequence: finish uploads, mark running tasks failed, reconcile, then the integrity check and its alert (#27); retried until the database is reachable | REQ-165 | manager | impl-manager | **high** | `bm/services/importer/integrity.py`, `bm/services/importer/startup.py` | TASK-141, TASK-149, TASK-150 (`repositories/catalog_integrity.py`), TASK-153, TASK-155, TASK-156; #27, #102, #103 | 170 | PostgreSQL with temporary folders: REQ-165 (1)–(4) and (6) hold; a clean catalog raises no alert; the steps run in the stated order (a recorded step log). **Crash window** (user ruling, 2026-10-27): every leftover the reconcile removed (TASK-156 case (b)) is one difference in the same `catalog_integrity_failed` alert, `check` = "leftover of an interrupted delete", subject the file path. Extra tests: a delete committed with its upload file left on disk gives, after a restart, the file gone, the policy still deleted, no `bit_import` row and one alert listing the file; a restart with only live uploaded policies gives no alert. |
| TASK-159 | Folder watcher: inotify on both folders through a stdlib `ctypes` binding (PD-33 (b)); the #102 events; `*.bit` only, no subfolders; self-caused events ignored; each event handled under the catalog lock; one log line and no watcher where inotify is missing | REQ-164 | manager | impl-manager | **high** | `bm/services/importer/inotify.py`, `bm/services/importer/watcher.py` | TASK-156; #102, PD-33 | 190 | Linux with temporary folders and PostgreSQL: REQ-164 (1), (3) and (4) hold within 5 s; events for `n.txt`, `.n.bit` and `sub/n.bit` do nothing; on Windows the watcher logs one line and returns. |
| TASK-160 | Catalog service and `serve` wiring: `CatalogService` (upload, delete, start a rebuild on one worker thread, the #102 start-up gate); `Runtime.catalog`; the start-up sequence and the watcher started and stopped by `ServeLifecycle` | REQ-164, REQ-165, REQ-172 | manager | impl-manager | **high** | `bm/services/importer/service.py`, `bm/cli/serve.py`, `bm/runtime.py` | TASK-152, TASK-155, TASK-157, TASK-158, TASK-159; #102 | 180 | With fakes: a call before start-up ends gets the #102 refusal and succeeds afterwards; a started rebuild runs on the worker and its task ends `succeeded`; `ServeLifecycle.stop` stops the watcher and waits for the worker. On Linux, `serve` with a temporary bits folder imports a folder file at start-up, and `/healthz` stays 200 with the database down. |
| TASK-161 | Profiles service and routes `GET /policies`, `GET /policies/{id}`, `PATCH /policies/{id}` (#98 shapes, #9); status audit and `policy_reenabled`; re-export `manager/openapi.json` | REQ-168, REQ-169, REQ-174, REQ-178 | manager | impl-manager | low (reads and status; RBAC and alert plants under the security rule) | `bm/services/importer/profiles.py`, `bm/api/user/policies.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-150, TASK-153; #9, #98 | 200 (+1 generated) | Through the API on PostgreSQL: REQ-168 (1)–(5) and REQ-169 (1)–(5) hold, `bsa_` and `bse_` get 401, and G6 holds after the export. |
| TASK-162 | Upload route `POST /policies/import` per design note D5: the `bit` body-cap entry with the #99 allowance, in-memory multipart (one `file` part), the #98 answers; re-export `manager/openapi.json` with the multipart body | REQ-163, REQ-170, REQ-174, REQ-177 | manager | impl-manager | **high** | `bm/api/user/policy_import.py`, `bm/app.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-139, TASK-160; #98, #99 | 170 (+1 generated) | Through the API on PostgreSQL: REQ-170 (1)–(5) and REQ-163 (1) and (5) hold; nothing is spooled to disk while parsing (a `tempfile` spy); every other route keeps its 1 MiB cap. |
| TASK-163 | Delete route `DELETE /policies/{id}`: admin TOTP session, sink gate (#1), 204, 409, the #98 answers; re-export `manager/openapi.json` | REQ-171, REQ-174, REQ-177 | manager | impl-manager | **high** | `bm/api/user/policies.py`, `manager/openapi.json` | TASK-160, TASK-161; #1, #98 | 60 (+1 generated) | Through the API on PostgreSQL: REQ-171 (1)–(4) hold and REQ-167 (1) is seen through the route. |
| TASK-164 | Rebuild and task routes: `POST /policies/rebuild` (admin TOTP session, sink gate, 202 `{task_id}`) and `GET /tasks/{id}` (admin); re-export `manager/openapi.json` | REQ-172, REQ-174, REQ-177 | manager | impl-manager | **high** | `bm/api/user/rebuild.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-160; #20, #98 | 90 (+1 generated) | Through the API on PostgreSQL: REQ-172 (1)–(4) hold. |
| TASK-165 | Import history route `GET /imports` (admin, cursor, newest first); re-export `manager/openapi.json` | REQ-173, REQ-174 | manager | impl-manager | low | `bm/api/user/imports.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-149; #98 | 70 (+1 generated) | Through the API on PostgreSQL: REQ-173 (1)–(4) hold and `bsa_` gets 401. |
| TASK-166 | CLI `bits rebuild`: DSN from `/etc/bitscan/secrets/app.dsn`, folder per #107, the REQ-166 rebuild in the foreground with its task row and alerts, one line per file, the #107 exit codes, `--help` | REQ-175 | manager | impl-manager | **high** | `bm/cli/bits.py`, `bm/cli/__init__.py` | TASK-157; #107 | 120 | Against Testcontainers PostgreSQL with a temporary DSN file and folders: REQ-175 (1)–(6) hold. |
| TASK-167 | README: the M7 user guide (REQ-184) | REQ-184 | manager | impl-manager | low (docs) | `README.md` | TASK-162, TASK-163, TASK-164, TASK-165, TASK-166; #100 | 120 (docs) | The tester follows each new section against a WSL manager and each step behaves as written; no secret, task id or process note. |
| TASK-168 | Web: regenerate `schema.d.ts` from the M7 `openapi.json`; map `policy_managed_on_server` and the #102 start-up answer in `problems.ts` | REQ-183 | web | impl-web | low | `web/src/api/schema.d.ts`, `web/src/app/problems.ts` | TASK-161, TASK-162, TASK-163, TASK-164, TASK-165; PD-20 | 20 (+1 generated) | G16 shows no diff; every new path starts with `/api/v1/`; both problem types map to their messages and an unknown type still maps to the generic one. |
| TASK-169 | Web: Profiles list screen (status filter, paging, plain text) | REQ-181 | web | impl-web | low | `web/src/screens/Profiles.tsx` | TASK-168; PD-34 | 120 | UI test: REQ-181 (1) and (4) for the list, hostile text rendered literally. |
| TASK-170 | Web: Profile detail screen (plugins in order with display names; admin status actions; delete with confirmation and the TOTP-session prompt) | REQ-181, REQ-182 | web | impl-web | low | `web/src/screens/ProfileDetail.tsx` | TASK-168; PD-34 | 190 | UI test: REQ-181 (1)–(3) and REQ-182 (2). |
| TASK-171 | Web: Upload screen (multipart through the generated client with a `FormData` body; outcome and findings as text) | REQ-182 | web | impl-web | low | `web/src/screens/PolicyUpload.tsx` | TASK-168; PD-34 | 140 | UI test: REQ-182 (1) and (5); a 413 and a 409 show their messages. |
| TASK-172 | Web: Import history and Rebuild screens (task polling that stops at `succeeded` or `failed`) | REQ-182 | web | impl-web | low | `web/src/screens/Imports.tsx`, `web/src/screens/Rebuild.tsx` | TASK-168; PD-34 | 190 | UI test: REQ-182 (3)–(5); a 403 `totp_session_required` on rebuild shows the sign-in-again prompt. |
| TASK-173 | Web: hash routes, role table and navigation for the M7 screens | REQ-183 | web | impl-web | low | `web/src/app/router.ts`, `web/src/app/routes.tsx` | TASK-169, TASK-170, TASK-171, TASK-172 | 80 | UI test: REQ-183 (3); every new route parses and prints back to the same hash; `npm run typecheck` passes with the exhaustive route switch. |
| TASK-174 | Sample policy: Ubuntu 24.04 Level 1 server (the SR §1.1 plugin first, about 15 read-only checks, the #111 note) | REQ-179 | bits | impl-bits | low (second look, PD-35) | `bits/samples/cis-ubuntu-24.04-l1-server.bit` | none; #111 | 200 (data) | G59 (run once TASK-154 is done): imports with `success`, no Reject finding and no BIT102; the review's per-plugin script-rule rows pass. |
| TASK-175 | Sample policy: Ubuntu 22.04 Level 1 server (about 15 read-only checks, its own ids, the #111 note) | REQ-179 | bits | impl-bits | low (second look, PD-35) | `bits/samples/cis-ubuntu-22.04-l1-server.bit` | none; #111 | 200 (data) | As TASK-174, and its `PolicyName` and plugin ids differ from TASK-174's. |

Totals: 36 REQ (REQ-150 to REQ-185), 37 TASK (TASK-139 to TASK-175), 31 test-plan items (TP-M7-00 to TP-M7-30), 13 waves (W1 to W13) plus the gate. 25 high-risk tasks (the importer: TASK-140 to TASK-160, TASK-162 to TASK-164, TASK-166), 12 low-risk. Every task is within 5 files and about 200 hand-written lines; TASK-145, TASK-148, TASK-151, TASK-154 and TASK-161 are at the limit (if one grows: TASK-145 splits off here-documents; TASK-148 splits plugins from policy and family; TASK-151 splits the case decision from the writes; TASK-154 splits the record transaction; TASK-161 splits PATCH from the reads).

REQ to TASK: REQ-150 TASK-141, TASK-154; REQ-151 TASK-143; REQ-152 TASK-140, TASK-142, TASK-144; REQ-153 TASK-142, TASK-144; REQ-154 TASK-142, TASK-144; REQ-155 TASK-140, TASK-144, TASK-154; REQ-156 TASK-145; REQ-157 TASK-146, TASK-154; REQ-158 TASK-148, TASK-151; REQ-159 TASK-148, TASK-151, TASK-156; REQ-160 TASK-149, TASK-154; REQ-161 TASK-147; REQ-162 TASK-153, TASK-154; REQ-163 TASK-155, TASK-162; REQ-164 TASK-156, TASK-159, TASK-160; REQ-165 TASK-150, TASK-153, TASK-155, TASK-158, TASK-160; REQ-166 TASK-149, TASK-153, TASK-157; REQ-167 TASK-150, TASK-152, TASK-153; REQ-168 TASK-150, TASK-153, TASK-161; REQ-169 TASK-150, TASK-161; REQ-170 TASK-162; REQ-171 TASK-163; REQ-172 TASK-160, TASK-164; REQ-173 TASK-149, TASK-165; REQ-174 TASK-161 to TASK-165; REQ-175 TASK-166; REQ-176 TASK-141, TASK-143, TASK-154; REQ-177 TASK-146, TASK-151, TASK-162, TASK-163, TASK-164; REQ-178 TASK-147, TASK-161; REQ-179 TASK-174, TASK-175; REQ-180 TASK-141, TASK-144, TASK-146; REQ-181 TASK-169, TASK-170; REQ-182 TASK-170, TASK-171, TASK-172; REQ-183 TASK-168, TASK-173; REQ-184 TASK-167; REQ-185 TASK-139. REQ-176 to REQ-178 and REQ-180 are test requirements: the tester proves them (TP-M7-01, -14, -30) on the code those tasks deliver. Every M7 REQ has at least one TASK, and every TASK has at least one REQ.

### M7 owner and review notes

- **Owners:** impl-manager: TASK-139 to TASK-167. impl-web: TASK-168 to TASK-173. impl-bits: TASK-174, TASK-175. No impl-agent or impl-deploy task (no agent, unit, packaging or workflow change; CI already runs the whole pytest suite, which holds the new security suite). The tester owns every test file and fixture: `manager/tests/`, `bits/tests/`, `web/**/*.test.tsx`, `tests/m7/`.
- **Two approvals (TS §8.2 L1268, "importer"):** TASK-140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 162, 163, 164 and 166 (25 tasks). The user's second approval is asked once per wave for the wave's tasks (speed rule), on TEST PASS and reviewer APPROVED with no open blocking or should-fix finding. No M7 task touches auth code: TASK-163 and TASK-164 reuse `require_totp_session` unchanged.
- **Second looks (PD-35, recommended):** TASK-139 (a new runtime dependency), TASK-161 (`PATCH` re-enables profiles), TASK-174 and TASK-175 (commands that will run on every host).
- **Shared files, never in the same wave:** `bm/runtime.py` (TASK-147 W1, TASK-160 W7); `bm/api/user/__init__.py` (TASK-161 W3, TASK-165 W4, TASK-162 W8, TASK-164 W10); `manager/openapi.json` (TASK-161 W3, TASK-165 W4, TASK-162 W8, TASK-163 W9, TASK-164 W10); `bm/api/user/policies.py` (TASK-161 W3, TASK-163 W9). Every other file has one task.
- **Merge with M6:** M6 also edits `manager/pyproject.toml` (TASK-129, wheel section) and `README.md` (TASK-137); TASK-139 and TASK-167 touch other sections of those files, so the M6 merge is expected to resolve by hand only there. No other M7 file is in M6's list.
- **Interface for M8:** `bm/services/importer/values.py` (the #13 number grammar and the RE2 compile helper) is the one place both BIT012/BIT013 and M8's `evaluate()` use; M8 imports it and does not copy it.
- Planted violations are made in a throwaway copy, never left in the tree.

### M7 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m7/test-plan.md`, check ids `CHK-M7-###`; suggested ranges: 001–019 fixtures and model, 020–099 parser, structure, values and validators, 100–139 lexer and BIT102, 140–199 repositories, store, pipeline and lock, 200–249 uploads, folders, rebuild, delete, start-up and watcher, 250–289 routes and security, 290–299 CLI, 300–309 samples and README, 310–319 web and gate rows, 320 on the mutation table). PostgreSQL items run in WSL with `CI=true` and pytest-xdist; on the Windows box they are reported NOT RUN. Waits are skewed, never waited out (decisions 2026-10-26).

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M7-00 | Phase test plan and the M7 index row | all M7 | phase start; report at the gate | `tests/m7/test-plan.md`, `tests/test-plan.md` | none |
| TP-M7-01 | Fixtures: BIT001 set (external entities, parameter entity, billion laughs, quadratic blow-up, DTD only, UTF-16, ISO-8859-1, bad UTF-8, not well-formed, empty; oversize generated at test time), one fixture per BIT code, the TS §1.4 sample tag forms, the BIT102 must-pass and must-reject corpora, hostile client names | REQ-180 | W1 (before TASK-141 TEST) | `bits/tests/**` | none |
| TP-M7-02 | Model and code table | REQ-152, REQ-155 | TASK-140 TEST | `manager/tests/test_bit_model.py` | TASK-140 IMPL |
| TP-M7-03 | Parser: BIT001 fixtures, no file or network access, memory, lines, 10,000 random inputs | REQ-150, REQ-176 | TASK-141 TEST | `manager/tests/test_bit_parse.py`, `manager/tests/test_bit_fuzz.py` | TP-M7-01 |
| TP-M7-04 | Value helpers: #13, RE2 versus `re`, #109, trimming, `control_ref`, no stderr | REQ-152, REQ-153, REQ-154 | TASK-142 TEST | `manager/tests/test_bit_values.py` | TASK-142 IMPL |
| TP-M7-05 | Structure: BIT002 and BIT016 fixtures, #2, #10, #16, #105 | REQ-151 | TASK-143 TEST | `manager/tests/test_bit_structure.py` | TP-M7-01 |
| TP-M7-06 | Validators: one case per code, bounds, order, warnings | REQ-152 to REQ-155 | TASK-144 TEST | `manager/tests/test_bit_validate.py` | TP-M7-04, TP-M7-05 |
| TP-M7-07 | Lexer table, fail-closed cases, property test | REQ-156 | TASK-145 TEST | `manager/tests/test_bit102_lexer.py` | TASK-145 IMPL |
| TP-M7-08 | BIT102 corpora | REQ-157 | TASK-146 TEST | `manager/tests/test_bit102.py` | TP-M7-01, TP-M7-07 |
| TP-M7-09 | Catalog lock and pinned session (PostgreSQL) | REQ-161 | TASK-147 TEST | `manager/tests/test_catalog_lock_pg.py` | TASK-147 IMPL |
| TP-M7-10 | Repositories as `bitscan_app`: grants suffice, #21 counts, retire, soft delete, list and detail, S608 | REQ-158, REQ-160, REQ-167 to REQ-169, REQ-173 | TASK-148, 149, 150 TEST | `manager/tests/test_catalog_repo_pg.py`, `manager/tests/test_imports_repo_pg.py` | TASK-148 to 150 IMPL |
| TP-M7-11 | Store: every SR §3.6 step, BIT007, BIT015, server-folder move, rename and #106, override, version, #14 | REQ-158, REQ-159 | TASK-151 TEST | `manager/tests/test_import_store_pg.py` | TP-M7-10 |
| TP-M7-12 | Alert kinds, builders, counter | REQ-162 | TASK-153 TEST | `manager/tests/test_import_alerts.py` | TASK-153 IMPL |
| TP-M7-13 | Delete service | REQ-167 | TASK-152 TEST | `manager/tests/test_policy_delete_pg.py` | TP-M7-10, TP-M7-12 |
| TP-M7-14 | Pipeline: fixtures end to end, `skipped`, records, alerts; 500 generated files with no partial import; a file with `formatVersion="2.0"` plus a BIT003 fault reports both BIT016 and BIT003 (only BIT001 and BIT002 stop the content rules, SR L250; lead's ruling 2026-10-27) | REQ-150, REQ-155, REQ-157, REQ-160, REQ-162, REQ-176 | TASK-154 TEST | `manager/tests/test_import_pipeline_pg.py`, `manager/tests/test_import_fuzz_pg.py` | TP-M7-03 to TP-M7-13 |
| TP-M7-15 | Uploads: hostile names, symlink at the temp path, faults, interrupted uploads, mode 0600 | REQ-163, REQ-165 | TASK-155 TEST | `manager/tests/test_uploads_pg.py` | TP-M7-14 |
| TP-M7-16 | Folders and reconcile | REQ-159, REQ-164, REQ-165 | TASK-156 TEST | `manager/tests/test_folders_pg.py` | TP-M7-14 |
| TP-M7-17 | Rebuild, including the corrupted catalog and untouched tables | REQ-166 | TASK-157 TEST | `manager/tests/test_rebuild_pg.py` | TP-M7-16 |
| TP-M7-18 | Integrity check and start-up order | REQ-165 | TASK-158 TEST | `manager/tests/test_catalog_startup_pg.py` | TP-M7-15, TP-M7-16 |
| TP-M7-19 | Watcher on Linux | REQ-164 | TASK-159 TEST | `manager/tests/test_watcher_linux.py` | TP-M7-16 |
| TP-M7-20 | Catalog service, start-up gate, worker, `serve` lifecycle | REQ-164, REQ-165, REQ-172 | TASK-160 TEST | `manager/tests/test_catalog_service.py`, `manager/tests/test_serve_catalog_linux.py` | TP-M7-17 to TP-M7-19 |
| TP-M7-21 | Profiles routes | REQ-168, REQ-169, REQ-174 | TASK-161 TEST | `manager/tests/test_policies_api_pg.py` | TP-M7-10 |
| TP-M7-22 | Import history route | REQ-173 | TASK-165 TEST | `manager/tests/test_imports_api_pg.py` | TP-M7-10 |
| TP-M7-23 | Upload route: multipart forms, caps, 409, RBAC, no spooling | REQ-170, REQ-163 | TASK-162 TEST | `manager/tests/test_policy_import_api_pg.py` | TP-M7-20 |
| TP-M7-24 | Delete route: TOTP session, API token, sink gate, 409 | REQ-171 | TASK-163 TEST | `manager/tests/test_policy_delete_api_pg.py` | TP-M7-20, TP-M7-21 |
| TP-M7-25 | Rebuild and task routes | REQ-172 | TASK-164 TEST | `manager/tests/test_rebuild_api_pg.py` | TP-M7-20 |
| TP-M7-26 | CLI `bits rebuild` | REQ-175 | TASK-166 TEST | `manager/tests/test_cli_bits_pg.py`, `manager/tests/test_cli.py` (help text) | TP-M7-17 |
| TP-M7-27 | Samples gate G59 and the per-plugin script-rule review rows | REQ-179 | TASK-174, 175 TEST (after TASK-154) | `manager/tests/test_bits_samples_pg.py` | TP-M7-14 |
| TP-M7-28 | README walk | REQ-184 | TASK-167 TEST | none in the tree (evidence) | TP-M7-23 to TP-M7-26 |
| TP-M7-29 | Web: regeneration, problem mapping, the four screens, routes and navigation, hostile text | REQ-181 to REQ-183 | TASK-168 to 173 TEST (one batch) | `web/src/screens/{Profiles,ProfileDetail,PolicyUpload,Imports,Rebuild}.test.tsx`, `web/src/app/{problems,router}.test.ts`, `web/src/app/App.test.tsx` | TASK-168 to 173 IMPL |
| TP-M7-30 | M7 security suite (TS §8.3 Security, importer half) and alert suite; the M7 gate and mutation table | REQ-162, REQ-174, REQ-177, REQ-178 | M7 gate (security suite also re-run in each high-risk route task's TEST) | `manager/tests/test_security_m7.py`, `manager/tests/test_catalog_alerts_pg.py` | all above |

### M7 waves and dependency spine

Spine: `TASK-140 → {TASK-141, TASK-143, TASK-142 → TASK-144, TASK-145 → TASK-146} → TASK-154 → TASK-155 → TASK-158 → TASK-160 → TASK-162 → TASK-163 → TASK-164 → TASK-168 → {TASK-169..172} → TASK-173`; `TASK-148, TASK-150 → TASK-151 → TASK-154`; `TASK-151 → TASK-144` (the `Candidate` and `RuleKeys` types, added after approval with the plans); `TASK-147, TASK-149, TASK-153 → TASK-154`; `TASK-147, TASK-150, TASK-153 → TASK-152 → TASK-156 → {TASK-157, TASK-158, TASK-159} → TASK-160`; `TASK-157 → TASK-166`; `TASK-150, TASK-153 → TASK-161 → TASK-163`; `TASK-149 → TASK-165`; `TASK-139 → TASK-162`; `TASK-162..166 → TASK-167`. TASK-174 and TASK-175 depend on nothing (their TEST waits for TASK-154). The graph is acyclic.

Interface first: TASK-140 fixes `Finding`, `Node`, `ParsedPolicy` and the code table before the parser, structure, validators and lexer users; TASK-147 fixes the pinned-session and lock protocol and TASK-148 to TASK-150 the repository signatures before the store, pipeline and delete; TASK-153 fixes the alert kinds before every raiser; TASK-160 fixes `CatalogService` before the routes; #98 fixes every M7 request and response before TASK-161 to TASK-165 and the web screens.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-139, 140, 147, 148, 149, 150, 174, 175; tester TP-M7-00, TP-M7-01 | `manager/pyproject.toml`, `manager/requirements*.txt` · `bm/services/importer/{__init__,model}.py` · `bm/db/pool.py`, `bm/runtime.py`, `bm/repositories/catalog_lock.py` · `bm/repositories/{catalog,catalog_plugins}.py` · `bm/repositories/imports.py` · `bm/repositories/{catalog_admin,catalog_integrity}.py` · `bits/samples/cis-ubuntu-24.04-l1-server.bit` · `bits/samples/cis-ubuntu-22.04-l1-server.bit` · `tests/m7/test-plan.md`, `tests/test-plan.md`, `bits/tests/**` |
| W2 | TASK-141, 142, 143, 145, 151, 153 | `bm/services/importer/parse.py` · `values.py` · `structure.py` · `shlex_{model,grammar,posix}.py` · `store.py`, `store_decide.py` · `bm/services/audit/{alerts,metrics}.py`, `bm/services/importer/alerts.py` |
| W3 | TASK-144, 146, 152, 161 | `bm/services/importer/validate.py` · `bit102.py` · `delete.py` · `bm/services/importer/profiles.py`, `bm/api/user/{policies,__init__}.py`, `manager/openapi.json` |
| W4 | TASK-154, 165 | `bm/services/importer/pipeline.py` · `bm/api/user/{imports,__init__}.py`, `manager/openapi.json` |
| W5 | TASK-155, 156 | `bm/services/importer/uploads.py` · `folders.py` |
| W6 | TASK-157, 158, 159 | `bm/services/importer/rebuild.py` · `integrity.py`, `startup.py` · `inotify.py`, `watcher.py` |
| W7 | TASK-160, 166 | `bm/services/importer/service.py`, `bm/cli/serve.py`, `bm/runtime.py` · `bm/cli/{bits,__init__}.py` |
| W8 | TASK-162 | `bm/api/user/{policy_import,__init__}.py`, `bm/app.py`, `manager/openapi.json` |
| W9 | TASK-163 | `bm/api/user/policies.py`, `manager/openapi.json` |
| W10 | TASK-164 | `bm/api/user/{rebuild,__init__}.py`, `manager/openapi.json` |
| W11 | TASK-167, 168 | `README.md` · `web/src/api/schema.d.ts`, `web/src/app/problems.ts` |
| W12 | TASK-169, 170, 171, 172 | `web/src/screens/Profiles.tsx` · `ProfileDetail.tsx` · `PolicyUpload.tsx` · `Imports.tsx`, `Rebuild.tsx` |
| W13 | TASK-173 | `web/src/app/{router.ts,routes.tsx}` |
| Gate | tester TP-M7-30 and the gate; reviewer's M7 closing review | tester files only |

Per-wave batches under testing by risk: W1 low batch = TASK-139 (TEST at once) and TASK-174, 175 (IMPL in W1, TEST with W5 after TASK-154, one batch); W3 low = TASK-161; W4 low = TASK-165; W11 low = TASK-167, 168; W12 + W13 = one web batch (TASK-168 to 173). Every other task is high risk, tested and reviewed on its own. With one impl-manager instance, W1 to W7 run one task after another inside a wave; a second instance can take W1 to W3, where files are disjoint. Waves W8 to W10 hold one route task each (PD-24 (a)); the reads and the import history route are pulled forward into W3 and W4 so the web contract is mostly fixed early.

### M7 gate

On a clean tree every command is green, and each gate turns red on its planted violation. G7 to G11, G17 and G35 to G41 (agent, units, packaging) are not re-run: M7 changes no agent, unit or package file (the lead may re-run G30 and G35 as a contract regression, REQ-174 (3)).

| Gate | Command (summary) | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1–G4 | ruff (S608, the `re` and `xml.*` bans), ruff format, `mypy --strict`, hashed locks | CHK-M7-336, -337, -347, -348; an untyped function in `store.py` | local; CI |
| G5 | services coverage ≥ 85 % (now including `services/importer`), Linux run | an untested function in `bm/services/importer/folders.py` sized from the clean report | WSL; CI |
| G6, G16 | OpenAPI export byte-identical; client regenerated with no diff | a route added in `policies.py` without re-export; `openapi.json` changed without regenerating the client | local; CI |
| G12–G15 | web lint, typecheck, format, tests (with the M7 screens) | CHK-M7-370, -371 | local; CI |
| G18 | full manager suite, 0 skipped, `-n auto` | any of G54 to G61 | WSL; CI |
| G34 | `pytest tests/test_invariants_m3.py` (route walk with the eight M7 operations) | CHK-M7-361 | local; CI |
| G54 | importer unit suite: `test_bit_model.py`, `test_bit_parse.py`, `test_bit_values.py`, `test_bit_structure.py`, `test_bit_validate.py`, `test_bit102_lexer.py`, `test_bit102.py`, `test_import_alerts.py` (SR §1.1 example; one case per BIT code; corpora) | the G54 rows | local; WSL; CI |
| G55 | property and fuzz: `test_bit_fuzz.py` (unit), `test_import_fuzz_pg.py` (no partial import) | CHK-M7-340 | local (unit); WSL; CI |
| G56 | importer integration: `test_catalog_lock_pg.py`, `test_catalog_repo_pg.py`, `test_imports_repo_pg.py`, `test_import_store_pg.py`, `test_policy_delete_pg.py`, `test_import_pipeline_pg.py`, `test_uploads_pg.py`, `test_folders_pg.py`, `test_rebuild_pg.py`, `test_catalog_startup_pg.py`, `test_catalog_service.py` | the G56 rows | WSL; CI |
| G57 | catalog API and the M7 security suite: `test_policies_api_pg.py`, `test_imports_api_pg.py`, `test_policy_import_api_pg.py`, `test_policy_delete_api_pg.py`, `test_rebuild_api_pg.py`, `test_security_m7.py` | the G57 rows | WSL; CI |
| G58 | `test_cli_bits_pg.py` | CHK-M7-362 | WSL; CI |
| G59 | `test_bits_samples_pg.py`: all `bits/samples/*.bit` together in one fresh catalog, and the SR §1.1 example alone in another (the 24.04 sample shares its name and first plugin id, #111), each import with `success`, no Reject, no BIT102 | CHK-M7-366 | WSL; CI |
| G60 | `test_catalog_alerts_pg.py`: every M7 alert (entry, kind, sink, counter) | the G60 rows | WSL; CI |
| G61 | `test_watcher_linux.py`, `test_serve_catalog_linux.py` (inotify, start-up in `serve`) | CHK-M7-367, -368 | WSL; CI (Linux only) |

**No gate is lowered.** NOT RUN at the M7 gate, with reasons: the TS §8.3 Sandbox half "the full CIS plugin set passes under the sandbox" (no runner until M10; the BIT102 half is G59); the end-to-end import step on VMs (M11 nightly); the load tests (deferred by the user).

### M7 mutation table (tester; CHK-M7-320 onwards)

Each row is planted in a throwaway copy and must turn the named gate red. Rows 320 to 365 are security rows; each runs as a targeted mini-run.

| CHK | Plant | Red in | Target |
| --- | --- | --- | --- |
| CHK-M7-320 | XXE: the parser built with `forbid_external=False` | G54 (external-entity fixtures accepted or canary read) | TASK-141 |
| CHK-M7-321 | DTD allowed: `forbid_dtd=False` | G54 (DTD-only fixture passes BIT001) | TASK-141 |
| CHK-M7-322 | Entity expansion: `forbid_entities=False` | G54 (billion laughs not BIT001; memory cap exceeded) | TASK-141 |
| CHK-M7-323 | Oversize: the parser cap raised to 50 MiB | G54 (5 MiB + 1 accepted) | TASK-141 |
| CHK-M7-324 | Oversize: the import route's cap entry removed (falls back to 1 MiB) or raised past 5 MiB + #99 | G57 (a 5 MiB file refused, or a 6 MiB file accepted) | TASK-162 |
| CHK-M7-325 | Non-RE2: the BIT013 check done with Python `re` (behind `noqa`) | G54 (`(?=x)` and `(a)\1` accepted) | TASK-142 |
| CHK-M7-326 | BIT013 check skipped for `not_regex` | G54 | TASK-144 |
| CHK-M7-327 | BIT102 by substring search instead of the lexer | G54 (`echo "rm"` rejected; `r''m` accepted) | TASK-146 |
| CHK-M7-328 | BIT102 bypass: path-qualified names not reduced (`/bin/rm`) | G54 | TASK-146 |
| CHK-M7-329 | BIT102 bypass: commands inside `$( )`, backticks, subshells or `-c` scripts not checked | G54 | TASK-146 |
| CHK-M7-330 | BIT102 bypass: wrappers (`env rm`, `busybox rm`) not unwrapped | G54 | TASK-146 |
| CHK-M7-331 | BIT102 bypass: a redirect to `/tmp/../etc/x` or `"$F"` allowed | G54 | TASK-146 |
| CHK-M7-332 | BIT102 bypass: lexer errors treated as pass (fail open) | G54 | TASK-145, 146 |
| CHK-M7-333 | BIT102 bypass: BIT102 skipped in `rebuild` mode (or for uploads) | G56 (entry-point row of REQ-157 (3)) | TASK-154 |
| CHK-M7-334 | BIT001 or BIT002 failure still runs the content rules | G54 | TASK-143, 144 |
| CHK-M7-335 | BIT015 check removed | G56, G57 | TASK-151 |
| CHK-M7-336 | SQL from strings: an f-string query in `repositories/catalog.py` | G1 (S608) | TASK-148 |
| CHK-M7-337 | SQL from strings: an f-string in `repositories/catalog_admin.py` | G1 (S608) | TASK-150 |
| CHK-M7-338 | Partial import: a commit per plugin | G56 (fault after plugin 3 leaves rows) | TASK-151, 154 |
| CHK-M7-339 | `bit_import` written in the catalog transaction (lost on reject) | G56 | TASK-154 |
| CHK-M7-340 | A late exception swallowed and the transaction committed | G55 (no partial import) | TASK-154 |
| CHK-M7-341 | API token accepted on `DELETE /policies/{id}` (`require_role("admin")`) | G57 | TASK-163 |
| CHK-M7-342 | API token accepted on `POST /policies/rebuild` | G57 | TASK-164 |
| CHK-M7-343 | Sink gate off on `DELETE /policies/{id}` (`sink_gate=False`, against #1) | G57 | TASK-163 |
| CHK-M7-344 | Sink gate off on rebuild | G57 | TASK-164 |
| CHK-M7-345 | Upload accepted for an operator | G57 | TASK-162 |
| CHK-M7-346 | Delete accepted for an operator | G57 | TASK-163 |
| CHK-M7-347 | `import xml.etree.ElementTree` in `parse.py` | G1 | TASK-141 |
| CHK-M7-348 | `import re` in `validate.py` | G1 | TASK-144 |
| CHK-M7-349 | Missing audit or alert: no `policy_imported` on a successful import | G60 | TASK-154 |
| CHK-M7-350 | Missing alert: no `policy_import_rejected` (or no failure count) on a rejection | G60 | TASK-154 |
| CHK-M7-351 | Missing alert: no `policy_deleted` on delete (route, watcher or rebuild path) | G60 | TASK-152 |
| CHK-M7-352 | Missing alert: no `policy_rebuilt` | G60 | TASK-157 |
| CHK-M7-353 | Missing alert: no `policy_reenabled` on PATCH re-enable | G60 | TASK-161 |
| CHK-M7-354 | The import alert drops the changed Executes or the flags | G60 | TASK-153 |
| CHK-M7-355 | No `catalog_integrity_failed` alert on a corrupted catalog | G60 | TASK-158 |
| CHK-M7-356 | The catalog lock removed | G56 (concurrency row) | TASK-147, 154 |
| CHK-M7-357 | `O_EXCL` or `O_NOFOLLOW` removed from the temp-file open | G56 (planted symlink followed) | TASK-155 |
| CHK-M7-358 | The client file name used in the stored path | G57 (hostile-name row) | TASK-155, 162 |
| CHK-M7-359 | A rejected upload replaces the stored file, or a rollback leaves the temp file | G56 | TASK-155 |
| CHK-M7-360 | Upload of a server-folder policy accepted (no 409) | G57 | TASK-155 |
| CHK-M7-361 | `PATCH` accepts `execute` (a route that edits commands) | G34, G57 | TASK-161 |
| CHK-M7-362 | The CLI reads the DSN from an environment variable or argv | G58 | TASK-166 |
| CHK-M7-363 | Symlinks in the server folder followed | G56 | TASK-156 |
| CHK-M7-364 | Rebuild changes `agent`, `scan_result` or `audit_log` rows | G56 | TASK-157 |
| CHK-M7-365 | Delete issues a hard `DELETE` (the grant refuses it; the test must see the failure) or skips the job cancel | G56 | TASK-150, 152 |
| CHK-M7-366 | A sample with `rm` in a plugin, or two samples sharing a plugin id | G59 | TASK-174, 175 |
| CHK-M7-367 | The watcher follows subfolders or non-`.bit` files | G61 | TASK-159 |
| CHK-M7-368 | Start-up runs the integrity check before the reconcile | G61, G56 | TASK-158 |
| CHK-M7-369 | `status_overridden` ignored on a file update; version +1 on an identical hash (non-revival); `auto` not skipping or `manual` skipping | G56 | TASK-151, 154 |
| CHK-M7-370 | `dangerouslySetInnerHTML` for a policy description in `ProfileDetail.tsx` | G12, G15 | TASK-170 |
| CHK-M7-371 | The rebuild screen asks for or sends an API token on `totp_session_required` | G15 | TASK-172 |

### Open items for M7

All are in `work/open-questions.md` ("M7"), each with a recommended answer. "Needed by" is the start of the wave whose task or test cannot finish without it.

| Item | Blocks | Needed by |
| --- | --- | --- |
| PD-33 (new): runtime dependencies (`python-multipart`; inotify through `ctypes`) | TASK-139, TASK-159, TASK-162 | W1 |
| PD-36 (new): the five design plans written after approval | TASK-141, 145, 151, 154, 162 | W2 |
| #111 (new): sample content and CIS control numbers | TASK-174, 175 | W1 |
| #105 (new): parser details and limits | TASK-141, 143 | W2 |
| #108 (new): BIT102 matching scope | TASK-145, 146 | W2 |
| #109 (new): uppercase `PluginId` | TASK-142 | W2 |
| #13, #17 (re-checked): number grammar; trimming | TASK-142 | W2 |
| #2, #10, #16 (re-checked) | TASK-143, 144 | W2 |
| #14, #15, #21, #104, #106 | TASK-151 (W2), TASK-156 (W5) | W2 |
| #100, #101 (new): import alert content; audit actions, kinds, metric | TASK-153 | W2 |
| #98 (new): bodies and statuses of the M7 routes | TASK-161 (W3) and every route task; web | W3 |
| #9 (re-checked): deleted policies in `GET /policies` | TASK-161 | W3 |
| #110 (new): warnings stored | TASK-144, 154 | W3 |
| #99 (new): multipart, caps, client name, 413 and 409 logging | TASK-154 (W4), TASK-162 (W8) | W4 |
| #23 (re-checked): skipped and rebuild alerts | TASK-154, 157 | W4 |
| #102 (new): watcher events, start-up gate, file-name rules | TASK-156, 158, 159, 160 | W5 |
| #20, #27, #103 | TASK-157, 158 | W6 |
| #107 (new): CLI folder, output, exit codes | TASK-166 | W7 |
| #1 (re-checked): sink gate on delete | TASK-163 | W9 |
| PD-34 (new): M7 UI scope | TASK-168 to 173 | W11 |
| PD-35 (new): second approvals and second looks | each wave's REVIEW | W1 |
| #11 (re-checked): operators as written | none in M7 (M8) | — |

### Coverage matrix (M7)

| Spec section | Covered by | Status in M7 |
| --- | --- | --- |
| TS §1.1 G4, G5 (L16–L17) | REQ-158, REQ-164 to REQ-166, REQ-169 | Covered |
| TS §1.4 L41 display name, L43 canonical tags | REQ-151, REQ-169, REQ-181 | Covered |
| TS §2.1 importer and UI rows (L101, L104); §2.2 rebuildable catalog (L113); §2.3 flow 0 (L131) | REQ-166, REQ-170, REQ-181 | Covered |
| TS §4.1 import pipeline (L513–L532), every paragraph | REQ-150 to REQ-165 | Covered |
| TS §4.2 automatic vs manual loading (L536–L542) | REQ-160, REQ-164 to REQ-166, REQ-172, REQ-175 | Covered |
| TS §4.3 profiles (L546–L551) | REQ-159, REQ-167 to REQ-169, REQ-181 | Covered; "blocks new scans" and scan refusals are **M9** |
| TS §4.4 scans | REQ-167 (delete cancels queued jobs, disables schedules) | Only the delete side effects; scan building, states and the derivation after a cancel are **M9** |
| TS §4.5 result evaluation | REQ-153 (shared number grammar and RE2 helper) | **M8**; M7 fixes only the shared helpers |
| TS §4.6 loading `.bit` files (L607–L615) | REQ-163, REQ-164, REQ-170, REQ-175 | Covered |
| TS §5.1 catalog rows; §5.2 catalog DDL (L642–L707), `task` (L941–L949), `v_plugin` (L1035–L1041), grants (L992–L1013) | REQ-158, REQ-160, REQ-166, REQ-169 | Used as migrated; **no schema change**; the schema-diff test stays green |
| TS §5.3 L1048 (catalog fixed by rebuild), L1049 (no app change to `bit_import`) | REQ-160, REQ-166 | Covered |
| TS §6 L1056 route groups; §6.2 L1129 | REQ-174 | Covered |
| TS §6.2 L1084 (rebuild is sensitive; upload is not) | REQ-170, REQ-172 | Covered |
| TS §6.2 L1100–L1107 (policies, import, delete, rebuild, tasks, imports) | REQ-168 to REQ-173 | Covered (bodies #98) |
| TS §6.3 errors, pagination, ids (L1133, L1134, L1139) | REQ-169, REQ-173, REQ-174 | Covered |
| TS §6.3 multipart import and `.bit` 5 MB cap (L1137–L1138) | REQ-170 | Covered (#99); carried from M2 |
| TS §6.3 plain text (L1141) | REQ-169 (4), REQ-181, REQ-182 | Covered |
| TS §6.3 CSV (L1142) | none | No export in M7 (results CSV is **M11**) |
| TS §8.1 manager compromise and stolen credentials (alerts on every import and delete), unintended policy, verdict tampering, plugin changes host (BIT102), XML attacks, SQL injection, privilege misuse, XSS, local users (L1240–L1244, L1251–L1255) | REQ-150, REQ-157, REQ-162, REQ-167, REQ-170, REQ-171, REQ-174, REQ-181 | Covered; the sandbox half of "plugin changes host" is **M10** |
| TS §8.2 L1263 `bits/`, L1266 client, L1268 two approvals | REQ-179, REQ-183; owner notes | Covered |
| TS §8.3 Unit (parser, validators, BIT102 lexer; SR §1.1 example) | REQ-150 to REQ-157 / G54 | Covered |
| TS §8.3 Property / fuzz (`.bit` parser) | REQ-176 / G55 | Covered |
| TS §8.3 Integration (all endpoints, rebuild on a corrupted catalog) | REQ-166, REQ-178 / G56, G57 | Covered for M7 |
| TS §8.3 Security (non-admin upload and delete, hostile names, BIT015 and BIT102, API tokens on delete and rebuild) | REQ-177 / G57 | Covered (importer half) |
| TS §8.3 Sandbox ("full CIS plugin set passes under the sandbox and BIT102") | REQ-179 / G59 | BIT102 half covered; sandbox half **M10** |
| TS §8.3 End-to-end ("import" step) | none | **M11** nightly |
| TS §8.4 import failures metric; imported, rebuilt, deleted, re-enabled alerts; import rejected; integrity check failed (L1288–L1291) | REQ-162, REQ-165 to REQ-168 / G60 | Covered (#100, #101) |
| TS §8.5 (L1296–L1298) | #10, #11, #111 | Kept as written; CIS numbers per #111 |
| TS §8.6 `BITSCAN_BITS_DIR` (L1314) | REQ-164, REQ-175 | Covered |
| TS §8.7 folders and modes (L1344), CLI `bits rebuild` (L1347), `ReadWritePaths` and `UMask` (L1377, L1395) | REQ-163, REQ-175 | Covered; carried from M1 and M2 |
| SR §1 structure, §1.1 example | REQ-151, REQ-158 (1), G54, G59 | Covered |
| SR §2.1 to §2.3 elements | REQ-151 to REQ-154 | Covered |
| SR §2.4 operators and evaluation | REQ-153 (BIT012 to BIT014 only) | Operator semantics **M8** |
| SR §2.4 script rules (L155–L162) | REQ-179 | Covered for the samples |
| SR §3.1 to §3.6 mapping and algorithm | REQ-158 to REQ-160 | Covered |
| SR §4, §4.1 validation rules; §4.2 BIT102 | REQ-150 to REQ-157 | Covered |
| CLAUDE.md out of scope and owner decisions | none | Nothing planned: no signing, approval or diff workflow, policy editor, plugin edit route or ad-hoc command |

## M8 evaluator (result evaluation and scoring)

Planned 2026-10-29 (planner-m8) in the worktree `Bitscan-m8` (branch `m8-evaluator`, from main `67a6dfa`, M7 merged). Consistency pass done: every TASK links a REQ and every REQ has a TASK; waves are file-disjoint; every task is within 5 files and about 200 hand-written lines; the spine is acyclic; no gate is lowered. Summary for the user: `work/plans/M8-breakdown.md`.

Scope: REQ-186 to REQ-205 in `work/requirements.md`. In this section `bm/` means `manager/bitscan_manager/`.

**No new spec deviation.** Every open item (#112 to #120 new; #11, #12, #13 reused as agreed; PD-38) carries a recommended answer in `work/open-questions.md` ("M8"). **No migration, no route, no agent change, no new dependency.**

Rules every M8 task follows:
- **Testing by risk (user, 2026-10-25).** The evaluator is a high-risk area (lead's M8 brief): every M8 task gets full rigor per task, with a plant for every security row, every boundary and every race the task's rows name, and a second review round if needed. There is no low-risk batch in M8.
- **Time-skewing (user, 2026-10-26):** tests never wait out a timer; races are driven by barriers and two sessions, never by sleeps.
- `api → services → repositories`. The pure modules (`model`, `normalise`, `operators`, `evaluate`, `verdict`, `eval_spec`, `score`) take plain values and import no database, repository or API code (REQ-202); the two services take `runtime.Database`. Parameterised SQL only (ruff S608); RE2 only, through `services/importer/values.py` (ruff bans `re`).
- **Reuse, don't copy** (M7 interface note): the #13 number grammar (`values.is_number`, `values.parse_number`), the RE2 compile helper (`values.compile_pattern`, which already adds `(?m)` and silences RE2's error log) and the operator tuples (`importer.model.OPERATORS`, `NUMERIC_OPERATORS`, `REGEX_OPERATORS`, `PRESENCE_OPERATORS`) are imported, never re-implemented. No M8 task edits `values.py` or `importer/model.py`.
- `bm/services/evaluator/__init__.py` holds only a docstring; callers import the submodules (`…evaluator.evaluate`, `…evaluator.verdict`), so no two tasks share it.
- Nothing in M8 writes `scan_result`, `scan_job` or `scan`; the only writes are `scan_result_reeval` and `audit_log` inserts in TASK-185. No log line, exception message, audit detail or `eval_detail` carries stdout, stderr, an expected value or a pattern.
- Implementers check `work/reviews/builder-checklist.md` before every hand-off.

### M8 design notes (for the tasks with real design risk)

Written out in `work/plans/TASK-178.md` (D1, D2, and the TASK-176 interface), `work/plans/TASK-182.md` (D3) and `work/plans/TASK-185.md` (D4, and the TASK-183 interface).
- **D1 classify (TASK-178).** One ordered pre-check list, then normalise, then `operators.compare()`. Order (#112): timed out → no exit code → 126 `cannot run` → 127 `not found` → ≥ 128 or < 0 `killed by signal` → `truncated` `stdout truncated`; then normalise both strings; then `compare()`, whose `CannotEvaluate` signal (operator not one of the 14, a numeric operator with a non-numeric expected value, a pattern RE2 refuses, text RE2 cannot encode) gives `cannot evaluate` and whose `NotNumeric` signal gives `stdout not numeric`. `evaluate()` is `classify(...).code`. A final `except Exception` is **not** used: totality comes from the explicit signals, and the property test (REQ-186 (3)) proves it.
- **D2 operators (TASK-177).** `compare(operator, expected, stdout) -> bool` on already-normalised text. Text: `==`, `!=`, `in`, `not in`. RE2: `values.compile_pattern(expected).search(stdout) is not None`, the `UnicodeEncodeError` RE2 raises for a lone surrogate turned into `CannotEvaluate`. Numeric: `values.parse_number` on both; `None` for expected is `CannotEvaluate`, for stdout `NotNumeric`; compared as `Decimal`. Presence: `stdout == ""`.
- **D3 effective verdicts (TASK-182).** `scan_result_reeval` has no index on `(job_id, plugin_uuid)` and none may be added, so the latest row is taken in one pass: `SELECT DISTINCT ON (job_id, plugin_uuid) … FROM scan_result_reeval WHERE job_id = ANY(<the scan's job ids>) ORDER BY job_id, plugin_uuid, reeval_id DESC`, joined to `scan_result` by `(job_id, plugin_uuid)`; `scan_result` is read by `job_id` and `job_created_at` (partition pruning). Not run comes from `jsonb_array_length(payload->'plugins')` of the original jobs (`retry_of IS NULL`).
- **D4 re-evaluation transaction (TASK-183, TASK-185).** One `db.transaction()`: `pg_advisory_xact_lock(hashtext('scan_reeval'), hashtext(<scan_id text>))` → read the scan (`ScanNotFound`) → one statement for the current version, `deleted_at` and every listed plugin's Operator and ExpectedResult (`PolicyDeleted`) → a server-side cursor over the scan's results, 1,000 at a time → per row keep an intake detail or `classify()` → one `INSERT … SELECT FROM unnest(…)` per chunk → `append_entry(... action="scan.reevaluate" ...)` → commit; `tx.on_commit(wake)` wakes the audit shipper.

### M8 tasks

| TASK | Title | REQ links | Area | Owner | Risk | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-176 | Evaluator model and normaliser (interface): `Operator` (the 14 as a `Literal`), `VerdictCode` with `PASS`/`FAIL`/`ERROR`, `Detail` (the #112 vocabulary), `INTAKE_DETAILS`, `STDOUT_CAP`/`STDERR_CAP` (#116), `Verdict` (code and detail with its invariant), `PluginSpec`, the read-only `ResultLike` protocol; `normalise()` (#115) | REQ-187, REQ-193, REQ-202 | manager | impl-manager | **high** | `bm/services/evaluator/__init__.py` (docstring only), `bm/services/evaluator/model.py`, `bm/services/evaluator/normalise.py` | none; #112, #115, #116 | 130 | Unit: `Operator`'s values equal `importer.model.OPERATORS` in order; `Verdict(0, Detail.TIMED_OUT)`, `Verdict(2, None)`, `Verdict(3, None)` raise; `Detail` is exactly the eleven #112 values; the REQ-187 table holds; a `ResultItem` from `api/agent/schemas.py` type-checks as `ResultLike` under `mypy --strict`. |
| TASK-177 | The 14 operators on normalised text per design note D2: `compare()` with the `NotNumeric` and `CannotEvaluate` signals; numeric through `values.parse_number`, RE2 through `values.compile_pattern` | REQ-188, REQ-189, REQ-190, REQ-191 | manager | impl-manager | **high** | `bm/services/evaluator/operators.py` | TASK-176; #11, #13 | 110 | Unit: every row of the REQ-188 to REQ-191 tables gives the stated boolean or signal, and a lone surrogate in stdout under `regex` and `not_regex` gives `CannotEvaluate`, not an exception. |
| TASK-178 | `classify()` and `evaluate()` per design note D1: the ERROR pre-checks in #112 order, normalising both strings, `compare()`, signals mapped to `stdout not numeric` and `cannot evaluate`; total over the declared types | REQ-186, REQ-192, REQ-193, REQ-205 | manager | impl-manager | **high** | `bm/services/evaluator/evaluate.py` | TASK-176, TASK-177; #12, #112, #113, #114 | 100 | Unit: REQ-186 (1), (2), (4), REQ-192 (1)–(4), REQ-193 (1)–(3) and REQ-205 (1) hold, and the REQ-186 (3) property test finds no exception in 10,000 inputs. |
| TASK-179 | `result_verdict()` for intake: UTF-8 byte caps (`oversize`, #116), then the runner error (#12), then `classify()`; `utf8_size()` | REQ-194, REQ-205 | manager | impl-manager | **high** | `bm/services/evaluator/verdict.py` | TASK-178 (TASK-180 for the REQ-205 (2) test only); #12, #112, #116 | 70 | Unit: REQ-194 (1)–(6) and REQ-205 (2) hold. |
| TASK-180 | `eval_spec` contract (#117): `EvalSpec` with `get()`, `build_eval_spec()` (JSON-ready, payload order), strict `parse_eval_spec()` with a fixed-message `EvalSpecError` | REQ-195 | manager | impl-manager | **high** | `bm/services/evaluator/eval_spec.py` | TASK-176; #117 | 140 | Unit: REQ-195 (1)–(4) hold. |
| TASK-181 | Pure score and effective-verdict rule: `HostScore` and `host_score()` (#120); `ReevalRow`, `Effective` and `effective()` (latest by `reeval_id`, #119) | REQ-196, REQ-197 | manager | impl-manager | **high** | `bm/services/evaluator/score.py` | TASK-176; #119, #120 | 90 | Unit: REQ-196 (1)–(3) and REQ-197 (1), (2) hold. |
| TASK-182 | Results read repository per design note D3: `effective_results(conn, scan_id)` (both verdicts per result, with the agent and the latest row's `policy_version`) and `host_counts(conn, scan_id)` (passed, failed, errors, not run per agent) | REQ-197, REQ-198 | manager | impl-manager | **high** | `bm/repositories/results.py` | none (M1 schema); #119 | 170 | PostgreSQL as `bitscan_app` with owner-written rows: REQ-198 (1)–(5) hold. |
| TASK-183 | Re-evaluation repository (design note D4): `lock_scan()` (the per-scan transaction lock, then the scan row), `current_definitions()` (one statement), `stored_results()` (server-side cursor, chunks of at most `chunk`), `insert_reevals()` (one `unnest` insert per chunk) | REQ-200, REQ-201 | manager | impl-manager | **high** | `bm/repositories/reeval.py` | none (M1 schema); #118 | 160 | PostgreSQL as `bitscan_app`: each function works with only the TS §5.2 grants; the definitions read is one statement (statement spy); chunks never exceed the given size and cover each result exactly once; inserting N rows adds exactly N; two sessions locking one scan serialise and two scans do not; ruff S608 passes and a planted f-string is red. |
| TASK-184 | Host scores service `scan_host_scores(db, scan_id)` | REQ-197, REQ-199 | manager | impl-manager | **high** | `bm/services/evaluator/scores.py` | TASK-181, TASK-182; #120 | 60 | PostgreSQL: REQ-199 (1)–(4) hold, and the REQ-197 (3) property test shows the SQL and `effective()` agree on 200 random sets. |
| TASK-185 | Re-evaluation service `reevaluate_scan(db, scan_id, *, user_id, wake)` per design note D4: lock, definitions, chunked `classify()`, intake details kept, rows inserted, the `scan.reevaluate` audit entry in the same transaction, `ScanNotFound` and `PolicyDeleted`, `ReevalResult` | REQ-200, REQ-201, REQ-202 | manager | impl-manager | **high** | `bm/services/evaluator/reevaluate.py` | TASK-176, TASK-178, TASK-183; #12, #118 | 150 | PostgreSQL as `bitscan_app`: REQ-200 (1)–(9) and REQ-201 (1)–(5) hold. |

Totals: 20 REQ (REQ-186 to REQ-205), 10 TASK (TASK-176 to TASK-185), 15 test-plan items (TP-M8-00 to TP-M8-14), 4 waves (W1 to W4) plus the gate. All 10 tasks are high risk. Every task is within 5 files and about 200 hand-written lines; TASK-182 and TASK-183 are the largest (if one grows: TASK-182 splits `host_counts` into `results_counts.py`; TASK-183 splits the read side from `insert_reevals`; one task id each, as in M7).

REQ to TASK: REQ-186 TASK-178; REQ-187 TASK-176; REQ-188 TASK-177; REQ-189 TASK-177; REQ-190 TASK-177; REQ-191 TASK-177; REQ-192 TASK-178; REQ-193 TASK-176, TASK-178; REQ-194 TASK-179; REQ-195 TASK-180; REQ-196 TASK-181; REQ-197 TASK-181, TASK-182, TASK-184; REQ-198 TASK-182; REQ-199 TASK-184; REQ-200 TASK-183, TASK-185; REQ-201 TASK-183, TASK-185; REQ-202 TASK-176, TASK-185 (and every pure-module task by its imports); REQ-203 TASK-176 to TASK-181; REQ-204 TASK-183, TASK-185; REQ-205 TASK-178, TASK-179. REQ-203 and REQ-204 are test requirements: the tester proves them (TP-M8-08, TP-M8-12, TP-M8-13) on the code those tasks deliver. Every M8 REQ has at least one TASK, and every TASK has at least one REQ.

### M8 owner and review notes

- **Owners:** impl-manager: TASK-176 to TASK-185. No impl-web, impl-agent, impl-bits or impl-deploy task (no screen, agent, sample, unit, packaging or workflow change; CI already runs the whole pytest suite, which picks up the new files). The tester owns every test file and fixture: `manager/tests/`, `tests/m8/`.
- **Approvals (TS §8.2 L1268):** the evaluator is not one of the two-approval areas (importer, auth, agent, runner), and no M8 task edits importer, auth, agent or runner code (it only imports `importer/values.py` and `importer/model.py`). One reviewer approval per task suffices by the spec; PD-38 asks whether you want more.
- **Shared files:** none. Every file has exactly one task.
- **Interfaces for M9 and M11** (frozen once W1 and W2 pass): `evaluator.model` (`Verdict`, `Detail`, `INTAKE_DETAILS`, caps, `PluginSpec`, `ResultLike`); `evaluator.eval_spec` (`build_eval_spec` for M9's job builder, `parse_eval_spec` for intake); `evaluator.verdict.result_verdict` (intake stores its code and detail); `evaluator.scores.scan_host_scores` and `repositories.results` (M11's scan summary and results views); `evaluator.reevaluate.reevaluate_scan` (M11's `POST /scans/{id}/reevaluate`, behind `require_totp_session("admin")`, which also applies the sink gate). M11 adds paging and filters to `repositories/results.py` rather than writing a second effective-verdict query.
- Planted violations are made in a throwaway copy, never left in the tree.

### M8 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m8/test-plan.md`, check ids `CHK-M8-###`; suggested ranges: 001–019 model and normaliser, 020–099 operators, `classify`, `evaluate`, details and the SR §1.1 example, 100–139 `result_verdict`, `eval_spec`, score and the property suite, 140–219 PostgreSQL repositories, services and races, 220–259 security and boundaries, 300–319 gate rows, 320 on the mutation table). PostgreSQL items run in WSL with `CI=true` and pytest-xdist; on the Windows box they are reported NOT RUN. Races use barriers and two sessions, never sleeps (decisions 2026-10-26).

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M8-00 | Phase test plan and the M8 index row | all M8 | phase start; report at the gate | `tests/m8/test-plan.md`, `tests/test-plan.md` | none |
| TP-M8-01 | PostgreSQL fixture builder: owner-written `scan`, original and retry `scan_job` rows (payload in the TS §6.5 shape, `eval_spec` per #117), `scan_result` rows with matching `job_created_at`, `scan_result_reeval` rows; row checksums; a stdout, stderr and expected canary | REQ-198 to REQ-201, REQ-204 | W1 (before TASK-182 TEST) | `manager/tests/evaluator_pg_fixtures.py` | none |
| TP-M8-02 | Model and normaliser | REQ-187, REQ-193 | TASK-176 TEST | `manager/tests/test_evaluator_model.py`, `manager/tests/test_evaluator_normalise.py` | TASK-176 IMPL |
| TP-M8-03 | Operators: the REQ-188 to REQ-191 tables | REQ-188 to REQ-191 | TASK-177 TEST | `manager/tests/test_evaluator_operators.py` | TP-M8-02 |
| TP-M8-04 | `classify` and `evaluate`: ERROR rules, exit-code boundaries, detail order, SR §1.1 | REQ-186, REQ-192, REQ-193, REQ-205 | TASK-178 TEST | `manager/tests/test_evaluate.py` | TP-M8-03 |
| TP-M8-05 | `result_verdict`: caps in bytes, runner errors, stdout only | REQ-194, REQ-205 | TASK-179 TEST | `manager/tests/test_evaluator_verdict.py` | TP-M8-04 |
| TP-M8-06 | `eval_spec` build and parse | REQ-195 | TASK-180 TEST | `manager/tests/test_eval_spec.py` | TASK-180 IMPL |
| TP-M8-07 | Score and effective rule | REQ-196, REQ-197 | TASK-181 TEST | `manager/tests/test_evaluator_score.py` | TASK-181 IMPL |
| TP-M8-08 | Property suite (hypothesis): totality, normaliser idempotence for inputs with no CR directly before a CRLF (REQ-187 (2); decisions 2026-10-29, "Normaliser: one-pass CRLF → LF"; `"a\r\r\nb"` is the pinned counterexample), `Decimal` oracle, `evaluate` = `classify` = `result_verdict` codes, score bounds, `eval_spec` round trip | REQ-186, REQ-187, REQ-190, REQ-195, REQ-196, REQ-203 | TASK-178 TEST (grown in TASK-179, 180, 181 TEST) | `manager/tests/test_evaluator_property.py` | TP-M8-04 |
| TP-M8-09 | Results repository on PostgreSQL | REQ-197, REQ-198 | TASK-182 TEST | `manager/tests/test_results_repo_pg.py` | TP-M8-01 |
| TP-M8-10 | Re-evaluation repository on PostgreSQL: grants, one statement, chunks, insert, lock | REQ-200, REQ-201 | TASK-183 TEST | `manager/tests/test_reeval_repo_pg.py` | TP-M8-01 |
| TP-M8-11 | Host scores service, SQL-versus-`effective()` property test | REQ-197, REQ-199 | TASK-184 TEST | `manager/tests/test_scores_pg.py` | TP-M8-07, TP-M8-09 |
| TP-M8-12 | Re-evaluation service: REQ-200 cases, the races, the memory row, audit entry and chain | REQ-200, REQ-201, REQ-204 | TASK-185 TEST | `manager/tests/test_reevaluate_pg.py`, `manager/tests/test_reevaluate_race_pg.py` | TP-M8-04, TP-M8-10 |
| TP-M8-13 | M8 security and boundary suite: import graph, canary over the M8 suites, grant probes, statement spies, `re` and S608 plants | REQ-189, REQ-202, REQ-204 | each M8 TEST that touches a row; whole at the gate | `manager/tests/test_security_m8.py` | TP-M8-02 to TP-M8-12 |
| TP-M8-14 | M8 gate and mutation table | all M8 | M8 gate | `tests/m8/report.md` (folded by the lead, decisions 2026-10-27) | all above |

### M8 waves and dependency spine

Spine: `TASK-176 → TASK-177 → TASK-178 → {TASK-179, TASK-185}`; `TASK-176 → TASK-180` (and TASK-180 → TASK-179's REQ-205 (2) test); `TASK-176 → TASK-181 → TASK-184`; `TASK-182 → TASK-184`; `TASK-183 → TASK-185`. The graph is acyclic.

Interface first: TASK-176 fixes `Verdict`, `Detail`, `PluginSpec`, `ResultLike` and the caps before every other evaluator task; TASK-180 fixes the `eval_spec` JSON before M9 builds jobs; TASK-182 and TASK-183 fix the repository signatures (`work/plans/TASK-182.md` §2, `work/plans/TASK-185.md` §2) in W1, before the services that use them.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-176, 182, 183; tester TP-M8-00, TP-M8-01 | `bm/services/evaluator/{__init__,model,normalise}.py` · `bm/repositories/results.py` · `bm/repositories/reeval.py` · `tests/m8/test-plan.md`, `tests/test-plan.md`, `manager/tests/evaluator_pg_fixtures.py` |
| W2 | TASK-177, 180, 181 | `bm/services/evaluator/operators.py` · `eval_spec.py` · `score.py` |
| W3 | TASK-178, 184 | `bm/services/evaluator/evaluate.py` · `scores.py` |
| W4 | TASK-179, 185 | `bm/services/evaluator/verdict.py` · `reevaluate.py` |
| Gate | tester TP-M8-13 (whole) and TP-M8-14; reviewer's M8 closing review | tester files only |

Every task is high risk, so each is tested and reviewed on its own (no batches). With one impl-manager instance a wave's tasks run one after another; a second instance can take the repository tasks (TASK-182, 183) in W1 and TASK-184, 185, whose files are disjoint from the pure modules.

### M8 gate

On a clean tree every command is green, and each gate turns red on its planted violation. G7 to G11, G17, G35 to G41 (agent, units, packaging) and the web gates G12 to G16 are not re-run: M8 changes no agent, unit, package or web file. G6 and G34 are re-run to show M8 added no route.

| Gate | Command (summary) | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1–G4 | ruff (S608, the `re` ban), ruff format, `mypy --strict --config-file manager/pyproject.toml manager`, hashed locks | CHK-M8-320, -349, -350; an untyped function in `evaluate.py` | local; CI |
| G5 | services coverage ≥ 85 % (now including `services/evaluator`), Linux run | an untested function in `bm/services/evaluator/reevaluate.py` sized from the clean report | WSL; CI |
| G6 | OpenAPI export byte-identical (unchanged by M8) | a route added without re-export | local; CI |
| G18 | full manager suite, 0 skipped, `-n auto` | any of G62 to G65 | WSL; CI |
| G34 | `pytest tests/test_invariants_m3.py` (route walk; no new operation) | a planted `POST /scans/{id}/reevaluate` stub | local; CI |
| G62 | evaluator unit suite: `test_evaluator_model.py`, `test_evaluator_normalise.py`, `test_evaluator_operators.py`, `test_evaluate.py`, `test_evaluator_verdict.py`, `test_eval_spec.py`, `test_evaluator_score.py` (every operator, every ERROR case, every detail, the normaliser, SR §1.1) | the G62 rows | local; WSL; CI |
| G63 | evaluator property suite: `test_evaluator_property.py` | CHK-M8-338, -364 | local; WSL; CI |
| G64 | evaluator integration on PostgreSQL: `test_results_repo_pg.py`, `test_reeval_repo_pg.py`, `test_scores_pg.py`, `test_reevaluate_pg.py`, `test_reevaluate_race_pg.py` | the G64 rows | WSL; CI |
| G65 | M8 security and boundary suite: `test_security_m8.py` | the G65 rows | local (unit part); WSL; CI |

**No gate is lowered.** NOT RUN at the M8 gate, with reasons: the TS §8.3 Integration item "verdict uses the queued `eval_spec` after a catalog change" end to end (needs result intake, **M9**; M8 proves the API-level half, REQ-204); the end-to-end scan → results step (**M11** nightly); load tests (deferred by the user).

### M8 mutation table (tester; CHK-M8-320 onwards)

Each row is planted in a throwaway copy and must turn the named gate red. Security rows (S) run as targeted mini-runs; every row is full rigor (evaluator is high risk).

| CHK | Plant | Red in | Target | S |
| --- | --- | --- | --- | --- |
| CHK-M8-320 | `import re` in `operators.py` and `regex` evaluated with `re.search` | G1; G62 (`(?=x)` gives PASS/FAIL instead of `cannot evaluate`) | TASK-177 | S |
| CHK-M8-321 | `regex` compiled with its own `re2.compile` without `(?m)` | G62 (multiline row) | TASK-177 | |
| CHK-M8-322 | `regex` uses `fullmatch`/`match` instead of `search` | G62 (`foo` in `xfoo`) | TASK-177 | |
| CHK-M8-323 | `not_regex` returns PASS when the pattern does not compile | G62 | TASK-177 | S |
| CHK-M8-324 | Normaliser does not replace CRLF | G62 | TASK-176 | |
| CHK-M8-325 | Normaliser uses `str.strip()` (Unicode whitespace) | G62 (U+00A0 rows) | TASK-176 | |
| CHK-M8-326 | Comparison case-folded | G62 | TASK-177 | |
| CHK-M8-327 | Numeric comparison through `float()` | G62 (2⁵³ + 1 row) | TASK-177 | |
| CHK-M8-328 | Numeric parse through `Decimal()` without the #13 grammar (accepts `1e3`, `nan`) | G62 | TASK-177 | |
| CHK-M8-329 | `ne` returns PASS on non-numeric stdout | G62 | TASK-177 | S |
| CHK-M8-330 | Exit code decides: exit 1 gives FAIL | G62 (`grep` row) | TASK-178 | |
| CHK-M8-331 | `exit_code > 128` instead of `>= 128` | G62 (128 row) | TASK-178 | |
| CHK-M8-332 | 126 or 127 not ERROR | G62 | TASK-178 | |
| CHK-M8-333 | Negative or None exit code compared normally (against #114) | G62 | TASK-178 | |
| CHK-M8-334 | `timed_out` ignored | G62 | TASK-178 | S |
| CHK-M8-335 | `truncated` ignored | G62 | TASK-178 | S |
| CHK-M8-336 | Detail order changed (`stdout truncated` before `timed out`) | G62 | TASK-178 | |
| CHK-M8-337 | `Verdict` invariant removed (PASS with a detail, ERROR without one) | G62 | TASK-176 | |
| CHK-M8-338 | `classify` raises on an unknown operator (no totality) | G63 | TASK-177, 178 | S |
| CHK-M8-339 | Caps measured in characters, not UTF-8 bytes | G62 (multi-byte row) | TASK-179 | S |
| CHK-M8-340 | Caps compared with `>=` instead of `>` | G62 (65,536 row) | TASK-179 | |
| CHK-M8-341 | Oversize decided from the agent's `truncated` flag only | G62 | TASK-179 | S |
| CHK-M8-342 | Runner error still evaluated (`classify` called) | G62 (spy row) | TASK-179 | S |
| CHK-M8-343 | stderr compared instead of, or as well as, stdout | G62 | TASK-179 | |
| CHK-M8-344 | `parse_eval_spec` accepts an extra key or a duplicate `plugin_uuid` | G62 | TASK-180 | S |
| CHK-M8-345 | `build_eval_spec` writes `execute` | G62 | TASK-180 | S |
| CHK-M8-346 | Score counts ERROR in the denominator | G62 | TASK-181 | |
| CHK-M8-347 | Score 0 ÷ 0 returns 0.0 instead of None | G62 | TASK-181 | |
| CHK-M8-348 | Effective rule takes the lowest `reeval_id`, or orders by `reevaluated_at` | G62, G64 | TASK-181, 182 | S |
| CHK-M8-349 | An f-string query in `repositories/results.py` | G1 (S608) | TASK-182 | S |
| CHK-M8-350 | An f-string query in `repositories/reeval.py` | G1 (S608) | TASK-183 | S |
| CHK-M8-351 | Counts query looks up the latest re-evaluation per result (a lateral or correlated subquery over `scan_result_reeval`) | G64 (EXPLAIN row) | TASK-182 | |
| CHK-M8-352 | Not run ignores the retry's results, or counts retry plugins twice | G64 | TASK-182 | |
| CHK-M8-353 | Re-evaluation UPDATEs `scan_result.eval_code` (the grant refuses it; the test must see the failure) | G64, G65 | TASK-185 | S |
| CHK-M8-354 | Definitions read per plugin in separate statements (no single snapshot) | G64 (race row) | TASK-183 | S |
| CHK-M8-355 | Intake-decided ERRORs re-evaluated (`oversize` row becomes PASS for `empty`) | G64 | TASK-185 | S |
| CHK-M8-356 | Rows added for plugins the current version no longer lists | G64 | TASK-185 | |
| CHK-M8-357 | Re-evaluation allowed for a deleted policy | G64 | TASK-185 | |
| CHK-M8-358 | The per-scan lock removed | G64 (concurrent row) | TASK-183 | S |
| CHK-M8-359 | Audit entry missing, or written in its own transaction (survives the injected fault) | G64 | TASK-185 | S |
| CHK-M8-360 | All results fetched at once (`fetchall`, no chunks) | G64 (memory row) | TASK-183, 185 | |
| CHK-M8-361 | A pure module imports `repositories.catalog` (evaluation reads the current plugin row) | G65 (import graph) | TASK-178 | S |
| CHK-M8-362 | stdout logged at DEBUG in `classify`, or carried in an exception message | G65 (canary) | TASK-178, 185 | S |
| CHK-M8-363 | `eval_detail` built as `"stdout not numeric: " + stdout` | G62, G65 | TASK-178 | S |
| CHK-M8-364 | `Verdict` accepts code 3 ("anything else" not stored as 2) | G62, G63 | TASK-176 | |

### Open items for M8

All are in `work/open-questions.md` ("M8"), each with a recommended answer. "Needed by" is the start of the wave whose task or test cannot finish without it.

| Item | Blocks | Needed by |
| --- | --- | --- |
| #112 (new): `eval_detail` vocabulary, where it comes from, order, totality | TASK-176, 178 | W1 |
| #115 (new): normaliser whitespace set | TASK-176 | W1 |
| #116 (new): server-side caps (bytes, boundary, order, what M9 stores) | TASK-176 (constants), 179 | W1 |
| #119 (new): "latest" re-evaluation and the effective pair | TASK-181, 182 | W1 |
| #118 (new): re-evaluation scope, deleted or disabled policies, audit, concurrency | TASK-183, 185 | W1 |
| #117 (new): `eval_spec` JSON shape | TASK-180 | W2 |
| #120 (new): score value and scope | TASK-181, 184 | W2 |
| #113 (new; the `evaluator.md:28` own question): stderr-only truncation | TASK-178 (W3); the runner in M10 | W3 |
| #114 (new): null and negative exit codes | TASK-178 | W3 |
| #11, #12, #13 (agreed, reused) | TASK-176 (`INTAKE_DETAILS`, #12), 177, 178, 179, 185 | W1 |
| PD-38 (new): approvals and second looks for M8 | each task's REVIEW | W1 |

### Coverage matrix (M8)

| Spec section | Covered by | Status in M8 |
| --- | --- | --- |
| TS §1.1 G4 (L16) compliance profiles | REQ-200 (re-evaluation against the profile's current version) | Covered for evaluation; scans are **M9** |
| TS §2.1 L105 result evaluator ("compare stdout … compute scores", "in the API process, on result arrival") | REQ-186 to REQ-199 | Covered; the call on arrival is **M9** intake |
| TS §2.2 L114 immutable results, re-evaluation adds rows | REQ-200, REQ-204 | Covered |
| TS §2.3 compliance flow step 6 (L137) | REQ-194, REQ-195 | Pure verdict and `eval_spec` covered; "stored with its verdict in one insert" is **M9** |
| TS §3.3 L226 `spool_overflow` | REQ-194 | Covered (manager side) |
| TS §3.5 L248 Operator and ExpectedResult stay on the manager | REQ-195 | Covered (the contract keeps them out of the payload); the pull is unchanged (M3) |
| TS §3.5 L251–L252 caps and flags | REQ-194, #113 | Manager side covered; runner truncation and the flag are **M10** |
| TS §4.4 L577–L579 retry, late results, score updates | REQ-198, REQ-199 | Read side covered (scores computed on read); first-result-wins and late intake are **M9** |
| TS §4.4 L583 *Not run* left out of the score | REQ-196, REQ-198 | Covered |
| TS §4.5 L587 evaluate against the queued `eval_spec` | REQ-195, REQ-202, REQ-204 | API-level covered; end to end through intake **M9** |
| TS §4.5 L589–L593 return codes and ERROR cases | REQ-186, REQ-192, REQ-193, REQ-194 | Covered (#12, #112, #113, #114) |
| TS §4.5 L595 operators | REQ-188 to REQ-191 | Covered (#11: as written) |
| TS §4.5 L596 input is the redacted stdout | REQ-194 | Covered (stdout taken as received); redaction is **M10** |
| TS §4.5 L597 normalisation | REQ-187 | Covered (#115) |
| TS §4.5 L598 exit code does not decide | REQ-192 | Covered (#114) |
| TS §4.5 L599 server-side caps | REQ-194 | Decision covered (#116); storing the result is **M9** |
| TS §4.5 L600 one pure function, unit tests, RE2 | REQ-186, REQ-189, REQ-203 | Covered |
| TS §4.5 L601 re-evaluation; latest row used; `result` and `original_result` | REQ-197, REQ-198, REQ-200, REQ-201 | Computation and rule covered (#118, #119); the route, TOTP session, sink gate and response are **M11** |
| TS §4.5 L602 score; "n/a"; error count beside it | REQ-196, REQ-199 | Value covered (#120); display is **M11** |
| TS §4.5 L603 snapshots | REQ-195 (`name`, `operator`, `expected` in `eval_spec`) | Snapshot columns written by intake, **M9** |
| TS §5.2 L880, L888 `eval_spec` | REQ-195 | Covered (#117) |
| TS §5.2 L892–L927 `scan_result`; L929–L938 `scan_result_reeval` | REQ-198, REQ-200 | Read and insert as migrated; **no schema change** |
| TS §5.2 L1005–L1006 the app never changes results or re-evaluations | REQ-200, REQ-204 | Covered (grant probes, statement spies) |
| TS §5.3 L1049 re-evaluations added only through the admin route | REQ-200 | Service covered; the admin route is **M11** |
| TS §5.3 L1052 no results in logs | REQ-202 | Covered |
| TS §6.2 L1120–L1123 scan summary, results, re-evaluate routes | none | **M11** |
| TS §6.5 L1184 Results fields | REQ-194 (`ResultLike`) | Read only; contract unchanged |
| TS §8.1 L1243 tampering with verdicts; L1249 sensitive output; L1252 SQL injection | REQ-200, REQ-202, REQ-198 | Covered |
| TS §8.3 Unit (normaliser, evaluator) | REQ-203 / G62, G63 | Covered |
| TS §8.3 Integration ("re-evaluation adds rows only"; "verdict uses the queued `eval_spec` after a catalog change") | REQ-204 / G64 | First covered; second API-level only, end to end **M9** |
| TS §8.3 Security ("first result wins under concurrent retries") | none | **M9** |
| TS §8.4 L1287 logs; L1288 "plugin ERROR rate" metric | REQ-202 | Logs covered; the metric is counted at intake, **M9** |
| TS §8.5 L1296 confirm the 14 operators and normalisation | #11, #115 | Kept as written |
| SR §1.1 L87 canonical PASS and FAIL | REQ-205 | Covered |
| SR §2.4 L124–L154 operators, return codes, normalisation, stdout only, numbers, who evaluates | REQ-186 to REQ-195 | Covered |
| SR §2.4 L155–L162 script rules | none | Authoring rules (M7 samples); nothing to evaluate |
| CLAUDE.md out of scope and owner decisions | none | Nothing planned: no CVE matching, remediation, signing or approval workflow; the evaluator only reads and reports |

## M9 scan engine (jobs, scans, schedules, result intake)

Planned 2026-10-30 (planner-m9) in the worktree `Bitscan-m9` (branch `m9-scan-engine`, from main `d09c537`, M8 merged). Consistency pass done: every TASK links a REQ and every REQ has a TASK (or is a named test requirement); waves are file-disjoint; every task is within 5 files and about 200 hand-written lines; the spine is acyclic; no gate is lowered. Summary for the user: `work/plans/M9-breakdown.md`.

Scope: REQ-206 to REQ-233 in `work/requirements.md`. In this section `bm/` means `manager/bitscan_manager/`.

**No new spec deviation.** Every open item (#121 to #129 new; #3, #18, #22, #12, #116, #117, #54 (c), #66 reused as agreed; PD-39, PD-40) carries a recommended answer in `work/open-questions.md` ("M9"). **No migration, no agent change, no contract change, no new dependency.** Seven user operations are added, all TS §6.2 routes; the two agent job routes change behaviour, not shape.

Rules every M9 task follows:
- **Testing by risk (user, 2026-10-25).** High risk, full rigor per task (a plant for every security row, boundary and race the task names): every task touching the agent routes, result intake, first-result-wins, job building, or RBAC on the scan routes. Low risk, batched TEST and REVIEW allowed: TASK-207 (web regeneration) and TASK-208 (README).
- **Time-skewing (user, 2026-10-26):** clock control only; races driven by barriers and two sessions, never sleeps.
- `api → services → repositories`. The pure modules (`states`, `scan_state`, `targets`, `build`, `intake_plan`, `cron`, `api/user/idempotency`) take plain values and import no database, repository or API code. Parameterised SQL only (ruff S608); RE2 only (ruff bans `re`).
- **Reuse, don't copy:** M8's `evaluator.eval_spec` (`EvalSpec`, `build_eval_spec`, `parse_eval_spec`), `evaluator.verdict.result_verdict` and `over_caps`, `evaluator.model.PluginSpec`; M3's `TxAudit`, `refuse_results`, `agent_windows`, `read_settings`, `PICKUP_WINDOW`; M3's tag constants in `services/agents/admin.py` (`MAX_TAGS`, `MAX_TAG_LENGTH`, `TAG_CHARACTERS`); M2's `require_role`, `page_params`, `page_of`. No M9 task edits an M7 importer file, an M8 evaluator file or an auth file.
- Lock order everywhere a unit is touched: the root job (`COALESCE(retry_of, job_id)`) `FOR UPDATE`, then the job `FOR UPDATE` (#124 (c)). The scan queue: queue lock, then the policy row `FOR SHARE` (#125 (d)).
- Nothing in M9 writes `payload`, `eval_spec`, `agent_id`, `scan_id` or `retry_of` of an existing job, or updates or deletes a `scan_result`. No log line, exception message or audit detail carries stdout, stderr, `execute` or an expected value.
- Implementers check `work/reviews/builder-checklist.md` before every hand-off.

### M9 design notes (for the tasks with real design risk)

Written out in `work/plans/TASK-198.md` (D1, with the TASK-188, 189 and 193 interfaces), `work/plans/TASK-199.md` (D2, with the TASK-186, 190 and 195 interfaces), `work/plans/TASK-202.md` (D3, with the TASK-187, 194 and 196 interfaces) and `work/plans/TASK-203.md` (D4, with the TASK-191, 197 and 201 interfaces).
- **D1 queue a scan (TASK-198).** One `db.transaction()`: `pg_advisory_xact_lock(hashtext('scan_queue:' || policy_id))` → policy row `FOR SHARE` → one snapshot statement (version, status, `deleted_at`, active plugins in `sort_order` with display names) → refusals → `build.plugins_and_spec()` (unstorable-text check) → target resolved (one statement) → INSERT `scan` → INSERT every job in one `INSERT … SELECT FROM unnest(job_ids, agent_ids)` with the payload composed in SQL from one `plugins` JSONB parameter → cancel older queued jobs of the policy for those agents (uses `ix_job_pending`) → `scan.create` entry (or the alert entry) → commit.
- **D2 result intake (TASK-199).** The route caps and decodes (unchanged M3 code). Then one transaction: root `FOR UPDATE` → job `FOR UPDATE` → acceptance (`states.accepts_results`, the agent, the kind) → `parse_eval_spec` (fails closed, #124 (h)) → result uuids of the unit (the sibling looked up through `retry_of` only when the posted job is a `failed`, `partial` or `completed` original, #127 (f); decisions 2026-10-30, "First result wins includes completed originals") → `intake_plan.plan()` (membership, #121 text rule, in-batch and unit duplicates, `result_verdict`, snapshots) → one INSERT → `states.after_batch()` → UPDATE progress columns → commit → `bitscan_plugin_results_total` on commit. A refusal leaves the transaction and is written by M3's `refuse_results` in its own.
- **D3 sweep and scan refresh (TASK-202).** Three new steps after the M3 ones, each its own transaction: `compliance_deadline` and `never_started` (candidates `FOR UPDATE SKIP LOCKED` on the root, then the job; outcome by `states.after_deadline`; retry built by `build.retry()` and inserted in the same transaction, #126 (c)); then `scan_states` (one grouped read of unit facts for the #127 (f) candidates, `scan_state.derive()`, UPDATE only the changed scans).
- **D4 schedules (TASK-203).** A `scan_schedules` APScheduler interval job every 30 s: due rows `FOR UPDATE SKIP LOCKED`; a due time older than 2 min is `missed`; skip rules (#128 (f)); `queue_scan(trigger='scheduled')`; `next_run_at` from `cron.next_fire()` strictly after now. Cron is crontab(5) translated for APScheduler 3 (weekday numbers to names; both day fields restricted refused).

### M9 tasks

| TASK | Title | REQ links | Area | Owner | Risk | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-186 | Job state rules (interface, pure): transitions, `deadline_at()`, `after_batch()`, `after_deadline()`, `accepts_results()`, `FINAL` (plan TASK-199 §2) | REQ-206, REQ-217 | manager | impl-manager | **high** | `bm/services/jobs/states.py` | none; #124 (a), #127 (a)–(c) | 120 | Unit: REQ-206 (1)–(5) hold. |
| TASK-187 | Scan state derivation (interface, pure): `Unit` facts and `derive()` returning state and finished (plan TASK-202 §2) | REQ-207, REQ-219 | manager | impl-manager | **high** | `bm/services/jobs/scan_state.py` | none; #22, #127 (d), (e) | 80 | Unit: REQ-207 (1)–(3) hold. |
| TASK-188 | Scan targets (interface, pure): `Target`, `parse_target()`, `InvalidTarget`, `stored_target()` (plan TASK-198 §2) | REQ-208 | manager | impl-manager | **high** | `bm/services/jobs/targets.py` | none; #122 (b)–(d) | 90 | Unit: REQ-208 (1), (2) and (4) hold. |
| TASK-189 | Job and retry builder (interface, pure): `CatalogPlugin`, `plugins_and_spec()`, `payload()`, `retry()`, `UnstorableText` (plan TASK-198 §2) | REQ-209, REQ-210, REQ-212 | manager | impl-manager | **high** (second look, PD-39) | `bm/services/jobs/build.py` | none (M8 `eval_spec`); #117, #125 (a)–(c), (g), #126 (a), (b) | 150 | Unit: REQ-209 (1)–(4) and (6) and REQ-210 (1)–(4) hold for plugins given as values. |
| TASK-190 | Intake plan (interface, pure): #121 text rule, plugin membership, in-batch and unit duplicates, verdict and snapshot values per row (plan TASK-199 §2) | REQ-214, REQ-215, REQ-216 | manager | impl-manager | **high** (TS §8.2 second approval, PD-39) | `bm/services/jobs/intake_plan.py` | none (M8 `result_verdict`); #12, #116 (d), #121, #124 (a), (b) | 130 | Unit: for a given `eval_spec`, payload, set of existing result uuids and batch, the plan lists exactly the rows to insert with their verdicts and snapshots and the duplicates count, or refuses a batch naming a plugin outside the job; REQ-215 (2), (4), (6) hold at plan level. |
| TASK-191 | Cron and time zone (interface, pure): `parse_schedule()`, `next_fire()`, `InvalidSchedule` on APScheduler 3 `CronTrigger` with crontab(5) weekday translation (plan TASK-203 §2) | REQ-223 | manager | impl-manager | **high** | `bm/services/scheduler/cron.py` | none; #128 (a)–(c) (DST per the user's decision of 2026-10-30, r1) | 100 | Unit: REQ-223 (1)–(4) hold, the DST rows giving the decided behaviour (gap shifted, repeat run once). |
| TASK-192 | Idempotency store (pure, in memory): per user and key, 24 h, 100,000 entries, per-key lock, body comparison | REQ-222 | manager | impl-manager | **high** | `bm/api/user/idempotency.py` | none; #123 | 90 | Unit with a fake clock and two threads: REQ-222 (1)–(3) hold. |
| TASK-193 | Scan queue repository: queue lock, policy snapshot `FOR SHARE` in one statement, target resolution, scan insert, one-statement job insert, older queued jobs cancelled (plan TASK-198 §3) | REQ-208, REQ-211, REQ-230 | manager | impl-manager | **high** | `bm/repositories/scan_queue.py` | none (M1 schema); #125 (d)–(f) | 180 | PostgreSQL as `bitscan_app`: REQ-208 (3) holds; the snapshot is one statement and a concurrent policy delete waits for the scan's commit; N jobs are one INSERT; the older-queued cancel touches only queued compliance jobs of that policy for the listed agents; G1 is red on a planted f-string. |
| TASK-194 | Scan progress repository: unit facts for many scans in one statement, refresh candidates (#127 (f)), scan state update, a scan's open jobs cancelled (plan TASK-202 §3) | REQ-219, REQ-220, REQ-230 | manager | impl-manager | **high** | `bm/repositories/scan_progress.py` | none; #127 (d)–(f) | 160 | PostgreSQL as `bitscan_app`: unit facts match owner-written fixtures (originals with retries, results, every state); candidates exclude `completed` scans and finished scans older than 8 days; cancel moves only `queued`, `dispatched` and `running` jobs of that scan; only `state` and `finished_at` of `scan` are updated. |
| TASK-195 | Intake repository: root then job `FOR UPDATE`, job read with payload and `eval_spec`, unit result uuids, sibling lookup, one-statement result insert, progress updates (plan TASK-199 §3) | REQ-215, REQ-216, REQ-217, REQ-230 | manager | impl-manager | **high** (TS §8.2 second approval, PD-39) | `bm/repositories/job_intake.py` | none; #124 (c), #127 (f) | 170 | PostgreSQL as `bitscan_app`: a second session locking the same root waits; N rows insert in one statement with `job_created_at` accepted by the trigger; `started_at` and `deadline_at` are written only while NULL; G1 is red on a planted f-string. |
| TASK-196 | Compliance sweep repository: deadline and never-started candidates, root-first `SKIP LOCKED`, unit results, state update, retry insert (plan TASK-202 §3) | REQ-218, REQ-230 | manager | impl-manager | **high** | `bm/repositories/job_sweep.py` | none; #126, #127 (b) | 160 | PostgreSQL as `bitscan_app`: candidates follow the strict boundaries; a root held by another session is skipped; the retry row has the given payload, `eval_spec` and `retry_of`; only progress columns of the original change. |
| TASK-197 | Schedules repository: CRUD SQL, cursor page, due rows `FOR UPDATE SKIP LOCKED`, the previous scan's `finished_at`, run bookkeeping, the policy row `FOR SHARE` for create and enable (r1, decisions 2026-10-30 "M9 builder rulings" (5)) (plan TASK-203 §3) | REQ-224, REQ-225, REQ-230 | manager | impl-manager | **high** | `bm/repositories/schedules.py` | none; #122 (h), #128 (d) | 150 | PostgreSQL as `bitscan_app`: CRUD round trip; due selection skips rows another session holds; the policy read for create and enable holds `FOR SHARE`, so a concurrent policy delete waits for its commit; DELETE leaves that schedule's scans with `schedule_id` NULL. |
| TASK-198 | Queue service `queue_scan()` per design note D1, with `scan.create` and the all-hosts alert | REQ-209, REQ-211, REQ-212, REQ-227 | manager | impl-manager | **high** (second look, PD-39) | `bm/services/jobs/queue.py` | TASK-188, 189, 193; #3, #18, #122 (f), #125, #129 (a), (b) | 150 | PostgreSQL as `bitscan_app`: REQ-211 (1)–(6), REQ-209 (5), REQ-212 (2) and REQ-227 (1), (2) for `scan.create` and the alert hold. |
| TASK-199 | Intake service `accept_results()` per design note D2, and the `bitscan_plugin_results_total` counter | REQ-214, REQ-215, REQ-216, REQ-217, REQ-226, REQ-227 | manager | impl-manager | **high** (TS §8.2 second approval, PD-39) | `bm/services/jobs/intake.py`, `bm/services/audit/metrics.py` | TASK-186, 190, 195; #12, #116 (d), #121, #124, #127 (a), (c), #129 (c) | 170 | PostgreSQL service-level: REQ-214 (1)–(3), (5), (6), REQ-215 (1)–(6), REQ-216 (1)–(5), REQ-217 (1)–(6) and REQ-226 (1)–(3) hold. |
| TASK-200 | Cancel service `cancel_scan()` | REQ-219, REQ-220, REQ-227 | manager | impl-manager | **high** | `bm/services/jobs/cancel.py` | TASK-187, 194; #122 (g), #127 (d), #129 (a) | 70 | PostgreSQL: REQ-220 (1), (3)–(5) hold. |
| TASK-201 | Schedule management service: create, update, delete, get, list; validation; `next_run_at`; audit; create and enable lock the policy `FOR SHARE` before the not-deleted check (r1, decisions 2026-10-30 "M9 builder rulings" (5)) | REQ-224, REQ-227 | manager | impl-manager | **high** | `bm/services/scheduler/schedules_admin.py` | TASK-188, 191, 197; #122 (h), (i), #128 (d), #129 (a) | 150 | PostgreSQL service-level: REQ-224 (1)–(4), (6), (7) hold, including the create and enable races with a policy delete. |
| TASK-202 | `offline_sweep` compliance steps and the scan state refresh per design note D3 | REQ-218, REQ-219, REQ-228, REQ-229 | manager | impl-manager | **high** | `bm/services/scheduler/sweep.py` | TASK-186, 187, 189, 194, 196; #126, #127 | 140 | Clock control on PostgreSQL: REQ-218 (1)–(8), REQ-219 (1)–(5), REQ-228 (1), (2) and REQ-229 (1), (2) hold. |
| TASK-203 | Scheduled runs and the scheduler tick per design note D4 | REQ-225, REQ-227 | manager | impl-manager | **high** | `bm/services/scheduler/scan_schedules.py`, `bm/services/scheduler/runner.py` | TASK-191, 197, 198; #3, #128 (e)–(g) | 150 | Clock control on PostgreSQL: REQ-225 (1)–(8) hold, and `SchedulerRunner` starts the 30 s tick and still waits for a running job on `stop()`. |
| TASK-204 | Agent job routes for compliance jobs: pull returns compliance jobs; the results route calls `accept_results()`; re-export `manager/openapi.json` only if it changes | REQ-213, REQ-214, REQ-215, REQ-216, REQ-229 | manager | impl-manager | **high** (TS §8.2 second approval, PD-39) | `bm/repositories/jobs.py`, `bm/services/jobs/pull.py`, `bm/services/jobs/__init__.py`, `bm/api/agent/jobs.py`, (`manager/openapi.json`) | TASK-199; #124, PD-40 | 110 | A simulated agent through the real routes on PostgreSQL: REQ-213 (1)–(5), REQ-214 (1)–(6), REQ-215 (3)–(5) and REQ-216 (1)–(3) hold end to end, gzip, 400 and 413 behave as REQ-066, and REQ-229 (3) holds. |
| TASK-205 | Scan routes `POST /scans` (with `Idempotency-Key`) and `POST /scans/{id}/cancel`; re-export `manager/openapi.json` | REQ-212, REQ-220, REQ-221, REQ-222 | manager | impl-manager | **high** (second look, PD-39) | `bm/api/user/scans.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-192, 198, 200; #122, #123 | 160 (+1 generated) | Through the API on PostgreSQL: REQ-221 (1)–(5), REQ-222 (4), REQ-212 (1) and REQ-220 (2) hold. |
| TASK-206 | Schedule routes CRUD `/scan-schedules`; re-export `manager/openapi.json` | REQ-212, REQ-224 | manager | impl-manager | **high** | `bm/api/user/scan_schedules.py`, `bm/api/user/__init__.py`, `manager/openapi.json` | TASK-201; #122 (h), (i) | 170 (+1 generated) | Through the API on PostgreSQL: REQ-224 (1)–(7) and REQ-212 (1) for the schedule bodies hold. |
| TASK-207 | Web: regenerate `schema.d.ts` from the M9 `openapi.json` | REQ-232 | web | impl-web | low | `web/src/api/schema.d.ts` | TASK-204, 205, 206; PD-20 | 0 (+1 generated) | G16 shows no diff, every new path starts with `/api/v1/`, and `npm run typecheck` passes. |
| TASK-208 | README: scans and schedules (REQ-233) | REQ-233 | manager | impl-manager | low (docs) | `README.md` | TASK-205, 206 | 120 (docs) | The tester follows each new section against a WSL manager and each step behaves as written; no secret, token or process note. |

Totals: 28 REQ (REQ-206 to REQ-233), 23 TASK (TASK-186 to TASK-208), 21 test-plan items (TP-M9-00 to TP-M9-20), 6 waves (W1 to W6) plus the gate. 21 tasks are high risk, 2 low. Every task is within 5 files and about 200 hand-written lines; TASK-193 and TASK-195 are the largest (if one grows: TASK-193 splits target resolution into `bm/repositories/scan_targets.py`; TASK-199 moves the metric to its own task; one task id each, as in M7).

REQ to TASK: REQ-206 TASK-186; REQ-207 TASK-187; REQ-208 TASK-188, 193; REQ-209 TASK-189, 198; REQ-210 TASK-189; REQ-211 TASK-193, 198; REQ-212 TASK-189, 198, 205, 206; REQ-213 TASK-204; REQ-214 TASK-190, 199, 204; REQ-215 TASK-190, 195, 199, 204; REQ-216 TASK-190, 195, 199, 204; REQ-217 TASK-186, 195, 199; REQ-218 TASK-196, 202; REQ-219 TASK-187, 194, 200, 202; REQ-220 TASK-194, 200, 205; REQ-221 TASK-205; REQ-222 TASK-192, 205; REQ-223 TASK-191; REQ-224 TASK-197, 201, 206; REQ-225 TASK-197, 203; REQ-226 TASK-199; REQ-227 TASK-198, 199, 200, 201, 203; REQ-228 TASK-202 (and TASK-199 for the flood; test requirement); REQ-229 TASK-202, 204; REQ-230 TASK-193 to TASK-197; REQ-231 every M9 task (test requirement, proven by the tester); REQ-232 TASK-207 (G6 by TASK-204, 205, 206); REQ-233 TASK-208. Every M9 REQ has at least one TASK, and every TASK has at least one REQ.

### M9 owner and review notes

- **Owners:** impl-manager: TASK-186 to TASK-206 and TASK-208; impl-web: TASK-207. No impl-agent, impl-bits or impl-deploy task (no agent, sample, unit, package or workflow change; CI already runs the whole pytest suite). The tester owns every test file and fixture: `manager/tests/`, `tests/m9/`.
- **Approvals (TS §8.2 L1268; PD-39):** two approvals for TASK-204 (agent job routes) and TASK-190, 195, 199 (the intake path behind it), applied under the pre-authorisation on a clean TEST PASS and "APPROVED, no open blocking or should-fix findings". A lead's second look for TASK-189 and TASK-198 (commands that run on every host) and TASK-205 (RBAC and the API-token alert). No M9 task edits auth code.
- **Shared files (never in one wave):** `bm/api/user/__init__.py` (TASK-205 in W4, TASK-206 in W5); `manager/openapi.json` (TASK-204 in W3 only if its export changes, TASK-205 W4, TASK-206 W5; PD-24). Every other file has exactly one task: `bm/services/jobs/__init__.py` (TASK-204), `bm/services/audit/metrics.py` (TASK-199), `bm/services/scheduler/sweep.py` (TASK-202), `bm/services/scheduler/runner.py` (TASK-203), `bm/repositories/jobs.py` (TASK-204).
- **M3 tests replaced by requirement (PD-40):** in TASK-204 TEST the tester rewrites REQ-072 (4) and REQ-073 (1) checks only, and lists each old CHK id with its replacement in `tests/m9/report.md`.
- **Interfaces for M10 and M11** (frozen once W1 passes): `states`, `scan_state`, `targets`, `build`, `intake_plan`, `cron`; `repositories/scan_progress.py` (M11's `GET /scans/{id}` reads scan state from `scan`, not by re-deriving); `queue_scan()` and `cancel_scan()`.
- Planted violations are made in a throwaway copy, never left in the tree.

### M9 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m9/test-plan.md`, check ids `CHK-M9-###`; suggested ranges: 001–079 pure modules, 080–099 property suite, 100–219 PostgreSQL repositories, services, sweep, schedules and races, 220–279 API, contract and security, 300–319 gate rows, 320 on the mutation table). PostgreSQL items run in WSL with `CI=true` and pytest-xdist; on the Windows box they are reported NOT RUN.

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M9-00 | Phase test plan and the M9 index row | all M9 | phase start; report at the gate | `tests/m9/test-plan.md`, `tests/test-plan.md` | none |
| TP-M9-01 | Fixtures: catalog through M7's store (policies enabled, disabled, deleted; the SR §1.1 plugin), agents in all six statuses with tags, owner-written scans, jobs (originals and retries, every state), results; a clock double; a simulated agent built from `manager/tests/contract/fixtures/{jobs,results}` with a real `bsa_` token; a canary | REQ-208 to REQ-230 | W1 (before TASK-193 TEST) | `manager/tests/scan_pg_fixtures.py`, `manager/tests/agent_sim.py` | none |
| TP-M9-02 | Job state rules | REQ-206, REQ-217 | TASK-186 TEST | `manager/tests/test_job_states.py` | TASK-186 IMPL |
| TP-M9-03 | Scan state derivation | REQ-207 | TASK-187 TEST | `manager/tests/test_scan_state.py` | TASK-187 IMPL |
| TP-M9-04 | Targets | REQ-208 | TASK-188 TEST | `manager/tests/test_scan_targets.py` | TASK-188 IMPL |
| TP-M9-05 | Job and retry builder | REQ-209, REQ-210, REQ-212 | TASK-189 TEST | `manager/tests/test_job_build.py` | TASK-189 IMPL |
| TP-M9-06 | Intake plan | REQ-214 to REQ-216 | TASK-190 TEST | `manager/tests/test_intake_plan.py` | TASK-190 IMPL |
| TP-M9-07 | Cron and time zone | REQ-223 | TASK-191 TEST | `manager/tests/test_cron.py` | TASK-191 IMPL |
| TP-M9-08 | Idempotency store | REQ-222 | TASK-192 TEST | `manager/tests/test_idempotency.py` | TASK-192 IMPL |
| TP-M9-09 | Property suite (hypothesis): state-machine invariants, derivation, intake-plan accounting (accepted + duplicates = items for an accepted batch), `next_fire` strictly increasing | REQ-206, REQ-207, REQ-216, REQ-223 | TASK-186 TEST (grown in 187, 190, 191 TEST) | `manager/tests/test_jobs_property.py` | TP-M9-02 |
| TP-M9-10 | Repositories on PostgreSQL: grants, one-statement checks, locks and SKIP LOCKED with two sessions | REQ-208, REQ-211, REQ-216 to REQ-220, REQ-224, REQ-225, REQ-230 | TASK-193 to 197 TEST | `manager/tests/test_scan_queue_repo_pg.py`, `test_scan_progress_repo_pg.py`, `test_job_intake_repo_pg.py`, `test_job_sweep_repo_pg.py`, `test_schedules_repo_pg.py` | TP-M9-01 |
| TP-M9-11 | Queue service and its races | REQ-209, REQ-211, REQ-212, REQ-227 | TASK-198 TEST | `manager/tests/test_queue_scan_pg.py`, `manager/tests/test_queue_scan_race_pg.py` | TP-M9-10 |
| TP-M9-12 | Intake service; first result wins under concurrent retries (200 barrier repetitions; the M8 double count with the lock planted away) | REQ-214 to REQ-217, REQ-226 | TASK-199 TEST | `manager/tests/test_intake_pg.py`, `manager/tests/test_first_result_wins_race_pg.py` | TP-M9-06, TP-M9-10 |
| TP-M9-13 | Cancel | REQ-219, REQ-220 | TASK-200 TEST | `manager/tests/test_cancel_pg.py` | TP-M9-10 |
| TP-M9-14 | Schedule management and scheduled runs with clock control | REQ-224, REQ-225 | TASK-201, 203 TEST | `manager/tests/test_schedules_admin_pg.py`, `manager/tests/test_scan_schedules_pg.py` | TP-M9-07, TP-M9-10 |
| TP-M9-15 | Sweep compliance steps, retries and scan refresh with clock control; M3 sweep regression | REQ-218, REQ-219, REQ-228, REQ-229 | TASK-202 TEST | `manager/tests/test_sweep_compliance_pg.py` | TP-M9-10 |
| TP-M9-16 | Agent job routes end to end with the simulated agent: pull, start notice, batches, final, late results, 409 cases, 0.1.0 `runner_unavailable`, NUL fixture, catalog change after queue | REQ-213 to REQ-216, REQ-229 | TASK-204 TEST | `manager/tests/test_agent_jobs_api_pg.py` | TP-M9-12 |
| TP-M9-17 | Scan and schedule routes: bodies, refusals, RBAC, token groups, alert, idempotency | REQ-212, REQ-220 to REQ-222, REQ-224 | TASK-205, 206 TEST | `manager/tests/test_scans_api_pg.py`, `manager/tests/test_scan_schedules_api_pg.py` | TP-M9-11, TP-M9-14 |
| TP-M9-18 | M9 security and boundary suite: canary, import graph, grant probes, statement spies, S608 and `re` plants, payload-writer grep, no-ad-hoc and inventory invariants | REQ-212, REQ-229, REQ-230 | each M9 TEST that touches a row; whole at the gate | `manager/tests/test_security_m9.py` | TP-M9-02 to TP-M9-17 |
| TP-M9-19 | M3 checks replaced by requirement (PD-40), old → new CHK list | REQ-213, REQ-214 | TASK-204 TEST | the affected M3 test files; `tests/m9/report.md` | TP-M9-16 |
| TP-M9-20 | M9 gate and mutation table | all M9 | M9 gate | `tests/m9/report.md` | all above |

### M9 waves and dependency spine

Spine: `TASK-186, 190, 195 → TASK-199 → TASK-204`; `TASK-188, 189, 193 → TASK-198 → {TASK-203, TASK-205}`; `TASK-187, 194 → TASK-200 → TASK-205`; `TASK-186, 187, 189, 194, 196 → TASK-202`; `TASK-188, 191, 197 → TASK-201 → TASK-206`; `TASK-191, 197, 198 → TASK-203`; `TASK-192 → TASK-205`; `TASK-204, 205, 206 → TASK-207`; `TASK-205, 206 → TASK-208`. The graph is acyclic.

Interface first: W1 fixes every pure interface (states, scan derivation, targets, builder, intake plan, cron, idempotency) and every repository signature (the plans' §2 and §3) before any service or route uses them.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-186, 187, 188, 189, 190, 191, 192 (pure); TASK-193, 194, 195, 196, 197 (SQL); tester TP-M9-00, 01 | `bm/services/jobs/{states,scan_state,targets,build,intake_plan}.py` · `bm/services/scheduler/cron.py` · `bm/api/user/idempotency.py` · `bm/repositories/{scan_queue,scan_progress,job_intake,job_sweep,schedules}.py` · tester files |
| W2 | TASK-198, 199, 200, 201 | `bm/services/jobs/queue.py` · `bm/services/jobs/intake.py`, `bm/services/audit/metrics.py` · `bm/services/jobs/cancel.py` · `bm/services/scheduler/schedules_admin.py` |
| W3 | TASK-202, 203, 204 | `bm/services/scheduler/sweep.py` · `bm/services/scheduler/{scan_schedules,runner}.py` · `bm/repositories/jobs.py`, `bm/services/jobs/{pull,__init__}.py`, `bm/api/agent/jobs.py`, (`manager/openapi.json`) |
| W4 | TASK-205 | `bm/api/user/scans.py`, `bm/api/user/__init__.py`, `manager/openapi.json` |
| W5 | TASK-206 | `bm/api/user/scan_schedules.py`, `bm/api/user/__init__.py`, `manager/openapi.json` |
| W6 | TASK-207, 208 | `web/src/api/schema.d.ts` · `README.md` |
| Gate | tester TP-M9-18 (whole), TP-M9-20; reviewer's M9 closing review | tester files only |

W1 is wide on purpose (12 independent files). Two impl-manager instances split it as pure (186–192) and SQL (193–197); W2 to W5 then follow the spine. Every high-risk task is tested and reviewed on its own; TASK-207 and TASK-208 may be batched.

### M9 gate

On a clean tree every command is green, and each gate turns red on its planted violation. G7 to G11, G17, G35 to G41 (agent, units, packaging) and G12 to G15 are not re-run: M9 changes no agent, unit, package or web source file (only the generated `schema.d.ts`, covered by G16).

| Gate | Command (summary) | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G1–G4 | ruff (S608, the `re` ban), ruff format, `mypy --strict --config-file manager/pyproject.toml manager`, hashed locks | CHK-M9-376; an untyped function in `intake.py` | local; CI |
| G5 | services coverage ≥ 85 % (now including `services/jobs` and the new scheduler modules), Linux run | an untested function in `bm/services/jobs/intake.py` sized from the clean report | WSL; CI |
| G6 | OpenAPI export byte-identical | a route added without re-export | local; CI |
| G16 | web client regenerated with no diff | a hand edit to `schema.d.ts` | local; CI |
| G18 | full manager suite, 0 skipped, `-n auto` | any of G66 to G70 | WSL; CI |
| G19 | schema diff (no migration) | a throwaway migration adding `ix_job_scan` | WSL; CI |
| G30 | agent contract suite unchanged | `operator` added to `ComplianceJob`; the NUL fixture made invalid | local |
| G31, G33 | M3 agent-auth and sweep/inventory suites | CHK-M9-365, -381 | WSL; CI |
| G34 | route walk with the seven M9 operations | a planted `POST /scans/{id}/run` with an `execute` body | local; CI |
| G66 | M9 unit suite: `test_job_states.py`, `test_scan_state.py`, `test_scan_targets.py`, `test_job_build.py`, `test_intake_plan.py`, `test_cron.py`, `test_idempotency.py` | the G66 rows | local; WSL; CI |
| G67 | property suite: `test_jobs_property.py` | CHK-M9-338, -362 | local; WSL; CI |
| G68 | M9 integration on PostgreSQL (TP-M9-10 to 15) | the G68 rows | WSL; CI |
| G69 | races and security: `test_first_result_wins_race_pg.py`, `test_queue_scan_race_pg.py`, `test_security_m9.py` | the G69 rows | WSL; CI |
| G70 | API suites: `test_agent_jobs_api_pg.py`, `test_scans_api_pg.py`, `test_scan_schedules_api_pg.py` | the G70 rows | WSL; CI |

**No gate is lowered.** NOT RUN at the M9 gate, with reasons: a real runner executing plugins and redacting (**M10**); the nightly end-to-end scan → results on VMs and the read views (**M11**); load tests (deferred by the user).

### M9 mutation table (tester; CHK-M9-320 onwards)

Each row is planted in a throwaway copy and must turn the named gate red. S = security row (targeted mini-run).

| CHK | Plant | Red in | Target | S |
| --- | --- | --- | --- | --- |
| CHK-M9-320 | Root lock removed (no `FOR UPDATE` on `COALESCE(retry_of, job_id)`) | G69 (double count in `host_counts`) | TASK-195, 199 | S |
| CHK-M9-321 | The posted job locked instead of the root | G69 | TASK-195 | S |
| CHK-M9-322 | Duplicate check ignores the sibling job | G68, G69 | TASK-190, 199 | S |
| CHK-M9-323 | Second item for one plugin in a batch stored (PK error → 500) | G66, G68 | TASK-190 | |
| CHK-M9-324 | Batch with a plugin outside the job: the other items stored | G66, G68 | TASK-190 | S |
| CHK-M9-325 | `cancelled` job accepted | G66, G70 | TASK-186, 199 | S |
| CHK-M9-326 | 7-day window `<` instead of `≤` | G66 | TASK-186 | |
| CHK-M9-327 | Window measured from `created_at` | G68 | TASK-199 | |
| CHK-M9-328 | Inventory job accepted on the results route | G70 | TASK-199, 204 | S |
| CHK-M9-329 | Verdict from the current catalog plugin, not `eval_spec` | G68 (catalog-change row) | TASK-199 | S |
| CHK-M9-330 | `oversize` stored with its streams | G66, G68 | TASK-190 | S |
| CHK-M9-331 | NUL replaced after evaluation, or stored raw | G66, G70 | TASK-190 | |
| CHK-M9-332 | `execute_snap` from the catalog, not the payload | G68 | TASK-190 | |
| CHK-M9-333 | `received_at` from the item's `finished_at` | G68 | TASK-199 | |
| CHK-M9-334 | Second start notice resets `started_at`/`deadline_at` | G66, G68 | TASK-186, 195 | |
| CHK-M9-335 | Deadline with floor division, or `max_parallel_plugins` ignored | G66 | TASK-186 | |
| CHK-M9-336 | Deadline adds 10 s instead of 10 min | G66 | TASK-186 | |
| CHK-M9-337 | `partial` on a non-final batch | G66 | TASK-186 | |
| CHK-M9-338 | A late batch changes a `completed` job | G66, G67 | TASK-186 | |
| CHK-M9-339 | Sweep deadline `≤` instead of `<` | G68 | TASK-196 | |
| CHK-M9-340 | Never-started 24 h measured from `created_at` | G68 | TASK-196 | |
| CHK-M9-341 | A retry is retried | G68 | TASK-202 | S |
| CHK-M9-342 | Retry for a job that ended `partial` by a final batch | G68 | TASK-202 | |
| CHK-M9-343 | Retry holds every plugin | G66, G68 | TASK-189 | |
| CHK-M9-344 | Retry rebuilt from the current catalog | G66, G68 | TASK-189, 202 | S |
| CHK-M9-345 | Retry inserted in its own transaction (fault leaves `failed` without a retry) | G68 | TASK-202 | |
| CHK-M9-346 | State guard removed: two sweeps make two retries | G68 | TASK-196 | |
| CHK-M9-347 | `operator`/`expected` copied into the payload | G66, G70, G30 | TASK-189 | S |
| CHK-M9-348 | `eval_spec` built from a different plugin order | G66 | TASK-189 | |
| CHK-M9-349 | Builder accepts U+0000 | G66 | TASK-189 | S |
| CHK-M9-350 | `pickup_by` + 25 h, or without `Z` | G66 | TASK-189 | |
| CHK-M9-351 | `redaction_patterns` empty instead of the setting | G66, G68 | TASK-189, 198 | S |
| CHK-M9-352 | Retired plugin included, or a disabled policy queued | G68 | TASK-193, 198 | S |
| CHK-M9-353 | Policy `FOR SHARE` removed (delete race leaves queued jobs) | G69 | TASK-193 | S |
| CHK-M9-354 | Resolution includes decommissioned or awaiting agents | G68 | TASK-193 | |
| CHK-M9-355 | Offline agents excluded | G68 | TASK-193 | |
| CHK-M9-356 | Tags matched all-of | G68 | TASK-193 | |
| CHK-M9-357 | Zero agents writes an empty scan | G68, G70 | TASK-198 | |
| CHK-M9-358 | Newer-cancels-older hits a dispatched job, another policy, or is run by a retry | G68 | TASK-193, 202 | |
| CHK-M9-359 | Cancel leaves dispatched jobs | G68 | TASK-194 | |
| CHK-M9-360 | Scan cancelled after results stays `cancelled` | G66 | TASK-187 | |
| CHK-M9-361 | Derivation per job, not per unit | G66 | TASK-187 | |
| CHK-M9-362 | Derivation can return `dispatched` | G66, G67 | TASK-187 | |
| CHK-M9-363 | Refresh skips finished non-completed scans (late results lost) | G68 | TASK-194, 202 | |
| CHK-M9-364 | `POST /scans` role check removed (viewer 202) | G70 | TASK-205 | S |
| CHK-M9-365 | `bsa_` accepted on `/scans` | G70, G31 | TASK-205 | S |
| CHK-M9-366 | All-hosts alert missing for `bsk_`, or raised for a session | G70 | TASK-198 | S |
| CHK-M9-367 | Idempotency: another body gets the first answer; no per-key lock | G66, G69 | TASK-192 | |
| CHK-M9-368 | Weekday 0 passed raw to APScheduler (Monday) | G66 | TASK-191 | |
| CHK-M9-369 | Day of month and day of week both accepted | G66 | TASK-191 | |
| CHK-M9-370 | Time zone ignored (UTC used) | G66, G68 | TASK-191, 203 | |
| CHK-M9-371 | Missed runs back-filled after a restart | G68 | TASK-203 | |
| CHK-M9-372 | Unfinished-previous skip removed | G68 | TASK-203 | |
| CHK-M9-373 | `SKIP LOCKED` removed: two ticks make two scans | G68 | TASK-197 | |
| CHK-M9-374 | Result counter incremented before commit, or counts duplicates | G68 | TASK-199 | |
| CHK-M9-375 | stdout logged at DEBUG in intake | G69 (canary) | TASK-199 | S |
| CHK-M9-376 | An f-string query in a new repository | G1 | TASK-193 to 197 | S |
| CHK-M9-377 | `UPDATE scan_job SET payload` in the sweep (grant refusal must surface) | G68, G69 | TASK-196 | S |
| CHK-M9-378 | Pull still inventory-only | G70 | TASK-204 | |
| CHK-M9-379 | Pull returns `eval_spec` | G70, G30 | TASK-204 | S |
| CHK-M9-380 | Flood counts cancelled-job 409s, or stops counting the others | G70 | TASK-199 | |
| CHK-M9-381 | A compliance scan cancels the agent's inventory job | G68, G33 | TASK-193 | S |
| CHK-M9-382 | `POST /scans` accepts an extra `execute` key | G70, G69 | TASK-205 | S |

### Open items for M9

All are in `work/open-questions.md` ("M9"), each with a recommended answer. "Needed by" is the start of the wave whose task or test cannot finish without it.

| Item | Blocks | Needed by |
| --- | --- | --- |
| #121 (new): stdout/stderr NUL and lone surrogates | TASK-190 | W1 |
| #124 (new): intake acceptance, counts, locks, flood exclusion | TASK-186, 190, 195 | W1 |
| #125 (new): job building | TASK-189, 193 | W1 |
| #126 (new): retries | TASK-189, 196 | W1 |
| #127 (new): job and scan state rules, refresh timing | TASK-186, 187, 194, 196 | W1 |
| #128 (new): cron, time zones, ticks, skips | TASK-191, 197 | W1 |
| #122 (new): route bodies and statuses, targets | TASK-188 (W1), 198, 201, 205, 206 | W1 |
| #123 (new): `Idempotency-Key` | TASK-192 | W1 |
| #129 (new): audit actions, alert kind, metric | TASK-198, 199, 200, 201, 203 | W2 |
| #3, #18, #22, #12, #116, #117, #54 (c), #66 (agreed, reused) | TASK-186, 187, 198, 199, 203 | W1 |
| PD-39 (new): approvals and second looks | each task's REVIEW | W1 |
| PD-40 (new): M3 checks replaced by requirement | TASK-204 TEST | W3 |

### Coverage matrix (M9)

| Spec section | Covered by | Status in M9 |
| --- | --- | --- |
| TS §1.1 G4, G6 (profiles; scheduled and manual scans per host, tag or fleet) | REQ-208, REQ-211, REQ-225 | Covered |
| TS §1.1 G2 inventory cannot be disabled | REQ-229 | Covered (regression) |
| TS §2.1 L103 scheduler (APScheduler) | REQ-223, REQ-225 | Covered |
| TS §2.1 L105 evaluator "on result arrival" | REQ-215 | Covered (M8's `result_verdict`) |
| TS §2.2 L111 pull-only; L112 first result wins; L114 immutable results | REQ-212, REQ-216, REQ-215, REQ-230 | Covered |
| TS §2.3 compliance flow steps 1–6 | REQ-211, REQ-213, REQ-214, REQ-215 | Covered; step 4 (runner) **M10**; step 7 (views) **M11** |
| TS §3.3 L203, L210–L214 pull rules | REQ-212, REQ-213 | Covered (manager side) |
| TS §3.3 L218 sweep timeouts and retries | REQ-218 | Covered |
| TS §3.3 L222 start notice | REQ-217 | Covered |
| TS §3.3 L224 answers to result posts | REQ-214 | Covered |
| TS §3.4 inventory | REQ-229 | Unchanged, regression only |
| TS §3.5 L248 job content; L251–L253 truncation, redaction, batches | REQ-209; REQ-214 | Job content covered; runner side **M10** |
| TS §4.1 L530 queued jobs keep commands | REQ-210, REQ-211 | Covered |
| TS §4.3 L547 disable; L550 delete cancels and disables | REQ-211, REQ-218, REQ-219, REQ-224 | Covered (#18); the delete itself is M7's, its scan effect is refreshed here |
| TS §4.4 L555–L583 | REQ-206 to REQ-211, REQ-216 to REQ-220, REQ-225 | Covered (#3, #22, #122, #124 to #128) |
| TS §4.5 L587, L593, L599, L603 | REQ-215 | Covered; L601 re-evaluation route **M11** |
| TS §5.2 L846–L913 scanning tables; L1005–L1013 grants | REQ-209, REQ-215, REQ-224, REQ-230 | Covered; **no schema change** |
| TS §5.3 L1047 scan retention | none | **M11** (retention task) |
| TS §5.3 L1052 no results in logs | REQ-230 | Covered |
| TS §6.1 L1064, L1065, L1071, L1072 | REQ-213, REQ-214, REQ-216 | Covered |
| TS §6.2 L1119 `POST /scans`, L1122 cancel, L1124 schedules | REQ-221, REQ-224 | Covered |
| TS §6.2 L1111, L1118, L1120, L1121, L1123 (read views, re-evaluate) | none | **M11** (no M9 acceptance test needs them) |
| TS §6.2 L1129 no ad-hoc command, no inventory disable | REQ-212, REQ-229 | Covered |
| TS §6.3 L1133–L1139 (problems, paging, `Idempotency-Key`, caps, ids) | REQ-221, REQ-222, REQ-224 | Covered; CSV **M11** |
| TS §6.4 manual scan example | REQ-221 | Covered |
| TS §6.5 Job and Results contracts | REQ-209, REQ-213, REQ-232 | Unchanged contract, used by M9 |
| TS §8.1 L1239 (unintended command), L1248 (rogue agent), L1252 (SQL injection) | REQ-212, REQ-214, REQ-230 | Covered |
| TS §8.3 Unit, Integration, Security ("first result wins under concurrent retries"), Contract | REQ-231, REQ-216, REQ-232 | Covered; End-to-end **M11**; Load deferred |
| TS §8.4 L1288 plugin ERROR rate; L1290 all-hosts API-token alert; L1291 thresholds | REQ-226, REQ-227, REQ-228 | Covered |
| SR §2.3 `@timeout` used in the deadline | REQ-206 | Covered |
| CLAUDE.md out of scope and owner decisions | none | Nothing planned: no job signing, push channel, ad-hoc command, remediation or inventory switch |

## M10 agent runner and sandbox

Planned 2026-10-30 (planner-m10) in the worktree `Bitscan-m10` (branch `m10-runner`, from main `328b097`, M9 merged). Consistency pass done: every TASK links a REQ and every REQ has a TASK (or is a named test requirement); waves are file-disjoint (one shared file, `ag/internal/spool/spool.go`, is touched by TASK-212 in W2 and TASK-219 in W3 only); every task is within 5 files and about 200 hand-written lines; the spine is acyclic; no gate is lowered. Summary for the user: `work/plans/M10-breakdown.md`.

Scope: REQ-234 to REQ-263 in `work/requirements.md`. In this section `ag/` means `agent/`.

**No new spec deviation, no manager change, no unit change.** Every open item (#130 to #143 new; #4, #28, #29, #30, #31, #57, #60, #74, #78, #113, #114, #116, #121, #124 (f) reused as agreed; PD-41 to PD-45) carries a recommended answer in `work/open-questions.md` ("M10"). No migration, route, setting or contract change. One new Go module if PD-41 (a) is taken (`golang.org/x/sys`). The TS §3.7 units and D-Bus policy stay verbatim; a run that shows a unit must change goes to the user as a spec question.

Rules every M10 task follows:
- **Testing by risk (user, 2026-10-25): M10 is the highest-risk milestone.** Full rigor for every agent, runner, redaction and capread task: a plant for every security row, every boundary and every race the task names, and a second review round if needed. Low risk, batched TEST and REVIEW allowed: TASK-231 (docs and changelog) only.
- **Time-skewing (user, 2026-10-26):** clock control only (the agent's `schedule.Clock`, an injected clock in the runner); races driven by barriers, never by sleeps. The sandbox suites on real hosts measure wall time only where the spec gives one (timeouts).
- **Linux only where the code is Linux:** the `_linux.go` files are tested in WSL (when `/sys/fs/cgroup` is cgroup2 there), in CI on `ubuntu-22.04` and `ubuntu-24.04`, and on the VMs; the pure packages (`runner/proto`, `redact`, `spool`, the agent loops with fakes) also run on Windows. G8 counts only on Linux.
- Agent and runner code passes a cancellable `context.Context` through every job, wraps errors with `%w`, uses only the clock it is given, and never logs a plugin command, output, pattern or token. The agent never executes a plugin command; the runner takes only whole jobs; nothing listens except the two systemd sockets; no capability beyond the unit's; nothing can switch inventory off.
- Implementers check `work/reviews/builder-checklist.md` before every hand-off. Planted violations are made in throwaway copies, never left in the tree.

### M10 design notes (for the tasks with real design risk)

Written out in four plans, each with interfaces, edge cases and spec quotes:
- **D1 protocol, `work/plans/TASK-209.md`** (TASK-209, and the client TASK-218, the serve loop TASK-225 and the agent's failure mapping in TASK-223). One connection per job; a length-prefixed request `{v, job, max_parallel_plugins}`; replies `accepted` or `refused`, then `result` frames in completion order, then `done`; deadlines; one connection at a time (`busy`); the `Executor` interface that lets TASK-225 be built beside TASK-224.
- **D2 cgroups and process start, `work/plans/TASK-215.md`** (TASK-215, 216, 221, 224's cleanup). Own cgroup from `/proc/self/cgroup`; `supervisor` leaf; plugins born in their own `p-<n>` by a cgroup hop under a spawn lock (not `clone3`, which `RestrictNamespaces=yes` may make fail with ENOSYS); niceness and I/O class set on a locked, discarded OS thread; no `Pdeathsig` (it fires when that thread exits); `cgroup.kill`, pidfd kills in `supervisor`, the subtree sweep and the runner-moved case.
- **D3 redaction and capture, `work/plans/TASK-210.md`** (TASK-210, 214). Read 1 MiB, drain the rest, sanitise UTF-8, patterns in order, cut-off rule, growth guard, rune-boundary cut; one plugin redacted at a time to stay inside `MemoryMax=256M`.
- **D4 spool and posting, `work/plans/TASK-212.md`** (TASK-212, 219, 220, 223). Per-job manifest and item files; size in bytes on disk; oldest-first `spool_overflow` markers; the sender's batch rules and the TS §3.3 L224 answer classes; interrupted jobs never get a final batch.

### M10 tasks

| TASK | Title | REQ links | Area | Owner | Risk | Files expected | Depends on | Est. LOC | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-209 | Agent–runner protocol (interface, pure): `Request`, `Reply`, `Result` (only via `NewResult` or decoding), reason words, length-prefixed frames with caps, strict decoding (plan TASK-209 §2) | REQ-234 | agent | impl-agent-r | **high** (TS §8.2 second approval) | `ag/internal/runner/proto/proto.go`, `ag/internal/runner/proto/frame.go` | none (M4 `wire`); #29, #60, #130 | 170 | Unit on Windows and Linux: REQ-234 (1)–(5) hold. |
| TASK-210 | Redaction engine (pure): `Compile` (count, compile, can-match-empty check), `Apply` (sanitise, ordered patterns, cut-off rule, growth guard, rune-boundary cut, `truncated`) (plan TASK-210 §2) | REQ-242, REQ-243, REQ-244 | agent | impl-agent-r | **high** (second approval) | `ag/internal/redact/redact.go`, `ag/internal/redact/cutoff.go`, `ag/internal/redact/patterns.go` | none; #113, #116 (a), #133, #134 | 180 | Unit on Windows and Linux: REQ-242 (1)–(8) and REQ-244 (1), (2) hold at package level, and the REQ-243 fixtures pass with the five patterns extracted from TS §8.6. |
| TASK-211 | Lint exceptions and the new module: `net.FileListener` only in `internal/sdsock/listen_linux.go`; G204 only in `internal/runner/spawn_linux.go` and `internal/capread/serve_linux.go`; `os/exec`, `os.StartProcess`, `syscall.ForkExec`/`Exec` forbidden outside those two files and `internal/inventory/command.go`; `golang.org/x/sys` pinned (PD-41) | REQ-256 | agent | impl-agent-r | **high** (second approval) | `ag/.golangci.yml`, `ag/go.mod`, `ag/go.sum` | none; PD-41 | 60 | On Linux G8 and G9 are green, each REQ-256 (1) plant made in a throwaway copy turns G8 red, and `go mod verify` fails on an altered `go.sum` line. |
| TASK-212 | Spool store: per-job manifest, item files, atomic writes through `os.Root`, size in bytes, ordered `Next`/`Ack`/`Drop`, reopen (interrupted jobs, 7-day expiry); `Put` answers `ErrFull` until TASK-219 (plan TASK-212 §2) | REQ-247 | agent | impl-agent-a | **high** (second approval) | `ag/internal/spool/spool.go`, `ag/internal/spool/manifest.go` | TASK-209; #4, #57, #139 | 180 | In a temporary directory with a fake clock, REQ-247 (1)–(7) hold. |
| TASK-213 | Runner job checks: fixed check order, `agent_id` file read per job, pickup window, in-memory seen set with expiry and the 100,000 bound, shape rules, pattern list through `redact.Compile`, reason words | REQ-236, REQ-244 | agent | impl-agent-r | **high** (second approval) | `ag/internal/runner/checks.go` | TASK-209, 210; #132 | 150 | With a fake clock and a temporary `agent_id` file, REQ-236 (1)–(4) and REQ-244 (1), (2) hold and the exec counter of the test build stays 0 for every refused request. |
| TASK-214 | Capture and result building: concurrent bounded reads of both pipes (1 MiB kept, the rest drained), `redact.Apply` per stream, wait status → exit code (#114), times, `timed_out`, `proto.NewResult`; the `runner_unavailable` item (plan TASK-210 §4) | REQ-241, REQ-242 | agent | impl-agent-r | **high** (second approval) | `ag/internal/runner/capture.go`, `ag/internal/runner/result.go` | TASK-209, 210; #113, #114 | 120 | Unit with pipes and synthetic wait statuses: REQ-241 (1), (2), (4) hold, a writer producing 3 MiB is never blocked, and REQ-242 (6) holds through the capture path. |
| TASK-215 | cgroup v2 (Linux): start-up usability check, `supervisor` leaf and self-move, per-plugin cgroup create, `StartIn` hop, `Kill`, wait-empty, remove, the subtree sweep with pidfd kills in `supervisor`, runner-moved recovery (plan TASK-215 §2–§4) | REQ-238, REQ-240, REQ-237 | agent | impl-agent-r | **high** (second approval) | `ag/internal/runner/cgroup_linux.go`, `ag/internal/runner/cgroup.go` | TASK-211; #136 (a), #137, #138 | 190 | On a fake cgroup tree REQ-238 (1) holds; under `systemd-run -p Delegate=yes` (CI, sandbox host) a planted stray in `supervisor`, in a nested cgroup and in a plugin cgroup are all gone after `Sweep`, and the runner stays alive in `supervisor`. |
| TASK-216 | Runner hygiene and start-up refusals (Linux): `PR_SET_DUMPABLE` 0 first, euid 0 refused, `CapEff`/`CapBnd` subset of `CAP_DAC_READ_SEARCH`, cgroup2 statfs check (plan TASK-215 §5) | REQ-237 | agent | impl-agent-r | **high** (second approval) | `ag/internal/runner/hygiene_linux.go` | TASK-211; #137 | 110 | Unit with injected readers: REQ-237 (1) holds; on Linux `PR_GET_DUMPABLE` returns 0 after `Harden()`. |
| TASK-217 | systemd socket activation and peer check (Linux, shared by runner and capread): `LISTEN_*` validation, fd 3 checks, close-on-exec of every inherited descriptor above 2, `net.FileListener`, `SO_PEERCRED` uid check per connection, uid lookup by user name without CGO (plan TASK-209 §5) | REQ-235 | agent | impl-agent-r | **high** (second approval) | `ag/internal/sdsock/listen_linux.go`, `ag/internal/sdsock/peer_linux.go` | TASK-211; #130 (j) | 130 | Unit on Linux with a Unix socket passed as fd 3 to a child test process: REQ-235 (1), (2) and (5) hold. |
| TASK-218 | Runner client (agent side): dial `runner.sock`, send one request, read replies with the #130 deadlines, `busy` retry, failure words of #131 (a), per-result callback; no other call (plan TASK-209 §6) | REQ-245, REQ-234 | agent | impl-agent-a | **high** (second approval) | `ag/internal/agent/runnerclient/client.go` | TASK-209; #130, #131 | 160 | Against a fake runner on a Unix socket with a fake clock, every #131 (a) failure kind yields its word, `busy` is retried every 2 s for 30 s, and a normal run delivers each result once, in order received. |
| TASK-219 | Spool overflow: oldest-first conversion to `spool_overflow` markers across jobs, the new item as a marker, oldest markers dropped last, in-flight batches protected; `Put` calls it (plan TASK-212 §4) | REQ-248 | agent | impl-agent-a | **high** (second approval) | `ag/internal/spool/overflow.go`, `ag/internal/spool/spool.go` (the `Put` call site only) | TASK-212; #140 | 120 | In a temporary directory, REQ-248 (1), (2) and (4) hold and the size never exceeds the bound after any `Put`. |
| TASK-220 | Results sender loop: start notice, batches (50 items, 1,572,864 bytes uncompressed), gzip, the 30 s rule, final batch, the M4 answer classes, back-off, `Wake()` (plan TASK-212 §5) | REQ-246 | agent | impl-agent-a | **high** (second approval) | `ag/internal/agent/loops/results.go` | TASK-212; #141 | 180 | Fake clock and fake manager: REQ-246 (1)–(6) hold. |
| TASK-221 | Plugin start (Linux): locked OS thread with niceness 10 and I/O class idle, `StartIn` the plugin cgroup, `/bin/sh -c`, the exact environment, temp directory as working directory, stdin `/dev/null`, pipes, no `Pdeathsig`; temp directory create and remove (plan TASK-215 §3) | REQ-239, REQ-241 | agent | impl-agent-r | **high** (second approval) | `ag/internal/runner/spawn_linux.go` | TASK-211, 215; #31, #135, #136 | 170 | On Linux under `systemd-run -p Delegate=yes`, REQ-239 (1)–(5) and (7) hold for a test command and the child appears in its own cgroup from its first instruction. |
| TASK-222 | capread helper server: the two-name table, request read and validation, peer uid `bitscan-runner` through `sdsock`, sequential serving, absolute path, empty environment, 10 s timeout, 1 MiB cap, reply lines (#142) | REQ-252 | agent | impl-agent-a | **high** (second approval) | `ag/internal/capread/capread.go`, `ag/internal/capread/serve_linux.go` | TASK-211, 217; #142 | 170 | Unit with the in-package command table swapped and a Unix socket: REQ-252 (1)–(4) hold. |
| TASK-223 | Compliance handler and run state: replace the #74 `Unavailable` handler; record the job, run the runner client, spool results, the #131 (b) fill, finish, `last_error`, `current_job_id`; `Deps.SpoolBytes` and the heartbeat's `spool_bytes`; a nil handler is refused (plan TASK-209 §7, TASK-212 §6) | REQ-245, REQ-249, REQ-250 | agent | impl-agent-a | **high** (second approval) | `ag/internal/agent/loops/compliance.go`, `ag/internal/agent/loops/jobs.go`, `ag/internal/agent/loops/pull.go`, `ag/internal/agent/loops/run.go`, `ag/internal/agent/loops/heartbeat.go` | TASK-212, 218, 220; #28, #78, #131 | 190 | Fake manager, fake runner, fake clock: REQ-245 (1)–(6), REQ-249 (2)–(4) and REQ-250 (1)–(3) hold, and the M4 pull and heartbeat suites pass except the PD-45 rows. |
| TASK-224 | Job executor: parallelism cap, per plugin cgroup → start → capture → timeout kill → wait empty → remove → temp delete → redact (one at a time) → emit; cancellation; after the job the sweep and the private `/tmp` and `/var/tmp` emptied (plan TASK-215 §6) | REQ-239, REQ-240, REQ-241 | agent | impl-agent-r | **high** (second approval) | `ag/internal/runner/job.go` | TASK-210, 214, 215, 221; #135, #136 (f), #138 | 190 | On Linux under `systemd-run -p Delegate=yes`, REQ-240 (1)–(7), (9), (10) and REQ-239 (6) hold through `Executor.Run`, and REQ-241 (5) holds with injected failures. |
| TASK-225 | Runner serve loop: accept through `sdsock`, one connection at a time, read the request within 30 s, checks, `accepted` or `refused`, stream results through the `Executor` interface with the write deadline, `done`, cancel on close (plan TASK-209 §4) | REQ-234, REQ-235, REQ-236, REQ-261 | agent | impl-agent-r | **high** (second approval) | `ag/internal/runner/serve.go` | TASK-209, 213, 217; #130 | 170 | With a fake executor and a Unix socket, REQ-235 (4), REQ-236 (2) and the REQ-261 malformed-request cases hold, and closing the client cancels the executor's context within 1 s. |
| TASK-226 | capread client and `bitscan-capread` main: argument check, connect, copy, exit codes; `--serve` wiring through `sdsock` and TASK-222 | REQ-253, REQ-252 | agent | impl-agent-a | **high** (second approval) | `ag/internal/capread/client.go`, `ag/cmd/bitscan-capread/main.go` | TASK-222; #142 | 120 | Unit with a fake server and the built binary run by hand: REQ-253 (1), (2) hold. |
| TASK-227 | `bitscan-agent` main for M10: open the spool (`spool_max_mb`), start the results sender beside the heartbeat, pull and inventory loops, pass the compliance handler; SIGTERM closes the runner connection | REQ-245, REQ-246, REQ-247, REQ-249, REQ-251 | agent | impl-agent-a | **high** (second approval) | `ag/cmd/bitscan-agent/main.go` | TASK-219, 220, 223 | 80 | Against a fake manager and a fake runner the binary runs a compliance job end to end, SIGTERM mid-job exits 0 within 5 s with the spool intact, and REQ-251 (1) holds for `cmd/bitscan-agent`. |
| TASK-228 | `bitscan-runner` main: `Harden()`, the start-up checks, cgroup set-up and start-up sweep, socket from systemd, serve loop with the executor, SIGTERM → cancel and sweep; structured logs without payload | REQ-237, REQ-238, REQ-240, REQ-251 | agent | impl-agent-r | **high** (second approval) | `ag/cmd/bitscan-runner/main.go` | TASK-215, 216, 217, 224, 225 | 110 | Under `systemd-run` with the verbatim runner unit's properties and a socket unit (WSL with cgroup2, or CI), the driver's job runs and REQ-237 (2) and REQ-251 (1), (3) hold for `cmd/bitscan-runner`. |
| TASK-229 | Agent CI: replace the M0 stub step for runner and capread with start-up refusal checks; keep `go test` on `ubuntu-22.04` and `ubuntu-24.04` | REQ-257, REQ-260 | deploy | impl-deploy | medium (one approval) | `.github/workflows/agent.yml` | TASK-226, 228; PD-27 | 60 | On a PR, the new step passes on the M10 binaries and turns red when the M0 stub runner is put back, and `go test ./...` runs on both runners. |
| TASK-230 | Sandbox CI: build the `.deb`, install it on `ubuntu-22.04` and `ubuntu-24.04` hosted runners, run `ag/test/sandbox` (G77), publish the row report; path filters per REQ-257 | REQ-257, REQ-259, REQ-261 | deploy | impl-deploy | **high** (lead's second look, PD-43) | `.github/workflows/sandbox.yml` | TASK-227, 228; tester TP-M10-20; PD-44 | 150 | On a PR the job runs both hosts, reports every G77 row as PASS, FAIL or NOT RUN with a reason, and turns red on a sandbox row made to fail in a throwaway branch. |
| TASK-231 | Docs and version: runbook additions (cgroup v2, `runner_unavailable`, capread on the host, `findmnt --task 1`, spool), README paragraph, changelog entry per PD-42 | REQ-258, REQ-255 | deploy | impl-deploy | low (docs) | `deploy/runbooks/agent-install.md`, `README.md`, `deploy/debian/changelog` | TASK-226, 227, 228; PD-42 | 120 (docs) | The tester follows the new runbook steps on a sandbox VM and each behaves as written, `dpkg-parsechangelog` gives the PD-42 version, and no secret or process note appears. |

Totals: 30 REQ (REQ-234 to REQ-263), 23 TASK (TASK-209 to TASK-231), 25 test-plan items (TP-M10-00 to TP-M10-24), 6 waves (W1 to W6) plus the gate. 22 tasks are high or medium risk, 1 low. Every task is within 5 files and about 200 hand-written lines; TASK-215, 223 and 224 are the largest (if one grows: TASK-215 moves the sweep into `ag/internal/runner/sweep_linux.go`; TASK-223 moves the heartbeat change into its own task; TASK-224 moves the `/tmp` emptying into `ag/internal/runner/tmpclean_linux.go`; one task id each, as in M7).

REQ to TASK: REQ-234 TASK-209, 218, 225; REQ-235 TASK-217, 225; REQ-236 TASK-213, 225; REQ-237 TASK-215, 216, 228; REQ-238 TASK-215, 228; REQ-239 TASK-221, 224; REQ-240 TASK-215, 224, 228; REQ-241 TASK-214, 221, 224; REQ-242 TASK-210, 214; REQ-243 TASK-210 (fixtures: tester); REQ-244 TASK-210, 213; REQ-245 TASK-218, 223, 227; REQ-246 TASK-220, 227; REQ-247 TASK-212, 227; REQ-248 TASK-219; REQ-249 TASK-223, 227; REQ-250 TASK-223; REQ-251 TASK-227, 228 (and TASK-211 for G8); REQ-252 TASK-222, 226; REQ-253 TASK-226; REQ-254 TASK-231 (runbook) and the tester's static and package rows (test requirement: no code may enable a unit); REQ-255 TASK-231 (version) and the tester's package rows (G37–G40); REQ-256 TASK-211; REQ-257 TASK-229, 230; REQ-258 TASK-231; REQ-259 TASK-230 (CI) and tester TP-M10-20 (test requirement); REQ-260 TASK-229 and every agent task (test requirement); REQ-261 TASK-225, 230 and tester TP-M10-21 (test requirement); REQ-262 tester TP-M10-20, 24 (test requirement); REQ-263 tester TP-M10-22 (test requirement; product code from every task). Every M10 REQ has at least one TASK or is a named test requirement, and every TASK has at least one REQ.

### M10 owner and review notes

- **Owners:** two impl-agent instances (agent type `implementer`). **impl-agent-r** (runner side): TASK-209, 210, 211, 213, 214, 215, 216, 217, 221, 224, 225, 228. **impl-agent-a** (agent side and capread): TASK-212, 218, 219, 220, 222, 223, 226, 227. **impl-deploy:** TASK-229, 230, 231 (and `README.md` in TASK-231, at the lead's routing, since no area owns it). No impl-manager, impl-web or impl-bits task: no manager, web or sample change (a sample that fails #143 is a finding routed to impl-bits by the lead). The tester owns every `*_test.go`, `ag/test/sandbox/`, `deploy/tests/`, `e2e/`, `manager/tests/` (the RE2 cross-check) and `tests/m10/`. Suggested two testers: tester-m10 (Go unit and Linux suites, W1–W5) and tester-m10b (the sandbox harness, CI rows and VM rows from W2 on, harness first).
- **Approvals (TS §8.2 L1268, PD-43):** the TS §8.2 second approval for every agent, runner, redaction and capread task (TASK-209 to TASK-228, including the lint task TASK-211), applied under the user's M10 pre-authorisation on a clean TEST PASS and "APPROVED, no open blocking or should-fix findings". A lead's second look at TASK-230 (it gates the sandbox and security suites). One approval for TASK-229 and TASK-231.
- **Shared files (never in one wave):** `ag/internal/spool/spool.go` (TASK-212 in W2; TASK-219 in W3 changes only the `Put` call site); `ag/internal/agent/loops/` (TASK-220 adds `results.go` in W3; TASK-223 changes `compliance.go`, `jobs.go`, `pull.go`, `run.go`, `heartbeat.go` in W4); `ag/go.mod`, `ag/go.sum` (TASK-211 only; any further module asks the lead first, PD-25). Every other file has exactly one task.
- **Frozen interfaces once W1 passes:** `proto` (TASK-209), `redact` (TASK-210); once W2 passes: the `spool` API (TASK-212), the `runnerclient` API (TASK-218), the `cgroup` API (TASK-215); the `Executor` interface is fixed in plan TASK-209 §4 before W4.
- **M4 checks replaced by requirement (PD-45):** in TASK-223 TEST the tester rewrites only the TP-M4-18 checks of the #74 compliance handler to REQ-245, listing each old CHK id with its replacement in `tests/m10/report.md`; every other M4 assertion stays.
- **Units are not edited.** If a sandbox row fails because of a unit directive (for example a read-only cgroup tree or a blocked system call), the lead raises a spec question; no task changes `deploy/systemd/` or `deploy/dbus/`.
- **Carry-over, not planned:** TASK-146 (the BIT102 review, its TS §8.2 second approval and r2) waits for a fresh session (decisions 2026-10-30 (3)).

### M10 test-plan items (tester)

Drafted from the acceptance criteria at phase start (`tests/m10/test-plan.md`, check ids `CHK-M10-###`; suggested ranges: 001–079 pure packages (proto, redact, checks, capture, spool, client, sender), 080–099 fuzz and property, 100–199 Linux integration (cgroup, spawn, executor, serve, binaries under `systemd-run`), 200–259 sandbox rows (CI and VM), 260–289 security rows, 290–299 first compliance run, 300–319 gate rows, 320 onwards the mutation table). "WSL" means the WSL Ubuntu 24.04 distro with systemd, used for the delegated-cgroup items only when `stat -fc %T /sys/fs/cgroup` there prints `cgroup2fs` (otherwise those items run in CI and on the VMs). "VM" means `bitscan-u2204` and `bitscan-u2404` restored to `clean` (PD-44).

| TP | What | REQ | Runs in | Files (tester) | Depends on |
| --- | --- | --- | --- | --- | --- |
| TP-M10-00 | Phase test plan and the M10 index row | all M10 | phase start; report at the gate | `tests/m10/test-plan.md`, `tests/test-plan.md` | none |
| TP-M10-01 | Harness: fake runner (Unix socket), fake manager (M4's), exec counter build tag for unit builds, the driver (`ag/test/sandbox/driver/`), the probe (`ag/test/sandbox/probe/`), the VM runner script on top of `e2e/m6/vm.sh`, planted test listeners for the blocked sockets, the redaction corpus | REQ-234 to REQ-263 | W1 (before TASK-213 TEST); VM parts before the gate | `ag/test/sandbox/…`, `ag/internal/redact/testdata/`, `manager/tests/contract/fixtures/redaction/` | none |
| TP-M10-02 | Protocol | REQ-234 | TASK-209 TEST | `ag/internal/runner/proto/proto_test.go` | TASK-209 IMPL |
| TP-M10-03 | Redaction: fixtures with patterns extracted from TS §8.6, fuzz, growth guard, boundaries; the Go vs `google-re2` cross-check | REQ-242, REQ-243, REQ-244 | TASK-210 TEST (local, WSL, CI) | `ag/internal/redact/redact_test.go`, `manager/tests/test_redaction_crosscheck.py` | TP-M10-01 |
| TP-M10-04 | Lint plants and `go mod verify` | REQ-256 | TASK-211 TEST | none in the tree (evidence) | TASK-211 IMPL |
| TP-M10-05 | Spool store: order, sizes, crash injection, reopen, expiry, modes, `os.Root` | REQ-247 | TASK-212 TEST | `ag/internal/spool/spool_test.go` | TASK-212 IMPL |
| TP-M10-06 | Runner job checks | REQ-236, REQ-244 | TASK-213 TEST | `ag/internal/runner/checks_test.go` | TASK-213 IMPL |
| TP-M10-07 | Capture and result | REQ-241, REQ-242 | TASK-214 TEST | `ag/internal/runner/capture_test.go` | TP-M10-03 |
| TP-M10-08 | cgroup: fake tree; delegated cgroup under `systemd-run -p Delegate=yes` | REQ-238, REQ-240 | TASK-215 TEST (WSL or CI) | `ag/internal/runner/cgroup_linux_test.go` | TASK-215 IMPL |
| TP-M10-09 | Hygiene and start-up refusals | REQ-237 | TASK-216 TEST | `ag/internal/runner/hygiene_linux_test.go` | TASK-216 IMPL |
| TP-M10-10 | Socket activation and peer check (child process with fd 3) | REQ-235 | TASK-217 TEST | `ag/internal/sdsock/sdsock_linux_test.go` | TASK-217 IMPL |
| TP-M10-11 | Runner client against the fake runner | REQ-245, REQ-234 | TASK-218 TEST | `ag/internal/agent/runnerclient/client_test.go` | TP-M10-02 |
| TP-M10-12 | Spool overflow | REQ-248 | TASK-219 TEST | `ag/internal/spool/overflow_test.go` | TP-M10-05 |
| TP-M10-13 | Results sender | REQ-246 | TASK-220 TEST | `ag/internal/agent/loops/results_test.go` | TP-M10-05 |
| TP-M10-14 | capread server and client | REQ-252, REQ-253 | TASK-222, 226 TEST | `ag/internal/capread/capread_test.go` | TP-M10-10 |
| TP-M10-15 | Plugin start (Linux, delegated cgroup) | REQ-239, REQ-241 | TASK-221 TEST | `ag/internal/runner/spawn_linux_test.go` | TP-M10-08 |
| TP-M10-16 | Compliance handler and heartbeat; the PD-45 rewrite of the #74 checks | REQ-245, REQ-249, REQ-250 | TASK-223 TEST | `ag/internal/agent/loops/compliance_test.go`, the affected M4 test files | TP-M10-11, 13 |
| TP-M10-17 | Executor (Linux, delegated cgroup) | REQ-239, REQ-240, REQ-241 | TASK-224 TEST | `ag/internal/runner/job_linux_test.go` | TP-M10-15 |
| TP-M10-18 | Serve loop with a fake executor | REQ-234, REQ-235, REQ-236, REQ-261 | TASK-225 TEST | `ag/internal/runner/serve_test.go` | TP-M10-06, 10 |
| TP-M10-19 | Binaries: agent main against fakes; runner main under `systemd-run` with the unit's properties; import-boundary test (`go list -deps`) | REQ-245 to REQ-251, REQ-237 | TASK-227, 228 TEST | `ag/cmd/bitscan-agent/main_test.go`, `ag/cmd/bitscan-runner/main_test.go`, `ag/internal/boundary_test.go` | TP-M10-16, 17, 18 |
| TP-M10-20 | Sandbox suite (G76 on the VMs, G77 on hosted runners): every REQ-259 row, REQ-237 (2), REQ-238 (2)–(4), REQ-239 (1)–(6), REQ-240, REQ-252 (5), (6), REQ-254 (1), the #143 sample run, `systemd-analyze verify` | REQ-259, REQ-262 | from W5; whole at the gate | `ag/test/sandbox/…` | TP-M10-01, 19 |
| TP-M10-21 | Runner security suite (G78): expired, foreign, replayed, wrong peer, non-job requests, capread names; agent half re-run (G36) | REQ-261 | TASK-225 TEST (unit part); gate (host part) | `ag/test/sandbox/security_test.go`, `ag/internal/agent/security_test.go` (extend) | TP-M10-18, 20 |
| TP-M10-22 | First compliance run on `bitscan-u2404` against the WSL manager (G79) | REQ-263 | gate | `e2e/m10/first_run.sh` | TP-M10-20 |
| TP-M10-23 | CI plants (TASK-229, 230) and the runbook walk (TASK-231) | REQ-257, REQ-258 | TASK-229, 230, 231 TEST | none in the tree (evidence) | TASK-229, 230, 231 IMPL |
| TP-M10-24 | M10 gate, VM plan rows and the mutation table | all M10 | M10 gate | `tests/m10/report.md` | all above |

### M10 waves and dependency spine

Spine (runner side): `TASK-211 → TASK-215, 216, 217`; `TASK-215 → TASK-221 → TASK-224 → TASK-228`; `TASK-209, 210 → TASK-213, 214`; `TASK-210, 214, 215, 221 → TASK-224`; `TASK-209, 213, 217 → TASK-225 → TASK-228`; `TASK-216, 217 → TASK-228`. Agent side: `TASK-209 → TASK-212 → TASK-219, 220`; `TASK-209 → TASK-218`; `TASK-212, 218, 220 → TASK-223 → TASK-227`; `TASK-219 → TASK-227`. capread: `TASK-211, 217 → TASK-222 → TASK-226`. CI and docs: `TASK-226, 228 → TASK-229`; `TASK-227, 228 → TASK-230`; `TASK-226, 227, 228 → TASK-231`. The graph is acyclic; the longest path is `TASK-211 → 215 → 221 → 224 → 228 → 230` (six waves).

Interface first: W1 fixes the protocol, the redaction API and the lint and dependency rules; W2 fixes the spool, client, cgroup and socket APIs; the `Executor` interface (plan TASK-209 §4) lets TASK-225 be built beside TASK-224.

| Wave | Tasks (parallel) | Files touched (disjoint within the wave) |
| --- | --- | --- |
| W1 | TASK-209, 210, 211; tester TP-M10-00, 01 | `ag/internal/runner/proto/{proto,frame}.go` · `ag/internal/redact/{redact,cutoff,patterns}.go` · `ag/.golangci.yml`, `ag/go.{mod,sum}` · tester files |
| W2 | TASK-212, 213, 214, 215, 216, 217, 218 | `ag/internal/spool/{spool,manifest}.go` · `ag/internal/runner/checks.go` · `ag/internal/runner/{capture,result}.go` · `ag/internal/runner/{cgroup,cgroup_linux}.go` · `ag/internal/runner/hygiene_linux.go` · `ag/internal/sdsock/{listen_linux,peer_linux}.go` · `ag/internal/agent/runnerclient/client.go` |
| W3 | TASK-219, 220, 221, 222 | `ag/internal/spool/overflow.go` (+ the `Put` call site in `spool.go`) · `ag/internal/agent/loops/results.go` · `ag/internal/runner/spawn_linux.go` · `ag/internal/capread/{capread,serve_linux}.go` |
| W4 | TASK-223, 224, 225, 226 | `ag/internal/agent/loops/{compliance,jobs,pull,run,heartbeat}.go` · `ag/internal/runner/job.go` · `ag/internal/runner/serve.go` · `ag/internal/capread/client.go`, `ag/cmd/bitscan-capread/main.go` |
| W5 | TASK-227, 228; tester TP-M10-19, sandbox rows begin | `ag/cmd/bitscan-agent/main.go` · `ag/cmd/bitscan-runner/main.go` |
| W6 | TASK-229, 230, 231 | `.github/workflows/agent.yml` · `.github/workflows/sandbox.yml` · `deploy/runbooks/agent-install.md`, `README.md`, `deploy/debian/changelog` |
| Gate | tester TP-M10-20 (whole, VMs and CI), 21, 22, 24; reviewer's M10 closing review | tester files only |

impl-agent-r carries the runner spine (W1: 209, 210, 211; W2: 213–217; W3: 221; W4: 224, 225; W5: 228); impl-agent-a carries the agent spine and capread (W2: 212, 218; W3: 219, 220, 222; W4: 223, 226; W5: 227). Every task is tested and reviewed on its own; only TASK-231 may be batched.

### M10 gate

On a clean tree every command is green, and each gate turns red on its planted violation. G1–G6, G16, G18, G19 and G30–G34 are not re-run beyond CI: M10 changes no manager, web or contract file (TP-M10-03's cross-check is a new manager test file only).

| Gate | Command (summary) | Planted violation that must turn it red | Where |
| --- | --- | --- | --- |
| G7–G11 | gofmt; golangci-lint on Linux; `go mod verify`; `CGO_ENABLED=0` static amd64 build of the three binaries; the nolint grep | CHK-M10-378, -379; an altered `go.sum` line; `import "C"` in `runner` | WSL; CI |
| G17 | units and D-Bus verbatim check, then `systemd-analyze verify` with the real binaries installed | one character changed in `bitscan-runner.service` | WSL; CI |
| G35, G36 | Go contract test (unchanged); agent security subset (M4 rows plus the agent half of REQ-261) | the M4 rows; CHK-M10-356, -358 | WSL; CI |
| G37–G40 | lintian; maintainer scripts with the `0.1.0-1` → M10 upgrade; reproducible double build; SBOM (with the PD-41 module) | the M4 rows | WSL; CI |
| G41 | `e2e/agent_manager.sh` inventory chain against the real manager in WSL (regression) | the reverse-order `list_sha256` `.deb` | WSL |
| G71 | redaction: `go test ./internal/redact/...` (fixtures, fuzz seed corpus, boundaries) and `manager/tests/test_redaction_crosscheck.py` | the G71 rows | local; WSL; CI |
| G72 | runner Linux suites: `go test ./internal/runner/... ./internal/sdsock/...`, the delegated parts under `systemd-run -p Delegate=yes` | the G72 rows | WSL (cgroup2 only); CI |
| G73 | agent suites: `go test ./internal/agent/... ./internal/spool/...` | the G73 rows | local (pure parts); WSL; CI |
| G74 | capread: `go test ./internal/capread/...` | the G74 rows | WSL; CI |
| G75 | protocol suite and the import-boundary test (`go list -deps`, REQ-251 (1)) | CHK-M10-323, -380 | local; CI |
| G76 | sandbox suite on `bitscan-u2204` and `bitscan-u2404` (`ag/test/sandbox/run_vm.sh`), plus the VM-only rows (cgroup v1 boot on u2204, capread with `nft` and `auditd`) | the rows marked VM | VM |
| G77 | sandbox suite on GitHub `ubuntu-22.04` and `ubuntu-24.04` runners (`sandbox.yml`) | the rows marked VM, re-planted on a throwaway branch where a hosted runner can run them | CI |
| G78 | runner security suite (unit parts everywhere; host parts through the driver) | the rows marked S | WSL; CI; VM |
| G79 | first compliance run on `bitscan-u2404` against the M9 manager in WSL (`e2e/m10/first_run.sh`) | CHK-M10-344 (a canary reaches the stored stdout) | VM + WSL |

**No gate is lowered.** NOT RUN at the M10 gate, with reasons: the nightly end-to-end run on three VMs, the results views, CSV and re-evaluation (**M11**); the N / N−1 matrix (**M11**); load tests (deferred by the user); Debian 12 and arm64 rows of TS §8.3 (not supported, decisions 2026-10-24). A VM row refused by a safety check is NOT RUN with its reason and its lower-level cover (see "M10 VM plan"); M10 does not merge with such a row until the user decides whether it is a gate exception (decisions 2026-10-30 (2)).

### M10 VM plan

| Row group | Needs | Lower-level cover if the VM row is NOT RUN |
| --- | --- | --- |
| Plugin cannot write, open IP sockets, exec outside system paths, gain privileges, load modules, change clock or hostname (REQ-259) | VM (G76) | G77 on both hosted runners (same suite, same units); `check_units_verbatim.py` (G17) for the directives |
| Blocked local sockets (Docker, containerd, snapd, journald) | VM with planted test listeners (G76) | G77 (hosted runners have a real `/run/docker.sock`); G17 for `InaccessiblePaths=` |
| `ptrace`, `process_vm_readv`, `/proc/<pid>/mem`, inherited socket, socket replacement | VM (G76) | G77; TP-M10-09 (`PR_GET_DUMPABLE`), TP-M10-10 (fdinfo `O_CLOEXEC`) |
| D-Bus: state-changing calls refused, read-only calls work | VM (G76) | G77; G17 verbatim policy |
| No plugin outlives its job; cgroup layout; environment; niceness and I/O class | VM (G76) | G77; TP-M10-08, 15, 17 under `systemd-run -p Delegate=yes` in CI |
| Runner refuses to start without unified cgroup v2 | VM only: `bitscan-u2204` booted with `systemd.unified_cgroup_hierarchy=0`, then restored | TP-M10-09 unit with injected statfs and `/proc/self/cgroup` |
| capread with real `nft` and `auditctl`, its capabilities | VM (G76; `auditd` installed on the VM from the Ubuntu archive) | G77 (`nft` only); TP-M10-14 |
| Full sample plugin set under the sandbox (#143) | VM (G76) | G77 |
| Planted-fault builds (rows marked VM) | VM, one throwaway `.deb` per plant, VM restored to `clean` after each | the same plant on a throwaway branch run by G77; the unit-level row named in the mutation table |
| First compliance run with the real manager (G79) | `bitscan-u2404` plus the manager in WSL (M6 network set-up) | the same walk against the fake manager in G77, plus TP-M10-16 |

### M10 mutation table (tester; CHK-M10-320 onwards)

Each row is planted in a throwaway copy and must turn the named gate red. S = security row (targeted mini-run). VM = also planted as a throwaway `.deb` on a sandbox host.

| CHK | Plant | Red in | Target | S / VM |
| --- | --- | --- | --- | --- |
| CHK-M10-320 | Peer check removed (any uid served) | G72, G78, G76 | TASK-217 | S, VM |
| CHK-M10-321 | Peer check compares the gid, not the uid | G72, G78 | TASK-217 | S |
| CHK-M10-322 | A second request frame on one connection is run | G72, G78 | TASK-225 | S |
| CHK-M10-323 | Unknown key (`"command"`) beside `job` accepted | G75, G78 | TASK-209 | S |
| CHK-M10-324 | Inventory job accepted by the runner | G72, G78 | TASK-209, 213 | S |
| CHK-M10-325 | `agent_id` check removed in the runner | G72, G78, G76 | TASK-213 | S, VM |
| CHK-M10-326 | `pickup_by` more than 25 h ahead accepted | G72, G78 | TASK-213 | S |
| CHK-M10-327 | Runner seen set removed (replay runs) | G72, G78, G76 | TASK-213 | S, VM |
| CHK-M10-328 | `pickup_by` = now accepted | G72 | TASK-213 | S |
| CHK-M10-329 | `PR_SET_DUMPABLE` not set | G72, G76 | TASK-216 | S, VM |
| CHK-M10-330 | fd 3 left without close-on-exec | G72, G76 | TASK-217 | S, VM |
| CHK-M10-331 | Plugin inherits the runner's environment | G72, G76 | TASK-221 | S, VM |
| CHK-M10-332 | `TMPDIR` added, or `PATH` changed | G72 | TASK-221 | |
| CHK-M10-333 | stdin inherited instead of `/dev/null` | G72, G76 | TASK-221 | VM |
| CHK-M10-334 | Niceness not applied | G72, G76 | TASK-221 | VM |
| CHK-M10-335 | I/O class not applied | G72, G76 | TASK-221 | VM |
| CHK-M10-336 | Plugin started in `supervisor` (no own cgroup) | G72, G76 | TASK-221, 224 | S, VM |
| CHK-M10-337 | `cgroup.kill` not written when a plugin exits (a background child survives) | G72, G76 | TASK-224 | S, VM |
| CHK-M10-338 | Subtree sweep removed (a plugin moved into `supervisor` survives) | G72, G76 | TASK-215 | S, VM |
| CHK-M10-339 | Sweep skips cgroups nested under `supervisor` | G72, G76 | TASK-215 | S, VM |
| CHK-M10-340 | Runner starts on cgroup v1 (statfs check removed) | G72, G76 (u2204 v1 boot) | TASK-216 | S, VM |
| CHK-M10-341 | Plugin temp directory not deleted | G72, G76 | TASK-221, 224 | |
| CHK-M10-342 | Private `/tmp` not emptied after a job | G72, G76 | TASK-224 | |
| CHK-M10-343 | Timeout not enforced | G72, G76 | TASK-224 | S, VM |
| CHK-M10-344 | Redaction after truncation (a secret on the 64 KiB boundary partly returned) | G71, G79 | TASK-210, 214 | S |
| CHK-M10-345 | Cut-off key rule skipped when pattern 2 is absent | G71 | TASK-210 | S |
| CHK-M10-346 | Read limit removed, or the drain removed (a 3 MiB writer blocks and times out) | G71, G72 | TASK-214 | |
| CHK-M10-347 | `truncated` not set when over 1 MiB but under 64 KiB after redaction | G71 | TASK-210 | |
| CHK-M10-348 | Cut splits a UTF-8 rune | G71 | TASK-210 | |
| CHK-M10-349 | Cutting stderr sets `truncated` | G71 | TASK-210 | |
| CHK-M10-350 | Replacement with capture-group expansion (`Expand` instead of literal) | G71 | TASK-210 | |
| CHK-M10-351 | 51 patterns accepted | G71, G72 | TASK-210, 213 | S |
| CHK-M10-352 | A pattern that fails to compile is skipped and the others applied | G71, G72 | TASK-210, 213 | S |
| CHK-M10-353 | A pattern that can match the empty string accepted | G71 | TASK-210 | |
| CHK-M10-354 | Growth guard removed | G71 | TASK-210 | |
| CHK-M10-355 | Signal death reported as −1 | G72 | TASK-214 | |
| CHK-M10-356 | The agent writes the job (with `execute`) into the spool or state directory | G73, G36 | TASK-212, 223 | S |
| CHK-M10-357 | The runner sends raw output when redaction fails | G71, G72 | TASK-214 | S |
| CHK-M10-358 | The agent resends the job to a restarted runner | G73, G36 | TASK-223 | S |
| CHK-M10-359 | The agent posts a final batch for a job interrupted by its own restart | G73 | TASK-212, 223 | |
| CHK-M10-360 | A batch of 51 items | G73 | TASK-220 | |
| CHK-M10-361 | A batch over 1,572,864 bytes uncompressed | G73 | TASK-220 | |
| CHK-M10-362 | A 409 retried | G73 | TASK-220 | |
| CHK-M10-363 | A 429 dropped | G73 | TASK-220 | |
| CHK-M10-364 | Overflow drops the newest first | G73 | TASK-219 | |
| CHK-M10-365 | Overflow drops a result without a `spool_overflow` marker | G73 | TASK-219 | |
| CHK-M10-366 | Spool write not atomic (crash leaves a partial item the reader accepts) | G73 | TASK-212 | |
| CHK-M10-367 | Heartbeat `spool_bytes` still 0 | G73 | TASK-223 | |
| CHK-M10-368 | Start notice missing, or sent after results | G73 | TASK-220 | |
| CHK-M10-369 | Two compliance jobs handed to the runner at once | G73 | TASK-223 | |
| CHK-M10-370 | An inventory job waits for the running compliance job | G73, G41 | TASK-223, 227 | S |
| CHK-M10-371 | capread accepts a third name | G74, G76 | TASK-222 | S, VM |
| CHK-M10-372 | capread passes request text as an argument | G74 | TASK-222 | S |
| CHK-M10-373 | capread passes its environment to the command | G74, G76 | TASK-222 | S, VM |
| CHK-M10-374 | capread peer check removed | G74, G76 | TASK-222 | S, VM |
| CHK-M10-375 | capread timeout 60 s | G74 | TASK-222 | |
| CHK-M10-376 | capread output cap removed, or a cut ruleset sent | G74 | TASK-222 | |
| CHK-M10-377 | capread serves two requests at once | G74 | TASK-222 | |
| CHK-M10-378 | `net.FileListener` in a non-`sdsock` file | G8 | TASK-211 | S |
| CHK-M10-379 | `exec.Command` in `ag/internal/agent/loops/compliance.go` | G8 | TASK-211 | S |
| CHK-M10-380 | `cmd/bitscan-agent` imports `internal/runner` or `internal/redact` | G75 | TASK-227 | S |
| CHK-M10-381 | `cmd/bitscan-runner` imports `net/http` or the agent transport | G75 | TASK-228 | S |
| CHK-M10-382 | The runner logs a stdout canary at debug level | G72, G76 (canary sweep) | TASK-224, 225 | S |
| CHK-M10-383 | The agent logs a received result's stdout | G73 | TASK-223 | S |
| CHK-M10-384 | A heartbeat answer makes the agent connect to the runner | G73 | TASK-223 | S |
| CHK-M10-385 | euid 0 accepted at start-up | G72 | TASK-216 | S |
| CHK-M10-386 | Capability self-check removed, with a planted unit holding `CAP_SYS_ADMIN` | G72, G76 | TASK-216 | S, VM |
| CHK-M10-387 | One character changed in a shipped unit | G17 | units (no task) | S |
| CHK-M10-388 | Planted D-Bus policy allowing `StartUnit` | G17, G76 | units (no task) | S, VM |
| CHK-M10-389 | Planted runner unit without its `InaccessiblePaths=` lines | G17, G76 | units (no task) | S, VM |
| CHK-M10-390 | Planted runner unit without `NoExecPaths=` | G17, G76 | units (no task) | S, VM |
| CHK-M10-391 | The runner keeps running plugins after the agent closes the connection | G72, G76 | TASK-224, 225 | S, VM |
| CHK-M10-392 | A result for a plugin not in the job is spooled by the agent | G73 | TASK-218, 223 | S |
| CHK-M10-393 | The runner reads the `agent_id` file once at start instead of per job | G72 | TASK-213 | |

### Open items for M10

All are in `work/open-questions.md` ("M10"), each with a recommended answer. "Needed by" is the start of the wave whose task or test cannot finish without it.

| Item | Blocks | Needed by |
| --- | --- | --- |
| #130 (new): protocol framing, replies, deadlines, busy | TASK-209 (W1), 218, 225 | W1 |
| #133 (new; the `runner-sandbox.md:43` marker): cut-off key rule always applies | TASK-210 | W1 |
| #134 (new): redaction units, UTF-8, growth guard, empty-match refusal, Go `regexp` | TASK-210 | W1 |
| PD-41 (new): `golang.org/x/sys` | TASK-211 | W1 |
| #132 (new): runner job-check details | TASK-213 | W2 |
| #136 (new): plugin start mechanics, exit codes | TASK-214, 215, 221 | W2 |
| #137 (new): runner start-up refusals | TASK-216 | W2 |
| #138 (new): sweep semantics, runner moved | TASK-215 | W2 |
| #139 (new): spool layout and rules | TASK-212 | W2 |
| #131 (new; refines #28): runner failures as the agent sees them | TASK-218, 223 | W2 |
| #140 (new): overflow details | TASK-219 | W3 |
| #141 (new): posting cadence and size | TASK-220 | W3 |
| #142 (new): capread wire and output | TASK-222, 226 | W3 |
| #135 (new; refines #31): temp directory and private `/tmp` | TASK-221, 224 | W3 |
| #143 (new): "the full CIS set passes under the sandbox" | TP-M10-20 | W5 |
| PD-42 (new): package version | TASK-231 | W6 |
| PD-43 (new): approvals | each task's REVIEW | W1 |
| PD-44 (new): VM and plant execution | TP-M10-20, 22, 24 | W2 (harness) |
| PD-45 (new): M4 checks replaced by requirement | TASK-223 TEST | W4 |
| #4, #28, #29, #30, #31, #57, #60, #74, #78, #113, #114, #116, #121, #124 (f) (agreed, reused) | TASK-209 to 231 | W1 |

### Coverage matrix (M10)

| Spec section | Covered by | Status in M10 |
| --- | --- | --- |
| TS §1.1 G1 (`.deb` agent pulls compliance jobs) | REQ-245, REQ-246, REQ-255 | Covered (agent side) |
| TS §1.1 G2 inventory cannot be disabled | REQ-249 | Covered (regression) |
| TS §1.2 no remediation | REQ-259 (plugins cannot change the host) | Covered: nothing added |
| TS §2.2 L111 pull-only, agent opens every connection | REQ-235, REQ-251 | Covered |
| TS §2.3 compliance flow steps 3–6 | REQ-245, REQ-246, REQ-263 | Covered; step 7 (views) **M11** |
| TS §3 L152 unified cgroup v2 or `runner_unavailable` | REQ-237, REQ-245 | Covered (#131, #137) |
| TS §3.1 package, units, install, logs | REQ-255, REQ-254, REQ-251 | Covered; Debian 12 and arm64 **not supported** (decisions 2026-10-24) |
| TS §3.3 L212 job checks (agent and runner) | REQ-236, REQ-249, REQ-261 | Covered |
| TS §3.3 L222 one at a time, start notice; L224 answers; L226 back-off and spool | REQ-245, REQ-246, REQ-247, REQ-248 | Covered |
| TS §3.4 inventory | REQ-249 | Unchanged, regression only |
| TS §3.5 L248–L253 job execution, cleanup, redaction, capture, batches | REQ-239 to REQ-242, REQ-246 | Covered |
| TS §3.6 `spool_max_mb`, `max_parallel_plugins` | REQ-245, REQ-247 | Covered (#4) |
| TS §3.7 L273–L285 privilege model, socket, peer check, hygiene, supervisor, re-checks | REQ-235 to REQ-240 | Covered |
| TS §3.7 L289–L482 units and D-Bus policy | REQ-255, REQ-259 | Verbatim, unchanged; verified under test |
| TS §3.7 L484 capread helper; L486–L496 file ownership; L500–L505 trade-offs | REQ-252 to REQ-254, REQ-258, REQ-259 | Covered |
| TS §4.4 L577 retry after agent crash | REQ-245 (4), REQ-247 | Covered (no final for an interrupted job, #131 (d)) |
| TS §4.5 L593, L596, L599 (ERROR cases, redacted input, caps) | REQ-241, REQ-242, REQ-248 | Covered on the host side; manager side M8/M9 |
| TS §6.5 Job and Results contracts | REQ-234, REQ-246 | Unchanged contract, used by M10 |
| TS §8.1 L1239, L1244–L1249 (unintended command, plugin changes host, outlives job, agent compromise, in transit, sensitive output) | REQ-235 to REQ-242, REQ-259, REQ-261 | Covered; the accepted risks stay accepted (no signing) |
| TS §8.2 L1265, L1268 Go standards, two approvals | REQ-251, REQ-256; PD-43 | Covered |
| TS §8.3 Unit (redaction fixtures), Agent, Sandbox, Security | REQ-243, REQ-260, REQ-259, REQ-261, REQ-262 | Covered on Ubuntu 22.04 and 24.04 amd64; End-to-end **M11**; Load deferred |
| TS §8.4 L1287 logs without output or tokens | REQ-251 | Covered |
| TS §8.6 L1324, L1329–L1339 redaction patterns | REQ-242 to REQ-244 | Covered (runner side) |
| TS §6.2 L1121, L1123, CSV; TS §8.3 End-to-end; N / N−1 | none | **M11** |
| CLAUDE.md out of scope and owner decisions | none | Nothing planned: no job signing, client certificates, push channel, listening port, ad-hoc command, remediation, inventory switch or manager-side host change |
