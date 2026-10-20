# Tasks

Owner: planner. Ids are never renumbered or reused. Each TASK becomes `TASK-### IMPL`, `TASK-### TEST`, `TASK-### REVIEW`, in that order. Requirements are in `work/requirements.md`; plans for risky tasks are in `work/plans/`.

Row format: `TASK-### | title | REQ links | area | owner | files expected (<= 5) | depends on | est. LOC (<= 200) | acceptance test`.

LOC counts hand-written lines only. Generated files (`manager/requirements*.txt`, `web/package-lock.json`, `manager/openapi.json`, `web/src/api/schema.d.ts`) are counted as files, not lines; the reviewer checks they are reproducible from the stated command, not line by line.

## M0 scaffolding

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

## Waves and dependency spine

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

## Changes since approval

| Date | Change | Why |
| --- | --- | --- |
| 2026-10-20 | **No-cgo check.** REQ-010 (3) and the TASK-004 plan no longer say a `CGO_ENABLED=0` build fails on any `import "C"` file. TASK-010 (row and plan) and gate G10 gain a CI step: `CGO_ENABLED=1 GOOS=linux go list -f '{{if .CgoFiles}}{{.ImportPath}}: {{.CgoFiles}}{{end}}' ./...` for amd64 and arm64, failing on any output. Its planted violation is an `import "C"` file next to `main.go` in `agent/cmd/bitscan-agent/`. TASK-010 stays at 2 files; its estimate goes from 120 to 130 lines. TASK-004 itself is unchanged; its acceptance test now also names the listing. | impl-agent found (`work/reports/TASK-004-impl.md`) that with `CGO_ENABLED=0` such a file is silently left out of the build. The build then exits 0 unless the file is the package's only one, so the build alone could not prove "no CGO" (TS §8.2 L1265). |
| 2026-10-20 | **No-nolint step and Linux lint runner.** TASK-010 (row, plan) and gate G8 gain a CI step in `agent.yml`. It fails when any non-test `.go` file under `agent/` contains a `//nolint` directive (`grep -rnE --include='*.go' --exclude='*_test.go' '//[[:space:]]*nolint'`). Its planted violation is `//nolint:forbidigo` on a `net.Listen` call. M0 has no allow-list; any future exception needs a reviewed allow-list added by its own two-approval task. Agent lint is stated to run on a Linux runner, because `_linux.go` files are not linted on the Windows dev box. TASK-010 adds REQ-012 to its links, stays at 2 files, and goes from 130 to 140 lines. | Reviewer finding on TASK-004: `//nolint:all` or `//nolint:forbidigo,gosec` silences the listener and TLS guards (REQ-012, TS §2.2, §8.1), and golangci-lint cannot forbid that itself. |
| 2026-10-20 | **`//go:linkname` added to the same step.** The TASK-010 step (row, plan step 7) and gate G8 now also fail on `//go:linkname` in any non-test `.go` file under `agent/` (pattern `'//[[:space:]]*(nolint\|go:linkname)'`). Planted violation: `//go:linkname listen net.Listen` in `agent/cmd/bitscan-agent/`. The plan states the step's result equals the reviewer's reference command for the nolint part, and why it uses the `if grep …` form rather than a pipeline (with `bash -e`/`pipefail`, a grep that finds nothing would kill the step). TASK-010 stays at 2 files and about 140 lines. | Reviewer request: `//go:linkname` can reach unexported standard-library listener internals that `forbidigo` does not name (REQ-012, TS §2.2). |
| 2026-10-20 | **Assembly and object files.** REQ-010 (3) and REQ-012 are widened, and the TASK-010 listing (row, plan step 6) and gate G10 now use `{{if or .CgoFiles .SFiles .SysoFiles}}…{{end}}`. They fail on cgo, hand-written assembly (`.s`) or prebuilt object (`.syso`) files in any agent package. New planted violations: `raw_amd64.s` next to `agent/cmd/bitscan-agent/main.go`, implementing a body-less func, and a `.syso` file. No size change (TASK-010: 2 files, about 140 lines). | Reviewer finding on TASK-010: `.s` and `.syso` files bypass every agent gate (gofmt, golangci-lint, the grep step and the REQ-012 guards). |
