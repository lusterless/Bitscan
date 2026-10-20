# TASK-010 IMPL report: CI workflows for agent gates and systemd units verify

Implementer: impl-deploy. REQs: REQ-017, REQ-010, REQ-011, REQ-012, REQ-016. Spec: TS §8.2 (gofmt, golangci-lint, no CGO, `go.sum`), TS §8.3 (static gates; Sandbox row "Units pass `systemd-analyze verify` as written"), TS §2.2 (no listener), TS §3.7 / §8.7 (units). Plan: `work/plans/TASK-010.md`. M0 gate rows G7 to G10 and G17.

## Files (2 new, LF, 177 lines including blank lines)

- `.github/workflows/agent.yml` (117 lines): one job, `gates`, on `ubuntu-24.04`. The steps, in plan order:
  1. checkout
  2. setup-go from `agent/go.mod`
  3. gofmt (G7)
  4. install golangci-lint v2.14.0
  5. `golangci-lint run ./...` (G8)
  6. no-nolint/no-linkname grep in the plan's `if grep` form (G8)
  7. `go mod verify` (G9)
  8. `CGO_ENABLED=0` linux/amd64 and linux/arm64 builds into `bin/linux_<arch>/`, then `go version -m` must show `CGO_ENABLED=0`, `GOOS=linux` and the matching `GOARCH` for all six binaries, and `file -b` must say `statically linked` (G10)
  9. **(round 2, `main` ruling)** "Run linux/amd64 stubs" for REQ-010 (4), CHK-M0-146. Each of the three amd64 binaries runs under `timeout 1` and fails the step if:
     - it exits 0;
     - it times out or cannot be executed (exit 124 or higher);
     - it writes anything to stdout;
     - its stderr is not exactly one line `<name>: not implemented`.

     The exit code is captured with `if … then … else rc=$?` instead of `|| true`. The static-link check with `file` stays in step 8, for both architectures.
  10. the listing for amd64 and arm64, failing and printing on any output (G10). **Round 3** (reviewer CHANGES_REQUESTED, `work/reviews/TASK-010.md`): the step is now "No cgo, assembly or object files (go list)", with template `{{if or .CgoFiles .SFiles .SysoFiles}}{{.ImportPath}}: cgo={{.CgoFiles}} asm={{.SFiles}} syso={{.SysoFiles}}{{end}}`. See "Round 3" below.
  11. `go test ./...` (G10)
- `.github/workflows/units.yml` (60 lines): one job, `verify`, on `ubuntu-24.04`. The steps:
  1. checkout, setup-go and setup-python 3.12
  2. `python deploy/tests/check_units_verbatim.py all`, which is the tester's script; I only call it, as `main` allowed
  3. build the amd64 stubs and `sudo install -m 0755` them to `/usr/sbin/`
  4. a venv in `$RUNNER_TEMP`, the dev lock installed with `--require-hashes`, `pip install --no-deps --no-build-isolation ./manager`, `sudo ln -s` to `/usr/bin/bitscan-manager`, then `bitscan-manager --help`
  5. `systemd-analyze verify deploy/systemd/*`, which fails on a non-zero exit **or any output** and prints that output (G17)

Both workflows:
- run on `pull_request` and on `push` to `main`, with no path filters, so every PR runs them (REQ-017);
- set `permissions: contents: read` only, `defaults.run.shell: bash` (Actions runs `bash -eo pipefail`) and checkout `persist-credentials: false`;
- contain no secrets, no `|| true`, no `continue-on-error` and no `if:` conditions.

## Action pins (all verified)

| Action | SHA | Tag | How verified |
| --- | --- | --- | --- |
| `actions/checkout` | `3d3c42e5aac5ba805825da76410c181273ba90b1` | v7.0.1 (newest) | `git ls-remote https://github.com/actions/checkout.git` |
| `actions/setup-go` | `b7ad1dad31e06c5925ef5d2fc7ad053ef454303e` | v7.0.0 (newest) | same |
| `actions/setup-python` | `5fda3b95a4ea91299a34e894583c3862153e4b97` | v7.0.0 (newest) | same |

- All three tags are lightweight: no `^{}` line, so the SHA is the commit.
- I fetched each commit (`git fetch --depth 1 <url> <sha>`) and read its `action.yml`:
  - the inputs I use exist: `persist-credentials`, `go-version-file`, `cache`, `python-version`;
  - all three run on `node24`.
- setup-go's `dist/setup/index.js` adds `$(go env GOPATH)/bin` to `PATH`, so the `go install`ed golangci-lint is found.
- golangci-lint is installed with `go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.14.0`. No third-party action is needed. The module is checked against `sum.golang.org`, and it is built with the same Go (1.27.2) that the module targets.

## Deviation from the plan, for the reviewer

Plan step 2 of `units.yml` says to install `manager/requirements.txt`. I install `manager/requirements-dev.txt` instead.
- `--no-build-isolation` needs the build backend in the venv, and hatchling is only in the dev lock (TASK-001 report).
- Tested on Windows: with the runtime lock only, `pip install --no-deps --no-build-isolation ./manager` fails with `BackendUnavailable: Cannot import 'hatchling.build'` (exit 2).
- With the dev lock it exits 0 and `bitscan-manager --help` exits 0.
- The install is non-editable (`./manager`, not `-e`), so the `/usr/bin` symlink does not depend on the checkout.
- The symlink is CI scaffolding only (open question #6), and a comment in the workflow says so.

## Local validation (Windows 11, Git Bash)

- **YAML and workflow lint:**
  - `actionlint` v1.7.12, built with `go install` into a throwaway `GOPATH`/`GOBIN` (nothing installed globally): `Found 0 errors in 2 files`, exit 0.
  - shellcheck and pyflakes are not available, so actionlint skipped those two rules.
  - A planted `runs-onn:` typo in a copy made actionlint exit 1.
  - PyYAML is not installed. actionlint's parser is the YAML parse.
- **Step harness:** a scratch script in a temp dir, not committed, extracts every `run:` block from `agent.yml` with its `working-directory`. It runs each block on its own with `bash --noprofile --norc -eo pipefail -c`, as Actions does, against a throwaway copy of `agent/`.
  - The golangci-lint install step was skipped there, and the local golangci-lint 2.14.0 was used.
  - **Clean copy: all eight steps GREEN.** This was round 1. The round-2 stub-run step needs Linux ELF execution, so it was proven separately (see the REQ-010 (4) note below).
  - actionlint was re-run after round 2: 0 errors.
  - Each planted violation then went into its own fresh copy, which was deleted afterwards:

| Plant (gofmt-clean unless noted) | Red step(s) | Green steps that matter |
| --- | --- | --- |
| G7 misformatted `bad.go` | gofmt (lists `agent\cmd\bitscan-agent\bad.go`) | |
| G8 ignored `os.Remove` error | golangci-lint (errcheck) | |
| G8 `fmt.Errorf("read: %v", err)` | golangci-lint (errorlint) | |
| G8 `net.Listen("tcp", "127.0.0.1:0")` | golangci-lint (forbidigo) | |
| G8 `&tls.Config{InsecureSkipVerify: true}` | golangci-lint (gosec G402) | |
| G8 (a) `net.Listen(...) //nolint:forbidigo` | nolint grep (prints the line); golangci-lint also red (nolintlint: no explanation) | build |
| G8 (a2) `net.Listen(...) //nolint:forbidigo // planted` | **nolint grep only** (prints the line) | golangci-lint, build |
| G8 (b) `//go:linkname listen net.Listen` + body-less `func listen`, `import _ "unsafe"` in `cmd/bitscan-agent/link.go` | **nolint grep only** (prints the directive) | golangci-lint, build, go test |
| Control: `//nolint:forbidigo // ...` in `x_test.go` only | (golangci-lint red: nolintlint "unused directive") | **nolint grep GREEN** (test files exempt) |
| G10 (b) `cgo_probe.go` (`package main`, `import "C"`) next to `main.go` | **CgoFiles listing only**: `bitscan.local/agent/cmd/bitscan-agent: [cgo_probe.go]` (round 1 output format; round 3 adds `cgo=`/`asm=`/`syso=`) | build (`CGO_ENABLED=0`), golangci-lint, go test |
| G10 (a) `internal/p/p.go` with only `import "C"`, imported by `main.go` | build ("build constraints exclude all Go files"), listing, golangci-lint, go test | |

- Note on G10 (a): if the `import "C"` file is the only file of a `cmd/` main package that nothing imports, `./cmd/...` skips the package and the build stays green. The listing still catches it (`bitscan.local/agent/cmd/bitscan-capread: [main.go]`). This matches the TASK-004 report.
- Build evidence: `go version -m` shows `build CGO_ENABLED=0`, `build GOARCH=arm64`, `build GOOS=linux`. Git Bash `file -b` reports `ELF 64-bit LSB executable, ARM aarch64, ... statically linked` for arm64 and `..., x86-64, ... statically linked` for amd64. Running the ELF stubs: NOT RUN locally (Windows).
- **units.yml:**
  - The verbatim step, run from a throwaway copy of `docs/spec/` and `deploy/`, gave `OK 9 units checked, 0 problems`, exit 0.
  - It exited 1 for a planted end-of-line comment (`DIFF bitscan-runner.service line 48`) and for a planted unknown directive (`DIFF bitscan-agent.service line 39: got b'Bogus=1'`).
  - The verify step's logic was run against a stub `systemd-analyze`: silent exit 0 is GREEN; output with exit 0 is RED and prints the output; exit 1 is RED and prints the output.
  - The manager install commands were run on Windows with `Scripts/` in place of `bin/`: dev lock exit 0, package install exit 0, `bitscan-manager --help` exit 0.
  - `sudo install`, the `/usr/bin` symlink and real `systemd-analyze verify`: **NOT RUN locally**, because there is no systemd, WSL or Docker. They run on the PR.

## `go list` with `CGO_ENABLED=1` needs no C compiler (confirmed)

On this machine there is no C compiler on `PATH`; `go env CC` says `gcc`, which does not exist. I ran `CC=/nonexistent/cc CGO_ENABLED=1 GOOS=linux GOARCH=<arch> go list -f '{{if .CgoFiles}}...{{end}}' ./...` for amd64 and arm64:
- clean tree: exit 0, prints nothing;
- with `cgo_probe.go`: exit 0, prints `bitscan.local/agent/cmd/bitscan-agent: [cgo_probe.go]`.

`go list` without `-compiled`, `-export` or `-deps` builds and runs nothing, so it never calls the C compiler. On the Ubuntu runner gcc exists anyway. Without `CGO_ENABLED=1`, the file would appear under `IgnoredGoFiles`, not under `CgoFiles` (plan step 6).

## Round 3: assembly and object files (reviewer should-fix, agent.yml listing step)

The gap: a body-less Go func in `cmd/bitscan-agent/raw.go`, implemented in `raw_amd64.s` with `MOVQ $41, AX; SYSCALL` (socket). It passes the build (confirmed: amd64 `CGO_ENABLED=0` build exits 0), golangci-lint, the nolint/linkname grep and the old CgoFiles listing. The fix widens the listing to `.SFiles` and `.SysoFiles` and renames the step and its message ("cgo, assembly or object files", TS §8.2 and §2.2). It stays at `CGO_ENABLED=1`, for both architectures, and still fails on any output.

Proof: the step's script was extracted from `agent.yml` with `awk` and run under `bash -eo pipefail`, with `CC=/nonexistent/cc`, against throwaway copies of `agent/`:

| Copy | Result |
| --- | --- |
| clean | exit 0, prints nothing |
| `cgo_probe.go` (`import "C"`) next to `main.go` | exit 1: `bitscan.local/agent/cmd/bitscan-agent: cgo=[cgo_probe.go] asm=[] syso=[]` (linux/amd64) |
| `raw.go` (body-less `func rawSocket() int`) + `raw_amd64.s` (SYSCALL 41) | exit 1: `... cgo=[] asm=[raw_amd64.s] syso=[]` (linux/amd64) |
| `raw_arm64only.go` (`//go:build arm64`) + `raw_arm64.s` (SVC, x8=198) | exit 1 in the **arm64** pass: `... asm=[raw_arm64.s]` (amd64 pass empty), so both architectures are needed |
| `blob_linux_amd64.syso` | exit 1: `... syso=[blob_linux_amd64.syso]` |

No C compiler is needed: every run above used `CC=/nonexistent/cc` and no compiler is on `PATH`. actionlint after round 3: 0 errors. agent.yml + units.yml: 177 lines.

## For the tester

- G9 cannot go red until the first dependency exists (M6), as the gate table says.
- G17 cannot be shown locally. On the PR, the clean tree must be green. A copy with an end-of-line comment or an unknown directive turns both the verbatim step and `systemd-analyze verify` red.
- If the runner's systemd prints any warning for the verbatim units, the step goes red by design. The plan says that is a spec question for `main`, not something to filter.
- REQ-010 (4) / CHK-M0-146 (round 2): `main` ruled that CI runs the amd64 stubs. Local proof of the step:
  - The step's script, extracted from `agent.yml` with `awk`, was run under `bash -eo pipefail` against mock stub scripts. Good stubs: exit 0 (green). Each of these was red with a message naming the stub:
    - a stub that exits 0;
    - one that writes `hi` to stdout;
    - one that sleeps 3 s (`exit 124`);
    - one with the wrong stderr text;
    - one with two stderr lines.
  - The same step against Windows-native builds of the real stub source (renamed to drop `.exe`, as a proxy for the ELF files): exit 0.
  - The real linux/amd64 ELF stubs: NOT RUN locally (Windows). They run on the PR.
- **arm64 stub execution: NOT RUN.** There is no arm64 runner decision yet, so I did not add emulation (for example QEMU). The arm64 binaries are only built, and checked with `go version -m` and `file`.

## Note for the user (via `main`)

The arm64 stubs are built and checked to be static, but never executed in CI. Running them needs a decision: either an arm64 GitHub runner (for example `ubuntu-24.04-arm`) or an emulation setup. TS §8.3 already plans the agent suite on arm64 hardware in M6.
- To rerun the step harness, extract each `run:` block with its `working-directory` and run it with `bash --noprofile --norc -eo pipefail -c "<block>"` from a copy of the repo, in the order above.
