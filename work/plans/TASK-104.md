# TASK-104 plan: inventory collection, body, upload and the dpkg watcher

Covers TASK-091 (watcher), TASK-094 (`os_info` and commands), TASK-095 (dpkg parse, hash, body) and TASK-104 (upload loop). REQ-100 to REQ-102. Owner: impl-agent. **Two approvals.** Tests: TP-M4-06, 09, 10, 19; mutation rows CHK-M4-344, 345, 350 to 352. Blocked on **#35**, **#77**, **#80**; #72 is agreed.

## Spec quotes

- TS §3.4 L234–L235: `os_info` from "`/etc/os-release`, `uname -r -m`, `hostnamectl`, `/proc/meminfo`, `nproc`, `ip -j addr`, `/proc/uptime`"; packages from `dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${Status}\t${Source}\t${Installed-Size}\n'`.
- L238: "Collection runs in `bitscan-agent` (no root or runner needed)."
- L239: watch `/var/lib/dpkg/` (`IN_MOVED_TO`, `IN_CLOSE_WRITE` on `status`), "uploads an unscheduled snapshot, without `job_id`, when packages change, debounced to once per 10 min."
- TS §6.5 L1186: body shape and `list_sha256` definition.

## Commands (#35 recommendation; `inventory/command.go`)

| Purpose | argv (first existing path) | Limit |
| --- | --- | --- |
| host name details | `/usr/bin/hostnamectl` (plain status output, parsed; `--json` needs systemd 250, Ubuntu 22.04 has 249) | 5 s |
| addresses | `/usr/sbin/ip -j addr`, `/usr/bin/ip -j addr`, `/sbin/ip -j addr`, `/bin/ip -j addr` | 5 s |
| packages | `/usr/bin/dpkg-query -W -f=<TS §3.4 format>` | 60 s |

`uname -r -m` and `nproc` are read without exec (`syscall.Uname`, `runtime.NumCPU()` which honours the affinity mask as `nproc` does), giving the same values (#35 recommendation). Each command: `exec.CommandContext` with a fixed argv (no shell), `Env` = `PATH=/usr/sbin:/usr/bin:/sbin:/bin` and `LC_ALL=C`, stdin `/dev/null`, output capped (16 MiB for dpkg-query, 1 MiB otherwise), killed at its limit. No argument ever comes from a job, a heartbeat response or any manager answer.

## Field derivation (#77 recommendation)

| Field | From |
| --- | --- |
| `os_id`, `os_version_id`, `os_pretty_name` | `/etc/os-release` `ID`, `VERSION_ID`, `PRETTY_NAME` |
| `kernel_release`, `architecture` | `uname` release and machine (`x86_64`; amd64 only in v1) |
| `cpu_count` | `nproc` equivalent |
| `memory_mb` | `MemTotal` kB ÷ 1024, rounded down |
| `ip_addresses` | every `addr_info.local` with `/prefixlen` from `ip -j addr`, all interfaces including loopback, IPv4 and IPv6, at most 256 |
| `uptime_s` | first field of `/proc/uptime`, rounded down |
| `raw` | `{"os_release": {all key/value pairs}, "hostnamectl": {key: value}, "meminfo": {"MemTotal_kb": n}, "ip_addr": <parsed ip -j addr>, "errors": {source: fixed reason}}` |

A source that fails or times out leaves its fields `null` and adds a fixed reason under `raw.errors`. An `os_info` value that would fail the contract (too long, U+0000) is sent as `null` with a reason in `raw.errors`; `raw` entries that would break its limits (256 KiB, nesting) are dropped with a reason. Package rows are sent exactly as dpkg printed them (the agent never hides packages; a contract failure shows as a 422 and `last_error`).

## dpkg parsing and body (TASK-095)

Split on `\n`, then on `\t` into exactly 6 fields (a line with another count is a parse error for that line, reported in `raw.errors` count only). Empty `Source` → `null`; empty `Installed-Size` → `null`, else integer. `list_sha256`: lines `name\tversion\tarchitecture\tstatus\n`, encoded UTF-8, sorted with `bytes.Compare`, concatenated, SHA-256, lowercase hex. Body: compact JSON, gzip (default level), `Content-Encoding: gzip`.

## Watcher (TASK-091; #80 recommendation)

`syscall.InotifyInit1(IN_CLOEXEC)`, `InotifyAddWatch(dir, IN_MOVED_TO|IN_CLOSE_WRITE)`, filter on the name `status`. Debounce: a change starts a 60 s quiet timer (dpkg writes `status` many times per run); when it fires, signal once if 10 min 30 s have passed since the last unscheduled upload, otherwise when that hold-off ends. The margin covers the manager measuring the 10 minutes on its own clock. If the watch cannot be set (no directory, inotify limit), log once and carry on; scheduled inventory is unaffected.

## Upload loop (TASK-104)

`RunJob(jobID)`: collect, build, `PUT …/inventory?job_id=<id>`; Retry class → back-off and retry the same body for up to 30 minutes after the job was received (after that the manager has failed the job; give up and log). `Unscheduled()`: collect, build, `PUT …/inventory`; Retry class → back-off; a newer watcher signal replaces a pending one (the latest state is sent). Drop class (409, 413, 422) → `last_error`, no retry.
