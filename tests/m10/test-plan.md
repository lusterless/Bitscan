# M10 test plan (agent runner and sandbox)

Owner: `tester-m10` (Go unit, agent, race, fuzz, property and Linux suites, non-VM plants, the RE2 cross-check, the M10 gate report `work/reports/M10-gate-test.md`). Written 2026-10-30 from `work/tasks.md` "M10 agent runner and sandbox" (TASK-209 to TASK-231 acceptance tests, design notes D1 to D4, TP-M10-00 to TP-M10-24, gates G7–G11, G17, G35–G41, G71–G79, mutation table CHK-M10-320 to -393), `work/requirements.md` REQ-234 to REQ-263, `work/plans/M10-breakdown.md`, `TASK-209.md`, `TASK-210.md`, `TASK-212.md`, `TASK-215.md`, the approved answers in `work/open-questions.md` "M10" (#130 to #143, PD-41 to PD-45; #4, #28 to #31, #57, #60, #74, #78, #113, #114, #116 (a), #121, #124 (f) reused; `work/decisions.md` 2026-10-30 "M10 breakdown APPROVED") and the spec (TS §3.3 L202–L226, §3.4, §3.5 L248–L253, §3.6, §3.7 L271–L505, §6.5 L1157–L1190, §8.1, §8.3 L1271–L1283, §8.6 L1324–L1339). Written **before any M10 product code was read** (`agent/internal/runner/`, `redact/`, `spool/`, `sdsock/`, `capread/` did not exist when the expected values below were fixed). Names are the plans' interfaces; where the code names something differently the row keeps its expected value and the report names what it bound to. Results: [report.md](report.md) (folded by `main` from `work/reports/TASK-###-test.md` if the harness blocks the tester).

`ag/` means `agent/`. Sizes per #57: 1 MiB = 1,048,576; 64 KB = 65,536; 16 KB = 16,384; 1.5 MB = 1,572,864; 32 MiB = 33,554,432; 4 MiB = 4,194,304.

## VM and sandbox rows: NOT RUN (decisions 2026-10-30, "M10 VM sandbox work stopped by the safety check")

The safety classifier stopped the VM sandbox work before any boot, build or file write. Under the user's up-front rule (2) and the lead's ruling, **the sandbox harness (`ag/test/sandbox/`, `e2e/m10/first_run.sh`) is not built by anyone in this session**, and every row that needs it is recorded **NOT RUN, reason "safety-classifier refusal (VM sandbox)"**, with its lower-level cover named. This covers G76, G77 (TASK-230 only runs that harness), the host half of G78, G79, the 23 VM-planted mutation rows, and every CHK-M10-200 to -299 row. The rows are still defined below, from the acceptance criteria, so a fresh session or the user can run them. Owner: **open** (the lead decides). M10 does not merge while they are NOT RUN until the user decides whether they are a gate exception.

## Conventions

- Type: **CODE** = static gate, unit, race, fuzz or property test on the tree. **APP** = a built binary, or the real code against a real kernel facility (Unix sockets, cgroup v2 under `systemd-run`, real processes).
- Where:
  - **L**: Windows 11 + Git Bash, worktree `C:\Users\kaiquan.koh\Documents\Bitscan-m10`, Go 1.27.2 (`go version go1.27.2 windows/amd64`). Pure packages only: `runner/proto`, `redact`, `spool`, `agent/runnerclient` (if it builds on Windows), `agent/loops` with fakes.
  - **W**: WSL Ubuntu 24.04 (`wsl -d Ubuntu-24.04 -u root`, `MSYS_NO_PATHCONV=1`), Go `/opt/go1.27.2/bin/go` (= `agent/go.mod` `go 1.27.2`). Each run is in its own copy `/root/bstest-m10-<label>`: `agent/`, `docs/spec/`, `bits/samples/`, `manager/tests/contract/fixtures/` copied from the worktree. `-race` on every unit run, and every run under `timeout`.
  - **WD**: W under a delegated cgroup: `systemd-run --wait --pipe --collect -p Delegate=yes [-p User=…] <go test binary> -test.run …`. Checked 2026-10-30 in WSL: `stat -fc %T /sys/fs/cgroup` = `cgroup2fs`, systemd 255 is PID 1, and a `systemd-run -p Delegate=yes` unit sees its own `cgroup.kill`. The delegated-cgroup rows therefore run in WSL, not only in CI.
  - **CI**: GitHub Actions only.
  - **VM**: NOT RUN (see above).
- Python rows (the RE2 cross-check) run on W only: `/root/venv-m10` with `pip install --require-hashes -r manager/requirements-dev.txt`, `CI=true`, nothing skipped.
- **Exec counter**: a test double that counts calls. The serve loop is tested with a fake `Executor` that counts `Run`; the real executor with a counting `Spawn` func. "Exec counter 0" means the double saw no call, and on Linux rows also that no child process of the test binary appeared (a `/proc` scan for children before and after).
- **Canary**: `M10CANARY-<random hex>`, placed in an `execute`, a redaction pattern, a plugin's stdout and stderr, and a token. "Leaves no trace" means absent from every captured `slog` record (message and attributes), stderr of a built binary, error strings, and every file under the state or spool directory.
- **Time**: never waited out (decisions 2026-10-26). The agent uses its `schedule.Clock` fake and the runner an injected clock. Races are driven by barriers or channels, never by sleeps. Wall time is measured only where the spec gives one: plugin timeouts (`timeout_s` 2 killed within 3 s), the 1 s cancel bound of TASK-225, and the 5 s SIGTERM bound of TASK-227.
- **Planted violations** are made in a throwaway copy (`/root/bstest-m10-mut-<id>` on W), never in the worktree. The unmodified copy goes green first. "Red" means a non-zero exit **and** the named test fails for the planted reason.
- **Results are totals**: `passed/total`, plus failed, errors and skipped. A failing test is re-run alone by name after the fix, as its own row (`1/1 passed`).
- Every expected value comes from the spec or an approved answer, never from the implementation. Behaviour the spec and answers leave open is **recorded, not asserted**, and listed under "Questions".

## Expected values (spec and approved answers)

| Item | Expected | Source |
| --- | --- | --- |
| Frame | 4-byte big-endian unsigned length, then one compact UTF-8 JSON object; request length 1–33,554,432, reply 1–1,048,576; 0 or over the cap → refused after reading only the 4 header bytes | #130 (b); REQ-234 |
| Request | exactly `{"v": 1, "job": <TS §6.5 Job, strict, #60 bounds, kind compliance>, "max_parallel_plugins": 1–8}`; unknown keys at any level refused; no other request type | #130 (c); REQ-234 (2) |
| Replies | `{"type":"accepted"}`, `{"type":"refused","reason":<word>}`, `{"type":"result","result":<Results item>}`, `{"type":"done"}`; each shape strict | #130 (d) |
| Reason words (13) | `busy`, `malformed`, `not_compliance`, `bad_plugins`, `bad_parallel`, `bad_patterns`, `agent_id_unreadable`, `foreign_agent`, `pickup_passed`, `pickup_too_far`, `replayed`, `seen_full`, `internal` | #130 (d) |
| Exchange order | exactly one `accepted` or `refused`; after `accepted`, one `result` per plugin in completion order, then `done`; the runner closes after `refused` or `done`; a second request frame is never read | #130 (e); REQ-261 |
| Deadlines | runner: request within 30 s, else close; a reply that can't be written in 60 s cancels the job. Agent: 30 s from connect to the first reply, then max(`timeout_s`) + 30 s between replies | #130 (f) |
| Busy | a second connection while a job runs → `refused busy` at once; the agent retries every 2 s for up to 30 s, then `refused_busy` | #130 (g) |
| Result item caps | stdout ≤ 65,536 and stderr ≤ 16,384 UTF-8 bytes; `error` ∈ {null, `spool_overflow`, `runner_unavailable`}; when `error` is set, `exit_code` null and both streams empty; valid UTF-8 | REQ-234 (3); #116 (a) |
| `runner_unavailable` item (agent fill) | `exit_code` null, `stdout` and `stderr` "", `timed_out` and `truncated` false, `started_at` = `finished_at` = the agent's time | #131 (b) |
| `spool_overflow` marker | same `plugin_uuid`, `started_at`, `finished_at`; `exit_code` null; streams ""; `timed_out`, `truncated` false; `error: "spool_overflow"` | #140; REQ-248 |
| Check order (runner) | decode → kind → shape → patterns → `agent_id` → `pickup_by` → seen | #132 (e) |
| Shape | 1–5,000 plugins; `plugin_uuid`s distinct regardless of case (`bad_plugins`); `timeout_s` 1–600 (`bad_plugins`); `max_parallel_plugins` 1–8 (`bad_parallel`); patterns per REQ-244 (`bad_patterns`); empty pattern list allowed | #132 (d) |
| `agent_id` file | `/var/lib/bitscan-agent/agent_id`, read for every job; one trailing LF removed; must be a UUID; compared without regard to case; missing, unreadable or malformed → `agent_id_unreadable` | #132 (a) |
| Pickup window | `now < pickup_by ≤ now + 25 h` (runner clock) | #132 (b); TS L212 |
| Seen set | in memory; an id is added once its request decodes, refused or not; kept until `pickup_by` + 1 min; at most 100,000 ids; when full, new jobs are refused `seen_full` | #132 (c) |
| Redaction read | 1,048,576 bytes kept per stream; the rest read and discarded (the writer never blocks); `Overflow` = more was produced | #134 (a), (b) |
| Redaction order | invalid UTF-8 runs → one U+FFFD each (U+0000 kept); job patterns in list order, each whole match → literal `[REDACTED]` (no `$1` expansion); then the cut-off key rule; then cut at the last rune boundary ≤ cap | #134 (c), (d), (g); #133 |
| Cut-off rule | after the patterns: the first `-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----` with no `-----END [A-Z0-9 ]*PRIVATE KEY-----` after it → everything from its start to the end of the buffer becomes one `[REDACTED]`; complete blocks are left to the patterns; applies whatever the list holds | #133 |
| `truncated` | stdout only: true if more than 1 MiB was produced or the redacted text was cut; cutting stderr sets nothing | #113; #134 (g) |
| Growth guard | an intermediate result over 4,194,304 bytes → the whole stream is `[REDACTED]` (stdout: `truncated` true) | #134 (f) |
| Pattern refusal | > 50 entries, an entry Go `regexp` can't compile, or one that can match the empty string → `bad_patterns`, nothing runs | #134 (e); REQ-244 |
| Exit code | exit status; a signal death is 128 + signal (SIGKILL 137, SIGTERM 143, SIGSEGV 139); a timeout gives 137 and `timed_out` true; never negative | #114; #136 (e) |
| Plugin environment | argv `["/bin/sh", "-c", execute]`; `Env` exactly `["PATH=/usr/sbin:/usr/bin:/sbin:/bin"]` (no `TMPDIR`); stdin `/dev/null`; only fds 0, 1, 2; niceness 10; I/O class idle; working directory a fresh empty 0700 `/tmp/bitscan-p-<random>`; no `Pdeathsig` | TS L249; #135 (a); #136 (b), (c) |
| cgroups | own cgroup from the single `0::` line of `/proc/self/cgroup`; `supervisor` leaf with the runner in it; each plugin in a fresh `p-<n>` child, born there; on exit or timeout, `cgroup.kill` → wait for `populated 0` (≤ 5 s) → rmdir → temp dir removed; after each job and at start-up, a sweep of the whole subtree except the runner (pidfd SIGKILL in `supervisor`); runner moved back to `supervisor` if a plugin moved it; private `/tmp` and `/var/tmp` emptied after each job | #136 (a); #138; #135 (c) |
| Start-up refusals (runner) | `PR_SET_DUMPABLE` 0 first; then exit 1 with one log line when: euid 0; `CapEff` or `CapBnd` not a subset of `0x4` (`CAP_DAC_READ_SEARCH`); statfs of `/sys/fs/cgroup` not `CGROUP2_SUPER_MAGIC` (0x63677270); `/proc/self/cgroup` not exactly one `0::` line; own cgroup has no `cgroup.kill` or refuses `supervisor`; the `LISTEN_*` checks fail | #137; REQ-237 |
| Socket activation | `LISTEN_PID` = own pid; `LISTEN_FDS` = 1; fd 3 an `AF_UNIX` `SOCK_STREAM` socket in listening state; every inherited fd > 2 close-on-exec; the peer's `SO_PEERCRED` uid must equal the expected uid (runner: `bitscan`; capread: `bitscan-runner`), else closed unread with one log line naming the uid | REQ-235; #130 (j) |
| Spool | `spool/<job_id>/job.json` manifest (job id, received time, plugin uuids, `start_acked`, `finished`, `interrupted`, `final_acked`; never a command, pattern or evaluation data) and `spool/<job_id>/<seq>.json` items; files 0600, dirs 0700; atomic (tmp + fsync + rename + dir fsync) through `os.Root`; size = sum of file bytes vs `spool_max_mb` × 1,048,576 = `spool_bytes`; order: jobs by received time then job id, items by seq; reopen marks unfinished jobs interrupted (never a final batch); jobs received more than 7 days ago dropped with a log line and `last_error` | #139; REQ-247 |
| Overflow | oldest full results first (across jobs) → markers until the new item fits; else the new item is stored as a marker; markers count; if markers alone exceed the bound, the oldest markers are dropped with a log line; items in an in-flight batch are not converted | #140; REQ-248 |
| Sender | start notice `{"results": [], "final": false}` first; batches ≤ 50 items and ≤ 1,572,864 bytes of uncompressed JSON; always gzip with `Content-Encoding: gzip`; sent at 50 items or the size bound, 30 s after the oldest unsent item, or at job end; final batch `final: true` (empty if everything was already accepted); one sender, in order; 400/404/409/413/422 and 403 other than `pending_approval` drop that batch only, log and set `last_error`; 401 stops every loop; 403 `pending_approval`, 429, 5xx and network errors keep it and back off 10 s → 5 min | #139 (e); #141; TS L224, L226; REQ-246 |
| Agent failure words | `last_error` = `runner_unavailable: <word>`, word ∈ {`connect`, `timeout`, `broken`, `protocol`, `refused_<reason>`}; sent once, then cleared (#78 (e)) | #131 (c) |
| Unavailable kinds | connect error; no first reply in 30 s; any `refused` (busy only after 30 s); EOF before `done`; a reply deadline passing; a frame or item that fails decoding; a `result` for a plugin not in the job or already received | #131 (a) |
| Agent stop mid-job | no final batch and no `runner_unavailable` fill for that job; spooled results still sent after restart | #131 (d) |
| capread | request `name\n`, ≤ 32 bytes, read within 5 s; names exactly `nft_ruleset` → `/usr/sbin/nft -j list ruleset`, `audit_rules` → `/usr/sbin/auditctl -l`; empty `Env`; 10 s timeout; 1 MiB cap. Reply `ok\n` + stdout, or one line `error <word>` (`unknown_request`, `not_installed`, `timeout`, `too_large`, `failed <exit code>`); stderr never sent; over 1 MiB → `error too_large` with none of the output; one request at a time; peer uid `bitscan-runner` only | #142; REQ-252 |
| capread client | exactly one argument, one of the two names; stdout copied, exit 0 on `ok`; one line `bitscan-capread: <word>` on stderr and exit 1 on `error`, a missing socket (`not enabled`) or 30 s without an answer; any other argument list exits 2 without connecting; `--serve` needs valid `LISTEN_*` | #142 (f), (g); REQ-253 |
| Default patterns | the five lines of the `text` block after "**Default redaction patterns**" in TS §8.6, extracted at test time | TS L1329–L1337; REQ-243 |
| Package version | `0.2.0~pre1-1` | PD-42 |

## Gate map

| Gate | Checks | Where |
| --- | --- | --- |
| G7 gofmt, G8 golangci-lint, G9 `go mod verify`, G10 static build, G11 nolint grep | CHK-M10-300 to -304 (TP-M10-04); plants -378, -379 and the TP-M10-04 extras | W, CI |
| G17 units verbatim + `systemd-analyze verify` | CHK-M10-305; plants -387 to -390 (unit level) | W, CI |
| G35, G36 contract and agent security | CHK-M10-306, -307, -270 to -279 | L, W, CI |
| G37–G40 lintian, maintainer scripts, reproducible build, SBOM | CHK-M10-308 to -311 | W, CI |
| G41 inventory chain against the real manager | CHK-M10-312 | W |
| G71 redaction | CHK-M10-011 to -024, -080 to -086, -090 | L, W, CI |
| G72 runner Linux suites | CHK-M10-035 to -050, -100 to -136, -147 to -175, -188 to -195 | W, WD, CI |
| G73 agent suites | CHK-M10-025 to -034, -051 to -079, -182 to -187 | L, W, CI |
| G74 capread | CHK-M10-137 to -146, -176 to -181 | W, CI |
| G75 protocol and import boundary | CHK-M10-001 to -010, -196 to -199 | L, W, CI |
| G76 sandbox on VMs | CHK-M10-200 to -259 | VM: **NOT RUN** (safety-classifier refusal) |
| G77 sandbox on hosted runners | CHK-M10-200 to -259 | CI: **NOT RUN** (waits on the same harness) |
| G78 runner security | unit part CHK-M10-260 to -269; host part CHK-M10-280 to -289 | unit: L, W; host: **NOT RUN** |
| G79 first compliance run | CHK-M10-290 to -299 | **NOT RUN** |

## TP-M10-01 Harness (tester-m10's part)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-H01 | CODE | Fake runner for the agent tests: a Unix socket in `t.TempDir()` that speaks the #130 frames (scripted replies: accepted, refused `<word>`, N results, done, EOF after k, an oversize or malformed frame, silence, busy n times) and records every request it receives | W (L if `AF_UNIX` works on Windows Go) |
| CHK-M10-H02 | CODE | Fake executor and counting `Spawn` for the runner tests (the exec counter) | L, W |
| CHK-M10-H03 | CODE | Redaction corpus `ag/internal/redact/testdata/` (fixtures with expected outputs) and the shared corpus `manager/tests/contract/fixtures/redaction/corpus.json` (inputs, plus the expected match byte spans per default pattern) | L, W |
| CHK-M10-H04 | CODE | TS extraction helper (Go): reads `docs/spec/Technical_Specification.md`, takes the `text` fence after "**Default redaction patterns**", returns the five lines; fails if it doesn't find exactly 5 | L, W |
| — | — | The driver, probe, VM runner, planted listeners and `e2e/m10/first_run.sh` are **not built** (safety-classifier refusal; not re-delegated) | — |

## TP-M10-02 Protocol (TASK-209; REQ-234) — `ag/internal/runner/proto/proto_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-001 | CODE | Round trips: a request; `accepted`; `refused` with each of the 13 words; `result` (with and without `error`, `exit_code` null and set, multi-byte text); `done`. Each decodes to an equal value. The frame header is the body length, big-endian, and the body is compact JSON (no whitespace outside strings) | L, W |
| CHK-M10-002 | CODE | REQ-234 (1): each compliance job from `manager/tests/contract/fixtures/jobs/response_valid_*.json` is carried unchanged: request → frame → request gives a `job` whose JSON equals the fixture job's JSON (key-order-free deep equal) | L, W |
| CHK-M10-003 | CODE | REQ-234 (2), request refusals at decode: an unknown key at the top (`"command"` beside `"job"`), in the job, in a plugin; `v` 0, 2, `"1"`, `1.0`, missing; `max_parallel_plugins` missing, 0, 9, −1, `"2"`, 1.5, null; `job` missing or null; an inventory job; two JSON values in one frame (`{…}{…}`, `{…} 1`); a JSON array or string instead of an object; a case-variant key (`"V"`, `"Job"`). `RefusalFor` gives `not_compliance` for the inventory job and `malformed` for every other case, including `max_parallel_plugins` 0 and 9 and out-of-bound plugins (Q1). Recorded, not asserted: invalid UTF-8 inside a string, duplicate keys, trailing whitespace | L, W |
| CHK-M10-004 | CODE | Frame bounds: header 33,554,433 (request) and 1,048,577 (reply) are refused after reading **exactly 4 bytes** (a reader that fails the test on any further read); header 0 refused; a header of 2 bytes then EOF; a header announcing 100 then 50 bytes then EOF; all refused. A header of exactly 33,554,432 (1,048,576 for a reply) is not refused as oversize (the body is read, then judged as JSON) | L, W |
| CHK-M10-005 | CODE | Reply refusals: unknown `type`; extra key in each of the four shapes; `refused` with a word not in the list, or without `reason`; `result` without `result`; an unknown key inside the result item; `accepted` with a `reason` | L, W |
| CHK-M10-006 | CODE | REQ-234 (3), by both `NewResult` and the reply decoder (frame built by hand): stdout 65,536 bytes accepted, 65,537 refused (ASCII, and multi-byte, e.g. 21,845 × `€` + 2 bytes); stderr 16,384 / 16,385; `error` `"timeout"`, `""` refused; `error` set with `exit_code` not null, or with a non-empty stream, refused; invalid UTF-8 refused by `NewResult` | L, W |
| CHK-M10-007 | CODE | `Result` has no exported field (reflection); `Item()` returns a copy (changing the returned item leaves the `Result` unchanged); the zero `Result` is not accepted by whatever consumes it (recorded) | L, W |
| CHK-M10-008 | CODE | `UnavailableResult(uuid, now)` equals the #131 (b) item exactly; `OverflowMarker(r)` equals the #140 marker (uuid and times kept); both pass `NewResult` | L, W |
| CHK-M10-009 | CODE | REQ-234 (4), API listing via `go/types` over the package: no exported function or method takes a parameter of type `string`, `[]string` or `[]byte` (named string types of `wire` and `proto` itself are listed and judged one by one); `Request` has exactly the fields `V`, `Job` (`wire.Job`), `MaxParallelPlugins`; there is no exported function that builds a request from anything but a `wire.Job` | L, W |
| CHK-M10-010 | CODE | REQ-234 (5), purity: `go list -deps ./internal/runner/proto` holds only the standard library and `internal/agent/wire`, with no `os/exec`, `syscall`, `net`, `golang.org/x/sys`; tests pass with `GOOS=windows` (L) and on Linux (W). The exported reason constants are exactly the 13 words. Decode errors for a frame with a canary in an unknown key don't contain the canary | L, W |

## TP-M10-03 Redaction (TASK-210; REQ-242, REQ-243, REQ-244) — `ag/internal/redact/redact_test.go`, `manager/tests/test_redaction_crosscheck.py`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-011 | CODE | Constants: `ReadLimit` 1,048,576, `StdoutCap` 65,536, `StderrCap` 16,384, `GrowthLimit` 4,194,304, `MaxPatterns` 50, `Marker` `[REDACTED]` | L, W |
| CHK-M10-012 | CODE | REQ-244 (1) `Compile` refusals: 51 valid patterns (`ErrTooMany`); `(`; `a{1001}`; `\C`; `x*`; `(?:)`; `a?`; `\b`; `^`; also `$`, `\B`, `\z`, `\A`, `(a\|)`, `a{0,3}`, `(a*)+`, `(?i)`, `""`, `(?m)^$`, `[a-z]*`. Each is refused, with the index of the failing entry; the error text contains no pattern text (canary pattern `M10CANARY(`) | L, W |
| CHK-M10-013 | CODE | REQ-244 (2) accepted: 50 valid patterns; the five TS defaults; `[]`; nil; `a+`, `[a-z]`, `.`, `(?s).`, `ab\|c`, `\d+`, `a(b*)`, `a{1,3}`, `\bx` | L, W |
| CHK-M10-014 | CODE | REQ-243 (1) fixtures with the TS-extracted defaults, exact expected text: shadow line `root:$6$salt$hash…:19000:0:99999:7:::` → `root:[REDACTED]:19000:0:99999:7:::`; a full PEM RSA key between two lines → the lines kept, the block `[REDACTED]`; a cut-off PEM key (no END) → prefix + `[REDACTED]`; a full OpenSSH key → `[REDACTED]`; `password=hunter2` → `[REDACTED]`; `api_key: abc` → `[REDACTED]`; `Token = x`; `SECRET:y`; `bsa_`, `bse_`, `bsu_`, `bsk_` + 43 base64url chars → `[REDACTED]`; `AKIAIOSFODNN7EXAMPLE`, `ASIA` + 16 → `[REDACTED]`. Unchanged: `install ok installed`, `PasswordAuthentication no`, `passwd: files`, every `ExpectedResult` text of `bits/samples/*.bit` (XML parsed at test time) | L, W |
| CHK-M10-015 | CODE | REQ-243 (2): the extracted list has 5 entries and compiles in Go. In Python (W), the TS-extracted list equals byte for byte the default seeded by `m0005_privileges_seeds.py` and the settings default | L, W |
| CHK-M10-016 | CODE | REQ-243 (3) shared corpus: for every input in `corpus.json`, Go `regexp` `FindAllIndex` per default pattern equals the recorded spans (Go suite), and `google-re2` (`re2` module, on the UTF-8 bytes) gives the same spans (`test_redaction_crosscheck.py`). Inputs include multi-byte text next to `\b`, `(?i)` with `ſ` (U+017F) and `K` (U+212A, Kelvin), CRLF line ends, NUL and U+FFFD. A Go/RE2 difference is reported to `main`, not adjusted | L, W |
| CHK-M10-017 | CODE | Order and literal replacement: REQ-242 (5) `(a)(b)` on `ab` → `[REDACTED]`; pattern `a` on `a$1` → `[REDACTED]$1`; list order is applied over the previous result (`ab` then `\[REDACTED\]` gives `[REDACTED]` twice-redacted to `[REDACTED]`; the reverse order differs) | L, W |
| CHK-M10-018 | CODE | #133 cut-off rule with the empty list: `x\n-----BEGIN RSA PRIVATE KEY-----\nMIIE…` (no END) → `x\n[REDACTED]`; the same for `OPENSSH`, `EC`, `ENCRYPTED` and bare `PRIVATE KEY`; a complete block alone is unchanged; complete block + later cut block → the first kept, the second from its BEGIN to the end redacted; `BEGIN PUBLIC KEY` and `BEGIN CERTIFICATE` without END unchanged; BEGIN A, BEGIN B, END B → unchanged (A has an END after it: the #133 definition, recorded) | L, W |
| CHK-M10-019 | CODE | REQ-242 (2): BEGIN 100 bytes before 1 MiB, END beyond the read limit (`Data` = the first 1,048,576 bytes, `Overflow` true), with and without default pattern 2 → no key body byte in the output, `truncated` true | L, W |
| CHK-M10-020 | CODE | REQ-242 (1) and CHK-M10-344: a `bsa_` token at byte 65,530 of a 200 KB stdout (filler with no `b`) → output ≤ 65,536 bytes and no prefix of the token of length ≥ 2 (`bs`, `bsa`, `bsa_` …) appears; the same with a token straddling 65,536 (65,520–65,563); `truncated` true | L, W |
| CHK-M10-021 | CODE | REQ-242 (3) caps: 65,536 ASCII → unchanged, false; 65,537 → 65,536, true; 32,769 × `é` → 65,536 bytes, valid, true; 21,846 × `€` → 65,535 bytes, true; 16,385 × 4-byte emoji → 65,536; stderr 16,385 → 16,384, `truncated` false; stderr 8,193 × `é` → 16,384, valid. Every output ends on a rune boundary (CHK-M10-348) | L, W |
| CHK-M10-022 | CODE | REQ-242 (4): a run `\xff\xfe\xfd` → one U+FFFD; U+0000 kept; `password=\xffabc` → `[REDACTED]`; 65,535 ASCII + `\xff` (no overflow) → U+FFFD makes 65,538 → cut to 65,535, `truncated` true; for each, `json.Marshal` then decode gives a string ≤ cap in UTF-8 bytes | L, W |
| CHK-M10-023 | CODE | REQ-242 (6) and CHK-M10-347: 1 MiB of `a` with `Overflow` true and pattern `a+` → `[REDACTED]`, `truncated` true; short data with `Overflow` true → true; stderr with `Overflow` true → false (CHK-M10-349) | L, W |
| CHK-M10-024 | CODE | REQ-242 (7) growth guard: `[a-z]` then `[A-Z]` on 1 MiB of letters → exactly `[REDACTED]`, `truncated` true; boundaries with pattern `a` (×10 growth): 419,430 `a` + `zzzz` (intermediate exactly 4,194,304) → no guard (cut, true); + `zzzzz` (4,194,305) → guard; stderr guard → `[REDACTED]`, false. Heap growth across one `Apply` stays under 64 MiB (`runtime.ReadMemStats`, recorded with the value) | L, W |

## TP-M10-04 Lint plants and `go mod verify` (TASK-211; REQ-256) — evidence only, no tree file

Rows CHK-M10-300 to -304 (gate rows below) on the TASK-211 tree, plus these plants, each in a throwaway copy, with `golangci-lint run --uniq-by-line=false --max-same-issues=0 ./...` on Linux (W, v2.14.0): red for `exec.Command` in `internal/agent/loops/compliance.go` (CHK-M10-379); `net.FileListener` in `internal/runner/serve.go` (CHK-M10-378) and in `internal/sdsock/peer_linux.go`; `os.StartProcess`, `syscall.ForkExec`, `syscall.Exec`, `syscall.StartProcess`, `unix.Exec`, an `*exec.Cmd` type use, `net.Listen`, `unix.Socket` elsewhere; `os/exec` in any `internal/inventory` file other than `command.go` and `command_linux.go` (lead's note); a bare `// nolint`. Green controls: `net.FileListener` in `internal/sdsock/listen_linux.go`; `exec.Command` with a variable in `internal/runner/spawn_linux.go` and `internal/capread/serve_linux.go`; `*exec.Cmd` in `internal/inventory/command_linux.go`. G9: one character changed in the `golang.org/x/sys` `h1:` line, with a **cold** `GOMODCACHE`, makes `go mod download` fail (lead's note: a warm-cache `go mod verify` stays green, which is recorded). PD-41: `golang.org/x/sys` is a pinned direct requirement, and `cmd/bitscan-agent` does not link the module.

## TP-M10-05 Spool store (TASK-212; REQ-247) — `ag/internal/spool/spool_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-025 | CODE | REQ-247 (1): after every `StartJob`, `Put`, `Ack`, `Drop`, `Finish`, `Size()` equals the sum of the byte sizes of every file under the spool directory (walked); listing returns items in seq order | L, W |
| CHK-M10-026 | CODE | Order: jobs by received time then job id (two jobs with the same fake time ordered by id); items by seq; `Next` never hands out an item that is in flight | L, W |
| CHK-M10-027 | CODE | Start notice and final: a fresh job yields `{Start}` first; after `Ack`, its items; after `Finish`, the last items batch carries `Final`, or an empty `{Final}` batch if no items are left; nothing after `FinalAcked`; the job directory is removed when empty and (final acked or interrupted) | L, W |
| CHK-M10-028 | CODE | REQ-247 (2) crash states, reproduced on disk and then reopened: a partial `.tmp` item; a complete `.tmp` not renamed; a truncated `<seq>.json` (planted); a partial `job.json.tmp`. Reopen never yields a partial item. Leftover `.tmp` files are deleted and not counted in the size; a truncated item file is refused (dropped with a log line), never posted | L, W |
| CHK-M10-029 | CODE | REQ-247 (3): close and reopen → pending items in the same order; a job with `finished` false becomes `interrupted`, its items are still offered, and no `Final` batch ever comes (CHK-M10-359) | L, W |
| CHK-M10-030 | CODE | REQ-247 (4): a job received 7 d + 1 s before reopen is dropped (returned in `Dropped`, size reduced, log line, no item offered); 7 d − 1 s kept; exactly 7 d recorded | L, W |
| CHK-M10-031 | CODE | REQ-247 (5) and CHK-M10-356: after a job whose `execute` and pattern hold canaries, no spool file contains either (the API takes only uuids and `proto.Result`) | L, W |
| CHK-M10-032 | CODE | REQ-247 (6): files 0600, directories 0700 (W only) | W |
| CHK-M10-033 | CODE | REQ-247 (7): a symlink planted as `spool/<job>` or `spool/<job>/<seq>.json`, pointing outside the spool directory, is never written through (the target is unchanged, and the call errors or skips) | W |
| CHK-M10-034 | CODE | `Put` for an unknown job is refused; until TASK-219, an over-bound `Put` answers `ErrFull`; `Drop` of a batch removes only that batch and later batches are still offered (#139 (e)); a race of `Put`, `Next`, `Ack` from 8 goroutines under `-race` keeps the size equal to the disk size | L, W |

## TP-M10-06 Runner job checks (TASK-213; REQ-236, REQ-244) — `ag/internal/runner/checks_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-035 | CODE | REQ-236 (1) table (fake clock, temp `agent_id` file): foreign `agent_id` → `foreign_agent`; `pickup_by` = now and now − 1 s → `pickup_passed`; now + 25 h + 1 s → `pickup_too_far`; a replayed id → `replayed`; an inventory job → `not_compliance`; 0 and 5,001 plugins, a duplicate `plugin_uuid` (also differing only in case), `timeout_s` 0 and 601 → `bad_plugins`; `max_parallel_plugins` 0 and 9 → `bad_parallel`; a missing, empty or non-UUID `agent_id` file → `agent_id_unreadable` | L, W |
| CHK-M10-036 | CODE | Accepted: `pickup_by` = now + 25 h exactly; `agent_id` uppercase in the job; the file with one trailing LF; uppercase file content; a fresh id; an empty pattern list. Refused `agent_id_unreadable`: file with two LFs, CRLF, a leading space, or a 32-hex form | L, W |
| CHK-M10-037 | CODE | Fixed order (#132 (e)): inventory + bad parallel → `not_compliance`; bad plugins + bad patterns → `bad_plugins`; bad patterns + foreign → `bad_patterns`; foreign + expired → `foreign_agent`; unreadable file + expired → `agent_id_unreadable`; expired + replayed → `pickup_passed` | L, W |
| CHK-M10-038 | CODE | REQ-236 (3): a refused id is recorded as seen, so the same id resent correct is refused `replayed` | L, W |
| CHK-M10-039 | CODE | REQ-236 (4) seen bound: 100,000 distinct accepted ids, then a new one → `seen_full`; after the clock passes `pickup_by` + 1 min of the oldest ids, a new job is accepted again. At `pickup_by` + 1 min − 1 ns an id is still present (indirectly through the bound: 100,000 kept). A `seen_full` refusal does not record its id: the same job, resent once space frees, is accepted (Q2) | L, W |
| CHK-M10-040 | CODE | REQ-244 (1), (2) through the checks: each CHK-M10-012 pattern list → `bad_patterns`; each CHK-M10-013 list accepted | L, W |
| CHK-M10-041 | CODE | CHK-M10-393: the `agent_id` file is changed between two checks → the second uses the new content; deleted → `agent_id_unreadable` | L, W |
| CHK-M10-042 | CODE | Logs: a refused job logs `job_id` and the word only; no execute, pattern or agent-id-file canary in any record; the checks use only the injected clock (no `time.Now` in `checks.go`: static scan) | L, W |
| CHK-M10-043 | CODE | Concurrent checks of the same new id from 16 goroutines at a barrier → exactly one accepted, 15 `replayed` (`-race`) | L, W |

## TP-M10-07 Capture and result (TASK-214; REQ-241, REQ-242) — `ag/internal/runner/capture_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-044 | CODE | `Capture` over an `os.Pipe`: a writer of 3 MiB finishes (never blocked) and `Data` is exactly the first 1,048,576 bytes, `Overflow` true; exactly 1 MiB → `Overflow` false; 1 MiB + 1 → true; empty → empty, false (CHK-M10-346) | L, W |
| CHK-M10-045 | CODE | Both pipes at once: a process writing 3 MiB to stderr then 3 MiB to stdout finishes when both are captured concurrently (bounded by a 30 s test timeout, which is not a spec time) | W |
| CHK-M10-046 | CODE | REQ-241 (1) exit mapping: 0, 1, 126, 127, 255 → themselves; SIGKILL 137, SIGTERM 143, SIGSEGV 139 (portable form and real `syscall.WaitStatus` from `sh -c 'exit N'` and `sh -c 'kill -N $$'`); never negative (CHK-M10-355) | L, W |
| CHK-M10-047 | CODE | REQ-241 (2), (4): `Build` gives `started_at` ≤ `finished_at`, both UTC with `Z`; a timed-out outcome → `timed_out` true, `exit_code` 137; `truncated` from redaction; secrets in both streams redacted; every item passes `proto.NewResult` | L, W |
| CHK-M10-048 | CODE | CHK-M10-357: an outcome that `NewResult` would refuse (an invalid plugin uuid) → the item is `runner_unavailable` with empty streams; the raw stdout canary is in no returned field or log | L, W |
| CHK-M10-049 | CODE | REQ-242 (6) through capture: 1 MiB + 1 byte of `a` through a pipe, pattern `a+` → `[REDACTED]`, `truncated` true | L, W |
| CHK-M10-050 | CODE | The REQ-241 (5) `runner_unavailable` item of `result.go` has `exit_code` null, empty streams and flags false; no `slog` record from capture or build holds output | L, W |

## TP-M10-11 Runner client (TASK-218; REQ-245, REQ-234) — `ag/internal/agent/runnerclient/client_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-051 | CODE | Normal run against the fake runner: exactly one request, whose `job` equals the job passed and whose `max_parallel_plugins` is the value passed; each result delivered once, in the order received; `nil` after `done` | W |
| CHK-M10-052 | CODE | #131 (a) words: no socket → `connect`; a socket file with no listener (ECONNREFUSED) → `connect`; mode 0000 socket (EACCES, non-root run) → `connect`; 30 s without a first reply (fake clock) → `timeout`; `refused <w>` → `refused_<w>` for each word except busy; EOF after 2 of 5 → `broken`; an oversize frame header, a malformed frame, an unknown reply type → `protocol`; a result for a plugin not in the job, or one repeated → `protocol`, and that item not delivered | W |
| CHK-M10-053 | CODE | Busy: `refused busy` is redialled every 2 s (fake clock) and still `refused_busy` 30 s after the first attempt (16 attempts at most, recorded); busy 3 times then accepted → normal run | W |
| CHK-M10-054 | CODE | Reply deadline: after `accepted`, silence longer than max(`timeout_s`) + 30 s → `timeout`; silence just under it, then a result → continues | W |
| CHK-M10-055 | CODE | Agent stopping: `ctx` cancelled mid-run → returns `ctx.Err()` (not a `*Failure`), and the connection is closed (the fake runner sees EOF) | W |
| CHK-M10-056 | CODE | No other call: the client sends exactly one frame per connection, never reads `execute` back, and logs no reply body (canary in a result's stdout absent from logs) | W |
| CHK-M10-057 | CODE | `onResult` returning an error stops the run (recorded word) without delivering further results | W |
| CHK-M10-058 | CODE | Uses only the clock it is given: no `time.Now`, `time.Sleep`, `time.After` in `client.go` outside the clock (static scan) | L, W |

## TP-M10-12 Spool overflow (TASK-219; REQ-248) — `ag/internal/spool/overflow_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-059 | CODE | REQ-248 (1): `spool_max_mb` 1, thirty results of 64 KiB stdout put in turn → after every `Put` the disk size is ≤ 1,048,576; the oldest results are markers, the newest whole; order unchanged (CHK-M10-364) | L, W |
| CHK-M10-060 | CODE | REQ-248 (2): then every item is posted (drained through `Next`/`Ack`) exactly once; each converted one is a marker with its own `plugin_uuid`, `started_at` and `finished_at` (CHK-M10-365: no result vanishes without a marker while markers fit) | L, W |
| CHK-M10-061 | CODE | REQ-248 (3): every marker validates against `ResultItem` (the M4 contract schema) and is the #140 shape | L, W |
| CHK-M10-062 | CODE | REQ-248 (4): items in a batch handed out by `Next` and not yet answered are not converted by a `Put` that needs room; after `Ack` they're gone, after a wait answer they're convertible again | L, W |
| CHK-M10-063 | CODE | Across jobs: job A's (older) results convert before job B's; a new item too big even after converting everything is stored as a marker itself; markers alone over the bound (a tiny bound, many markers) → the oldest markers are dropped with a log line each and the size stays ≤ the bound; manifests are kept while they hold items | L, W |
| CHK-M10-064 | CODE | Conversion keeps the seq (the position in the order) and is atomic (the file is never seen partial: reopen after a planted partial `.tmp` from a conversion) | L, W |

## TP-M10-13 Results sender (TASK-220; REQ-246) — `ag/internal/agent/loops/results_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-065 | CODE | REQ-246 (1): 120 results of a finished job → start notice `{"results": [], "final": false}`, then 50, 50, 20, the last with `final: true` (CHK-M10-360, -368) | L, W |
| CHK-M10-066 | CODE | REQ-246 (2): 50 items of about 40 KiB with JSON-escaped characters → every body ≤ 1,572,864 uncompressed bytes; one maximal item (65,536 × U+0001 stdout, 6 bytes each encoded, + 16,384 stderr) is posted alone (CHK-M10-361) | L, W |
| CHK-M10-067 | CODE | REQ-246 (3): every body has `Content-Encoding: gzip`, decompresses to JSON valid against `ResultsRequest` | L, W |
| CHK-M10-068 | CODE | REQ-246 (4): 503 ×3 then 200 → retries 10, 20, 40 s (± jitter as the M4 back-off) and the batch is stored once; 429 kept and retried (CHK-M10-363); 409 on the second batch → dropped, the third still posted, `last_error` set (CHK-M10-362); each of 400, 404, 413, 422, 403 `rate_limited`-type → dropped; 403 `pending_approval` → kept with back-off; 401 → every loop stops; cap at 5 min | L, W |
| CHK-M10-069 | CODE | REQ-246 (5): three results then silence → posted 30 s after the first (not at 29 s) | L, W |
| CHK-M10-070 | CODE | REQ-246 (6): a job's final batch is never posted before every earlier entry of that job was answered (a hold on batch 2 keeps the final back); one sender goroutine, batches strictly ordered | L, W |
| CHK-M10-071 | CODE | `Wake()` makes a pending batch go out without waiting for the tick; many `Wake`s do not post twice | L, W |
| CHK-M10-072 | CODE | No body or stdout canary appears in any log record of the sender | L, W |

## TP-M10-16 Compliance handler and heartbeat (TASK-223; REQ-245, REQ-249, REQ-250; PD-45) — `ag/internal/agent/loops/compliance_test.go`, M4 files

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-073 | CODE | REQ-245 (1): a normal job via fake manager and fake runner → start notice first, then results, then `final: true`; the fake runner got exactly one request with `job` = the pulled job and `max_parallel_plugins` = the last heartbeat's value; REQ-245 (6): before any heartbeat answer, the `agent.yaml` value; a heartbeat value of 0 or 12 → clamped 1 or 8 | W |
| CHK-M10-074 | CODE | REQ-245 (2), for each #131 (a) kind (no socket, refused connection, 30 s silence, `refused <word>`, EOF after 2 of 5, an oversize or malformed frame, a result for a plugin not in the job): received results posted as received; the missing plugins `runner_unavailable` in the final batch; the runner gets no second request (CHK-M10-358); next heartbeat `last_error` = `runner_unavailable: <word>`, the one after null (REQ-250 (2)); CHK-M10-392: the foreign result is not posted | W |
| CHK-M10-075 | CODE | REQ-245 (3): busy every 2 s for 30 s → then unavailable `refused_busy` | W |
| CHK-M10-076 | CODE | REQ-245 (4): cancel mid-job → connection closed, spooled results kept, no final, no fill; reopen the spool and restart the loops → the results are posted and no final follows | W |
| CHK-M10-077 | CODE | REQ-245 (5): a canary `execute` is in no file of the state directory and no log line (CHK-M10-356, -383); the state directory after the job holds only the seen-ids file and spool files | W |
| CHK-M10-078 | CODE | REQ-249 (2): a job whose `pickup_by` passes while an earlier job runs is never sent to the runner and is logged; REQ-249 (3): an inventory job pulled during a long compliance job (held by a fake runner) is uploaded at once (CHK-M10-370); CHK-M10-369: two compliance jobs → never two runner connections at once | W |
| CHK-M10-079 | CODE | REQ-250 (1): with 3 MiB spooled, heartbeat `spool_bytes` = `Spool.Size()` (CHK-M10-367); `current_job_id` = the running job; REQ-250 (3): heartbeat answers (any values) make no runner connection (CHK-M10-384); a nil compliance handler is refused at construction. REQ-249 (1), (4): the M4 TP-M4-18 and TP-M4-19 suites pass except the PD-45 rows; no `agent.yaml` key, job field, runner reply or spool state turns inventory off (static scan of the inventory path plus a run with a full spool and a dead runner: inventory still uploads) | W |

PD-45 rewrite (filled at TASK-223 TEST, listed in `report.md`): CHK-M4-220 (the #74 single `runner_unavailable` batch with no runner contact) → CHK-M10-073 and -074; CHK-M4-221 (5,000-plugin #74 batches) → CHK-M10-065 (batching now by the sender) plus a 5,000-plugin job through the fake runner; CHK-M4-224 only where it asserts "only the seen-ids file changed" for a compliance job → CHK-M10-077. Every other M4 assertion stays. REQ-097 (2) (`spool_bytes` 0) is superseded by REQ-250 (1) (requirements "Changes (M10)"), but PD-45 names only TP-M4-18 (see Questions, Q3).

## TP-M10-08 cgroup (TASK-215; REQ-238, REQ-240) — `ag/internal/runner/cgroup_linux_test.go` (+ portable fake-tree test)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-100 | CODE | REQ-238 (1) fake tree: `Open` makes exactly: mkdir `supervisor`, own pid written to `supervisor/cgroup.procs`; per plugin, mkdir `p-<n>` (distinct n), `1` written to its `cgroup.kill`, rmdir; nothing else written (recording fake `CgroupFS`) | L, W |
| CHK-M10-101 | CODE | Refusals: a `/proc/self/cgroup` with two lines, a `1:name=systemd:` v1 line or no `0::` line; a tree without `cgroup.kill`; a symlink or a `..` path in the tree is never followed (a symlink `p-1` → outside dir: the outside dir is unchanged) | L, W |
| CHK-M10-102 | APP | WD: `Open` under `systemd-run -p Delegate=yes` → the runner's `/proc/self/cgroup` ends in `/supervisor`; a plugin started via `StartIn` reads its own `/proc/self/cgroup` as `…/p-<n>` (never `supervisor`), distinct per plugin | WD |
| CHK-M10-103 | APP | WD, the TASK-215 acceptance: planted strays (`sleep 300`) in `supervisor`, in a nested cgroup under `supervisor`, in a plugin cgroup and in a cgroup nested under a plugin cgroup → all gone after `Sweep`; the runner is alive and in `supervisor`; the subtree holds only `supervisor` (CHK-M10-338, -339) | WD |
| CHK-M10-104 | APP | WD #138 (b): the test process moved into `p-<n>` before `Sweep` (the plugin-moved-runner case) → after `Sweep` it is back in `supervisor` and alive | WD |
| CHK-M10-105 | APP | WD: `Kill` + `WaitEmpty` on a cgroup holding a forked tree (`sh -c 'sleep 300 & sleep 300 & wait'`) → `populated 0` and `Remove` succeeds; `WaitEmpty` on a cgroup that can't empty returns within its 5 s bound (recorded) | WD |
| CHK-M10-106 | CODE | Race: `StartIn` and `Sweep` from many goroutines never interleave (the spawn lock): a recording fake shows no write to `supervisor/cgroup.procs` by `Sweep` while a hop is open (`-race`) | L, W |

## TP-M10-09 Hygiene and start-up refusals (TASK-216; REQ-237) — `ag/internal/runner/hygiene_linux_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-110 | CODE | REQ-237 (1) with injected probes: euid 0 → refused (CHK-M10-385); `CapEff: 0000000000000004` and `CapBnd: 0000000000000004` → pass; `CapEff` 0 → pass (subset); `CapBnd` `000001ffffffffff` → refused; `CapEff` `0000000000200004` (+`CAP_SYS_ADMIN`) → refused (CHK-M10-386 unit part); statfs magic 0x01021994 (tmpfs) and 0x27e0eb (cgroup v1) → refused (CHK-M10-340); 0x63677270 → pass; `/proc/self/cgroup` two lines or a v1 line → refused. Each refusal names its check in a distinct message, and none quotes file contents beyond the check name | L, W |
| CHK-M10-111 | APP | On Linux, `PR_GET_DUMPABLE` returns 0 after `Harden()` (in a child test process, so the test binary stays dumpable) (CHK-M10-329 unit part) | W |
| CHK-M10-112 | CODE | Missing `CapEff`/`CapBnd` lines, a malformed hex value, a probe error → refused (fail closed) | L, W |

## TP-M10-10 Socket activation and peer check (TASK-217; REQ-235) — `ag/internal/sdsock/sdsock_linux_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-117 | APP | REQ-235 (1): a child test process gets a listening Unix socket as fd 3 with `LISTEN_PID` = its pid, `LISTEN_FDS=1`; with the expected uid = the test's uid, a connection is accepted and a byte exchanged | W |
| CHK-M10-118 | APP | REQ-235 (1): expected uid ≠ the peer's (the test runs as root: expected 1000, and expected 0 with a peer run as `nobody` via `setpriv`) → closed before any byte is read (the client's write is unread, the client sees EOF/ECONNRESET), one log line naming the uid and nothing else (CHK-M10-320 unit part, CHK-M10-321: a peer with the right gid but the wrong uid is closed) | W |
| CHK-M10-119 | APP | REQ-235 (2): `LISTEN_PID` missing or another pid; `LISTEN_FDS` 0, 2, missing; fd 3 a regular file; a datagram Unix socket; a stream socket not listening → `FromSystemd` error (start-up refused) | W |
| CHK-M10-120 | APP | REQ-235 (5) and CHK-M10-330: after `FromSystemd`, `/proc/self/fdinfo/<fd>` shows `O_CLOEXEC` for the listener and for every other fd > 2 that was inherited (the test passes extra fds 4 and 5 without CLOEXEC); a child exec'd afterwards sees only fds 0–2 (`ls /proc/self/fd`) | W |
| CHK-M10-121 | CODE | `LookupUID` reads `/etc/passwd` without CGO (`CGO_ENABLED=0` test build), finds `root` → 0, an unknown name → error | W |
| CHK-M10-122 | CODE | Static (REQ-235 (6)): the only `net.FileListener` in non-test code is in `internal/sdsock/listen_linux.go`; no non-test file calls `net.Listen*`, `syscall.Socket`/`Bind`/`Listen` or `unix.Socket`/`Bind`/`Listen` (go/ast scan of `agent/`) | L, W |

## TP-M10-15 Plugin start (TASK-221; REQ-239, REQ-241) — `ag/internal/runner/spawn_linux_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-127 | APP | REQ-239 (7): the spawned process has argv `/bin/sh -c <execute>` (`/proc/<pid>/cmdline`), environment exactly `PATH=/usr/sbin:/usr/bin:/sbin:/bin` (`tr '\0' '\n' < /proc/$$/environ`, CHK-M10-331, -332), working directory a fresh empty `/tmp/bitscan-p-*` of mode 0700, stdin `/dev/null` (CHK-M10-333), only fds 0–2 | WD |
| CHK-M10-128 | APP | REQ-239 (3): field 19 of `/proc/$$/stat` is 10 and `ionice -p $$` reports `idle` (CHK-M10-334, -335); the runner's own threads keep niceness 0 (`/proc/self/task/*/stat` after 20 spawns) | WD |
| CHK-M10-129 | APP | Born in its cgroup (#136 (a)): the plugin's first action `cat /proc/self/cgroup` prints its `p-<n>` (CHK-M10-336); `sleep 30 & echo x` → the child is in the same `p-<n>` (REQ-238 (3)) | WD |
| CHK-M10-130 | APP | No `Pdeathsig`: a plugin `sleep 2; echo done` started from the discarded locked thread completes with `done` (not killed when that thread exits) | WD |
| CHK-M10-131 | APP | Temp directory: removed by `RemoveTempDir` after the plugin; a symlink inside it pointing to an outside file → the outside file survives (CHK-M10-341) | WD |
| CHK-M10-132 | APP | Start failure: a forced cgroup-entry failure (the cgroup removed before `StartIn`) → error, no process started (`/proc` child scan) | WD |

## TP-M10-14 capread server and client (TASK-222, TASK-226; REQ-252, REQ-253) — `ag/internal/capread/capread_test.go`, `ag/cmd/bitscan-capread/main_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-137 | APP | REQ-252 (1): with the command table swapped for test commands (`/bin/echo`), `nft_ruleset\n` and `audit_rules\n` run their fixed argv with an empty `Env` (the test command prints `env` → nothing) and reply `ok\n` + its stdout (CHK-M10-373) | W |
| CHK-M10-138 | APP | REQ-252 (1) refusals, each `error unknown_request` with nothing run: `nft_ruleset x`, `NFT_RULESET`, `../nft`, `/usr/sbin/nft`, an empty line, 33 bytes, `nft_ruleset` without LF then EOF, `nft_ruleset\r\n`, any third name (CHK-M10-371, -372: no request text appears in any argv) | W |
| CHK-M10-139 | APP | REQ-252 (2): peer uid 0, the `bitscan` uid and any other uid → closed without a reply (CHK-M10-374) | W |
| CHK-M10-140 | APP | REQ-252 (3): a command running over 10 s (`sleep 60`) is killed and answered `error timeout` at 10 s (± 1 s, wall time, the spec value; CHK-M10-375); output of 1 MiB + 1 → `error too_large` with none of the output sent; exactly 1 MiB → `ok` + 1 MiB (CHK-M10-376); stderr of the command is never sent; a non-zero exit → `error failed <code>`; a missing binary → `error not_installed` | W |
| CHK-M10-141 | APP | REQ-252 (4): two clients at once → served one after the other (the second's command starts after the first's ends, by timestamps in the test commands' output) (CHK-M10-377) | W |
| CHK-M10-142 | CODE | The request read has a 5 s deadline: a client that connects and sends nothing is closed after 5 s and the next client is served | W |
| CHK-M10-176 | APP | REQ-253 (1): the client against a fake server sends exactly `nft_ruleset\n`, copies the output byte for byte (binary-safe, 1 MiB), exits 0; on `error timeout` writes exactly one line `bitscan-capread: timeout` to stderr and exits 1; missing socket → `bitscan-capread: not enabled`, exit 1; 30 s without an answer → exit 1 (fake clock or the client's injected timeout) | W |
| CHK-M10-177 | APP | REQ-253 (2), with the built binary: no argument, `nft_ruleset extra`, `/bin/sh`, `audit_rules nft_ruleset` → exit 2, nothing connects (a listening fake at the socket path sees no connection); `--serve` without `LISTEN_FDS` → start-up refusal (exit 1, one line) | W |

## TP-M10-17 Executor (TASK-224; REQ-239, REQ-240, REQ-241) — `ag/internal/runner/job_linux_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-147 | APP | REQ-240 (1)–(6) through `Executor.Run`, each a plugin with a harmless payload, after which the service subtree holds only the runner (no process other than itself in any cgroup of the subtree): `sleep 300 &`; `setsid nohup sleep 300 &`; a double fork; moves itself into `supervisor` and sleeps; creates a child cgroup under `supervisor`, and under its own `p-<n>`, and moves there; `trap '' TERM; sleep 300` (CHK-M10-337, -338, -339) | WD |
| CHK-M10-148 | APP | REQ-240 (7): `sleep 100` with `timeout_s` 2 → its result within 3 s of the start, `timed_out` true, `exit_code` 137 (CHK-M10-343) | WD |
| CHK-M10-149 | APP | REQ-240 (8): a plugin writes the runner's pid into its own `cgroup.procs` → the next `Run` still runs and the runner is in `supervisor` again (or `Run` errors and the test records a runner exit, accepted per #138 (c)); no plugin survives either way | WD |
| CHK-M10-150 | APP | REQ-240 (9): files a plugin writes under `/tmp/x` and `/var/tmp/y` are gone when `Run` returns (WD runs with a private `/tmp` via `-p PrivateTmp=yes`) (CHK-M10-342) | WD |
| CHK-M10-151 | APP | REQ-240 (10) and CHK-M10-391: `ctx` cancelled mid-job (two `sleep 300` plugins) → `Run` returns, and 1 s later no plugin process exists; nothing more is emitted after the cancel | WD |
| CHK-M10-152 | APP | REQ-239 (6): eight `sleep 2` with `max_parallel_plugins` 3 → never more than 3 running (start and end timestamps the plugins print), three rounds; with 1 → strictly sequential | WD |
| CHK-M10-153 | APP | REQ-241 (5): exec forced to fail for one plugin (a counting `Spawn` that fails the 2nd) → that item is `runner_unavailable` and the 3rd plugin runs; cgroup creation forced to fail at the 2nd → every plugin not yet started is `runner_unavailable` and no further process starts (exec counter) | WD |
| CHK-M10-154 | APP | REQ-241 (3) at unit level: `exit 3` → 3; `kill -9 $$` → 137; an unknown command → 127; one result per plugin, in completion order (a 0.1 s plugin listed after a 1 s plugin arrives first) | WD |
| CHK-M10-155 | APP | Redaction in the real path: a plugin printing a `bsa_` canary token and 3 MiB of filler → the emitted stdout holds `[REDACTED]`, no token body, ≤ 65,536 bytes, `truncated` true; the canary in no log record (CHK-M10-382) | WD |
| CHK-M10-156 | APP | The plugin's temp directory is gone after each plugin, and its cgroup removed (`p-<n>` absent) before the result is emitted | WD |

## TP-M10-18 Serve loop (TASK-225; REQ-234, REQ-235, REQ-236, REQ-261) — `ag/internal/runner/serve_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-163 | CODE | A good request → `accepted`, the fake executor's results as `result` frames in emit order, `done`, close; the executor saw the request unchanged | W |
| CHK-M10-164 | CODE | REQ-235 (4): while a job runs (executor held at a barrier), a second connection gets `refused busy` at once, without its request being read, and the running job is unaffected | W |
| CHK-M10-165 | CODE | REQ-261 malformed cases, each → one `refused` frame (word recorded against Q1), then close, exec counter 0: a bare JSON string; `{"plugins": […]}` without a job; an unknown key `"command"`; an inventory job (`not_compliance`); `v` 2; zero-length frame; oversize header; garbage bytes | W |
| CHK-M10-166 | CODE | CHK-M10-322: a second request frame sent on the same connection after the first → never read or run (exec counter 1, one `accepted`); after `refused`, a second frame → nothing | W |
| CHK-M10-167 | CODE | REQ-236 (2), through the socket: foreign, expired, too-far, replayed → `refused` with its word, exec counter 0, one log line (`job_id` + word only, no canary) | W |
| CHK-M10-168 | CODE | Request deadline: a connection that sends nothing (or half a header) is closed after 30 s (injected deadline or clock; recorded which), and the next connection is served | W |
| CHK-M10-169 | CODE | TASK-225 acceptance: closing the client mid-job cancels the executor's context within 1 s (wall time, the task's bound) | W |
| CHK-M10-170 | CODE | Write deadline: a client that stops reading while the executor emits 100 large results → the job is cancelled (after the 60 s deadline, injected), the runner goes on to serve the next connection | W |
| CHK-M10-171 | CODE | The serve loop logs no execute, pattern or result output canary in any record (CHK-M10-382 unit part) | W |

## TP-M10-19 Binaries (TASK-227, TASK-228; REQ-245 to REQ-251, REQ-237) — `ag/cmd/bitscan-agent/main_test.go`, `ag/cmd/bitscan-runner/main_test.go`, `ag/internal/boundary_test.go`

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-182 | APP | TASK-227: the built agent against a fake manager (M4's) and a fake runner runs a compliance job end to end (start notice, results, final) | W |
| CHK-M10-183 | APP | SIGTERM mid-job → exit 0 within 5 s; the spool directory still holds the received results; on restart they are posted and no final follows (REQ-245 (4) at binary level) | W |
| CHK-M10-184 | APP | The spool is opened with `spool_max_mb` from `agent.yaml` (1 → bound 1,048,576: an overflow appears at that size); `Dropped` entries at open set `last_error` | W |
| CHK-M10-185 | APP | REQ-249 (5) and CHK-M10-312: the inventory job still uploads while a compliance job runs and while the runner is absent | W |
| CHK-M10-188 | APP | TASK-228 under `systemd-run` with the verbatim runner unit's properties (from `deploy/systemd/bitscan-runner.service`, minus `User=` if the user doesn't exist in WSL: recorded) and a socket unit: a driver-less test client (the Go test as uid `bitscan` of a temp user) runs one job; REQ-237 (2) part: `CapEff`/`CapBnd` of the runner = `0000000000000004`. If WSL cannot run it as written, NOT RUN with the reason and CI cover | WD |
| CHK-M10-189 | APP | The runner outside systemd (no `LISTEN_*`) → exit 1, one line; as root → exit 1 (euid refusal); `PR_GET_DUMPABLE` 0 in the running runner (`/proc/<pid>/status` `Dumpable` not readable as 1) | W |
| CHK-M10-190 | APP | REQ-251 (3) unit level: the runner's and agent's stderr (journald stand-in) hold none of the canaries from execute, pattern, stdout, stderr and token, and every line is structured JSON with `job_id`/`agent_id` where known | W |
| CHK-M10-191 | APP | SIGTERM to the runner mid-job → the job is cancelled and swept: no plugin process 1 s after exit | WD |
| CHK-M10-196 | CODE | REQ-251 (1) `go list -deps`: `cmd/bitscan-agent` includes `internal/runner/proto` and no other `internal/runner/...` package, no `internal/redact`, no `golang.org/x/sys` (CHK-M10-380); `cmd/bitscan-runner` and `cmd/bitscan-capread` include no `net/http`, `crypto/tls`, `internal/agent/transport` (CHK-M10-381) | L, W |
| CHK-M10-197 | CODE | REQ-251 (5) / G10: `CGO_ENABLED=0 GOOS=linux GOARCH=amd64` builds of the three binaries are static ELF x86-64 (`file`: statically linked; no `.interp`) | W |
| CHK-M10-198 | CODE | REQ-254 (2) static: no agent, runner or capread non-test code calls `systemctl`, `busctl`, a D-Bus library, or writes under `/etc/systemd` or `/run/systemd` (string and import scan) | L, W |
| CHK-M10-199 | CODE | REQ-251 context and errors: every exported runner and agent job entry point takes a `context.Context`; `fmt.Errorf` calls that wrap an error use `%w` (go vet + an AST scan; recorded list of exceptions) | L, W |

## TP-M10-20 Sandbox suite (REQ-259, REQ-262 and the host rows) — NOT RUN (safety-classifier refusal (VM sandbox))

Each row is defined from its criterion so it can be run later. Owner: open. Cover is named per row.

| Check | What (on `bitscan-u2204`, `bitscan-u2404`, and the hosted runners) | Lower-level cover |
| --- | --- | --- |
| CHK-M10-200 | `systemd-analyze verify` of the units as written with the real binaries installed | G17 (CHK-M10-305) |
| CHK-M10-201 | A plugin cannot write to `/etc`, `/var/lib`, `/home`, `/root`, `/run`, `/usr/local`, `/dev/shm`, `/sys`, `/proc/sys`; can write to its private `/tmp`, `/var/tmp` | G17 (`ProtectSystem=strict`, `PrivateTmp=yes` verbatim) |
| CHK-M10-202 | No `AF_INET`, `AF_INET6`, `AF_PACKET` socket; no IP reachable | G17 (`RestrictAddressFamilies`, `IPAddressDeny`) |
| CHK-M10-203 | No exec of a copy of `true` in `/tmp`, `/var/tmp`, `/home` | G17 (`NoExecPaths=/`, `ExecPaths=`) |
| CHK-M10-204 | Blocked sockets: `/run/docker.sock`, `/var/run/docker.sock`, `/run/containerd`, snapd and journald sockets (planted 0666 listeners) unreachable | G17 (`InaccessiblePaths=`) |
| CHK-M10-205 | No `ptrace`/`process_vm_readv` of the runner; `/proc/<runner>/mem`, `environ` → EACCES (REQ-237 (2)) | CHK-M10-111, G17 (`~@debug`) |
| CHK-M10-206 | The runner's listening socket is not among a plugin's fds; `runner.sock` can't be replaced, renamed or unlinked; nothing can be created in `/run/bitscan/` | CHK-M10-120 |
| CHK-M10-207 | D-Bus: `systemctl stop/start/restart/enable/mask`, `busctl call … StartUnit`, `loginctl terminate-session`, `hostnamectl set-hostname`, `timedatectl set-time` refused; `systemctl is-active`, `is-enabled`, `list-units`, `list-unit-files` work | G17 (verbatim D-Bus policy) |
| CHK-M10-208 | No privilege gain (`sudo -n`, a setuid binary, `newgrp`); no module load, clock or hostname change, no block device open | G17 (`NoNewPrivileges`, `Protect*`) |
| CHK-M10-209 | Can read `/etc/shadow` (capability works) | CHK-M10-188 (`CapEff` 0x4) |
| CHK-M10-210 | REQ-238 (2)–(4) cgroup layout on the host | CHK-M10-102, -103 |
| CHK-M10-211 | REQ-239 (1)–(6) environment, fds, niceness, I/O class, temp dir, `id -u` ≠ 0, parallel cap | CHK-M10-127 to -131, -152 |
| CHK-M10-212 | REQ-240 (1)–(10) no plugin outlives its job | CHK-M10-147 to -151 |
| CHK-M10-213 | REQ-241 (3) exit codes on the host | CHK-M10-154 |
| CHK-M10-214 | REQ-237 (3) cgroup v1 boot on u2204 → runner refuses; agent reports per REQ-245 (2) | CHK-M10-110, -074 |
| CHK-M10-215 | REQ-237 (4) planted unit with `CAP_SYS_ADMIN` → runner refuses | CHK-M10-110 |
| CHK-M10-216 | REQ-235 (3): root and a member of group `bitscan` closed without a reply; a non-member gets EACCES | CHK-M10-118 |
| CHK-M10-217 | REQ-252 (5), (6): capread with real `nft` and `auditctl`; helper `CapEff` 0x40001000; runner and plugins 0x4 | CHK-M10-137 to -141 |
| CHK-M10-218 | REQ-253 (3): helper disabled → exit 1 and the fixed line; file-based checks still work | CHK-M10-176, -177 |
| CHK-M10-219 | REQ-254 (1): capread units disabled and inactive after install; `runner_helpers` `[]` → `["capread"]` → `[]` | G17; M4 heartbeat suite (#30) |
| CHK-M10-220 | REQ-251 (3), (4): canary sweep over the journals; `ss -ltnup` shows no listener of theirs | CHK-M10-190, -122 |
| CHK-M10-221 | REQ-255 (4): `bitscan-runner.service` inactive until the first job | none (package rows CHK-M10-308/309) |
| CHK-M10-222 | #143: every `bits/samples/` plugin under the sandbox: no error, no timeout, no exit 126/127, normalised stdout equal to root's outside the sandbox | none at unit level (recorded) |
| CHK-M10-223 | `clone3` under the verbatim unit: ENOSYS or not (fact for the owner) | none |

## TP-M10-21 Runner security suite (REQ-261; G78)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-260 | CODE | Unit part, expired, foreign, replayed jobs refused by the runner checks and through the serve loop (CHK-M10-035, -167), nothing executed, one log line without payload | L, W |
| CHK-M10-261 | CODE | Wrong peer (CHK-M10-118); non-job requests (CHK-M10-165, -166); capread names (CHK-M10-138) | W |
| CHK-M10-270 | CODE | Agent half (G36): the M4 security rows (expired, foreign, replayed by the agent; certificate failing verification or its pin) re-run unchanged; plus CHK-M10-356 and -358 (no job stored, no resend) in `ag/internal/agent/security_test.go` | W |
| CHK-M10-280 to -289 | APP | Host part through the driver (REQ-236 (5), REQ-261 (1) on a sandbox host) | **NOT RUN** (safety-classifier refusal (VM sandbox)); cover CHK-M10-260, -261 |

## TP-M10-22 First compliance run (REQ-263; G79) — NOT RUN

CHK-M10-290 (scan reaches `completed`, SR §1.1 plugin PASS), CHK-M10-291 (the `bsa_` canary stored `[REDACTED]`), CHK-M10-292 (masked runner → every result ERROR `runner_unavailable`, job `completed`, no retry): **NOT RUN** (safety-classifier refusal (VM sandbox)). Cover (REQ-263 (4)): CHK-M10-073, -074, -155 (fake manager and fake runner; real executor redaction).

## TP-M10-23 CI and docs (TASK-229, TASK-230, TASK-231; REQ-257, REQ-258)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-313 | CODE | TASK-229: `agent.yml` replaces the M0 stub step with: the runner and `bitscan-capread --serve` exit 1 outside systemd, the capread client with no argument exits 2; `go test ./...` on `ubuntu-22.04` and `ubuntu-24.04`; actions pinned by SHA as in M0; actionlint clean; `grep -n arm64` and `grep -n debian:12` find nothing new (REQ-257 (2)). The new step goes red with the M0 stub runner put back (run the step's commands locally on the stub build in W; the live PR run is recorded from CI) | W, CI |
| CHK-M10-314 | CODE | TASK-230 sandbox CI: **NOT RUN** (it runs only the refused harness; lead's ruling) | — |
| CHK-M10-315 | CODE | TASK-231: `dpkg-parsechangelog -S Version` = `0.2.0~pre1-1`; the runbook additions exist (unified cgroup v2 prerequisite and how `runner_unavailable` shows; enabling and disabling capread on the host; `findmnt --task 1`; the spool and `spool_bytes`); README says hosts run compliance jobs and the results views come with M11; no token, password, internal id or process note (grep for `bs[aeku]_`, `TASK-`, `REQ-`, `CHK-`, `tester`, `impl-`); `check_md_links.py` and `check_runbook_text.py` pass. The VM runbook walk (REQ-258 (1)) is NOT RUN (safety-classifier refusal (VM sandbox)); cover: each command checked for syntax and against the unit and file table | W |

## TP-M10-24 Gate rows

| Check | What | Where |
| --- | --- | --- |
| CHK-M10-300 | G7 `gofmt -l agent` prints nothing | W |
| CHK-M10-301 | G8 `golangci-lint run ./...` from `agent/` on Linux, `--uniq-by-line=false` for plants | W |
| CHK-M10-302 | G9 `go mod verify`; plant: an altered `go.sum` h1 line, with a cold module cache (`GOMODCACHE` empty) → `go mod download`/verify fails | W |
| CHK-M10-303 | G10 static amd64 builds (CHK-M10-197); plant `import "C"` in `internal/runner` → the `CGO_ENABLED=0` build fails | W |
| CHK-M10-304 | G11 no `//nolint` in non-test agent code | L, W |
| CHK-M10-305 | G17 `deploy/tests/check_units_verbatim.py` unchanged and green; `systemd-analyze verify deploy/systemd/*` (only "not executable" locally); plants CHK-M10-387 to -390 at unit level | W |
| CHK-M10-306 | G35 Go contract test unchanged | W |
| CHK-M10-307 | G36 agent security subset (CHK-M10-270) | W |
| CHK-M10-308 to -311 | G37 lintian, G38 maintainer scripts and the `0.1.0-1` → M10 upgrade (twice; `agent.yaml`, `token`, `agent_id` byte-identical), G39 reproducible double build, G40 SBOM lists `golang.org/x/sys`; REQ-255 (3): the packaged runner and capread contain no `not implemented` line. Run in a container in W, as M4 | W |
| CHK-M10-312 | G41 `e2e/agent_manager.sh` inventory chain against the real manager in W | W |
| CHK-M10-316 | G1–G4 (lead's ruling): ruff, ruff format, mypy --strict for `manager` (the cross-check test file) and the full agent G7–G11 | W |
| CHK-M10-317 | Full runs at the gate: `go test -race ./...` from `agent/` on W (and the pure packages on L), with totals | L, W |

## Fuzz and property (CHK-M10-080 to -099)

| Check | Type | What | Where |
| --- | --- | --- | --- |
| CHK-M10-080 | CODE | `FuzzApply` (REQ-242 (8)): random text with known secrets inserted at random offsets, including across 65,536 and 1,048,576 (random crypt hashes, `bs[aeku]_` tokens, AKIA/ASIA ids, PEM bodies, `token=` values), with the five defaults: no secret's random body (≥ 8 random chars) appears; output ≤ cap; valid UTF-8; `go test -fuzz=FuzzApply -fuzztime=120s` plus the seed corpus in every normal run | W (seeds also L) |
| CHK-M10-081 | CODE | `FuzzCompile`: no panic; any accepted pattern finds no empty match on a set of probe strings (`""`, `"a"`, `"\n"`, 100 random) | W |
| CHK-M10-082 | CODE | `FuzzReadRequest`, `FuzzReadReply` (protocol frames): no panic; never reads past the header for a header over the cap; anything accepted re-encodes and decodes to an equal value | W |
| CHK-M10-083 | CODE | Property, deterministic (seeded, 10,000 cases): the same as -080 with each secret type placed straddling each of the 65,536 / 16,384 / 1,048,576 boundaries and each invalid-UTF-8 position | L, W |
| CHK-M10-084 | CODE | Property for the spool: random sequences of `StartJob`/`Put`/`Next`/`Ack`/`Drop`/`Finish`/reopen (seeded, 2,000 runs) → size = disk bytes ≤ bound after every `Put`; no item delivered twice after an `Ack`; no final for an interrupted job | L, W |
| CHK-M10-085 | CODE | `FuzzCapreadRequest`: random request bytes → only the two exact names run anything | W |
| CHK-M10-090 | CODE | Fuzz crashes found are fixed in the product (routed to the owner) and the crashing input is kept in `testdata/fuzz/` | W |

## Mutation table (CHK-M10-320 to -393): where each plant must go red

Each plant is made in a throwaway copy and run against the named check. **VM** rows (also planted as a throwaway `.deb`) are NOT RUN on hosts (safety-classifier refusal (VM sandbox)), but their unit-level plant still runs where a unit check exists. Rows with no unit-level check are NOT RUN in full.

| CHK | Red in (unit level) | VM part |
| --- | --- | --- |
| -320 peer check removed | CHK-M10-118 | NOT RUN |
| -321 gid compared | CHK-M10-118 | — |
| -322 second frame run | CHK-M10-166 | — |
| -323 unknown key accepted | CHK-M10-003, -165 | — |
| -324 inventory job accepted | CHK-M10-003, -035, -165 | — |
| -325 runner `agent_id` check removed | CHK-M10-035, -167 | NOT RUN |
| -326 > 25 h accepted | CHK-M10-035 | — |
| -327 seen set removed | CHK-M10-035, -038, -167 | NOT RUN |
| -328 `pickup_by` = now accepted | CHK-M10-035 | — |
| -329 `PR_SET_DUMPABLE` not set | CHK-M10-111, -189 | NOT RUN |
| -330 fd 3 not CLOEXEC | CHK-M10-120 | NOT RUN |
| -331 runner environment inherited | CHK-M10-127 | NOT RUN |
| -332 `TMPDIR` added / `PATH` changed | CHK-M10-127 | — |
| -333 stdin inherited | CHK-M10-127 | NOT RUN |
| -334 niceness not applied | CHK-M10-128 | NOT RUN |
| -335 I/O class not applied | CHK-M10-128 | NOT RUN |
| -336 plugin in `supervisor` | CHK-M10-129, -102 | NOT RUN |
| -337 no `cgroup.kill` at exit | CHK-M10-147 | NOT RUN |
| -338 sweep removed | CHK-M10-103, -147 | NOT RUN |
| -339 sweep skips nested | CHK-M10-103, -147 | NOT RUN |
| -340 statfs check removed | CHK-M10-110 | NOT RUN |
| -341 temp dir kept | CHK-M10-131, -156 | — |
| -342 private `/tmp` not emptied | CHK-M10-150 | — |
| -343 timeout not enforced | CHK-M10-148 | NOT RUN |
| -344 truncate before redact | CHK-M10-020, -080 | (G79 NOT RUN) |
| -345 cut-off skipped without pattern 2 | CHK-M10-018, -019 | — |
| -346 read limit or drain removed | CHK-M10-044, -045 | — |
| -347 `truncated` not set on overflow | CHK-M10-023 | — |
| -348 cut splits a rune | CHK-M10-021, -080 | — |
| -349 stderr cut sets `truncated` | CHK-M10-021, -023 | — |
| -350 `Expand` replacement | CHK-M10-017 | — |
| -351 51 patterns accepted | CHK-M10-012, -040 | — |
| -352 bad pattern skipped | CHK-M10-012, -040 | — |
| -353 empty-match accepted | CHK-M10-012 | — |
| -354 growth guard removed | CHK-M10-024 | — |
| -355 signal → −1 | CHK-M10-046 | — |
| -356 job written to spool/state | CHK-M10-031, -077 | — |
| -357 raw output on redaction failure | CHK-M10-048 | — |
| -358 resend to restarted runner | CHK-M10-074 | — |
| -359 final for interrupted job | CHK-M10-029, -076 | — |
| -360 batch of 51 | CHK-M10-065 | — |
| -361 batch over 1,572,864 | CHK-M10-066 | — |
| -362 409 retried | CHK-M10-068 | — |
| -363 429 dropped | CHK-M10-068 | — |
| -364 newest dropped first | CHK-M10-059 | — |
| -365 dropped without marker | CHK-M10-060 | — |
| -366 non-atomic spool write | CHK-M10-028 | — |
| -367 `spool_bytes` 0 | CHK-M10-079 | — |
| -368 start notice missing or late | CHK-M10-065 | — |
| -369 two jobs at once | CHK-M10-078 | — |
| -370 inventory waits | CHK-M10-078 | — |
| -371 third capread name | CHK-M10-138 | NOT RUN |
| -372 request text as argument | CHK-M10-138 | — |
| -373 capread environment passed | CHK-M10-137 | NOT RUN |
| -374 capread peer check removed | CHK-M10-139 | NOT RUN |
| -375 capread timeout 60 s | CHK-M10-140 | — |
| -376 capread cap removed / cut sent | CHK-M10-140 | — |
| -377 capread parallel | CHK-M10-141 | — |
| -378 `net.FileListener` outside sdsock | CHK-M10-301, -122 | — |
| -379 `exec.Command` in `compliance.go` | CHK-M10-301 | — |
| -380 agent imports runner/redact | CHK-M10-196 | — |
| -381 runner imports `net/http` | CHK-M10-196 | — |
| -382 runner logs stdout canary | CHK-M10-155, -171 | (canary sweep NOT RUN) |
| -383 agent logs result stdout | CHK-M10-077 | — |
| -384 heartbeat triggers runner | CHK-M10-079 | — |
| -385 euid 0 accepted | CHK-M10-110 | — |
| -386 capability check removed | CHK-M10-110 | NOT RUN |
| -387 unit character changed | CHK-M10-305 | — |
| -388 D-Bus policy allows `StartUnit` | CHK-M10-305 | NOT RUN |
| -389 no `InaccessiblePaths=` | CHK-M10-305 | NOT RUN |
| -390 no `NoExecPaths=` | CHK-M10-305 | NOT RUN |
| -391 runner keeps running after close | CHK-M10-151, -169 | NOT RUN |
| -392 foreign result spooled | CHK-M10-074, -052 | — |
| -393 `agent_id` read once | CHK-M10-041 | — |

## Questions (answered by `main`, decisions row "tester-m10's M10 plan questions", 2026-10-30)

- **Q1 (TASK-209/225, REQ-236 (1) vs REQ-234 (2)):** a request whose job has 0 or 5,001 plugins, `timeout_s` 0 or 601, or `max_parallel_plugins` 0 or 9 is refused by the strict decoder before the checks run. **Answer: over the socket these get `malformed` at decode; `bad_plugins` and `bad_parallel` are TASK-213's unit-level check words only.** An inventory job stays `not_compliance` (plan TASK-209 §2). Asserted in CHK-M10-003 (`RefusalFor`) and CHK-M10-165.
- **Q2 (#132 (c)):** **Answer: a job refused `seen_full` is not recorded**; once space frees, the same job is accepted as a first run. Asserted in CHK-M10-039.
- **Q3 (PD-45 scope):** **Answer: yes**, CHK-M4-185's `spool_bytes` part is rewritten to REQ-250 (1) on the PD-45 old → new list; every other assertion stays.
