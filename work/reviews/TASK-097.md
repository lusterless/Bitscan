# TASK-097 REVIEW: agent CI (agent.yml), linux/amd64 only

Verdict: APPROVED (rounds 1–4). Round 4 is confirmed: its diff is limited to the pre-agreed step move (see "Round 4").

Reviewer: reviewer, 2026-10-24; round 4 confirmed 2026-10-25. One review round (CI, speed rule 6). Not on the two-approval list.

Scope reviewed: `.github/workflows/agent.yml`, the working-tree diff against the committed file (`work/reports/TASK-097-impl.md`, rounds 1–4). Sources: REQ-111, REQ-105, PD-27 (a), the decisions of 2026-10-24 (arm64 and Debian 12 dropped) and #74 (runner and capread stay stubs).

TEST: PASS on local evidence (`work/reports/TASK-097-test.md`). It covers actionlint 0, and a replay of every `run:` step: 2 controls and 11 plants, each red in its target step. Round 4 adds CHK-M4-130-r4 and -131-r4. The PR run on GitHub is NOT RUN until the branch is pushed.

## Checks
1. Spec and decisions:
   - Only linux/amd64 is built, listed and tested. `grep -i 'arm64|aarch64'` finds nothing, and there is no Debian job.
   - `go test ./...` runs on ubuntu-22.04 and ubuntu-24.04 runners, which are the supported hosts.
   - The stub check covers only `bitscan-runner` and `bitscan-capread` (#74).
   - The fixtures guard fails the job when `manifest.json` or `openapi.json` is missing, so the G35 contract test cannot pass vacuously.
2. Security and supply chain:
   - `permissions: contents: read` and `persist-credentials: false` in both jobs.
   - Actions are pinned by commit, setup-go has `cache: false`, and golangci-lint is pinned at v2.14.0 through `go install` (Go checksum DB).
   - The nolint/linkname grep, the CGO_ENABLED=0 static-binary checks and the cgo/asm/syso listing are unchanged.
   - Nothing was weakened compared with the committed file. Only the arm64 halves are removed and `go test` is moved.
3. Scope: 1 file, within the task.
4. Tests: every acceptance criterion has a red plant: a failing test, an altered go.sum, `import "C"`, gofmt, nolint, a lint failure and a missing fixture.

## Round 4 (ordered by the lead; not a finding against rounds 1–3)
`agent.yml:51-53` (round 3 line numbers). The problem, as the tester showed:
- `go mod verify` alone cannot detect an altered `go.sum`. With `cache: false` the module cache is empty, and verify compares the cache with its own download records, not with `go.sum`.
- The job is still red on that plant, but at the build's download step, so G9's own command stays green.

The fix: run `go mod download` (all modules) in `agent/` before `go mod verify`, in the same step or the step before it.

I accepted it without another review round, provided both of these hold:
- the diff is limited to that change;
- the tester shows the go.sum plant red at that step.

Anything wider comes back for review.

**Round 4 confirmed (2026-10-25).** Both conditions hold:
- The diff against the committed file is the round 1–3 changes I approved, plus:
  - a new `go mod download` step (`working-directory: agent`) with a three-line comment, at `agent.yml:28-33`;
  - the existing `go mod verify` step, moved without change from after the nolint grep to `agent.yml:35-37`, right after setup-go.
- Nothing else changed.
- CHK-M4-130-r4: actionlint rc 0. The new steps come first.
- CHK-M4-131-r4: the control replay passes. PL2 (one altered `h1:` line in `go.sum`) is first red at `go mod download`.

## Findings
1. nit, `agent.yml:150`. `go test` runs without `-race`. Not required by REQ-111. The race cases (TASK-099 rotation, TASK-091 watcher) are run with `-race` by the testers in WSL. Optional: add a `-race` run on one matrix entry (it needs CGO for the test binary only, never for the shipped build).
