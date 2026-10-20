# Status (lead)

Docs audit (rounds 1 to 3): complete. Delivery plan approved by the user (M0 to M8, one phase at a time; the user approves each phase breakdown and exit gate). Nothing is committed.

## Roadmap (reordered 2026-10-20, see decisions.md)
M0 scaffolding (done, PR #1 green) → M1 DB and audit core → M2 auth core → M3 agent API and scheduler (inventory) → M4 Go agent and pre-release `.deb` → M5 minimal host UI and package search → M6 first-release gate (agent heartbeat and `os_info` end to end) → M7 compliance catalog → M8 evaluator → M9 scan engine → M10 agent runner and sandbox → M11 results, re-evaluation, end-to-end. Next: planner breaks down M1; the lead brings the breakdown to the user for approval before any code.

## M0 scaffolding: ready for the user's exit-gate approval (2026-10-20)

All ten tasks: IMPL done, TEST PASS (locally runnable checks), REVIEW APPROVED. The user gave the second approval for TASK-004, TASK-007 and TASK-010 (decisions.md).

| Task | Rounds | TEST | REVIEW |
| --- | --- | --- | --- |
| TASK-001 manager config and locks | 1 + revisions 2, 3 | PASS | APPROVED |
| TASK-002 manager skeleton | 1 | PASS | APPROVED |
| TASK-003 PostgreSQL harness | 1 | PASS (tester-b); Docker checks NOT RUN | APPROVED |
| TASK-004 Go module, lint, stubs | 3 | PASS | APPROVED + user |
| TASK-005 web toolchain | 3 | PASS | APPROVED |
| TASK-006 generated API client | 1 | PASS | APPROVED |
| TASK-007 agent units | 1 | PASS | APPROVED + user |
| TASK-008 manager units | 1 | PASS | APPROVED |
| TASK-009 CI manager and web | 2 | PASS | APPROVED |
| TASK-010 CI agent and units | 3 | PASS | APPROVED + user |

Lead's own run of the M0 gates (2026-10-20, before TASK-005 revision 3): G1 ruff check, G2 ruff format, G3 mypy --strict (12 files), G5 pytest with coverage (55 passed, 3 skipped as not run: Docker unavailable; 100 %), G6 export byte-identical, G7 gofmt, G8 golangci-lint (0 issues), G9 go mod verify, G10 amd64 and arm64 builds, go test, cgo/asm listing empty, G12-G15 web lint, typecheck, format:check, test, units verbatim check (9 units): all green.

**Update 2026-10-20: PR #1 (https://github.com/lusterless/Bitscan/pull/1) first live runs: manager, web, agent and units all green** (58 pytest passed, 0 skipped, with Docker and the pinned Ryuk image on the runner; `systemd-analyze verify` clean; stubs run). Everything in the list below is now confirmed except arm64 stub execution (deferred to M6). Branch `m0-scaffolding`, not merged.

Previously NOT RUN locally (now confirmed in CI): the four workflows on GitHub Actions, the PostgreSQL tests under Docker (CHK-M0-050, 051, 052, 057), `systemd-analyze verify` (G17), the Linux ELF stub run, the Ryuk pull by digest. arm64 stub execution waits until M6.

Next: the user approves the M0 exit gate; then the planner breaks down M1 (open items for it: first-migration size rule PD-18, the audit hash chain core, harness switch to app roles, pytester test for the conftest hook).

Audit history: `work/audit/<role>.md` (merged), `work/audit/archive/` (history, ignore unless asked). Questions for the spec owner and process decisions: `work/open-questions.md`. Decisions: `work/decisions.md`. Tests: `tests/report.md`, `tests/m0/`.
