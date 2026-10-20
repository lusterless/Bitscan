# M0 team brief (shared by impl-manager, impl-agent, impl-web, impl-deploy, tester, reviewer)

Written by the lead (`main`). Read it completely before you start. Date: 2026-10-20.

## What we are doing
Milestone M0 (scaffolding) of Bitscan: trees that do nothing yet, with every CI gate running and able to fail. The user approved the breakdown in `work/tasks.md` (10 tasks, 17 REQ in `work/requirements.md`, plans for risky tasks in `work/plans/`). Read, in this order: `.claude/CLAUDE.md`, `.claude/rules/security-invariants.md`, `.claude/rules/testing.md`, your area's rule files, `work/tasks.md`, `work/requirements.md`, `work/decisions.md`, then the plan files for your tasks. The spec in `docs/spec/` wins and is never edited. No code outside the tasks; if a task needs something the spec does not say, message `main` and wait (never guess).

## Decisions already taken (work/decisions.md)
- Hashed Python locks: `uv pip compile --universal --generate-hashes` from `pyproject.toml`; `manager/requirements.txt` (runtime) plus `manager/requirements-dev.txt` (dev), both hashed.
- Tools: newest supported Go (installed: 1.27.2), golangci-lint v2 (2.14.0), Node Active LTS (installed: 24.22.0), `openapi-typescript` + `openapi-fetch`, OpenAPI file `manager/openapi.json`, ruff bans stdlib `re` in `bitscan_manager/`, hatchling, psycopg 3, `google-re2` (if wheels exist for CPython 3.12 on Windows amd64, Linux x86_64 and aarch64; otherwise message `main`), APScheduler 3.x, Vitest, version `0.1.0`, Go module path placeholder `bitscan.local/agent`.
- mypy runs as `mypy --strict --config-file manager/pyproject.toml manager`; test commands run from `manager/`: `pytest --cov=bitscan_manager/services --cov-fail-under=85`; Go `go test ./...` from `agent/`; web `npm test`. Go binaries go to `agent/bin/linux_<arch>/`.
- Docker and WSL are NOT installed on this machine. Anything needing them (PostgreSQL tests, `systemd-analyze verify`, running Linux binaries) is reported NOT RUN locally with the reason; it runs in CI.

## Environment (Windows 11 + Git Bash)
The tools below were installed at user level after this session started, so your shell PATH does not have them. Put this at the start of every Bash command, or call the tools by these absolute paths (Git Bash form):
`export PATH="/c/Users/kaiquan.koh/AppData/Local/Programs/Python/Python312:/c/Users/kaiquan.koh/AppData/Local/Programs/Python/Python312/Scripts:/c/Users/kaiquan.koh/AppData/Local/Programs/go/bin:/c/Users/kaiquan.koh/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe:/c/Users/kaiquan.koh/AppData/Local/Microsoft/WinGet/Packages/GolangCI.golangci-lint_Microsoft.Winget.Source_8wekyb3d8bbwe/golangci-lint-2.14.0-windows-amd64:$PATH"`
Node and npm are on the PATH already. Python runs from a venv at `manager/.venv` (create it with `uv venv --python 3.12 manager/.venv`; it is gitignored). Do not install anything system-wide or globally (no `npm i -g`, no `pip install` outside the venv, no winget). If a tool is missing or a command is denied, message `main`. Never commit, push or change branches. Leave all changes in the working tree. Planted violations for gate checks are made in a throwaway copy (for example a temporary directory or `git worktree`) and removed; never leave them in the tree.

## Who owns what (single writer per file)
- `impl-manager`: non-test files under `manager/`. `impl-agent`: `agent/`. `impl-web`: `web/`. `impl-deploy`: `deploy/` and `.github/workflows/`. Each also writes `work/reports/TASK-###-impl.md` for its tasks. `impl-bits` is not used in M0.
- `tester`: all test files and fixtures (`manager/tests/`, `*_test.go`, `*.test.ts(x)`, `tests/`, ...), `work/reports/TASK-###-test.md`. `reviewer`: `work/reviews/`. `main`: `work/status.md`, `work/decisions.md`. `planner-m0` owns `work/requirements.md`, `work/tasks.md`, `work/plans/`, `work/open-questions.md`.
- Anything else: message the owner. Do not edit `docs/spec/**`, `.claude/**` or the other teammates' files.

## Protocol
- Teammates: `impl-manager`, `impl-agent`, `impl-web`, `impl-deploy`, `tester`, `reviewer` (spawned later). The lead is `main`. Use SendMessage; put a one-line self-contained summary first.
- **Implementer, when a task's IMPL is done:** write `work/reports/TASK-###-impl.md` (what changed, files, how to run the checks, anything the tester must know), then message `tester` with the task id and report path, and copy `main`.
- **Tester:** first (before any code exists) write `tests/m0/test-plan.md` from the acceptance criteria in `work/tasks.md` and the M0 gate table G1 to G17; create the index files `tests/test-plan.md` and `tests/report.md`. Each check has an id `CHK-M0-###` and a type: CODE, or APP (running app; none exist in M0). After an implementer's message, run that task's checks, write one row per check to `tests/m0/report.md` (check id, command, PASS / FAIL / NOT RUN with reason, evidence), write `work/reports/TASK-###-test.md` as a one-page verdict linking to those rows, then message `impl-<area>`, `reviewer` and `main`. TEST completes only with PASS. A FAIL goes back to the implementer with evidence; after 3 rounds escalate to `main`.
- **Reviewer:** after TEST PASS, review the task's files against the spec, rules and security invariants; write `work/reviews/TASK-###.md` (`Verdict: APPROVED` or `CHANGES_REQUESTED`, numbered findings with severity and file:line). TASK-004 and TASK-007 need two approvals: the reviewer plus the user (batched by `main`).
- Ambiguity, an **Open spec question**, or a spec conflict: message `main`, then work on something else. The user is reached only through `main`.
- When your queue is empty send exactly one message to `main` beginning `FINAL:` (at most 150 words: tasks done, files, anything open).

## Quality rules
Each task is one PR-sized change: about 200 hand-written lines or fewer, at most 5 files, only the files listed in `work/tasks.md`. Stay in scope; no extra features or abstractions. Default to no comments. Security invariants are binding (defusedxml only, parameterised SQL only, RE2 for untrusted patterns, no listening socket in the agent, no `InsecureSkipVerify`, no CORS, no unauthenticated `/docs`).
