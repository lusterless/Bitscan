# Bitscan

Bitscan is a manager + agent platform that inventories Ubuntu/Debian endpoints and runs compliance checks defined in XML `.bit` policy files. Agents are pull-only: the manager never pushes commands. Supported hosts are Ubuntu 22.04, Ubuntu 24.04 and Debian 12 (amd64 and arm64, cgroup v2).

**Status:** M0 scaffolding done (see PR #1); next M1.

## Where things are

| Path | What |
| --- | --- |
| `docs/spec/Technical_Specification.md` | Technical specification (TS), the source of truth |
| `docs/spec/bit_Schema_Reference.md` | `.bit` file format and schema reference (SR) |
| `.claude/CLAUDE.md` | Project rules: layout, stack, CI-gate commands, owner decisions, out-of-scope list, agent-team conventions |
| `.claude/rules/` | Per-area rules that summarise the spec and cite sections as `TS §x.y` / `SR §x.y` |
| `.claude/agents/`, `.claude/skills/bitscan-team/` | Agent-team roles (planner, implementer, tester, reviewer) and the `/bitscan-team` manager skill |
| `docs/agent-teams-reference.md` | How Claude Code agent teams work |
| `docs/agent-teams-patterns.md` | Summary of the first workspace audit and lessons for running teams |
| `work/` | Team output: requirements, tasks, plans, reports, reviews, open questions, and `work/audit/` reports |
| `work/open-questions.md` | Questions waiting for the spec owner; do not implement the affected behaviour until they are answered |

## Planned layout

`manager/` (Python 3.12, FastAPI, PostgreSQL 16), `agent/` (Go, static binaries, `.deb`), `web/` (React + TypeScript), `bits/samples/` and `bits/tests/` (`.bit` policies and test fixtures), `deploy/` (systemd units, D-Bus policy, Debian packaging, runbooks), `e2e/` (end-to-end and load tests). Details are in `.claude/CLAUDE.md`.

## Local development

Windows 11 with Git Bash. You will need Python 3.12 (venv at `manager/.venv`), Go, Node.js and Docker (for PostgreSQL tests with Testcontainers). Linux-only suites (systemd sandbox, `.deb` packaging) need a Linux VM, WSL2 or CI.

## Working with the agent team

Start a new Claude Code session in this folder and run `/bitscan-team <goal>`, for example `/bitscan-team M1 database and audit core`. The session becomes the team manager: it asks a planner to break the goal into requirements (`REQ-###`) and micro-tasks (`TASK-###`), waits for your approval, then drives each task through implement, test and review. Agent teams are enabled in `.claude/settings.json`. Nothing is committed or pushed unless you ask.
