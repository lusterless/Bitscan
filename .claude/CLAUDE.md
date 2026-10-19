# Bitscan

Bitscan is a manager + agent platform that inventories Ubuntu/Debian endpoints and runs compliance checks defined in XML `.bit` policy files. Agents are pull-only; the manager never pushes commands.

## Source of truth

- The approved specs are `docs/spec/Technical_Specification.md` (TS) and `docs/spec/bit_Schema_Reference.md` (SR). Rules in `.claude/rules/` summarise them and cite sections as `TS §x.y` / `SR §x.y`.
- Before implementing or changing a feature, read the cited spec section. Do not rely on memory of the spec.
- Never edit the spec files as part of a code change. If code and spec disagree, or the spec is silent, stop and ask; do not guess.
- A rule line starting **Open spec question** marks behaviour the spec leaves undecided: stop and ask the owner before implementing it.
- The DDL in TS §5.2 is the schema. Alembic migrations must reproduce it exactly, including grants.
- Terms (TS §1.3): "agent" means the `bitscan-agent` and `bitscan-runner` services installed from one `.deb`; a job is one inventory collection or one compliance scan unit for one agent. A Policy (a `<Policy>`, shown in the UI as a compliance profile) belongs to one Family (the standard it implements, for example `CIS Ubuntu 24.04` or `Clustermax`) and holds Plugins (one check = one line item in the standard, with the shell command to run), displayed as `<family name> - <plugin name>` (TS §1.4).

## Goals (TS §1.1)

- G1 `.deb` agent: enrols, heartbeats every 5 min (300 s ± 30 s, TS §3.3), pulls jobs every `job_pull_seconds`.
- G2 Mandatory inventory (`os_info` + full `dpkg` list) that no user, role or API call can disable.
- G3 Fleet-wide package search (name, version, architecture, host).
- G4 One `<Policy>` in a `.bit` file = one selectable compliance profile.
- G5 `.bit` files load automatically and can be rebuilt manually.
- G6 Scheduled and manual scans per host, tag or whole fleet.

## Out of scope in v1 — do not implement (TS §1.2, §7.4; OIDC TS §6, client certificates TS §2.2 and §3.2, policy editor TS §4.1)

- Network or agentless scanning; Windows or macOS endpoints.
- CVE matching. `package` (name, version, source_name) is the future v2 join point; no inventory schema change is planned.
- Automatic remediation. Plugins only read and report state.
- A signed APT repository. v1 ships the `.deb` with a published SHA-256.
- OIDC or any external identity provider, agent client certificates (mTLS), and a policy editor in the UI.

## Owner decisions — do not "fix" these

- **No signing** of `.bit` files or jobs. Jobs are trusted because they arrive over TLS in reply to the agent's own authenticated request. The resulting risks are accepted and documented (TS §3.7, §8.1). Do not add signing, manifests or job signatures.
- **No policy approval or diff workflow.** An admin uploads a `.bit` (web session or API token) and it is live immediately.
- `<PolicyName>` is the policy's name and unique key. File names are never used as names.
- Each agent has its own `bsa_` token. A `bse_` enrolment token may be shared by many installs, for example in an org install script: `max_uses` 1–10,000, a required expiry, optional `allowed_cidrs`, `auto_approve` default off.
- API tokens are created only from a web session or the server CLI, never with an API token.
- The delete-policy API exists: `DELETE /policies/{id}` (admin, TOTP session).
- Certificate pinning on agents is optional. There is no signed APT repository in v1.
- Supported hosts: Ubuntu 22.04, Ubuntu 24.04 and Debian 12, on amd64 and arm64, with cgroup v2. Ubuntu 20.04 and Debian 11 are not supported.

## Repository layout

Create code in these locations; the path-scoped rules rely on them.

```text
manager/bitscan_manager/
  app.py              # FastAPI app factory and middleware (headers, size and rate limits)
  api/agent/          # /api/v1/agent/* routes (bsa_, bse_ tokens only)
  api/user/           # all other /api/v1 routes (bsu_, bsk_ tokens only)
  auth/               # sessions, passwords, TOTP, API tokens, RBAC and TOTP-session checks
  services/users/     # user accounts and roles
  services/enrolment/ # enrolment tokens and requests, agent token check and rotation
  services/agents/    # agent fleet: heartbeat handling, status, tags, revoke
  services/inventory/ # inventory upload ingestion
  services/packages/  # package search and CSV export
  services/importer/  # .bit parse, validate, store, rebuild, delete
  services/evaluator/ # evaluate() and scoring
  services/scheduler/ # inventory jobs, scheduled scans, offline_sweep
  services/jobs/      # job building, results intake, states, retries
  services/retention/ # retention task
  services/audit/     # audit chain, sink and disk queue, alerts, metrics
  services/settings/  # runtime settings
  config/             # start-up configuration
  repositories/       # SQL access only (parameterised)
  db/migrations/      # Alembic, forward-only
  cli/                # bitscan-manager CLI
manager/tests/
agent/cmd/{bitscan-agent,bitscan-runner,bitscan-capread}/
agent/internal/{agent,inventory,spool,runner,capread,redact}/
agent/test/sandbox/   # sandbox and security suites run on VMs
web/src/              # React + TypeScript UI
bits/samples/         # sample .bit policies (owned by impl-bits)
bits/tests/           # .bit test fixtures: malformed, XXE, billion-laughs, oversize (owned by tester)
deploy/{systemd,dbus,debian,runbooks,tests}/
e2e/                  # nightly end-to-end and load tests
.github/workflows/
docs/spec/            # TS and SR; never edited as part of a code change
work/                 # agent-team output (see "Agent team" below)
```

## Stack

- Manager: Python 3.12, FastAPI, Pydantic v2, APScheduler, PostgreSQL 16 (`pg_trgm`, `pgcrypto`, `debversion`), `defusedxml`, RE2. One manager instance in v1.
- Agent: Go (a currently supported release), static binaries, no CGO, systemd units.
- Web: React + TypeScript, strict mode, API client generated from the OpenAPI document.

## Commands (CI gates)

- Python lint and format: `ruff check manager && ruff format --check manager`
- Python types: `mypy --strict manager` (type hints everywhere)
- Python dependencies: `pip install --require-hashes -r manager/requirements.txt`
- Go: `gofmt -l agent` (must print nothing), `golangci-lint run ./...` and `go mod verify` from `agent/`; build with `CGO_ENABLED=0`
- Web: `npm run lint` and `npm run typecheck` from `web/`
- Units: `systemd-analyze verify deploy/systemd/*` (locally, before binaries are built, only "not executable" errors are acceptable; CI verifies the units as written, with the built binaries installed, and must report no errors)
- Migrations: `bitscan-manager db migrate` (runs as `bitscan_migrate`, `SET ROLE bitscan_owner`)

## Working conventions

- Python layering is `api → services → repositories`. There is no business logic in route handlers.
- Go: wrap errors with `%w`, and pass a `context.Context` with cancellation through every job.
- Conventional Commits and semantic versioning for agent and manager. Every PR needs one approval; changes to the importer, auth, agent or runner need two (TS §8.2).
- Compatibility: test manager N with agents N and N−1; the manager supports agents of its own version and the one before, and is upgraded first (TS §8.7).
- **Open spec question:** TS §8.2 also says "agent supports manager N and N-1"; ask whether agent N must also be tested against manager N−1.
- Each PR that implements spec behaviour names the TS/SR sections it implements.
- Add or update the tests listed for the area in TS §8.3; each rule's "Tests" line names them, and `.claude/rules/testing.md` holds the gates. Do not lower a gate.
- Local dev is Windows 11 + Git Bash. Python runs from the venv at `manager/.venv`; PostgreSQL tests need Docker (Testcontainers). Do not commit or push unless asked.

## Agent team (`/bitscan-team <goal>`, roles in `.claude/agents/`)

- Ids: `REQ-###` requirements, `TASK-###` micro-tasks; every TASK links at least one REQ. A micro-task is one PR-sized change: about 200 lines or fewer, at most 5 files, independently testable.
- Each TASK is tracked as `TASK-012 IMPL`, `TASK-012 TEST`, `TASK-012 REVIEW`, in that dependency order. TEST completes only with PASS and REVIEW only with APPROVED.
- Ownership: `planner` owns `work/requirements.md`, `work/tasks.md`, `work/plans/`, `work/open-questions.md`; `impl-<area>` (agent type `implementer`) owns non-test files in `manager/`, `agent/`, `web/`, `bits/samples/` or `deploy/`, plus `work/reports/TASK-###-impl.md`; `tester` owns all test files and fixtures (`manager/tests/`, `*_test.go`, `*.test.ts(x)`, `agent/test/`, `deploy/tests/`, `e2e/`, `bits/tests/`) plus `work/reports/TASK-###-test.md`; `reviewer` owns `work/reviews/`; the lead owns `work/status.md` and `work/decisions.md`. Need a change elsewhere: message the owner.
- Durable output goes in `work/` (plans, reports, reviews), not only in messages. Ambiguity or an **Open spec question**: message the lead (teammates address it as `main`), who asks the user. Never guess.
- `work/audit/archive/` is history; do not read it unless asked.
