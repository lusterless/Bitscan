# TASK-097 IMPL: agent CI, linux/amd64 only (round 3)

This task covers REQ-111, REQ-105, PD-27 (a) and the decision of 2026-10-24 "arm64 dropped from v1". It also covers #74: the 0.x runner and capread stay stubs.

Round 2 follows the lead's ruling that TASK-097 owns the PD-27 (a) Go-test matrix in `agent.yml`; TASK-105 owns only the package matrix in `package.yml`.

Round 3 follows the user's decision of 2026-10-24 that drops Debian 12 from v1: the supported hosts are Ubuntu 22.04 and 24.04, amd64 only. The `go-test-debian12` job from round 2 is removed. Test rounds 1 to 3 together.

## Files

The only file changed is `.github/workflows/agent.yml` (51 lines added, 23 removed, against the committed version). There are two jobs: `gates` and `go-test-ubuntu`. No other file was touched.

## What changed

### Round 1 (kept as it was)

1. **Build** (`gates`). The loop over `amd64 arm64` (old L58) is gone. The step builds `CGO_ENABLED=0 GOOS=linux GOARCH=amd64` into `bin/linux_amd64/`. It still checks `go version -m` (`CGO_ENABLED=0`, `GOOS=linux`, `GOARCH=amd64`) and "statically linked" for all three binaries.
2. **Stub step** (`gates`). It now runs only `bitscan-runner` and `bitscan-capread` (#74, REQ-111). `bitscan-agent` is no longer a stub. The checks are unchanged: non-zero exit within 1 s, no stdout, exactly one `<name>: not implemented` stderr line.
3. **cgo listing** (`gates`). The `amd64 arm64` loop (old L107) is replaced by a single linux/amd64 `go list`.

### Round 2

4. **`go test` moved out of `gates`** into the new `go-test-ubuntu` job, so `ubuntu-24.04` does not run the suite twice. `gates` keeps everything else from round 1: gofmt, golangci-lint, the nolint check, `go mod verify`, the build, the stubs and the cgo listing.
5. **`go-test-ubuntu`.** A matrix over `ubuntu-22.04` and `ubuntu-24.04` with `fail-fast: false`. Each runs checkout, then setup-go (same pins, `cache: false`), then the fixtures guard, then `GOOS=linux GOARCH=amd64 go test ./...`. These runners are amd64 and run as a non-root user, so the tests' non-root cases (mode-0000 files, read-only directory) run here.
6. **Round 3: `go-test-debian12` removed** (Debian 12 dropped from v1). The comment above `go-test-ubuntu` now names only the two Ubuntu releases.
7. **Fixtures guard.** It runs in each matrix entry. Before `go test`, it fails if `manager/tests/contract/fixtures/manifest.json` or `manager/openapi.json` is missing. The Go contract test (`agent/internal/agent/wire/contract_test.go`) reads both in place. The workflow has no path filter, so changes to the fixtures or to `openapi.json` also run the contract test on both Ubuntu releases.

Unchanged:
- The action pins (checkout v7.0.1 and setup-go v7.0.0, by commit) and golangci-lint v2.14.0.
- `permissions: contents: read`, and `persist-credentials: false` in every job.

## Checks run locally

- `grep -rn -i 'arm64\|aarch64' .github/workflows/` prints nothing (exit 1).
- The file is LF only.
- There is no actionlint or PyYAML here, so I reviewed the YAML by reading it. CHK-M4-130 runs actionlint.

## Plants (for TP-M4-12)

- **A failing test** makes `go test (linux/amd64)` fail on both matrix entries.
- **An altered `go.sum` hash** fails the build in `gates` (the module download refuses it with "SECURITY ERROR") and `go test` in both matrix entries. *Corrected after TASK-097 TEST:* it does **not** fail `go mod verify`. With `cache: false` the module cache is empty, so verify has nothing to check and exits 0. Even with a populated cache, verify checks the cache against its own download records, not against `go.sum`. The plant still turns the job red, at the download step. Round 4 (below) adds a step so the check stands on its own.
- **A non-test `import "C"`** fails the cgo listing in `gates`.
- **A missing fixtures manifest** fails the guard in both matrix entries.

## Round 4 (lead ruling after TASK-097 TEST rounds 1 to 3 passed)

The only change, in `gates`: a new `go mod download` step (working directory `agent`), and both it and `go mod verify` now sit right after setup-go, ahead of gofmt and golangci-lint (lead ruling, same round), with a three-line comment giving the reason. Nothing else in `agent.yml` changed. The cache starts empty (`cache: false`), so `go mod verify` alone has nothing to check. `go mod download` fetches every module in `go.mod` and checks each against `go.sum` and the Go checksum database, so G9 now fails on its own step.

- **Re-test (PL2):** change one `h1:` hash in `agent/go.sum`; the `go mod download` step must be the first red step of `gates` ("SECURITY ERROR" / checksum mismatch). Before the move, golangci-lint ran first and loaded the packages, so it would have failed before the download step.
- Local checks: the step parses as YAML (same shape as the step after it); `grep -rn -i 'arm64\|aarch64' .github/workflows/` still prints nothing.
