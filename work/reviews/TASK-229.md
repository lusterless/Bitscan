# TASK-229 REVIEW: agent CI, runner and capread start-up refusals, plus the delegated runner tests (r0, r1, r2)

Verdict: APPROVED

Reviewer: reviewer-m10c, 2026-11-01. REQ-257 (the `agent.yml` half), REQ-260. Medium risk, one approval (PD-43).

Scope reviewed, per `work/reports/TASK-229-impl.md` (r0, r1, r2): `.github/workflows/agent.yml` (sha256 `5335712d…`), +124 / −21. No other workflow changed.
- r0, job `gates`: the M0 stub step is replaced by "Runner and capread start-up refusals (linux/amd64)".
- r1 and r2, job `go-test-ubuntu`: one new step, "Runner delegated cgroup tests (systemd-run, Delegate=yes)".

TEST: PASS for the local parts (`work/reports/TASK-229-test.md`).
- The YAML parses. Every `uses:` is pinned to a 40-hex SHA. `permissions: contents: read`.
- All 12 `run:` blocks pass `bash -n`.
- The refusal step is green on the M10 build: 6/6 cases.
- The delegated step was run as written in WSL: 37 PASS, 0 FAIL.
- 8/8 plants are red.

Spec read: TS §3 L152; §3.7 L276–L285, L484; §8.3 (Agent, Sandbox rows); decisions rows "The delegated runner tests in CI are a TASK-229 r1", "Delegated real-kernel rows must run as the unit user", "TASK-229 r2 …"; builder checklist item 21; `.claude/rules/testing.md` (no gate lowered).

## Checks (the brief)
1. **Six start-up refusal cases under strace.**
   - Each case checks four things:
     - the exit code;
     - an empty stdout;
     - exactly one stderr line equal to the documented text (a `slog` line compared without its `time=` field);
     - under `strace -f`, none of `socket`, `bind`, `listen`, `accept`, `accept4` and `connect` after the binary's own `execve`. setpriv's NSS lookups before the `execve` are excluded, with the reason stated.
   - The cases:
     - the runner with the job's full bounding set;
     - the runner as `bitscan-runner` with only `dac_read_search` and `--no-new-privs`, which passes every check up to the missing socket;
     - `capread --serve`;
     - the client with no argument;
     - the client with `/bin/sh`;
     - `nft_ruleset` with the helper off. Here only `connect` is allowed.
   - `LISTEN_*` is unset in every case.
   - Red on the M0 runner stub, the M0 capread stub and a listen plant (CHK-M10-313b to d).
   - The expected lines match the code. `hygiene_linux.go:73` gives the CapBnd text, sdsock gives `LISTEN_PID is not this process`, `client.go:32` gives the usage line, and `cmd/bitscan-capread/main.go:40` gives the serve line.
2. **The delegated step runs unprivileged as the unit's user** (checklist 21).
   - `sudo systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes`.
   - r2 adds `-p PrivateTmp=yes -p StateDirectory=m10c-job -p WorkingDirectory=<checkout>/agent/internal/runner`.
   - The build is `go test -c -race -tags delegated` into `/opt/delegated` (0755).
   - It runs on both `ubuntu-22.04` and `ubuntu-24.04`.
   - It fails on any of:
     - `rc ≠ 0` (`|| rc=$?` under `pipefail`);
     - any `--- FAIL`, subtests included;
     - no `^--- PASS: TestDelegated` line, so zero tests is red.
   - Plants A (a failing test), B (tag dropped), C (no PrivateTmp), D (no WorkingDirectory) and E (zero tests) are all red.
   - The r2 chmod loop gives only `o+x` on the directories up to `/`, not including `/`, and `o+r` on the TS file only. It runs on an ephemeral hosted VM.
3. **The unpinned apt install of `strace`.** `apt-get install -y --no-install-recommends strace` takes the archive's current version. That matches every other apt install in `package.yml` and `release.yml` (`lintian`, `dpkg-dev`, `debhelper`), and the actions themselves stay SHA-pinned. This step's result doesn't depend on the strace version, only on its trace output format, which is stable. Acceptable (nit 1).
4. **No other gate lowered.**
   - Only the M0 stub step's assertions are removed. Its "not implemented" line no longer exists, and the new step is stricter.
   - Every other step is unchanged: the lint, the nolint grep, the static build, the cgo listing, `go mod verify` and `go test ./...` on both images.
   - No `continue-on-error`, no `if:` skip, and no new action.
   - No arm64 or Debian 12 job (REQ-257 (2)).

## NOT RUN rows and cover
- **Not run:**
  - the hosted PR run on `ubuntu-22.04` and `ubuntu-24.04`, because there was no push in this session;
  - `actionlint` and `shellcheck`, which aren't installed.
- **Cover:** the YAML parse, `bash -n`, and both step scripts run end to end in WSL as written, with plants. That's adequate for merge. CI on the PR is the deciding run.
- **Unproven until the hosted run:**
  - the hosted job user's `CapEff` is 0, so the first case gets the CapBnd reason;
  - delegation and the `o+x` chain work on the real hosted images;
  - the 37 delegated rows pass as `bitscan-runner` on 22.04's systemd 249 and kernel. This is the first real-kernel run on 22.04 for any M10 row.

## Findings
None blocking or should-fix.

1. nit, `agent.yml:91-92`: `strace` isn't version-pinned. That's consistent with the repository's other apt installs, and no gate depends on its version.
2. nit, `agent.yml` delegated step: `StateDirectory=m10c-job` carries a test-session name into CI. It's harmless (the hosted VM is thrown away), but a neutral name such as `bitscan-runner-test` would read better. That needs the test file changed too.
