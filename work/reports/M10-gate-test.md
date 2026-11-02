# M10 gate (TP-M10-24): PASS, except G38 and G41 NOT RUN (safety-check refusal) and the named VM exception NOT RUN

Tester: tester-m10c, 2026-11-01. Tree: worktree `Bitscan-m10`, branch `m10-runner`, which is main `328b097` plus the uncommitted M10 files.

Environments:
- **L:** Windows 11, Go 1.27.2. No `-race`: it needs cgo, and this host has no C compiler.
- **W:** WSL Ubuntu 24.04, cgroup2fs, systemd 255, Go `/opt/go1.27.2`, with my own GOCACHE and GOMODCACHE (`/root/m10c`) and my own venv (`/root/m10c/venv`, `pip install --require-hashes -r manager/requirements-dev.txt`, then `-e` of the copy). Every Go unit run used `-race`.
- **WD:** W, delegated, as `bitscan-runner`: `systemd-run --wait --pipe --collect -p Delegate=yes -p User=bitscan-runner -p Group=bitscan-runner -p AmbientCapabilities=CAP_DAC_READ_SEARCH -p CapabilityBoundingSet=CAP_DAC_READ_SEARCH -p NoNewPrivileges=yes -p PrivateTmp=yes -p StateDirectory=m10c-job`.

Plants were made only in throwaway copies; the worktree holds none.

**The named exception** (user, decisions 2026-11-01 (1)): G76, the VM half of G78, G79, the VM-planted CHK-M10 rows, TASK-230 (sandbox CI, G77) and TASK-231's runbook walk are NOT RUN, reason "VM hold (safety check)". They must run before any M11 code and before any release, and no tag is made. Each row below names its lower-level cover.

## Gates

| Gate | Command | Result | Evidence |
| --- | --- | --- | --- |
| Agent suite, W | `go test -race -count=1 ./...` from `agent/` (fresh copy with `manager/tests/contract/` incl. `loader.py`) | **PASS** | **1333/1341 passed, 2 failed, 6 skipped**. The 2 were `TestBuildBodyLargeLists/50000` and its parent, an M4 timing bound: "50,000 rows built in 6.27 s, want < 5 s" under full-suite `-race` load. Re-run alone: **3/3 passed** (0.94 s). Final: **1335/1341 passed, 0 failed, 6 skipped** (4 wire schema-gap skips per main's 2026-10-23 ruling, 1 `state` root-only row, 1 `inventory` row). 19 packages. Per package: cmd/bitscan-capread 1, cmd/bitscan-runner 8, internal (boundary) 1, agent/config 98, enrol 53, loops 124, runnerclient 38, schedule 12, state 47+1 skip, token 42, transport 56, wire 363+4 skip, capread 19, inventory 112+1 skip, redact 78, runner 121, runner/proto 108, sdsock 20, spool 34 |
| Agent suite, L | `go test -count=1 ./...` from `agent/` | PASS except the known pre-existing Windows rows | **1023/1052 passed, 25 failed, 4 skipped**. 17 packages: 11 pass, 3 have no Windows tests, 3 fail. Every failure is M4 code unchanged in M10 (`git diff HEAD -- agent/internal/agent/{enrol,state,transport}` is empty), and the Linux-only M10 files don't build on Windows:<br>• `enrol` 19 rows and `loops` 5 rows (TestJobChecks, TestJobSeenSevenDays, TestJobSeenBeforeAct, TestJobDispatchOrder, TestJobPickupRecheckedAtStart): `state.syncDir` fsyncs a directory, which Windows refuses ("Access is denied");<br>• `transport` TestTLSConfigErrors: chmod 0 isn't enforced on Windows.<br>Linux-only, not built on Windows: `compliance_linux_test.go`, `compliance_r1_linux_test.go`, `inventory_linux_test.go`, every `*_linux_test.go`. TestJobPickupRecheckedAtStart used to hang until the package timeout; a fail-fast was added (test-side only, no assertion changed). Loops on Windows: 93/98 passed, 5 failed (the rows above) |
| Delegated binary (G72 half) | WD, `-test.run Delegated` | **PASS** | **37/37 passed** (cgroup 5, spawn 7, remove-temp 3, job 22), unit exit 0. Identity logged: uid 999, CapEff/Prm/Bnd/Amb 0x4, NoNewPrivs 1 |
| G1 | `ruff check manager` (W) | PASS | "All checks passed!" |
| G2 | `ruff format --check manager` (W) | PASS | 386 files already formatted |
| G3 | `mypy --strict --config-file manager/pyproject.toml manager` (W) | PASS | "Success: no issues found in 386 source files" |
| G4 | the venv built with `--require-hashes`; `git diff --stat HEAD -- manager/requirements*.txt manager/pyproject.toml manager/bitscan_manager manager/openapi.json` | PASS | install OK; the diff is empty. M10 changed only manager **tests** (`tests/contract/fixtures/manifest.json`, `test_contract_fixtures.py`, `test_redaction_crosscheck.py`, the redaction corpus) |
| G5 | services coverage in G18 | PASS | **98.53 %** (5,692/5,777) of `bitscan_manager/services` (gate 85 %) |
| G6 | `tests/test_openapi.py` in G18; `git diff HEAD -- manager/openapi.json` | PASS | green; openapi.json unchanged |
| G18 | full manager suite, `pytest -n 2 -rfEs --cov` (W, `CI=true`, PostgreSQL 16 by Testcontainers) | **PASS** | First run: **11,205 passed, 3 failed, 3 errors** of 11,211 (26 min 45 s). All 6 were my environment: the WSL copy lacked the web UI build and `README.md` ("the web UI build is missing"; `FileNotFoundError …/README.md`). The UI was then built from a temp copy of `web/` (`npm ci --ignore-scripts`, `vite build --outDir <temp>/webui`), and it and README.md were copied into the WSL copy only, not the worktree. The 6 node ids re-ran: **6/6 passed**. Final: **11,211/11,211**, 0 skipped. Not product failures |
| G7 | `gofmt -l agent` | PASS | prints nothing |
| G8 | `golangci-lint run ./...` v2.14.0 (W, plus `--build-tags delegated`; L) | PASS | 0 issues in all three. During the gate, 4 findings in **my** new test files were fixed: 3 × G204 in `cmd/bitscan-capread/main_test.go` and `internal/boundary_test.go` (test-file `nolint:gosec` with a reason, the repo's practice for tests), and an unused field in `results_test.go`. A deprecated `runtime.GOROOT()` was replaced with `go` from PATH. Earlier, a G115 in `serve_linux_test.go` was fixed with a checked bound (reviewer-m10c) |
| G9 | `go mod verify`; cold-cache `go mod download` | PASS | "all modules verified"; the cold-cache download rc 0 |
| G10 | `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath ./cmd/...`; `go list` for cgo/asm/syso | PASS | three ELF x86-64 binaries, statically linked; no cgo, asm or syso |
| G11 | nolint/linkname grep, non-test agent code | PASS | 0 hits |
| G17 | `check_units_verbatim.py`; `systemd-analyze verify` of the five agent units (0644 copies) | PASS | "OK 10 files checked, 0 problems". Verify printed only "Command /usr/sbin/bitscan-* is not executable" (binaries not installed). Plants CHK-M10-387 to -390 red (table) |
| G35 | Go contract test (in the W suite), plus the manager's `test_contract_fixtures.py` | PASS | `internal/agent/wire` 363/367 (4 schema-gap skips, main ruling 2026-10-23). The `redaction/corpus.json` fix: the manifest has a `shared_files` section and both checks count it; 5/5 plants red (Go and Python) |
| G36 | `go test -race ./internal/agent/... -run 'Security\|TLS\|Job'` (W) | PASS | **64/64 passed**, 0 failed, 0 skipped |
| G37 | `test_build_deb.sh all` (lintian part) in m4b-build-u24 | PASS | `lintian --fail-on error,warning` passes, with no E:/W: tag and every override used and reasoned |
| G38 | `test_maintainer_scripts.sh --deb <0.2.0~pre1-1> --from <0.1.0-1> all upgradefrom` in a privileged m4b-sysd-u24 container | **NOT RUN** | The first `.deb` build for it stalled downloading the SBOM tool's modules: its log stopped at 16:58, so the network stalled. The next action, stopping that run and its throwaway container, **was refused by a safety check**, so per my brief G38 was not retried or worked around. main was told. Cover: G37, G39 and G40 passed on a fresh M10 `.deb` (108/108, contents byte-identical to `deploy/`), and `check_debian_meta.py` 81/81. The 0.1.0-1 → 0.2.0~pre1-1 ordering is checked with `dpkg --compare-versions` (TASK-231). The maintainer scripts are unchanged since M6 (`git diff HEAD -- deploy/debian/*.post* deploy/debian/*.pre*` empty). package.yml runs G38 in CI on the push |
| G39 | `test_build_deb.sh all` (repro) | PASS | Two builds at different paths. Identical sha256: `.deb` 5ac2b149…8045, `.sha256` 206fa92b…6e89, bitscan-agent 490cc875…8917, bitscan-runner fb65da6b…76c2, bitscan-capread 7d001846…e06e; SBOM bytes identical |
| G40 | `test_build_deb.sh all` (sbom) | PASS | The runner and capread SBOMs list `golang.org/x/sys v0.49.0` (PD-41); the agent's doesn't link it. `test_build_deb.sh` total **108/108** |
| REQ-255 (3) | the M0 stub text in the built binaries | PASS | The static gate builds (same flags as the package) hold 0 copies of `bitscan-runner: not implemented` / `bitscan-capread: not implemented`. The other "not implemented" strings are the Go runtime's (ENOSYS "function not implemented"), not stubs. The packaged runner and capread are the same source and flags (test_build_deb `flags` 108/108) |
| G41 | `e2e/agent_manager.sh` (the installed `.deb` against the real manager, W) | **NOT RUN** | It was queued behind G38 and needs that `.deb`, so it was stopped by the same safety-check refusal (above). Cover: the M10 agent binary walk against the fake manager (TASK-227, 120/120, inventory included), the inventory package suites (W), M9's inventory suites in G18 (11,211/11,211). The inventory path is unchanged in M10 |
| G71 | redaction: `go test -race ./internal/redact/...`; `test_redaction_crosscheck.py` | PASS | **78/78**; the RE2 cross-check is green in G18 (45/45 at TASK-210) |
| G72 | runner Linux suites `./internal/runner/... ./internal/sdsock/...`, plus the delegated binary | PASS | **141/141** (runner 121, sdsock 20), plus **37/37 passed** (cgroup 5, spawn 7, remove-temp 3, job 22), unit exit 0 delegated |
| G73 | `./internal/agent/... ./internal/spool/...` | PASS | **867/872 passed, 0 failed, 5 skipped** (5 skips: 4 wire schema gaps and 1 state root-only row) |
| G74 | `./internal/capread/... ./cmd/bitscan-capread/` | PASS | **20/20**; the WSL helper-unit row (TASK-226) |
| G75 | protocol and the import boundary | PASS | **109/109** (proto 108, boundary 1); plants -323, -380, -381 red |
| G76 | sandbox suite on `bitscan-u2204`/`bitscan-u2404` | **NOT RUN** | VM hold (safety check), the named exception. Cover: G77 is also held, so the cover is the WD rows (TASK-215/221/224), the TASK-228 runner under all 37 verbatim service directives in WSL, G17 |
| G77 | sandbox suite on hosted runners (TASK-230) | **NOT RUN** | VM hold: it runs only the held harness (lead's ruling). Cover: as G76 |
| G78 | runner security suite | unit part **PASS**; host part **NOT RUN** | Unit: CHK-M10-260/261 (TASK-213 checks; TASK-225 serve rows: expired, foreign, replayed, malformed, second frame, busy; TASK-217 wrong peer; TASK-222 capread names). The WSL unit row also refused root (closed, no frame), and `nobody` got EACCES (TASK-228). Host part (CHK-M10-280 to -289) NOT RUN: VM hold |
| G79 | first compliance run on `bitscan-u2404` against the WSL manager | **NOT RUN** | VM hold. Cover: the agent binary walk end to end (TASK-227, 120/120), the redaction rows (TASK-210 CHK-M10-020/080; TASK-224 CHK-M10-155) and the manager's M9 intake suites in G18 |
| CHK-M4-223 | `TestNoOtherJobSourceStatic` | **PASS** (rewritten) | User decision 2026-11-01 (2): rewritten as **CHK-M10-271**, with `runner.sock`/AF_UNIX only in `internal/agent/runnerclient`; 9/9 plants red (TASK-223 report). It was held FAIL before the decision; it is no longer FAIL |
| CHK-M4-100 (static), -344, -345 | `TestNoOtherProcessExecutionInAgent` | **PASS** (rewritten) | Found at this gate: it forbade the M10 process sites that REQ-256 allows. main's ruling: rewritten as **CHK-M10-272**, below; 4/4 plants red |
| Pre-existing M6 row | `check_runbook_text.py deploy/runbooks/agent-install.md` | pre-existing (not M10) | HEAD and M10 give the same 2 findings, both M6 placeholder lines in §3 Install: HEAD L76/L120 = M10 L79/L123 (`… password bse_REPLACE_WITH_THE_ENROLMENT_TOKEN`, `ENROL_TOKEN=bse_REPLACE_WITH_THE_ENROLMENT_TOKEN`). M10's sections (§1, §4, §6, §9–§11; 5 more sh blocks) add none. The checker isn't a CI gate for this file, and nothing was edited |

## Old → new check ids at this gate

| Old | New | Rule |
| --- | --- | --- |
| CHK-M4-223 | CHK-M10-271 | `runner.sock`, `"unix"`/`"unixgram"`/`"unixpacket"`, `net.UnixAddr`/`DialUnix`, `syscall/unix.AF_UNIX`/`Socket`/`Connect`/`Bind` and `golang.org/x/sys/unix` only in `internal/agent/runnerclient`; `net.Dial*` only in runnerclient and transport; `net.Listen*`/`FileListener`/`FileConn` nowhere. The exec-name and RunJob/Handle-caller assertions are kept. The test fails if the walk sees fewer than 2 runnerclient sites |
| CHK-M4-100 (static), -344, -345 | CHK-M10-272 | Per file and exact: `internal/inventory/command.go` has exactly one `exec.CommandContext` and the 3 #35 command literals; `internal/runner/spawn_linux.go` has exactly one `exec.Cmd` literal and `"/bin/sh"` and `"-c"` once each, with no `exec.Command*`; `internal/capread/serve_linux.go` has exactly one `exec.CommandContext` and no shell literal. `os/exec` is imported only by those three and `inventory/command_*.go`. Everything else is kept. Plants red: an exec in loops; a shell literal in capread; a second `CommandContext` in the runner; a second `exec.Cmd` literal in another runner file |
| CHK-M6-100 | CHK-M10-318 (+ new CHK-M10-319) | `check_debian_meta.py`: `X.Y.Z-R` or `X.Y.Z~preN-R` (N, R ≥ 1), and `release.yml` keeps its `*"~"*) … exit 1` guard (TASK-231 report) |
| CHK-M4-220, -221 | PD-45 rows | TASK-223 report |

## M10 mutation table (CHK-M10-320 to -393)

Each plant was made in a throwaway copy and turned its named check red for the planted reason. "VM half" rows are part of the named exception (NOT RUN, VM hold) and keep the unit-level red shown. Source is the TASK test report holding the evidence.

| CHK | Plant | Unit-level result | VM half | Source |
| --- | --- | --- | --- | --- |
| -320 | peer check removed | red (CHK-M10-118) | NOT RUN, VM hold | TASK-217 |
| -321 | gid compared, not uid | red | — | TASK-217 |
| -322 | second request frame run | red ("executor ran 2 times") | — | TASK-225 |
| -323 | `"command"` beside `job` accepted | red | — | TASK-209 (+ TASK-225 malformed rows) |
| -324 | inventory job accepted | red | — | TASK-209, TASK-213 |
| -325 | runner `agent_id` check removed | red | NOT RUN, VM hold | TASK-213 |
| -326 | `pickup_by` > 25 h accepted | red | — | TASK-213 |
| -327 | seen set removed | red | NOT RUN, VM hold | TASK-213 |
| -328 | `pickup_by` = now accepted | red | — | TASK-213 |
| -329 | `PR_SET_DUMPABLE` not set | red (unit) and red at binary level (TASK-228 `noharden`) | NOT RUN, VM hold | TASK-216, TASK-228 |
| -330 | fd 3 not CLOEXEC | red | NOT RUN, VM hold | TASK-217 |
| -331 | runner environment inherited | red (WD) | NOT RUN, VM hold | TASK-221 |
| -332 | `TMPDIR` added / `PATH` changed | red ×2 (WD) | — | TASK-221 |
| -333 | stdin inherited | red (WD) | NOT RUN, VM hold | TASK-221 |
| -334 | niceness not applied | red (WD) | NOT RUN, VM hold | TASK-221 |
| -335 | I/O class not applied | red (WD) | NOT RUN, VM hold | TASK-221 |
| -336 | plugin in `supervisor` | red (fake tree, WD spawn and job rows) | NOT RUN, VM hold | TASK-215, -221, -224 |
| -337 | no `cgroup.kill` at exit | red (fake tree, WD) | NOT RUN, VM hold | TASK-215, TASK-224 |
| -338 | sweep removed | red (fake tree, WD as bitscan-runner) | NOT RUN, VM hold | TASK-215, TASK-224 |
| -339 | sweep skips nested | red (fake tree, WD) | NOT RUN, VM hold | TASK-215 |
| -340 | statfs check removed | red (unit) | NOT RUN, VM hold (u2204 v1 boot) | TASK-216 |
| -341 | temp dir kept | red (WD spawn and job) | — | TASK-221, TASK-224 |
| -342 | private `/tmp` not emptied | red (WD job; binary level `notmp`) | — | TASK-224, TASK-228 |
| -343 | timeout not enforced | red (WD) | NOT RUN, VM hold | TASK-224 |
| -344 | redaction after truncation | red | G79 half NOT RUN, VM hold | TASK-210 |
| -345 | cut-off rule skipped without pattern 2 | red | — | TASK-210 |
| -346 | read limit or drain removed | red | — | TASK-214 |
| -347 | `truncated` not set on overflow | red | — | TASK-210 |
| -348 | cut splits a rune | red | — | TASK-210 |
| -349 | stderr cut sets `truncated` | red | — | TASK-210 |
| -350 | `Expand` replacement | red | — | TASK-210 |
| -351 | 51 patterns accepted | red | — | TASK-210, TASK-213 |
| -352 | bad pattern skipped | red | — | TASK-210, TASK-213 |
| -353 | empty-match pattern accepted | red | — | TASK-210 |
| -354 | growth guard removed | red | — | TASK-210 |
| -355 | signal → −1 | red | — | TASK-214 |
| -356 | job written to spool/state | red | — | TASK-212 (+ TASK-223/227 state greps) |
| -357 | raw output on redaction failure | red | — | TASK-214 |
| -358 | resend to a restarted runner | red ("2 runner requests, want 1"; unit), and green-guarded at binary level (walk `sigterm`) | — | gate plant (this report), TASK-223, TASK-227 |
| -359 | final for an interrupted job | red | — | TASK-212 (+ walk `sigterm`) |
| -360 | batch of 51 | red | — | TASK-220 |
| -361 | batch over 1,572,864 | red | — | TASK-220 |
| -362 | 409 retried | red | — | TASK-220 |
| -363 | 429 dropped | red | — | TASK-220 |
| -364 | newest dropped first | red | — | TASK-219 |
| -365 | dropped without a marker | red | — | TASK-219 |
| -366 | non-atomic spool write | red | — | TASK-212 |
| -367 | `spool_bytes` 0 | red | — | TASK-223 |
| -368 | start notice missing or late | red | — | TASK-220 |
| -369 | two jobs at once | red | — | TASK-223 |
| -370 | inventory waits for compliance | red at binary level (walk `invheld`: "inventory_uploaded_while_compliance_held" FAIL with both kinds on one worker) | — | gate plant (this report) |
| -371 | capread third name | red | NOT RUN, VM hold | TASK-222 |
| -372 | request text as an argument | red | — | TASK-222 |
| -373 | capread environment passed | red | NOT RUN, VM hold | TASK-222 |
| -374 | capread peer check removed | red | NOT RUN, VM hold (the WSL helper unit refused uid 997 and 0 on the real code, TASK-226) | TASK-222 |
| -375 | capread timeout 60 s | red | — | TASK-222 |
| -376 | capread cap removed / cut sent | red | — | TASK-222 (+ the TASK-226 client cap plant) |
| -377 | capread parallel | red | — | TASK-222 |
| -378 | `net.FileListener` outside sdsock | red (G8) | — | TASK-211 |
| -379 | `exec.Command` in `compliance.go` | red (G8) | — | TASK-211 (+ CHK-M10-271/272 plants) |
| -380 | agent imports runner/redact | red ×4 | — | TASK-227 |
| -381 | runner imports `net/http` | red ×2 | — | TASK-227 |
| -382 | runner logs a stdout canary | red (executor and serve halves) | canary sweep NOT RUN, VM hold | TASK-224, TASK-225 |
| -383 | agent logs a result's stdout | red ("a result's stdout was logged") | — | gate plant (this report) |
| -384 | heartbeat triggers the runner | red (CHK-M10-271 static) | — | TASK-223 |
| -385 | euid 0 accepted | red | — | TASK-216 |
| -386 | capability check removed | red (unit) | NOT RUN, VM hold | TASK-216 |
| -387 | one unit character changed | red ("DIFF bitscan-runner.service line 48") | — | gate plant (this report) |
| -388 | D-Bus policy allows `StartUnit` | red ("DIFF bitscan-runner.conf line 17") | NOT RUN, VM hold | gate plant (this report) |
| -389 | runner unit without `InaccessiblePaths=` | red ("DIFF bitscan-runner.service line 45") | NOT RUN, VM hold | gate plant (this report) |
| -390 | runner unit without `NoExecPaths=` | red ("DIFF bitscan-runner.service line 20") | NOT RUN, VM hold | gate plant (this report) |
| -391 | runner keeps running after the close | red (executor and serve halves) | NOT RUN, VM hold | TASK-224, TASK-225 |
| -392 | foreign result spooled | red | — | TASK-212, TASK-218 (+ TASK-223 r1 row) |
| -393 | `agent_id` read once | red | — | TASK-213 |

Summary: 74 rows (-320 to -393), all red at unit or binary level. The VM halves of -320, -325, -327, -329, -330, -331, -333 to -340, -343, -371, -373, -374, -386, -388 to -391 are NOT RUN (the named exception), along with the G79 half of -344 and the canary sweep of -382.

## NOT RUN at the M10 gate, with reason and cover

| Row | Reason | Cover |
| --- | --- | --- |
| G76 (sandbox suite on `bitscan-u2204`, `bitscan-u2404`), every CHK-M10-200 to -259 row | VM hold (safety check), the named exception (decisions 2026-11-01 (1)) | WD rows as bitscan-runner (TASK-215, -221, -224: 37/37). The TASK-228 runner under all 37 verbatim service directives and the 5 socket directives in WSL: caps 0x4, 8 parallel plugins, cgroup moves and kills, private `/tmp` only, SIGTERM sweep, peer refusal, EACCES for a non-member. The TASK-226 helper under all 23 verbatim directives (CapEff 0x40001000, real nft). G17 for the directives |
| G77 (TASK-230 sandbox CI) | VM hold: it runs only the held harness | as G76 |
| G78 host part (CHK-M10-280 to -289) | VM hold | G78 unit part (TASK-213/217/222/225) and the TASK-228 WSL row |
| G79 (first compliance run, CHK-M10-290 to -292) | VM hold | The agent binary walk (TASK-227, 120/120: end to end, runner absent → runner_unavailable, overflow), real-path redaction (TASK-224 CHK-M10-155), the M9 manager intake suites in G18 |
| VM halves of the mutation rows listed above | VM hold | each row's unit-level red |
| TASK-231 runbook walk (CHK-M10-315f, REQ-258 (1)) | VM hold | 23/23 quoted lines found in the code; the commands parse; the TASK-226/228 WSL rows saw the same lines |
| REQ-252 audit half (`auditctl -l` real output) | not possible in WSL: the kernel refuses audit netlink to the distro (root itself gets EPERM) | TASK-222 rows; the helper passes the exit status through (`failed 255`, the same as root); VM row (held) |
| TASK-229 hosted run on `ubuntu-22.04`/`ubuntu-24.04`; actionlint, shellcheck | no push in this session; tools not installed | the step scripts extracted and run end to end in WSL, with plants (TASK-229 report) |
| Binary-level plant of the TASK-221 r2 m0 lock | not reproducible: the real runner's m0 never took a start goroutine in 88 spawns | the unit-level plant `notestmainlock` is red, with m0 at nice 10 |
| Nightly end-to-end on three VMs, results views, CSV, re-evaluation, N/N−1 matrix | M11 (planned) | — |
| Load tests | deferred by the user | — |
| Debian 12, arm64 | not supported (decisions 2026-10-24) | — |
