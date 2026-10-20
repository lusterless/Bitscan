# TASK-010 plan: CI for agent gates and systemd units verify

REQs: REQ-017, REQ-010, REQ-011, REQ-016. Owner: impl-deploy. Depends on: TASK-002, TASK-004, TASK-007, TASK-008.

## Spec quotes

- TS §8.3 L1280: "Units pass `systemd-analyze verify` as written".
- CLAUDE.md "Commands": "CI verifies the units as written, with the built binaries installed, and must report no errors".
- TS §8.3 L1279: agent tests run on Ubuntu 22.04, 24.04 and Debian 12, amd64 and arm64. That suite is M6; M0 builds both architectures only.

## Approach

- `agent.yml`, on `pull_request` and `push` to `main`, in `agent/`:
  1. set up the Go version from `agent/go.mod`;
  2. `test -z "$(gofmt -l .)"` (print the list on failure);
  3. `golangci-lint run ./...` with the pinned version (PD-14 (c));
  4. `go mod verify`;
  5. `CGO_ENABLED=0 GOOS=linux GOARCH=amd64` and `GOARCH=arm64` builds into the PD-9 output path, then `go version -m` on each binary, failing unless it shows `CGO_ENABLED=0`, and `file` showing "statically linked";
  6. **No-cgo/asm/syso listing (REQ-010 (3)).** For each of amd64 and arm64, run:

     ```bash
     out="$(CGO_ENABLED=1 GOOS=linux GOARCH=$arch go list -f '{{if or .CgoFiles .SFiles .SysoFiles}}{{.ImportPath}}: cgo={{.CgoFiles}} s={{.SFiles}} syso={{.SysoFiles}}{{end}}' ./...)"
     ```

     If `$out` is non-empty, print it and `exit 1`. The step catches three kinds of file:
     - cgo files: with `CGO_ENABLED=0`, a file with `import "C"` is silently left out of the build, and the build still exits 0 when the package has other files (impl-agent finding, `work/reports/TASK-004-impl.md`);
     - hand-written assembly (`.s`) and prebuilt objects (`.syso`): they bypass gofmt, golangci-lint and the grep step, because none of these reads them (reviewer finding on TASK-010).

     Run both architectures, because suffixes such as `_amd64.s` select files per `GOARCH`.
     - Under the Actions `bash -e` shell, the assignment `out="$(…)"` is safe: unlike `grep`, `go list` exits 0 when the template prints nothing, so the step does not die on a clean tree. Confirm this on the runner.
     - `CGO_ENABLED=1` is required: with cgo off, such files show up under `IgnoredGoFiles`, not `CgoFiles`.
     - `go list` does not compile, so no C compiler is needed. Confirm this on the runner and on Windows Git Bash, and record it in the impl report. If it is false, set `CC` to a dummy value or use `go list -e`, verify that again, and report it. Do not drop the step.
     - Planted violations for the TEST step, each run on its own:
       - (a) a file `agent/cmd/bitscan-agent/cgo_probe.go` with `package main` and `import "C"`, next to `main.go`. The build stays green, and this step must go red, naming the `<module path>/cmd/bitscan-agent` package;
       - (b) `agent/cmd/bitscan-agent/raw_amd64.s` (for example `TEXT ·raw(SB),NOSPLIT,$0-0` then `RET`, with `#include "textflag.h"`), plus a body-less `func raw()` declared in `main.go` or a sibling `.go` file. The amd64 listing must print `s=[raw_amd64.s]` and the step must go red;
       - (c) any `.syso` file in an agent package (an empty file named `probe_linux_amd64.syso` is enough for `go list`). The step must go red.
  7. **No-nolint/no-linkname step (REQ-012).** Two directives can get around the lint guards in a non-test file:
     - `//nolint:all` or `//nolint:forbidigo,gosec` silences the listener and TLS guards, and golangci-lint has no option to forbid that (reviewer finding on TASK-004);
     - `//go:linkname` can reach unexported standard-library listener internals that `forbidigo` does not name (reviewer request).

     So, after `golangci-lint run`, from `agent/`:

     ```bash
     if grep -rnE --include='*.go' --exclude='*_test.go' '//[[:space:]]*(nolint|go:linkname)' .; then
       echo "nolint or go:linkname in non-test agent code (TS §2.2, §8.1); exceptions need a reviewed allow-list"
       exit 1
     fi
     ```

     - The nolint part gives the same result as the reviewer's reference command, `grep -rnE '//[[:space:]]*nolint' --include='*.go' agent | grep -vE '_test\.go:'`, which must print nothing. Use the `if grep …` form above in the workflow, not that pipeline: under the Actions shell (`bash -e`, with `pipefail` when `shell: bash` is set), a `grep` that finds nothing returns 1 and would kill a step that assigns the pipeline's output. The `if` form avoids that without `|| true`, which REQ-017 (1) forbids.
     - The pattern also catches `// nolint` and `// go:linkname`, which the tools ignore, so the rule is simply "neither appears at all".
     - `_test.go` files are exempt, matching the `forbidigo` test exclusion in the TASK-004 plan.
     - M0 has **no allow-list**. If an exception is ever needed, a separate task adds a reviewed allow-list file (path plus the exact directive). That task needs two approvals, as agent code does (TS §8.2 L1268, PD-3), and the step then skips only the listed lines. Do not add the file in this task.
     - Planted violations for the TEST step, each in a non-test file such as `agent/cmd/bitscan-agent/main.go`, each run on its own:
       - (a) `ln, err := net.Listen("tcp", ":0") //nolint:forbidigo`. golangci-lint passes, and this step must fail, printing that line.
       - (b) `//go:linkname listen net.Listen` above a body-less `func listen(network, address string) (net.Listener, error)`, with `import _ "unsafe"`. This step must fail, printing the directive line, whatever golangci-lint or the build do with it.
  8. `go test ./...` (PD-5).

  **Runner OS.** The whole `agent.yml` job, golangci-lint included, runs on a Linux runner (`ubuntu-*`). On the Windows dev box Go uses `GOOS=windows`, so files named `*_linux.go` or tagged `//go:build linux` are not type-checked or linted there. A clean local lint therefore does not prove the agent is clean; the Linux CI run is authoritative. Running `GOOS=linux golangci-lint run ./...` locally may cover those files, but it is unverified and not relied on.

  Steps 6 and 7 add about 20 lines; TASK-010 stays at 2 files and about 140 hand-written lines.
- `units.yml`, on changes to `deploy/systemd/**`, `agent/**` or `manager/**` (or on every PR, which is simpler and cheap), on an Ubuntu runner with systemd 248 or later:
  1. build the amd64 agent stubs and `sudo install -m 0755` them to `/usr/sbin/`;
  2. create a venv, install `manager/requirements.txt` with `--require-hashes`, install the package with `--no-deps --no-build-isolation` (TASK-001 plan), and `sudo ln -s <venv>/bin/bitscan-manager /usr/bin/bitscan-manager`. This symlink is CI scaffolding only, not the manager install method (#6);
  3. `systemd-analyze verify deploy/systemd/*`, failing on a non-zero exit **or any output**.

## Edge cases and risks

- If the verbatim spec units print a warning or error on the runner's systemd version, do not edit the units and do not filter the output: stop and tell `main`, because it is a spec question.
- `systemd-analyze verify` does not check `User=`, `LoadCredential=` sources or `EnvironmentFile=`; it does check that `ExecStart=` binaries exist and are executable, which is why step 1 and 2 come first.
- arm64 runners: an arm64 build needs no arm64 runner (cross-compile). Running on arm64 hardware is M6.
- No secrets in either workflow.

## Not in this task

The `.deb`, lintian, sandbox suites, reproducible-build and SBOM checks (M6).
