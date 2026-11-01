# TASK-229 IMPL: agent CI, runner and capread start-up refusal checks

Implementer: impl-deploy-m10, 2026-10-30. REQ-257 (the `agent.yml` half), REQ-260. Spec: TS §3 L152 (the runner refuses to start off the unified cgroup v2 hierarchy), §3.7 L276–L285 (runner: uid `bitscan-runner`, only `CAP_DAC_READ_SEARCH`, socket from systemd), L484 (capread: a request name only, helper off by default), §8.3 Agent row (L1279). Depends on TASK-226 and TASK-228 (both reported). One approval.

## File

- `.github/workflows/agent.yml`, job `gates`: the M0 step "Run linux/amd64 runner and capread stubs" (old L83–L110) is replaced by **"Runner and capread start-up refusals (linux/amd64)"** (new L83–L159, +70/−21 lines).

No other file changed. Every other step is unchanged. That includes the build step, the cgo listing, and the `go-test-ubuntu` job with `go test ./...` on the `[ubuntu-22.04, ubuntu-24.04]` matrix. Actions keep their commit pins, and no action was added.

## What the step does

Set-up:
- Installs `strace` with `apt-get --no-install-recommends`, the pattern `package.yml` already uses.
- Creates the packaged system users `bitscan` and `bitscan-runner` (no home, `nologin`) if missing. Without them the user lookup would refuse first and the systemd socket check would never be reached.
- Copies the two built binaries into a 0755 temp dir, so `bitscan-runner` can execute them (the hosted runner's home is not world-readable).

Then six cases. Each one checks four things:
- the exit code;
- an empty stdout;
- **exactly one** stderr line, equal to the documented text (a `slog` line is compared without its leading `time=…` field);
- under `strace -f`, no `socket`, `bind`, `listen`, `accept`, `accept4` or `connect` call after the `execve` of the binary under test. Earlier calls belong to `setpriv`'s own NSS lookups, which reach nscd and userdb.

`LISTEN_PID`, `LISTEN_FDS` and `LISTEN_FDNAMES` are unset in every case.

| Case | Runs as | Exit | stderr (after `time=`) | Forbidden calls |
| --- | --- | --- | --- | --- |
| runner, full bounding set | the job user (hosted runner: full `CapBnd`) | 1 | `level=ERROR msg="start-up refused" reason="runner: refusing to start: CapBnd holds capabilities beyond CAP_DAC_READ_SEARCH"` | all six |
| runner, the unit's user and bounding set | `sudo setpriv` to `bitscan-runner`, `--bounding-set=-all,+dac_read_search --inh-caps=-all --no-new-privs` (as `bitscan-runner.service` runs it, without the socket) | 1 | `level=ERROR msg="start-up refused" reason="sdsock: LISTEN_PID is not this process"` | all six |
| `capread --serve` | job user | 1 | `level=ERROR msg="no usable socket from systemd; not serving" reason="sdsock: LISTEN_PID is not this process"` | all six |
| capread client, no argument | job user | 2 | `bitscan-capread: usage: bitscan-capread nft_ruleset\|audit_rules` | all six (it connects nowhere) |
| capread client, `/bin/sh` | job user | 2 | same usage line | all six |
| capread client `nft_ruleset`, helper not enabled | job user | 1 | `bitscan-capread: not enabled` | `bind`, `listen`, `accept`, `accept4` (it may try to connect) |

The step reports every failing case, then exits 1 if any failed.

**Why it turns red on the M0 stubs.** The stubs print `<name>: not implemented` and exit 1. All six cases fail on the stderr line, and the two client usage cases also fail on the exit code (1, not 2).

The second runner case covers what REQ-257 means by "exit 1 outside systemd". The runner passes every start-up check up to the socket (non-root, `CapEff` 0, `CapBnd` = `0x4`, cgroup2, unified `/proc/self/cgroup`) and refuses only because systemd passed it no socket.

## How I checked it (local, Windows + WSL Ubuntu-24.04)

- **YAML parse:** PyYAML 6.0.1 in WSL loads the file. The `gates` steps are in the old order, with the new step in place of the stub step. The `go-test-ubuntu` matrix is `['ubuntu-22.04', 'ubuntu-24.04']`.
- **Shell syntax:** `bash -n` on the extracted `run:` block: OK.
- **Run of the step as written:** I built `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath` of `./cmd/bitscan-runner` and `./cmd/bitscan-capread` from the worktree into a scratch dir outside the repo. Then I extracted the `run:` block from the YAML and ran it under `bash --noprofile --norc -eo pipefail` (GitHub's shell) as root in WSL, with two local changes:
  - the two `apt-get` lines were dropped (strace is already installed);
  - the `self` prefix got `setpriv --reuid=1000` so those cases run non-root, as on a hosted runner.

  The run took place in a private mount namespace (`unshare -m`) where the two users exist only in bind-mounted copies of `/etc/passwd` and `/etc/group`. Nothing on the WSL host changed (checked afterwards: no `bitscan` users, no leftover files).

| Binaries | Result |
| --- | --- |
| M10 (worktree) | step exit 0, all six cases pass |
| M0 stubs (`git show HEAD:agent/cmd/bitscan-{runner,capread}/main.go`, built the same way) | step exit 1; all six cases red on the stderr line, and both usage cases also on exit 1 ≠ 2 |
| Plant: a runner that prints the exact CapBnd refusal line but first calls `net.Listen("unix", …)` | step exit 1; both runner cases red, showing the `socket`/`bind`/`listen` trace lines. The unit case is also red on its stderr line. |

My first run caught one real problem, now fixed: in the unit case `setpriv` resolves `--reuid`/`--regid` through NSS (`getpwnam` then a numeric fallback), so it connects to `/var/run/nscd/socket` before the exec. That's why the trace check counts only calls after the binary's `execve`.

## NOT RUN locally

- **The step on GitHub's hosted `ubuntu-24.04` runner:** it runs on the PR. Things only CI confirms:
  - the job user's `CapEff` is 0 (the first case expects the `CapBnd` reason, as TASK-228's report says for hosted runners);
  - `/proc/self/cgroup` is one `0::/…` line under `sudo`;
  - `sudo`, `setpriv` and `useradd` behave there as they do in WSL.
- **`actionlint` and `shellcheck`:** neither is installed locally (Windows or WSL).
- **The PR plant** (put the M0 stub runner back in a throwaway branch and see this step go red): that's the tester's TP-M10-23 row. The local M0 run above is the same check, run off CI.

## For the tester (TP-M10-23)

- Plant 1: restore the M0 `agent/cmd/bitscan-runner/main.go` (`git show 328b097:agent/cmd/bitscan-runner/main.go`) in a throwaway branch. The two runner cases go red.
- Plant 2 (optional): the M0 capread stub. All four capread cases go red.
- `go test ./...` keeps running on both `ubuntu-22.04` and `ubuntu-24.04` (its step is unchanged; r1 below adds one step after it).
- `grep -n 'arm64\|debian:12' .github/workflows/agent.yml` finds nothing new (REQ-257 (2)).
- The `strace` apt package is not version-pinned, which matches the existing apt installs in `package.yml` (`lintian`, `dpkg-dev`, `debhelper`). Actions stay pinned by commit.

## r1: the runner's delegated cgroup tests in CI (2026-10-30)

Lead rulings: decisions rows "The delegated runner tests in CI are a TASK-229 r1" and "Delegated real-kernel rows must run as the unit user". G72 needs the runner's `delegated`-tagged tests (TASK-215; TASK-221 and 224 add theirs to the same package) to run in CI. They need a delegated cgroup v2 subtree, so `go test ./...` never builds them.

### Change

Same file. In job `go-test-ubuntu`, one new step after `go test (linux/amd64)`: **"Runner delegated cgroup tests (systemd-run, Delegate=yes)"** (L201–L237, +37 lines). It runs on both matrix hosts, `ubuntu-22.04` and `ubuntu-24.04`. No other step changed.

1. Creates the system users `bitscan` and `bitscan-runner` if missing. This is a separate job and VM from `gates`, so the refusal step's users aren't there.
2. `GOOS=linux GOARCH=amd64 go test -c -race -tags delegated -o "$dir/runner.test" ./internal/runner/`, where `$dir` is `mktemp -d /tmp/delegated.XXXXXX`, chmod 0755. The binary is outside `$HOME`, 0755, so `bitscan-runner` can execute it.
3. Runs it as `bitscan-runner.service` runs:

   ```sh
   sudo systemd-run --wait --pipe --collect --quiet \
     -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner \
     -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH \
     -p NoNewPrivileges=yes \
     "$dir/runner.test" -test.run Delegated -test.v 2>&1 | tee "$log"
   ```

   The pipeline's status goes into `rc` (`|| rc=$?`, under GitHub's `bash -eo pipefail`).
4. Red when any of these holds:
   - `rc` ≠ 0;
   - any `--- FAIL` line, subtests included;
   - no top-level `^--- PASS: TestDelegated` line. That covers zero tests run, for example a missing tag or a renamed test, where Go prints `testing: warning: no tests to run` and `PASS` with exit 0.

### How I checked it

- **YAML parse** (PyYAML in WSL): the `go-test-ubuntu` matrix is still `['ubuntu-22.04', 'ubuntu-24.04']`. The steps are checkout, setup-go, fixtures, `go test`, then the new step. `bash -n` on the extracted `run:` block: OK.
- **systemd-run exit-code propagation** (WSL Ubuntu-24.04, systemd 255, as root, harmless `/bin/sh` payloads):
  - `systemd-run --wait --pipe --collect --quiet /bin/sh -c 'exit 3'` returns **3**, and `/bin/true` returns 0;
  - through `… 2>&1 | tee … || rc=$?` under pipefail, `rc` = **3**;
  - so a failing test binary (exit 1) turns the step red at the `rc` check.
- **The step's verdict logic**, run verbatim (the extracted lines from `if [ "$rc" -ne 0 ]` to the end) against sample `-test.v` logs:

  | Sample | Result |
  | --- | --- |
  | all PASS, rc 0 | exit 0 |
  | a subtest `--- FAIL` and a top-level FAIL | exit 1, "a test failed" |
  | `no tests to run` / `PASS` | exit 1, "no TestDelegated test passed" |
  | a subtest FAIL beside a top-level PASS | exit 1 |
  | all PASS but rc 1 | exit 1 |

- **The build command**, as the normal WSL user with throwaway caches: it compiles a race-enabled `runner.test`, and `runner.test -test.list Delegated` lists `TestDelegatedCgroups`. So the tag and the name filter select at least one test. `-race` needs cgo and gcc, which the hosted runners have; the binary is dynamically linked, which is fine for a test binary.

### NOT RUN

- **The step end to end in WSL**, as root through `systemd-run` with the unit's properties, plus the plant (one Delegated test made to fail, in a scratch copy outside the repo): **refused by the safety classifier.** I did not reword or retry it, and I told main. The pieces are covered separately: exit-code propagation (above, in WSL), the verdict logic (above), the build and test selection (above). TASK-215's TEST already ran the delegated rows under `systemd-run -p Delegate=yes` in WSL.
- **The hosted-runner run:** it happens on the PR. Only CI confirms:
  - cgroup v2 with delegation on both hosted images;
  - that the tests pass as `bitscan-runner` with only `CAP_DAC_READ_SEARCH`, which is the lead's point: earlier WSL runs were as root.
- **`actionlint` and `shellcheck`:** not installed.

### For the tester (TP-M10-23, G72)

- **Plant A:** in a throwaway branch, add a failing subtest to `TestDelegatedCgroups`. The step is red on `exit 1` (and `--- FAIL`), on both hosts.
- **Plant B:** drop `-tags delegated` from the build line, or rename the test. The step is red with "no TestDelegated test passed".
- **Control:** the unchanged tree is green on both hosts, and the log shows the subtests passing as `bitscan-runner`.
- TASK-221 and 224's `delegated` tests in `./internal/runner/` join the same binary with no CI change, **provided each test name contains `Delegated`** (for example `TestDelegatedSpawn`), so `-test.run Delegated` selects it. A test outside that name pattern would be built but never run.

## Revision 2 (2026-11-01)

Implementer: impl-deploy-m10c. Lead ruling: decisions row "TASK-229 r2: the CI delegated step matches the TASK-224 job rows" (2026-11-01). Source: the "Note for TASK-229" in `work/reports/TASK-224-test.md`. The delegated binary now holds TASK-224's job rows, and without these changes `TestDelegatedJobTmpEmptied` and `TestDelegatedJobRedaction` go red in CI.

### Change

Same file, `.github/workflows/agent.yml`, job `go-test-ubuntu`, step "Runner delegated cgroup tests (systemd-run, Delegate=yes)" only (comment and step now L202–L254, +17 lines). No other step changed.

1. **systemd-run** gets `-p PrivateTmp=yes -p StateDirectory=m10c-job` and `-p WorkingDirectory="$wd"`, where `wd="$GITHUB_WORKSPACE/agent/internal/runner"` (the checkout path).
2. **The test binary** moves from `mktemp -d /tmp/delegated.XXXXXX` to `/opt/delegated/runner.test`. That is outside `/tmp` (PrivateTmp would hide it) and outside `$HOME`. The directory is made with `sudo install -d -m 0755 -o "$(id -u)" -g "$(id -g)" /opt/delegated`, so the job user can build into it without sudo. The binary stays `chmod 0755`.
3. **Spec access, by chmod in place (not a copy).** For each of `$wd` and `$GITHUB_WORKSPACE/docs/spec`, every directory from that one up to (not including) `/` gets `sudo chmod o+x`, search only. Then `chmod o+r` goes on `docs/spec/Technical_Specification.md`. Nothing else gets `o+r`, so `bitscan-runner` can reach the working directory and read the TS, but can't list the runner's home. I chose chmod over a copy because item 3 puts the working directory in the checkout, and `../../../docs/spec/Technical_Specification.md` from there is the checkout's own TS. The runner package's tests read no other file from the tree: I grepped `agent/internal/runner/*_test.go` and the only relative read is `checks_test.go` L161, the TS. The loop runs `while [ "${#p}" -gt 1 ]`, so it also stops on `.`; a plain `!= /` test would loop forever on a relative path.
4. **Unchanged:**
   - `User`/`Group=bitscan-runner`, `AmbientCapabilities` and `CapabilityBoundingSet=CAP_DAC_READ_SEARCH`, `NoNewPrivileges=yes`, `Delegate=yes`;
   - `-test.run Delegated -test.v`, `2>&1 | tee "$log" || rc=$?` under GitHub's `bash -eo pipefail`;
   - the three failure rules: `rc` ≠ 0, any `--- FAIL`, no `^--- PASS: TestDelegated`;
   - the user creation, the `-race -tags delegated` build line, `working-directory: agent`, and the log in `$RUNNER_TEMP`.

### How I checked it

- **YAML parse** (PyYAML 6.0.1, WSL): the `go-test-ubuntu` matrix is still `['ubuntu-22.04', 'ubuntu-24.04']`. Its steps are still checkout, setup-go, fixtures, `go test`, then the delegated step, with `working-directory: agent`.
- **`bash -n`** on the extracted `run:` block: OK.
- **The chmod loop, dry run** (chmod and sudo stubbed to `echo`, `GITHUB_WORKSPACE=/home/runner/work/Bitscan/Bitscan`): it touches `…/agent/internal/runner`, `…/agent/internal`, `…/agent`, `…/docs/spec`, `…/docs`, the checkout, `/home/runner/work/Bitscan`, `/home/runner/work`, `/home/runner` and `/home` (o+x), plus the TS (o+r). It never touches `/`.
- **The chmod loop, real** (no sudo, my WSL user, a scratch 0750/0640 tree under `/tmp`, deleted afterwards): every directory on both paths ends `drwxr-x--x`. The TS ends `-rw-r--r--`, and a sibling file stays `-rw-r-----`.
- **The r2 unit properties, probed once** (WSL Ubuntu-24.04, systemd 255, root running `systemd-run`, payload as `bitscan-runner`). The command was the step's own `systemd-run` line with `WorkingDirectory` at this worktree's `agent/internal/runner`. Instead of the test binary, a read-only `/bin/sh -c` printed four things:
  - `id -u` = **999**;
  - `pwd` = the working directory;
  - `STATE_DIRECTORY=/var/lib/m10c-job`;
  - the TS at `../../../docs/spec/Technical_Specification.md` is readable, and `/tmp` and `/var/tmp` are 2 mount lines in the unit's own mountinfo (private).

  `rc=0`. WSL's `/mnt/c` drvfs modes are permissive, so this probe doesn't exercise the 0750-home case; the real-chmod run above covers it. `/var/lib/m10c-job` existed already from TASK-224's TEST runs.

### NOT RUN

- **The step end to end with the race-built test binary**, locally. That would install into `/opt` on the WSL host. TASK-224 TEST already ran the same binary with the same property set (the identical `systemd-run` line) as bitscan-runner in WSL: 31/31 ×3.
- **The hosted-runner run:** it happens on the PR. Only CI confirms:
  - the real home and workspace modes, and that the o+x chain suffices there;
  - `/opt` is writable via `sudo install`;
  - the job rows pass on both images.
- **`actionlint` and `shellcheck`:** not installed.

### For the tester (TP-M10-23, G72)

- **Control:** green on both hosts. The log shows TASK-224's `TestDelegatedJob*` rows passing, including `TestDelegatedJobTmpEmptied` and `TestDelegatedJobRedaction`.
- **Plant C:** drop `-p PrivateTmp=yes`. `TestDelegatedJobTmpEmptied` refuses ("not private mounts"), and the step goes red.
- **Plant D:** drop the `-p WorkingDirectory=` line. The cwd becomes `/`, so `../../../docs/spec` doesn't resolve, `TestDelegatedJobRedaction` can't extract the TS patterns, and the step goes red.
- **The chmods may not be strictly needed, so don't plant them.** The unit's ambient `CAP_DAC_READ_SEARCH` already bypasses read and search checks once the test runs, so dropping the chmods may well stay green. I don't know whether systemd's `chdir` to `WorkingDirectory` happens before that capability is effective. The chmods make the step independent of that order and of the hosted image's home mode.
- Plants A and B from r1 still apply.

## Revision 3 (2026-11-01)

Implementer: impl-deploy-m10c. Lead ruling: decisions row "PR #18 CI fixes accepted" (2026-11-01), item (1). Step text: `work/reports/PR18-ci-fix-test.md` §1, the YAML block under "agent.yml change needed (impl-deploy)".

### Change

Same file, `.github/workflows/agent.yml`, job `go-test-ubuntu`. One new step, **"Root-only tests (sudo)"** (comment and step L202–L232, +32 lines, nothing removed). It sits right after `go test (linux/amd64)` and before the delegated step. I inserted the block exactly as given in §1, with no edits. No other step changed.

What it does:
- Builds `runnerclient`, `capread` and `sdsock` test binaries as the job user (`go test -c -race`) into a 0755 `mktemp -d` directory.
- Runs each one under `sudo` from its package directory, with `-test.run "^<Test>$" -test.count=1 -test.v`.
- Is red when any of these holds: the binary exits non-zero; there is no `^--- PASS: <Test> (` line for `TestConnectPermissionDeniedLinux`, `TestPeerCheckThroughSdsock` or `TestPeerCheck`; or any `--- FAIL` or `--- SKIP` line appears.

### How I checked it

- **YAML parse** (PyYAML 6.0.1, WSL):
  - the `go-test-ubuntu` matrix is `['ubuntu-22.04', 'ubuntu-24.04']` with `runs-on: ${{ matrix.os }}`, so the step runs on both images;
  - the steps are checkout, setup-go, fixtures, `go test`, **Root-only tests (sudo)**, then the delegated step;
  - the new step's `working-directory` is `agent`.
- **Identical to the report:** the YAML block from `PR18-ci-fix-test.md` §1 appears in `agent.yml` exactly once, byte-identical.
- **`bash -n`** on the extracted `run:` block: OK.
- `git diff` on `agent.yml`: the 32 added lines only.

### NOT RUN

- **The step itself:** I didn't run it locally. tester-m10d ran the same body in WSL (R3: exit 0 as root; R4: exit 1 when every row skips; R6: exit 1 with the plants).
- **The hosted run:** it happens on the PR. Only CI confirms that `sudo`, `setpriv` and `python3` behave there as in WSL.
- **`actionlint` and `shellcheck`:** not installed.
