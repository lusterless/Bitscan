# M10 closing review (agent runner and sandbox)

Verdict: APPROVED (round 2)

Reviewer: reviewer-m10c, 2026-11-01.
- Gate record reviewed: `work/reports/M10-gate-test.md` (tester-m10c, TP-M10-24), as folded into `tests/m10/report.md`.
- Tree: worktree `Bitscan-m10`, branch `m10-runner`, which is main `328b097` plus the uncommitted M10 files.
- Basis, the user's decisions of 2026-11-01:
  - "User decisions before the M10 merge":
    - (1) the VM rows are a named gate exception;
    - (2) CHK-M4-223 is rewritten;
    - (3) every nit recorded on 2026-10-30 is accepted as built;
    - (4) the three spec notes are accepted.
  - "User decision: G38 and G41":
    - the merge waits for the PR's `package.yml` G38 run to be green;
    - G41 joins the named exception.
- Also the lead's rows "CHK-M4-100 … is rewritten as CHK-M10-272" and "M10 gate result".

## Task reviews
All 22 built tasks are APPROVED, in `work/reviews/TASK-209.md` to `TASK-229.md` and `TASK-231.md`.

| Rounds | Tasks |
| --- | --- |
| 1 | 209, 210, 211, 213, 214, 216, 217, 219, 220 (r1 as briefed), 222, 223 (r1 as briefed), 226, 227, 228, 229 (r0–r2), 231; 212 r1 delta |
| 2 | 215 (test evidence), 218 (test file), 221 (r1 and r2 under one TEST), 225 (test-file lint) |
| 3 | 224 (r1 blocking: the moved-shell hang; r2: the two nits fixed) |

TASK-230 (sandbox CI, G77) wasn't built. It runs only the held harness, so it is part of the named exception. TASK-146 stays the named carry-over.

PD-43:
- The TS §8.2 second approval applies to TASK-209 to TASK-228. Each is APPROVED with no open blocking or should-fix finding.
- TASK-212's second approval is re-applied for the r1 delta.
- TASK-229 and TASK-231 have one approval each.

## Whole-milestone checks (my own)
1. **Scope of the tree.**
   - Every changed or new non-test file belongs to one of the tasks:
     - the `agent/` runner, spool, capread, sdsock, redact, runnerclient and loops packages, and the three mains;
     - `.golangci.yml`, `go.mod` and `go.sum`;
     - `agent.yml`;
     - the runbook, the README and the changelog.
   - `git diff --stat HEAD -- deploy/systemd deploy/dbus manager/bitscan_manager manager/openapi.json manager/requirements.txt web` is empty. So there is no unit, D-Bus, manager product, contract or web change, as planned.
   - `agent/bitscan-runner.exe` is an untracked local build artefact. It must not be staged; the user's merge row already says so.
2. **Conformance to the TS sections M10 implements.**
   - **TS §3 L152:** the runner refuses to start off unified cgroup v2, and the agent reports `runner_unavailable` (TASK-216, 223).
   - **TS §3.3 L212, L222, L224, L226:**
     - job re-checks in the runner (TASK-213);
     - one compliance job at a time, with the start notice first (TASK-220, 223);
     - the M4 answer classes, with a release-and-rebuild back-off (TASK-220 r1);
     - a 50 MB spool: the oldest results are converted first to `spool_overflow`, and every unreported plugin is filled in or logged (TASK-212, 219, 223 r1).
   - **TS §3.5 L248–L253:**
     - `/bin/sh -c` with exactly `PATH`, stdin `/dev/null`, only the pipes, nice 10, idle I/O, its own cgroup and temp dir, and `timeout_s`, at most `max_parallel_plugins` at once (TASK-221, 224);
     - `cgroup.kill` at exit or timeout, which also holds for a shell that moved itself (TASK-224 r1);
     - the after-job subtree sweep (TASK-215);
     - redaction before truncation, with a 1 MiB read and 64/16 KiB caps (TASK-210, 214);
     - the captured fields, with `truncated` set on a cut capture (TASK-224 r2);
     - batches of ≤ 50 items and ≤ 1.5 MB, gzip, the final last (TASK-220).
   - **TS §3.7 L276–L285:**
     - non-root with only `CAP_DAC_READ_SEARCH`, shown under all 37 verbatim unit directives in WSL (TASK-228);
     - the systemd socket and the `SO_PEERCRED` check for uid `bitscan` (TASK-217);
     - whole jobs only (TASK-209, 225);
     - every fd close-on-exec, and `PR_SET_DUMPABLE` 0 (TASK-216, 217);
     - the `supervisor` leaf and per-plugin cgroups (TASK-215);
     - re-checks of `agent_id`, `pickup_by` and seen ids (TASK-213).
   - **TS §3.7 L484:** capread has two fixed names, an empty env, 10 s and 1 MiB limits, and uid `bitscan-runner` only. The client forwards only the name (TASK-222, 226).
   - **TS §8.4 L1287:** no plugin output, command, pattern or token in logs. Canary sweeps cover the runner, the agent and the journal, and cleanup errors are logged without paths (TASK-224 r2).
   - **TS §8.6:** the fixtures use the five default patterns extracted from the TS, and the RE2 cross-check is green (TASK-210).
3. **Security invariants** (`.claude/rules/security-invariants.md`), checked against the tree:
   - **No ad-hoc command path.** Processes start only at the three REQ-256 sites: `inventory/command.go`, `runner/spawn_linux.go` and `capread/serve_linux.go`. TASK-211's forbidigo rules and CHK-M10-272 enforce this per file. The runner takes only whole decoded jobs, and the capread client only a known name.
   - **No listening port or push channel.** The only `net.FileListener` is `sdsock/listen_linux.go`, which adopts systemd's sockets. CHK-M10-271 forbids listening anywhere in `internal/agent`. The agent dials only the manager (`transport`) and `runner.sock` (`runnerclient`).
   - **Inventory can't be disabled.** A nil handler, an unopenable spool or a missing runner still leaves inventory running (TASK-223, 227; the "exit on spool error" plant is red).
   - **No signing, approval workflow, client certificate, manager-side host change or remediation.** A grep finds no crypto, `systemctl` or D-Bus call in the new code, and the manager is unchanged.
   - **Redaction on the host before truncation.** The spool holds only redacted `proto.Result`. Operator and ExpectedResult never reach the agent: M9 is unchanged, and the spool manifest holds ids and booleans only.
   - **Unit hardening is unchanged.** The units are verbatim (G17, plants 387–390 red).
4. **The two M4 static guards, rewritten under the old-to-new rule.**
   - **CHK-M4-223 → CHK-M10-271** (user decision (2)). It is stricter, not weaker:
     - it keeps every old assertion;
     - `runner.sock` and AF_UNIX are allowed only in `runnerclient`;
     - it adds checks that dialling happens only in `runnerclient` and `transport`, and that nothing listens anywhere;
     - it fails if the allowed site isn't seen;
     - 9/9 plants are red.
   - **CHK-M4-100 → CHK-M10-272** (lead ruling, 2026-11-01). The walk is the same as M4's. The checks are now exact per file:
     - exec calls: exactly one `exec.CommandContext` in `inventory/command.go`, one in `capread/serve_linux.go`, and none anywhere else;
     - exactly one `exec.Cmd` literal, in `runner/spawn_linux.go`;
     - the shell literals `"/bin/sh"` and `"-c"`, once each, only in `spawn_linux.go`. M4 allowed none anywhere; M10 needs exactly these;
     - `os/exec` imported only by those three files and `inventory/command_*.go`;
     - the three #35 command literals, as before.

     Execution anywhere else is still red. Any other file that imports `os/exec` fails, whatever the alias, so the runner allowance can't spread beyond `spawn_linux.go`. It is also new that a second `exec.Cmd` literal is counted; M4 counted none.

     4/4 plants are red: an exec in loops, a shell literal in capread, a second `CommandContext` in the runner, and a second `exec.Cmd` in another runner file. This is not a weakening. One residual is listed under the nits.
5. **Static gates, re-run by me on Windows.**
   - `gofmt -l` prints nothing.
   - `go vet ./...` is clean on Windows and with `GOOS=linux`, plain and with `-tags delegated`.
   - `golangci-lint run ./...` v2.14.0 gives 0 issues on Windows, with `GOOS=linux`, and with `GOOS=linux --build-tags delegated`.
   - There is no `nolint` in non-test code.

## Gate record
- **PASS, each with its plant red where one is defined:**
  - G1–G6 and G18: manager 11,211/11,211, G5 98.53 %;
  - G7–G11, G17, G35, G36, G37, G39, G40;
  - G71–G75;
  - the agent suite: WSL `-race` 1335/1341 with 6 known skips, and delegated 37/37 as `bitscan-runner`.
- **Windows:** 1023/1052. Every failure is pre-existing M4 code that M10 didn't change: `state.syncDir` and the TLS chmod row. That matches main's "PD-45 … Linux-only" row.
- **Mutation table:** 74/74 rows (CHK-M10-320 to -393) red at unit or binary level. Their VM halves fall under the named exception.
- **Old to new:** CHK-M4-223 → -271, CHK-M4-100 → -272, CHK-M6-100 → -318 (+ -319), and CHK-M4-220/-221 → the PD-45 rows. No gate is lowered: each rewrite keeps or tightens the guard, and the release refusal of `~` versions gained a check.
- **Phase report:**
  - `tests/m10/report.md` folds the 22 TASK test reports and the gate report unchanged, under a verdict table, including the old-to-new and NOT RUN tables;
  - `tests/report.md` has the M10 row.

## NOT RUN, and what stays unproven
| Row | Reason | Cover | Unproven on a real host |
| --- | --- | --- | --- |
| G76; every CHK-M10-200 to -259 sandbox row | VM hold, named exception (1) | WD rows as `bitscan-runner` (37/37); the runner under all 37 verbatim service and 5 socket directives in WSL (TASK-228); the capread helper under its 23 verbatim directives (TASK-226); G17 | That, under the real installed units, plugins can't write outside `/tmp`, open IP sockets, exec outside system paths, reach the Docker, containerd, snapd or journald sockets, `ptrace` the runner, read `/proc/<runner>/mem`, call state-changing D-Bus methods or outlive the job. Also the full CIS sample set (#143) |
| G77 (TASK-230, not built) | Runs only the held harness | as G76 | as G76, on the hosted images |
| G78 host part, CHK-M10-280 to -289 | VM hold | G78 unit part (TASK-213, 217, 222, 225); the TASK-228 WSL peer rows | That the installed runner, driven through the driver, refuses expired, foreign and replayed jobs |
| G79, CHK-M10-290 to -292 | VM hold | The agent binary walk (TASK-227, 120/120); real-path redaction (TASK-224 CHK-M10-155); M9 intake suites in G18 | The first compliance run from the installed `.deb` to the real manager, with the redacted output stored |
| VM halves of -320, -325, -327, -329 to -331, -333 to -340, -343, -371, -373, -374, -386, -388 to -391; G79 half of -344; canary sweep of -382 | VM hold | Each row's unit-level red | The same plants as throwaway `.deb`s on a host |
| TASK-231 runbook walk (CHK-M10-315f) | VM hold | 23/23 quoted lines found in the code; commands parse; WSL rows saw the same lines | §1 cgroup v1 symptom and fix, §10 heartbeat `runner_helpers` change, §11 unopenable spool on an installed host |
| G41 (`e2e/agent_manager.sh`, the installed `.deb` against the real manager) | Safety-check refusal; **in the named exception by the user's decision** (runs with the VM checks, before any M11 code or release) | The agent binary walk against the fake manager (inventory included); inventory suites; M9 inventory suites in G18; inventory code unchanged in M10 | The inventory chain from the installed M10 `.deb` to the real manager |
| G38 (maintainer scripts, `0.1.0-1` → `0.2.0~pre1-1` upgrade) | Safety-check refusal locally; **the user's decision: the merge waits for the PR's `package.yml` run** | G37, G39, G40 on a fresh M10 `.deb` (108/108); maintainer scripts unchanged since M6; `dpkg --compare-versions` | Settled by the PR's CI |
| Cgroup v1 boot refusal (u2204) | VM hold | TP-M10-09: injected statfs and `/proc/self/cgroup` | The real v1 boot |
| `auditctl -l` through capread | Not possible in WSL: the kernel refuses audit netlink even to root | TASK-222 rows; the status is passed through (`failed 255`) | Real `auditctl -l` under the helper unit |
| TASK-229 hosted run; actionlint, shellcheck | No push in this session; tools not installed | Step scripts run end to end in WSL, with plants | The first 22.04 run (systemd 249, kernel 5.15) of the 37 delegated rows; hosted caps and modes |
| Binary-level plant of the TASK-221 r2 m0 lock | Not reproducible: m0 never took a start goroutine | Unit-level plant red, with m0 at nice 10 | — |
| Nightly 3-VM end to end, results views, CSV, re-evaluation, N/N−1 | M11 | — | — |
| Load tests | Deferred by the user | — | — |
| Debian 12, arm64 | Not supported | — | — |

**One item no row will show until 22.04 runs** (TASK-221, 228). systemd 249's `@system-service` filter may answer `fchmodat2` with EPERM instead of ENOSYS. If so, the chmod retry in `RemoveTempDir` fails; that retry runs only after a plugin has done `chmod 000` on its own subdirectory. The executor then treats the cleanup failure as fatal, and the runner restarts. That fails closed, but every such job ends without `done`.

## Nits left as built (all accepted by decision (3), or listed only)
- **209:**
  - (1) an error item may carry `timed_out` or `truncated` true;
  - (2) `UnavailableResult` and `OverflowMarker` aren't re-checked;
  - (3) size: 271 lines.
- **210:** a secret straddling the 1 MiB read limit. This is a spec note, accepted under (4).
- **211:**
  - (1) raw `SYS_EXECVE`, `CLONE` and `FORK` via `unix.Syscall` aren't forbidden (none in the tree);
  - (2) PD-41's "x/sys only in runner, sdsock and capread" has no depguard rule. For the agent, CHK-M10-271 now forbids `x/sys/unix` outside `runnerclient`, and `TestImportBoundary` shows that `cmd/bitscan-agent` links none.
- **212:**
  - (1) `nextSeq` isn't advanced before the dir fsync;
  - (2) an unreadable item at `Next` isn't logged;
  - (3) the hold rule reads item files first;
  - (4) a dropped batch that carried the final loses the final;
  - (5) an existing spool dir isn't re-moded.
- **213:**
  - (1) a `pickup_too_far` id holds its seen slot until its own `pickup_by` (kept by ruling);
  - (2) O(n) expiry walk.
- **214:**
  - (1) the unchecked `Unavailable` fallback;
  - (2) a comment on read-error draining.
- **215:** plugin cgroups made 0755 (0700 under `UMask`).
- **216:** `CapPrm` and `CapAmb` aren't checked at start-up. All four show as `0x4` under the verbatim unit (TASK-228).
- **217:**
  - (1) transient `Accept` errors restart the runner;
  - (2) refusal lines have no rate limit.
- **218:** 15–16 busy attempts.
- **219:** a full spool turns a new `runner_unavailable` item into `spool_overflow`.
- **220:** an early-armed 30 s timer can post up to 30 s late.
- **221:** `OpenRoot` on a swapped root dir.
- **222:**
  - (1) the capread timeout kills only the direct child;
  - (2) a stat-before-exec window that only changes the error word.
- **223:** a ctx ending just after `done` leaves the job unfinished. Its items are sent with no final, and M9 ends and retries it.
- **224:** none left; both r1 nits were fixed in r2. The "stdout truncated" wording for a stderr-only cut is on the lead's morning list.
- **225:** a silent `bitscan`-uid peer holds the one slot for 30 s.
- **226:** a helper that closes cleanly after part of an answer can't be detected (#142 has no length field).
- **227:** the deferred `sp.Close` can run beside the sender after the 5 s grace.
- **228:**
  - (1) no start-up check that `/tmp` and `/var/tmp` are private mounts;
  - (2) the m0-lock plant can't be shown at binary level.
- **229:**
  - (1) `strace` isn't version-pinned (consistent with the repo's other apt installs);
  - (2) the `m10c-job` StateDirectory name.
- **231:** §11's "fails after 24 h" doesn't mention the single M9 retry.
- **CHK-M10-272 (test):** inside the allowed file `spawn_linux.go`, a `new(exec.Cmd)` or an aliased `os/exec` selector would not be counted. This can't spread to another file, because the import check is by path, and TASK-211's type-aware forbidigo rule keeps `os/exec` identifiers to the same files.

## Findings
1. should-fix, round 1, **resolved**: the phase report. `tests/m10/report.md` is now folded and `tests/report.md` has the M10 row.
2. Round 1 item, **resolved by the user's decision** ("User decision: G38 and G41", 2026-11-01):
   - G38: the merge waits for the PR's `package.yml` run, which is its evidence.
   - G41: joins the named exception.
3. Observation, no change asked: M10 changed three manager test files: `manifest.json` (`shared_files`), `test_contract_fixtures.py` (tightened) and `test_redaction_crosscheck.py` (new). G18 passes at 11,211/11,211.

## Recommendation
**M10 can merge.** Every task is APPROVED, the TS conformance and the security invariants hold, and no gate is lowered.

The held items are decided by the user:
- the VM rows, TASK-230, the runbook walk and G41 are a named exception, run before any M11 code or release;
- CHK-M4-223 is rewritten;
- the nits and the spec notes are accepted.

Merge on a green PR CI, in particular:
- `package.yml`, which is G38;
- `agent.yml`'s refusal step and its delegated step on both hosted images. The delegated step is the first 22.04 run of the 37 delegated rows.

Stage explicit paths only, and never `agent/bitscan-runner.exe`. If a hosted delegated row fails on 22.04, for example the `fchmodat2` item above, that is a finding for a fresh review, not a CI-file fix.

## Addendum 2026-11-04: PR #20 (VM checks and the runner unit change)

Reviewer: reviewer, 2026-11-04. Full review: `work/reviews/PR20.md` (diff `9f2a99e..8260b4e`, verdict CHANGES_REQUESTED).

**What no longer holds as written above:**
- Check 1 ("no unit, D-Bus … change") and check 3 ("Unit hardening is unchanged") described the tree M10 merged in PR #18. That tree is still true. But the follow-up PR #20 changes `deploy/systemd/bitscan-runner.service`:
  - it adds `ReadOnlyPaths=/dev/shm`;
  - `NoExecPaths=/` becomes `NoExecPaths=/ /tmp /var/tmp`;
  - TS §3.7 is edited to match (user decision 2026-11-03 (1), (2)).
- The runner now runs under 39 `[Service]` directives, not 37.
- There is still no D-Bus, manager product, contract or web change.

**Why the change does not undo this recommendation:**
- It tightens the unit: it closes two gaps the sandbox suite found on real hosts (CHK-M10-201, -203).
- The unit is still verbatim with TS §3.7 (`check_units_verbatim.py all`: 0 problems).
- Every security-critical directive in `.claude/rules/deploy/packaging-and-units.md` survives.
- Plants 394 and 395 guard the new lines.
- I give the TS §8.2 second approval for the unit change itself in `PR20.md`.

**The named exception is cleared with evidence:**

| Item | Result | Note |
| --- | --- | --- |
| G76 | PASS on stand-in QEMU VMs, which the user ruled count | 2 NOT RUN rows, with reasons and cover |
| G77 / TASK-230 | green | |
| G78 host part | PASS | |
| G79 | PASS | |
| TASK-231 runbook walk | PASS | |
| G41 | PASS | |
| VM plants | red | except 333 and 382 (expected not red, user 2026-11-03) and 340 (second cgroup check holds), each recorded with its reason |
| Manager half of CHK-M10-344 | still open | the user's call |

**Does the recommendation still hold?** Yes for M10 as merged in PR #18, and yes for the unit and sample changes in PR #20. PR #20 itself should merge only after the following two findings in `PR20.md` are fixed (or the first gets a recorded user exception):
- finding 1 (blocking): the harness parses `.bit` XML with `xml.etree` instead of `defusedxml`;
- finding 2 (should-fix): a crashed row counts as "red" for plants without an `@part`.

Both are test-harness changes. Neither touches the unit, the samples or product code, so the unit approval above stands through those fixes, unless the fix round touches `deploy/systemd/` or `docs/spec/`.
