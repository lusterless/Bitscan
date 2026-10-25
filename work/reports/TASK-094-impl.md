# TASK-094 IMPL: `os_info` collector and the fixed command runner

REQ-100. TS §3.4 (L232–L235, L238, L240), §6.5 L1186. #35, #77; lead rulings 2026-10-24 "TASK-094/095" Q1–Q5 (Q1 applies here) and "TASK-094 lead rulings" (1) G204, (2) size. **Two approvals (TS §8.2, agent).** No tests were run (tester's job).

## Lead rulings applied

1. **gosec G204** on `exec.CommandContext` in `command.go`: one scoped exclusion in `agent/.golangci.yml`, under `linters.exclusions.rules`: `path: ^internal/inventory/command\.go$`, `linters: [gosec]`, `text: G204`, with a comment giving the reason (paths and arguments come only from the fixed #35 list in that file, no shell). The pattern is anchored, so it matches that one file only (not `command_test.go` or any other path). No `//nolint` anywhere.
2. **Size:** stays one task at about 430 code lines (ruling (2)), now about 440 with `ReadOSRelease` below.

## Files

| File | What |
| --- | --- |
| `agent/internal/inventory/command.go` (new) | The fixed #35 command list (`hostnamectlCmd`, `ipAddrCmd`, `dpkgQueryCmd`, plus `dpkgFormat`) and `command.run`. `dpkgQueryCmd` is used by TASK-095's `dpkg.go`. |
| `agent/internal/inventory/osinfo.go` (new) | `CollectOSInfo(ctx) (wire.OsInfo, error)`, `ReadOSRelease(path)`, the #77 derivation, `fitRaw`, `compactSize`, `readSmall`. |
| `agent/internal/inventory/osinfo_linux.go` (new) | **Not in the task's file list.** `syscall.Uname` exists only on Linux, so the `uname` hook is set here, following the `watch.go` / `watch_linux.go` pattern. |
| `agent/.golangci.yml` (edited) | **Outside the task's file list and outside `agent/internal/inventory/`** (lead ruling (1)). One exclusion rule added; the reviewer checks it is no wider than the ruling. The tester should re-run `golangci-lint run ./...` from `agent/` (both GOOS) since the config affects every package. |

`watch.go` and `watch_linux.go` (impl-agent) are untouched.

## Behaviour (maps to the AC)

- **Commands (#35):** these are the only execs. `/usr/bin/hostnamectl` (no args, 5 s, 1 MiB). The first existing of `/usr/sbin/ip`, `/usr/bin/ip`, `/sbin/ip`, `/bin/ip` with `-j addr` (5 s, 1 MiB). `/usr/bin/dpkg-query -W -f=<TS §3.4 format>` (60 s, 16 MiB). There is no shell. `Env` is exactly `PATH=/usr/sbin:/usr/bin:/sbin:/bin` and `LC_ALL=C`, `Dir` is `/`, and stdin and stderr are `/dev/null`. Output past the cap cancels (kills) the process. `WaitDelay` is 1 s, so a grandchild holding stdout cannot keep the call past limit + 1 s. `uname -r -m` comes from `syscall.Uname`. `nproc` comes from `runtime.NumCPU()`, which honours the affinity mask.
- **Derivation (#77):** `os_id`, `os_version_id` and `os_pretty_name` come from `/etc/os-release` `ID`, `VERSION_ID` and `PRETTY_NAME`, parsed per os-release(5): quotes, and `\` escapes inside double quotes. `kernel_release` and `architecture` come from uname (`x86_64`). `memory_mb` is `MemTotal` kB / 1024, rounded down. `uptime_s` is the whole seconds of the first `/proc/uptime` field. `ip_addresses` holds every `addr_info[].local` + `/` + `prefixlen` across all interfaces; an item with no `local` is skipped, and a `local` with no `prefixlen` is sent bare.
- **`ReadOSRelease(path string) (osID, osVersionID, osPrettyName *string)`** (for TASK-098 enrolment, impl-agent's request): the same parser and the same `wire.Validate` bounds (32/16/128, identical to `EnrolRequest`). Each value is nil when the file is unreadable (or over 1 MiB), the key is absent, or the value is outside the contract. It executes nothing. `CollectOSInfo` uses the same method with `osReleasePath`.
- **`raw`:** `os_release` (all pairs), `hostnamectl` (`Key: value` pairs, trimmed), `meminfo` `{"MemTotal_kb": n}`, `ip_addr` (the parsed JSON, numbers kept as `json.Number`), and `errors` (always present, possibly `{}`).
- **Failures (#77 (d), (e); Q1):** a source that fails gets `raw.errors[<source>]`, where the source is `os_release`, `uname`, `meminfo`, `uptime`, `hostnamectl` or `ip_addr`, and its fields stay null. The value is one of the fixed reasons `not found`, `timed out`, `output too large`, `failed`, `unreadable` or `unparsable`. A value that fails its contract bound is checked with `wire.Validate` on a probe, left null, and recorded as `raw.errors[<field>] = "value outside the contract"`. `ip_addresses` is never null. When `ip` fails or is unparsable, when there are more than 256 addresses (`"more than 256 addresses"`), or when any address fails the pattern, it is `[]` with one reason in `raw.errors["ip_addresses"]`.
- **`raw` limits:** a raw entry the contract refuses where it sits in the body (U+0000, depth past 32 from the body root) is dropped with `"dropped: outside the contract"`. The check is `wire.Validate` on a probe `InventoryBody`. Then the largest entries are dropped (ties go to the lowest key) with `"dropped: raw over 256 KiB"` until compact JSON without HTML escaping is at most 262,144 bytes. That measure is never below the manager's `json.dumps(ensure_ascii=False)`.
- **Hang:** when a command reaches its limit it is killed, its source gets `timed out`, and collection continues. `CollectOSInfo` returns an error only when its own `ctx` ends.
- Supported hosts are Ubuntu 22.04 and 24.04 on amd64 (decisions 2026-10-24); Debian 12 rows of TP-M4-09 are NOT RUN (dropped by the user).

## Test hooks (in-package tests, `package inventory`)

Package variables the tester may substitute: `osReleasePath`, `meminfoPath`, `uptimePath`, `uname`, and `hostnamectlCmd` / `ipAddrCmd` / `dpkgQueryCmd` (fields `source`, `paths`, `args`, `limit`, `maxOut`). The constant `waitDelay` is 1 s. Production never changes any of them, and nothing in them comes from configuration, a job or the manager. `ReadOSRelease` takes its path as an argument, so an external test can call it directly.

## Checks run (Windows, golangci-lint 2.14.0)

- `gofmt -l agent`: nothing.
- `GOOS=linux go vet` and `GOOS=linux golangci-lint run` over every package except `internal/agent/enrol`: clean, 0 issues; the same lint on GOOS=windows: 0 issues. `internal/agent/enrol` is excluded only because impl-agent's in-progress `enrol.go` (TASK-098) does not compile yet; it is not part of this task.
- `CGO_ENABLED=0 GOOS=linux go build ./internal/inventory/`: ok.
- Builder checklist: item 11 (no output or secrets in logs or errors) holds, because no text from the host enters any error or reason. Items 1–10 and 12–13 are manager-side or not applicable.

## Round 1 fix (tester-m4b, CHK-M4-097: a grandchild of a killed command survived)

- **Cause:** `exec.CommandContext` kills only `cmd.Process`, and `WaitDelay` only closes the pipes (Go `os/exec` `watchCtx` and `Wait`). The same holds when the direct child exits by itself and leaves a background child.
- **Fix:** every command now leads its own process group (`SysProcAttr.Setpgid`). `cmd.Cancel`, used at the limit, on output overflow and when `ctx` ends, sends SIGKILL to the whole group (`kill(-pid)`). After `Wait`, the rest of the group is killed in every case, including a normal exit. ESRCH counts as "already gone". The group id stays reserved while any member lives, so the sweep cannot hit an unrelated process. `WaitDelay` (1 s) is kept. `setpgid` and `kill` are allowed by the unit's `SystemCallFilter=@system-service`.
- **Files:** `command.go` gained the `isolate` and `reap` hooks, called around `cmd.Run()` (about 8 lines). New **`agent/internal/inventory/command_linux.go`** (about 25 lines, outside the original file list, Linux-only like `osinfo_linux.go`) sets the hooks. On other systems the hooks do nothing.
- **Re-run:** `TestCommandHangIsKilled` (all subtests) and the command tests that share `run()`.
- Checks: gofmt clean; `GOOS=linux go vet ./internal/inventory/` clean; `CGO_ENABLED=0 GOOS=linux go build ./...` ok; `golangci-lint run ./internal/inventory/...` with GOOS=linux and windows: 0 issues.

## For the tester

TP-M4-09; mutation rows CHK-M4-344 (no `sh -c`) and CHK-M4-345 (no argument from a job or heartbeat field). The static check should find exactly one `exec.` call, in `command.go`.
