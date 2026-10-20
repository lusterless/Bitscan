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
