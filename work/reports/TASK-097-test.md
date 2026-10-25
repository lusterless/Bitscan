# TASK-097 TEST: agent CI (agent.yml), rounds 1–3

**Verdict: PASS** (local evidence). A GitHub Actions run on a PR is NOT RUN until the branch is pushed.

REQ-111, REQ-105; PD-27 (a); decisions 2026-10-24 (arm64 and Debian 12 dropped; #74 stubs). Tester: tester-m4b. One round (CI, standard rigor).

## Commands
- `actionlint` v1.7.7 → rc 0. `grep -rniE 'arm64|aarch64' .github/workflows/` → nothing; `grep -ni debian` → only the L115 comment.
- Local replay of every `run:` step on throwaway copies: 2 controls and 11 plants; every plant red in its targeted step (CHK-M4-131).
- Round 4: actionlint rc 0; gates replay control 9/9 steps rc 0; PL2 (altered go.sum) first red step `go mod download` (rows CHK-M4-130-r4, CHK-M4-131-r4).

## Acceptance criteria
- `go test ./...` on linux/amd64 on Ubuntu 22.04 and 24.04, with the shared contract fixtures present: PASS (CHK-M4-130, -131 PL1, PL4, PL4b).
- No arm64 anywhere and no Debian job (rounds 1 and 3): PASS (CHK-M4-130).
- Stubs only for bitscan-runner and bitscan-capread: PASS (CHK-M4-130, PL7, PL7b).
- Pinned actions and tools: PASS (CHK-M4-130).
- Planted failures turn the job red (failing test, go.sum, import "C", plus gofmt, nolint, lint, fixtures): PASS (CHK-M4-131).

## Observation (not a defect of this task)
`go mod verify` (G9) cannot catch an altered go.sum in this workflow: the module cache is empty in CI, and verify compares the cache with its own download records, not with go.sum. The go.sum alteration is caught by the build's download check, so the job is still red. Option: run `go mod download` before `go mod verify`. Sent to main and tester-m4 (gate CHK-M4-302).
