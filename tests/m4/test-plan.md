# M4 test plan (Go agent and pre-release `.deb`)

Owner: tester (`tester-m4`). Written 2026-10-24 from `work/tasks.md` "M4 Go agent and pre-release `.deb`" (acceptance tests of TASK-085 to TASK-107, TP-M4-00 to TP-M4-24, the gate G7 to G11, G17, G35 to G41, the security mutation table CHK-M4-320 to -366), `work/requirements.md` REQ-091 to REQ-112, the plans `work/plans/TASK-086.md`, `-093`, `-099`, `-100`, `-101`, `-104`, the TS sections they cite (§2.2, §3 to §3.7, §6.3, §6.5, §8.1 to §8.3) and the answers agreed by the user on 2026-10-24 (`work/decisions.md` "M4 breakdown approved", "arm64 dropped from v1", "Speed rules from M3 on", "Test results as totals"; `work/open-questions.md` #4, #28, #30, #35, #74 to #82, PD-25 to PD-27), before any M4 implementation existed (`agent/internal/` was absent when this plan was written). Results go to [report.md](report.md) (written by `main` from the tester's messages if the harness blocks the tester).

`ag/` means `agent/`, `bm/` means `manager/bitscan_manager/`, Lnnn are lines of `docs/spec/Technical_Specification.md`.

**Changes after drafting (2026-10-24):**
- **Debian 12 dropped from v1 (user, 2026-10-24).** Supported hosts are Ubuntu 22.04 and 24.04, amd64 only. Every Debian 12 part of a check below (the `debian:12` container runs in CHK-M4-095, -098, -110, TP-M4-15 and CHK-M4-250) is **NOT RUN (dropped from v1 by the user)**; the Ubuntu 22.04 parts stay (W-c `ubuntu:22.04` or CI).
- **More than 256 addresses (replaces ruling 9):** `ip_addresses` is sent as `[]` (the contract does not allow null) with a fixed reason in `raw.errors` (lead, 2026-10-24).
- **Split with `tester-m4b` (lead, 2026-10-24):** `tester-m4` keeps TP-M4-00, -01 and TASK-086 to -090, 093, 098, 099, 101, 103, 106 and the gate; `tester-m4b` takes TASK-091, 094, 095 and the deploy tasks 096, 097, 100, 102, 105, 107, using the same check ids.

## Conventions

- Type: **CODE** = static gate, unit test or script on the tree. **APP** = a real binary or package: the built `bitscan-agent` against a fake or the real manager, an installed `.deb` under systemd, or the real M3 `bitscan-manager serve`.
- Where: **W** = WSL2 `Ubuntu-24.04` (x86_64, systemd on), run by the tester only through `C:\Users\kaiquan.koh\AppData\Local\Temp\tester2_m4_<name>.sh` launched with `MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/Users/kaiquan.koh/AppData/Local/Temp/tester2_m4_<name>.sh`; work folder `/root/bitscan-m4` (a copy of `agent/`, `deploy/`, `docs/spec/`, `manager/openapi.json` and `manager/tests/contract/`), Go at `/opt/go1.27.2/bin/go`, `GOTOOLCHAIN=local`, `GOFLAGS=-mod=readonly`, `GOPATH` and `GOMODCACHE` under the work folder, every command under `timeout` and every `go test` with `-timeout`. **W-u** = the same as the non-root user `bstester` (work folder `/home/bstester/bitscan-m4`), used where file modes, ownership or "cannot read root-only files" matter. **W-c** = a `debian:12` or `ubuntu:22.04` container in WSL Docker (PD-27), started and removed by the script itself (never a container it did not start; `docker ps` is checked before any run, and no Testcontainers run starts while `tester-h` runs one). **CI** = GitHub Actions only. **L** = Windows 11 + Git Bash, for `gofmt` and reading only; no Go test counts on L (G8 and G11 count only on Linux).
- Every run is reported as `passed/total` with failed, error and skipped counts (`go test -json` counted per test and subtest; skipped tests are listed by name). A Go test that calls `t.Skip` on Linux is a failure of the check unless the plan names the skip.
- **Fake manager** = an `httptest.NewTLSServer`/`NewUnstartedServer` in a `_test.go` file (listeners are allowed only in tests) serving the frozen contract, with a test CA made in the test. It records every request (method, path, query, headers, body bytes) so a test asserts the exact calls. **Real manager** = the M3 `serve` in WSL with PostgreSQL (TP-M4-23 only, coordinated with `tester-h`).
- **Fake clock** = the clock the agent code receives (TASK-090 and later); every time rule (intervals, back-off, rotation window, `pickup_by`, 7-day seen ids, the #80 debounce, 5 s SIGTERM) is tested by moving it, never by sleeping, except the binary-level checks of TP-M4-21, which use real time with bounds.
- **Canary** = `CANARY-<16 hex>` built into fake `bse_`/`bsa_` tokens (`bsa_` + 43 base64url characters, the canary inside), package names, `raw` values and job `execute` strings; a sweep greps stdout, stderr, journald and every file written for each canary.
- **Exec counter** = a test build hook or `PATH`/`/proc` probe that counts processes started by the agent; "no process execution" means the counter stays 0 (except the #35 commands where a check names them).
- **Planted violations** are made in a throwaway copy (`/root/bitscan-m4-mut/<chk>`), never in the tree; the unmodified copy must be green first; "red" = non-zero exit **and** the named test fails for the planted reason (its failure message is quoted in the report).
- Expected values come from the spec and the answered questions below, never from the implementation. Where an answer leaves a point open the check says so and `main` is asked; a check is never adapted to the code.
- Every task that touches `ag/internal/agent/wire/` re-runs TP-M4-01 (CHK-M4-010 to -019).

## Expected values (spec and answered questions)

| Item | Expected | Source |
| --- | --- | --- |
| Wire contract | the #60 field table as amended 2026-10-23; nullable keys always present (never omitted, `null` when absent); UUIDs hyphenated 8-4-4-4-12 on input (either case), lowercase on output; timestamps RFC 3339 with an offset on input (fractions allowed, naive refused), UTC `Z` on output; 64-bit counters 0..2^53 − 1; no U+0000 in agent-sent strings; at most 10 jobs; compliance job = `job_id`, `agent_id`, `kind`, `pickup_by`, `plugins` (1..5,000 of exactly `plugin_uuid`, `execute` non-empty, `timeout_s` 1..600), `redaction_patterns` (0..50); inventory job = the first four only; unknown keys refused in every body | REQ-091; #59, #60; decisions 2026-10-23 |
| `schema_gaps` | `lone surrogate` fixtures: assert nothing (Go turns `\ud800` into U+FFFD); `nan_inf` fixtures: not JSON, Go must refuse to parse them (manifest text; see question 3) | manifest `schema_gaps`; REQ-091 (1) |
| Problem types | `pending_approval`, `enrollment_rejected`, `token_revoked`, `token_expired`, `machine_id_mismatch`, `job_not_acceptable`, `too_large`, `rate_limited` (TS §6.5 L1190) plus `unauthorized`, `forbidden`, `invalid_request`, `about:blank` (#59); problem bodies decoded leniently (only `type`, `status` used) | L1190; #59; plan TASK-086 |
| `agent.yaml` | the TS §3.6 example loads to exactly `manager_url` `https://mgr.example:8443`, `ca_file` "", `manager_spki_sha256` "", `state_dir` `/var/lib/bitscan-agent`, `heartbeat_seconds` 300, `job_pull_seconds` 300, `max_parallel_plugins` 2, `spool_max_mb` 50, `log_level` `info`. Refused at start-up with one line naming the key: `manager_url` missing, empty or not `https://` (also `HTTPS://`? see question 4); `ca_file` set but missing or unreadable; pin not empty and not 64 hex (either case); `state_dir` other than `/var/lib/bitscan-agent`; `heartbeat_seconds` other than 300; `job_pull_seconds` outside 60..3,600; `max_parallel_plugins` outside 1..8; `spool_max_mb` outside 1..50; `log_level` not one of `debug`, `info`, `warn`, `error`; any other key (`inventory: false`); malformed YAML. The agent never writes the file | TS §3.6 L257–L267; #4; REQ-092 |
| State directory | `/var/lib/bitscan-agent/` (0700): `agent_id` 0644, `token` 0600, token times (plan: `token.json` 0600), `enroll.token` 0600 until enrolled, seen ids (plan: `seen_jobs.json` 0600) kept 7 days; owner the running user; every write = temporary file, fsync, rename, directory fsync; a crash between any two steps leaves the old or the new complete state; nothing written outside the directory | TS §3.1 L162, §3.2 L184, §3.7 file table; REQ-093 |
| TLS | minimum TLS 1.2 (a 1.1-only server refused; 1.3 negotiated when offered); chain and host name verified against the system store, or against `ca_file` only when set; pin (#79) = 64 hex (either case) SHA-256 of the leaf's DER SubjectPublicKeyInfo, checked in addition to verification; no client certificate; no `InsecureSkipVerify`; refusal before any request body is sent | L194; §8.3 L1283; #79; REQ-094 |
| HTTP | `Authorization: Bearer <bsa_>` and `X-Bitscan-Machine-Id` on every `bsa_` route; enrol: `Authorization: Bearer <bse_>`, no machine-id header; no proxy from the environment, no redirect followed (3xx = drop, #75); request time limits and a response size cap (plan: 32 MiB) refused without reading it all | L189; #75; REQ-094 |
| Response classes | 2xx success; 401 any `type` stop; 403 `pending_approval` wait (back-off); 403 other, 400, 404, 409, 413, 422 drop (log, `last_error`); 429, 5xx, network error retry (back-off); 3xx drop; any other status drop | L224; #75; plan TASK-093 |
| Back-off | 10, 20, 40, 80, 160, 300, 300 … s (cap 300 s), with jitter (bound: question 2), reset to 10 s after one success; same for both loops; a 429 uses it (no tight loop) | L226; §6.3 L1136; REQ-095 |
| Intervals | heartbeat uniform in 300 ± 30 s (270..330, both halves reached); pull `job_pull_seconds` ± 30 s with `job_pull_seconds` from the last heartbeat response, clamped 60..3,600 (so 30..90 s at 60, 3,570..3,630 s at 3,600); `max_parallel_plugins` clamped 1..8; until a response, the `agent.yaml` values | L202–L206; REQ-097, REQ-098 |
| Watcher (#80) | inotify on the directory, `IN_MOVED_TO` and `IN_CLOSE_WRITE`, name `status` only; a change starts a 60 s quiet timer (restarted by each further change); when quiet, signal if ≥ 10 min 30 s since the last unscheduled upload, else at the end of that hold-off; one signal per burst; a change during the hold-off is never lost; a watch that cannot be set returns an error and scheduled inventory carries on | L239; #80; REQ-102 |
| Commands (#35) | exactly `hostnamectl` (`/usr/bin/hostnamectl`), `ip -j addr` (first of `/usr/sbin/ip`, `/usr/bin/ip`, `/sbin/ip`, `/bin/ip`) and `/usr/bin/dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\t${Status}\t${Source}\t${Installed-Size}\n'`; no shell, `Env` = `PATH=/usr/sbin:/usr/bin:/sbin:/bin` and `LC_ALL=C` only, stdin `/dev/null`, limits 5 s, 5 s, 60 s, output caps 1 MiB, 1 MiB, 16 MiB; `uname` and `nproc` without exec; no argument from a job, heartbeat or manager answer | L234–L238; #35; plan TASK-104 |
| `os_info` (#77) | `os_id`, `os_version_id`, `os_pretty_name` from `/etc/os-release` `ID`, `VERSION_ID`, `PRETTY_NAME`; `kernel_release` and `architecture` = `uname -r` and `uname -m` (`x86_64`); `cpu_count` = `nproc`; `memory_mb` = `MemTotal` kB ÷ 1024 rounded down; `ip_addresses` = every `ip -j addr` address with `/prefixlen`, loopback and link-local included, at most 256; `uptime_s` = first field of `/proc/uptime` rounded down; `raw` = `{os_release, hostnamectl, meminfo: {MemTotal_kb}, ip_addr, errors}`; a failed source: its fields null and a fixed reason in `raw.errors`; a value that would fail the contract: null plus a reason; `raw` ≤ 262,144 bytes compact, within the decoder's 32-container depth, no U+0000 | L234; #77; REQ-100 |
| dpkg body | one item per line, 6 tab fields; empty `Source` → null, empty `Installed-Size` → null else integer; rows sent exactly as printed (duplicates not hidden); `list_sha256` = lowercase hex SHA-256 of the lines `name\tversion\tarchitecture\tstatus\n`, UTF-8, sorted by bytes; body compact JSON, gzip, `Content-Encoding: gzip` | L235, L1186; #33, #72; REQ-101 |
| Heartbeat body (#78) | `agent_version` = build version; `uptime_s` = the agent process's uptime; `last_pull_at` = last pull answered 200, else null; `current_job_id` = the compliance job being handled, else null; `spool_bytes` 0 in 0.x; `last_error` = latest drop or local failure as `"<route> <status> <type>"` or a fixed reason word, ≤ 1,024 characters, sent once then cleared; `runner_helpers` `["capread"]` iff `/run/bitscan/capread.sock` exists, else `[]` (#30); `clock` = the agent's time | L1163; #30, #78; REQ-097 |
| Job checks | accept only if `agent_id` = own, `now < pickup_by ≤ now + 25 h`, `job_id` not seen in 7 days (persisted, survives restart); the id is recorded as seen before acting, refused ids too; inventory job → one upload with `?job_id=` at once; compliance job (#74) → recorded as seen, one results POST with `final: true` in which every plugin has `error` `runner_unavailable`, `exit_code` null, `stdout` and `stderr` "", `timed_out` and `truncated` false, `started_at` = `finished_at` = handling time; no command run; the M3 manager's 409 is dropped; at most 10 jobs per pull handled in order; empty list → no other call | L210–L216, L222; #74; REQ-098, REQ-104 |
| Rotation | window start `issued_at + max(TTL − 30 d, TTL ÷ 2)`, TTL = `expires_at − issued_at` of the current token (TTL 365 d → day 335; TTL 60 d → day 30); triggered after a successful heartbeat only; one call at a time; persist (`token`, then times) before any use; lost response → retry with the old token; 429 → no attempt before `Retry-After`; 403 `forbidden` → next attempt after 24 h; 401 → stop | L190–L191; #62; plan TASK-099; REQ-099 |
| Enrolment (#76, #81) | `enroll.token` present (also with a `token`): read `/etc/machine-id` (exactly 32 lowercase hex, else refused at start-up), hostname, `ID`/`VERSION_ID`/`PRETTY_NAME` (absent → null), enrol with `bse_`; success: write `agent_id`, `token`, times, then delete `enroll.token`; 401: keep `enroll.token`, write nothing, stop with "enrolment refused; the host needs a new enrolment token"; 429, 5xx, network: back-off and retry; neither file: refused at start-up naming both; after a stop the process stays up and idle (no call) until restarted | L182–L191; #76, #81; REQ-096 |
| Package (REQ-106) | one `bitscan-agent_0.1.0~preN-1_amd64.deb`; files: `/usr/sbin/bitscan-{agent,runner,capread}` 0755, the five agent units and `/etc/dbus-1/system.d/bitscan-runner.conf` 0644 byte-identical to TS L289–L482 and L413–L430 (fences excluded), plus the package's own docs; ELF x86-64 static; no arm64 artifact; `rules`: `--no-enable` for `bitscan-runner.service`, `--no-enable --no-start` for both capread units; after install `bitscan-runner.socket` and `bitscan-agent.service` enabled and active, `bitscan-runner.service` not enabled, capread units neither enabled nor active | L158–L166, §3.7; PD-26; REQ-106 |
| Install inputs | debconf `bitscan/manager_url`, `bitscan/enrol_token` (`password`), `bitscan/ca_file`, `bitscan/manager_spki_sha256`, or `/etc/bitscan/install.env` root:root 0600 (refused otherwise), read then deleted; never an environment variable; token only in `passwords.dat`, cleared after use | L164; REQ-107 |
| Maintainer scripts | users `bitscan`, `bitscan-runner` system, shell `/usr/sbin/nologin`, no home; `agent.yaml` root:bitscan 0640 without the token; `/var/lib/bitscan-agent` bitscan:bitscan 0700; `enroll.token` bitscan:bitscan 0600; missing URL or token: one line naming the input, exit non-zero, package half-configured, no service running; upgrade keeps `agent_id`, `token`, `agent.yaml` byte-identical; purge (#82) removes `/var/lib/bitscan-agent`, `/etc/bitscan/agent.yaml`, `/etc/bitscan/install.env`, then `/etc/bitscan` only if empty; idempotent (each action twice) | L166–L175; #81, #82; REQ-108 |
| Build | `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -buildvcs=false -ldflags "-s -w -buildid= -X main.version=<version>"`; `SOURCE_DATE_EPOCH` from `debian/changelog`; two clean builds give identical SHA-256 for the three binaries and the `.deb`; CycloneDX SBOM (`cyclonedx-gomod`) naming every module of `go version -m` with versions; a `.sha256` file that `sha256sum -c` accepts | L177; PD-26; REQ-109 |

## Gate map

| Gate | Checks |
| --- | --- |
| G7 gofmt | CHK-M4-300 |
| G8 golangci-lint (Linux) and the nolint grep | CHK-M4-301 (with CHK-M4-321, -346) |
| G9 go mod verify | CHK-M4-302 (with CHK-M4-365, -027) |
| G10 CGO off build, static check, cgo listing | CHK-M4-303 |
| G11 go test ./... linux/amd64 | CHK-M4-304 |
| G17 units and D-Bus verbatim, `systemd-analyze verify` | CHK-M4-070, -071, -305 (with CHK-M4-362) |
| G35 contract | CHK-M4-010 to -019 (with CHK-M4-350, -353, -354) |
| G36 agent security suite | CHK-M4-306 (rows marked G36 in the mutation table) |
| G37 lintian | CHK-M4-205, -307 |
| G38 maintainer scripts | CHK-M4-165 to -184, -308 |
| G39 reproducibility | CHK-M4-200, -309 |
| G40 SBOM | CHK-M4-203, -310 |
| G41 `.deb` against the real M3 manager | CHK-M4-311 (TP-M4-23) |
| G1 to G6, G18 (TASK-085 only) | CHK-M4-280 to -286 |

## TP-M4-01 Go contract test (G35; REQ-091; `ag/internal/agent/wire/contract_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-010 | CODE | The test reads `manager/tests/contract/fixtures/manifest.json` (path found from the module root, never copied), implements the four `generate` ops exactly as the manifest's `about` says (`plugins_count`, `packages_count` with the recomputed hash, `ip_addresses_count`, `raw_bytes` exact compact size), and asserts the manifest has the 276 entries and every file exists. A self-check: the Go `generate` output equals the Python `loader.py` output for each generated fixture (byte length of compact JSON, item counts, `list_sha256`) | `go test ./internal/agent/wire/ -run Contract -count=1 -timeout 300s` | a generate op that makes 4,999 plugins: the 5,000-plugin case still decodes and the 5,001 one is refused, so the self-check must catch it | W |
| CHK-M4-011 | CODE | Every **valid response** fixture (enrol, heartbeat, jobs, results, rotate) decodes through `DecodeStrict` into its Go type with no error and validates against its response component (REQ-091 (1) asks responses only to decode; re-encoding is required of requests, CHK-M4-013) | same | strict decoding off (CHK-M4-354) does not turn this red; a field renamed in `wire.go` does (a key missing) | W |
| CHK-M4-012 | CODE | Every **invalid response** fixture is refused by `DecodeStrict` (error, not a zero value), one subtest per file, for every class in `required_invalid_classes` (extra key, missing key, wrong type, bad UUID, bad timestamp, enum, range, format, under-length). Includes the 11-job, 5,001-plugin, `operator`/`expected_result`/`eval_spec` and inventory-with-`plugins` fixtures | same | CHK-M4-354 (unknown keys accepted); a missing-key check removed (nullable key may be absent); `pickup_by` naive accepted | W |
| CHK-M4-013 | CODE | Every **valid request** fixture (enrol, heartbeat, results, rotate `{}`, inventory) decodes into the Go request type (test-only use of the decoder), passes the type's `Validate()`, and re-encodes to JSON equal to the fixture body (generated ones included; the 50,000-package body in under 10 s); nullable keys re-encode as `null`, never omitted. Decoder-marked fixtures (hash mismatch, duplicate, raw 256 KiB + 1): decode and re-encode as valid; `Validate()` per question 1 | same | CHK-M4-353 (`omitempty` on `current_job_id` or `source`) | W |
| CHK-M4-014 | CODE | Every **invalid request** fixture is refused by decode or `Validate()` (the agent's self-check before sending), one subtest per file; `schema_gap: lone surrogate` entries are skipped by name and listed in the run output; `nan_inf` entries must fail to parse (question 3) | same | `Validate()` that does not check NUL; `runner_helpers` duplicates allowed; `spool_bytes` 2^53 allowed | W |
| CHK-M4-015 | CODE | Every request body the agent's Go types encode (each valid fixture re-encoded, plus bodies built by the agent's own constructors where they exist) validates against its component schema in `manager/openapi.json` (`EnrolRequest`, `HeartbeatRequest`, `ResultsRequest`, `InventoryBody`, `RotateRequest`) with a JSON Schema 2020-12 validator (PD-25 (a), test-only `santhosh-tekuri/jsonschema/v6`, question 5) with format assertion for `date-time` and `uuid`; and every valid response fixture validates against its response component | same | a request encoder that writes a naive timestamp or an uppercase UUID | W |
| CHK-M4-016 | CODE | REQ-091 (3): a response with an extra key → refused; a missing nullable key → refused; `pickup_by` `…T12:00:00.000000Z` → accepted (same instant as `…T12:00:00Z`); an uppercase UUID → accepted and re-encoded lowercase. Also: `+08:00` offset accepted and output in UTC `Z`; 32-hex, `{…}` and `urn:uuid:` UUID forms refused | same | `time.RFC3339` (no fractions) instead of `RFC3339Nano`; UUID parse with `uuid.Parse` semantics (accepts 32-hex) | W |
| CHK-M4-017 | CODE | REQ-091 (4): a reflection walk over every exported contract type (all struct fields reachable from the six routes' bodies) finds no `omitempty` or `omitzero` and no `-` tag on a contract field, and every field has an explicit `json` name equal to the TS §6.5 key; plus a source grep of `ag/internal/agent/wire/*.go` (non-test) for `omitempty` | same | CHK-M4-353 | W |
| CHK-M4-018 | CODE | Integers are strict on decode: `1.0`, `1e3`, `true`, `"1"` and 2^53 refused for every integer field in responses (`job_pull_seconds`, `max_parallel_plugins`, `timeout_s`, `accepted`, `duplicates`); boundaries 60/3,600, 1/8, 1/600, 0 accepted and 59/3,601, 0/9, 0/601, −1 refused (fixtures plus generated cases) | same | `json.Number` converted through float64 | W |
| CHK-M4-019 | CODE | Problem bodies: each of the 12 problem types decodes to its `type` and `status` from a `application/problem+json` body with extra keys (lenient, as planned); a non-JSON or empty body gives an empty type, never a panic | same | strict decoding applied to problems (extra `instance` key refused) | W |

## TP-M4-02 Config (TASK-087; REQ-092, REQ-105; `ag/internal/agent/config/config_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-020 | CODE | The TS §3.6 block (read from the spec file, L257–L267 fence content, comments included) loads to exactly the expected values (expected-values table) | `go test ./internal/agent/config/ -count=1 -timeout 60s` | a default that differs (`job_pull_seconds` 600) | W |
| CHK-M4-021 | CODE | Each refusal in the expected-values table is refused, with an error that names the key in one line and does not contain the value of `manager_spki_sha256` or any URL user-info (`https://user:CANARY@…`): `http://`, `ftp://`, `//host`, empty, missing `manager_url`; `ca_file` missing path and an unreadable file (W-u: a 0600 root file); pin 63, 65, non-hex characters; `state_dir` `/tmp/x`; `heartbeat_seconds` 299, 301; `job_pull_seconds` 59, 3,601, `"300"`, 300.5; `max_parallel_plugins` 0, 9; `spool_max_mb` 0, 51; `log_level` `trace`, `INFO`? (question 4); unknown keys `inventory: false`, `Manager_url`, a nested map; duplicate key; malformed YAML (tab indent, unclosed quote); a YAML anchor/alias bomb (refused or bounded, no hang within 5 s); an empty file | same | CHK-M4-320, CHK-M4-343; `job_pull_seconds` range unchecked | W, W-u |
| CHK-M4-022 | CODE | Boundaries accepted: `job_pull_seconds` 60 and 3,600, `max_parallel_plugins` 1 and 8, `spool_max_mb` 1 and 50, pin 64 lowercase and 64 uppercase hex, every `log_level` value; a `ca_file` that exists and is readable | same | upper bound `<` instead of `<=` | W |
| CHK-M4-023 | CODE | The loader never writes: the file's bytes, mode and mtime are unchanged after `Load`; a static check finds no write, create, rename or chmod call on the config path in non-test code of `config/` (the package opens the file read-only) | same, plus `grep` | CHK-M4-342 | W |
| CHK-M4-024 | CODE | The loader reads only the path it is given (no environment overrides: `BITSCAN_MANAGER_URL=http://…` set in the test environment changes nothing) | same | an env override | W |
| CHK-M4-025 | CODE | The config gives the pull and parallel values only as initial values: a value object or accessor lets a later heartbeat override them (checked again in TP-M4-16) | same | none (interface check) | W |
| CHK-M4-026 | CODE | `go.mod` lists only the PD-25 modules (`go.yaml.in/yaml/v3`; the test-only validator per question 5) with exact versions; `go.sum` has both `h1:` and `/go.mod h1:` lines for each; `go mod verify` exits 0 on a clean module cache | `go mod verify` | none | W |
| CHK-M4-027 | CODE | `go mod verify` (or the build) fails when one `go.sum` hash line is altered, and `go mod verify` fails when a file in the module cache copy of the yaml module is modified | plants in a throwaway `GOMODCACHE` | CHK-M4-365 | W |
| CHK-M4-028 | CODE | REQ-105 (3): `go version -m` on a built `bitscan-agent` lists `go.yaml.in/yaml/v3` and no test-only module (no `jsonschema`) | `CGO_ENABLED=0 go build -trimpath ./cmd/bitscan-agent && go version -m` | the validator imported from non-test code | W |

## TP-M4-03 State directory (TASK-088; REQ-093; `ag/internal/agent/state/state_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-030 | CODE | In a temporary directory (0700), writing the enrolment result gives `token` 0600, `agent_id` 0644, the times file 0600, all owned by the running user (W-u: uid of `bstester`), regardless of a umask of 0000 and of 0077; contents read back exactly (token one line, agent id lowercase UUID, `issued_at`/`expires_at` RFC 3339) | `go test ./internal/agent/state/ -count=1 -timeout 120s` | CHK-M4-340 (`token` 0644); mode from umask | W, W-u |
| CHK-M4-031 | CODE | Crash injection between every pair of write steps (create tmp, write, fsync, close, rename, dir fsync; and between the token and the times file) through the package's fault hook, or by killing a child process at each step: reading afterwards gives either the complete old state or the complete new state, never a partial or empty `token`, `agent_id` or times file; a leftover `.<name>.tmp` is ignored or cleaned on the next write and never read as state | same | write in place (`O_TRUNC` on the final name); rename before fsync with the fault after rename | W |
| CHK-M4-032 | CODE | Atomic-write hardening: a pre-existing symlink at the temporary name or the final name pointing outside the directory is not followed (the target outside is unchanged; `O_EXCL|O_NOFOLLOW`); a pre-existing `.token.tmp` regular file left by a crash does not block the next write forever | same | `O_EXCL` dropped | W, W-u |
| CHK-M4-033 | CODE | `enroll.token` is deleted by the state API after a successful write of the new state, and only then (the delete is after the token write in the step order); deleting when it is absent is not an error | same | delete before write | W |
| CHK-M4-034 | CODE | Seen ids: an id added at t0 is "seen" at t0 + 7 d − 1 s and forgotten at t0 + 7 d + 1 s (fake clock; boundary at exactly 7 d per question 6); seen ids survive closing and re-opening the store (new process state, same directory); entries are pruned on load and on write; a corrupt seen-ids file is not silently treated as empty (error, or fail closed: see question 7) | same | CHK-M4-333 (memory only), CHK-M4-334 (6 days) | W |
| CHK-M4-035 | CODE | 1,000 seen ids (more than 7 days × 10 jobs × several pulls a day) stay bounded and the file stays 0600; adding the same id twice keeps the first-seen time | same | first-seen overwritten (would extend the window) | W |
| CHK-M4-036 | CODE | Nothing is written outside the directory: the test runs with the directory as the only writable path (W-u: a read-only parent and `TMPDIR` set to a read-only path), and an `strace -f -e trace=%file` or an `inotify` sweep of the parent shows no create, rename or unlink outside | same, and `strace` in W | temporary file created in `os.TempDir()` | W-u |
| CHK-M4-037 | CODE | Concurrency: 8 goroutines writing token state and 8 adding seen ids for 2 s under `-race` give no race report, and the final files are complete | `go test -race ./internal/agent/state/` | the store without its lock | W |
| CHK-M4-038 | CODE | The token string appears in no error message or log line from the state package (canary token through every error path: unwritable dir, rename failure) | same | `fmt.Errorf("write %s: %w", token, err)` | W |

## TP-M4-04 TLS (TASK-089; REQ-094; `ag/internal/agent/transport/tls_test.go`)

Test PKI made in the test: root CA A (trusted via `ca_file`), root CA B (untrusted), a leaf for `localhost`/`127.0.0.1` from A, a leaf from A for `wrong.example`, an expired leaf from A, a leaf from A with a different key, an intermediate chain A → I → leaf.

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-040 | CODE | Refused, each with zero request bytes reaching the server handler (the handler counts calls and body bytes): leaf from untrusted CA B; wrong host name; expired leaf; a not-yet-valid leaf; TLS 1.1-only server (`MaxVersion` 1.1); correct chain with a wrong pin; correct chain with the pin of the intermediate (#79: leaf only) | `go test ./internal/agent/transport/ -run TLS -count=1 -timeout 120s` | CHK-M4-322, -323, -325, -326 | W |
| CHK-M4-041 | CODE | Accepted: trusted chain without pin; trusted chain with the right pin (lowercase and uppercase hex); intermediate chain with the leaf's pin; TLS 1.2-only server works and a 1.3-capable server negotiates TLS 1.3 | same | pin compared case-sensitively | W |
| CHK-M4-042 | CODE | `ca_file` replaces the system store: with `ca_file` = CA A, a leaf from a CA that is in the system store but not in A is refused (test: `SSL_CERT_FILE`/`SSL_CERT_DIR` pointed at a bundle with CA B, server uses CA B, `ca_file` = A → refused); with `ca_file` empty the system store (CA B via `SSL_CERT_FILE`) is used → accepted | same | CHK-M4-324 (`ca_file` ignored or appended to the system pool) | W |
| CHK-M4-043 | CODE | A `ca_file` with no PEM certificate, or unreadable, makes `NewTLSConfig` return an error (no silent system store) | same | fallback to the system store on a parse error | W |
| CHK-M4-044 | CODE | No client certificate: a server with `ClientAuth: RequestClientCert` sees `len(PeerCertificates) == 0`; `tls.Config.Certificates` and `GetClientCertificate` are unset | same | none (plant: a self-signed client cert added) | W |
| CHK-M4-045 | CODE | The config has `MinVersion` ≥ TLS 1.2, `InsecureSkipVerify` false, no `VerifyPeerCertificate` that replaces verification; pin checked in `VerifyConnection` after normal verification (a wrong host name with the right pin is still refused) | same | CHK-M4-325 (pin replaces verification) | W |
| CHK-M4-046 | CODE | A pin that is not 64 hex characters is refused by `NewTLSConfig` (defence in depth behind TASK-087) | same | none | W |

## TP-M4-05 Back-off and intervals (TASK-090; REQ-095, REQ-097, REQ-098; `ag/internal/agent/schedule/schedule_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-050 | CODE | With a fake clock and seeded randomness, successive failures give nominal 10, 20, 40, 80, 160, 300, 300 … s, each actual delay inside the jitter bound (question 2), never above 300 s + bound, never 0 or negative; 100 consecutive failures never overflow (no negative or huge delay) | `go test ./internal/agent/schedule/ -count=1 -timeout 60s` | CHK-M4-338 (cap removed) | W |
| CHK-M4-051 | CODE | One success resets: the next failure is back at 10 s (± bound) | same | reset missing | W |
| CHK-M4-052 | CODE | 1,000 heartbeat intervals all in [270 s, 330 s]; min < 276 s and max > 324 s and the mean within 300 ± 3 s (uniform jitter, not constant); jitter differs between two seeds | same | jitter removed (constant 300); ± 60 | W |
| CHK-M4-053 | CODE | Pull interval: for `job_pull_seconds` 60, 300, 3,600 every interval in [p − 30, p + 30]; inputs 59, 0, −5 clamp to 60 and 3,601, 10^9 clamp to 3,600; `max_parallel_plugins` 0 → 1, 9 → 8 (if the clamp lives in TASK-090) | same | clamp missing at either end | W |
| CHK-M4-054 | CODE | The schedule uses only the injected clock and randomness: no `time.Now`, `time.Sleep`, `time.After` or global `math/rand` in non-test `schedule/` code (grep), and the fake-clock test needs no real wait (whole test < 1 s) | same plus `grep` | a `time.Sleep` inside | W |
| CHK-M4-055 | CODE | Context: a back-off wait returns promptly (< 100 ms real) when its context is cancelled | same | wait ignores the context | W |

## TP-M4-06 dpkg watcher (TASK-091; REQ-102; `ag/internal/inventory/watch_linux_test.go`)

Real inotify on a temporary directory, injected clock (the debounce uses the fake clock; inotify events are real).

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-060 | CODE | A rename onto `status` (write `status-new`, rename, as dpkg does) gives exactly one signal after 60 s of quiet (none at 59 s), with no previous upload | `go test ./internal/inventory/ -run Watch -count=1 -timeout 120s` | `IN_MOVED_TO` not watched | W |
| CHK-M4-061 | CODE | Open, write, close of `status` gives exactly one signal after 60 s quiet | same | `IN_CLOSE_WRITE` not watched | W |
| CHK-M4-062 | CODE | A storm: 50 changes spread over 10 minutes (fake clock advanced 12 s between each, so the quiet timer keeps restarting) give one signal 60 s after the last change, plus at most one more after the hold-off; never two signals less than 10 min 30 s apart (the whole timeline checked); a change during the hold-off leads to exactly one signal when the hold-off ends | same | CHK-M4-352 (no debounce); hold-off 10 min (no 30 s margin) | W |
| CHK-M4-063 | CODE | Other names cause nothing: `status-old`, `available`, `lock`, `status.tmp` created, written and renamed; a subdirectory `status/`? (not applicable); `info/foo.list` writes; `IN_MODIFY` without close | same | no name filter | W |
| CHK-M4-064 | CODE | A watch that cannot be set (missing directory, a file instead of a directory, `/proc/sys/fs/inotify/max_user_watches` exhausted simulated by an injected error) returns an error the caller can log, and does not panic or block | same | error swallowed | W, W-u |
| CHK-M4-065 | CODE | The watcher stops on context cancel within 1 s real time and closes its inotify descriptor (fd count before and after equal); no goroutine leak (goroutine count back to baseline) | same | fd leak | W |
| CHK-M4-066 | CODE | The watched path is injectable; the production default is `/var/lib/dpkg` (constant checked); the watcher takes no path from any network input (grep) | same | none | W |
| CHK-M4-067 | CODE | `IN_Q_OVERFLOW` (queue overflow) is treated as a change (one signal after the debounce), not ignored (question 8 if the implementation chooses otherwise) | same, with a tiny `max_queued_events` impossible without root: synthetic event via the parser hook | overflow ignored | W |

## TP-M4-07 D-Bus policy and package metadata (TASK-092; REQ-106; `deploy/tests/check_units_verbatim.py`, extended)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-070 | CODE | `deploy/dbus/bitscan-runner.conf` is byte-identical to TS L413–L430 (fence L412 ```` ```xml ````, L431 ```` ``` ````; `work/tasks.md` cites the block with its fences as L412–L431) with LF endings and a final newline, as the unit check does for the units; the extended script reports `IDENTICAL bitscan-runner.conf` and the existing five agent units still pass | `python deploy/tests/check_units_verbatim.py agent` | CHK-M4-362 (one character changed; a CRLF; a trailing space; an XML comment added) | L, W |
| CHK-M4-071 | CODE | The fence check guards the line numbers: if the spec lines move, the script fails with a fence error, not a silent pass | same with a copy of the spec shifted by one line | none | L |
| CHK-M4-072 | CODE | `deploy/debian/rules`: `dh_installsystemd` is called with `--no-enable` for `bitscan-runner.service` and `--no-enable --no-start` for `bitscan-capread.socket` and `bitscan-capread.service`, and with no `--no-enable` for `bitscan-runner.socket` or `bitscan-agent.service`; static parse of the `override_dh_installsystemd` target | `deploy/tests/check_debian_meta.py` (new) | CHK-M4-361 (runner service enabled; a capread unit without `--no-start`) | L, W |
| CHK-M4-073 | CODE | `control`: `Package: bitscan-agent`, `Architecture: amd64` (no `any`, no `arm64`), `Rules-Requires-Root: no`, debhelper compat 13 (`debhelper-compat (= 13)`), a `Depends` including `${misc:Depends}` and `adduser`, `${shlibs:Depends}` absent or harmless for static binaries; `changelog`: version `0.1.0~preN-1` (sorts below `0.1.0` by `dpkg --compare-versions`), a valid date; `copyright`: machine-readable DEP-5 format with a `License` stanza; `rules` is executable | same, plus `dpkg-parsechangelog`, `dpkg --compare-versions 0.1.0~pre1-1 lt 0.1.0` | `Architecture: any`; a version without `~` | W |
| CHK-M4-074 | CODE | `grep -rn arm64 deploy/debian deploy/dbus` finds nothing | `grep` | an arm64 line | L |
| CHK-M4-075 | CODE | `systemd-analyze verify` on the five agent units still reports only the "not executable" lines locally (no new errors from the package layout) | W `systemd-analyze verify deploy/systemd/bitscan-{agent,runner,capread}.*` | none | W |

## TP-M4-08 HTTP client and classification (TASK-093; REQ-094, REQ-095; `ag/internal/agent/transport/client_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-080 | CODE | Each of the five `bsa_` operations (heartbeat, jobs, results, inventory, rotate) sends exactly `Authorization: Bearer <bsa_>` and `X-Bitscan-Machine-Id: <32 hex>` (one value each), `Content-Type: application/json` where there is a body, `Content-Encoding: gzip` on inventory only; enrol sends `Authorization: Bearer <bse_>` and no `X-Bitscan-Machine-Id`; no `Cookie`, no other auth header; path and method as the manifest `routes` | `go test ./internal/agent/transport/ -count=1 -timeout 120s` | CHK-M4-329 | W |
| CHK-M4-081 | CODE | A 301, 302, 303, 307 and 308 (to a second recording server) are not followed: the second server sees no request, and the class is Drop | same | CHK-M4-327 | W |
| CHK-M4-082 | CODE | Proxy variables ignored: with `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY` and lowercase forms pointing at a recording proxy, the proxy sees nothing and the fake manager gets the request; `NO_PROXY` irrelevant | same | CHK-M4-328 (`http.ProxyFromEnvironment`) | W |
| CHK-M4-083 | CODE | Response size cap: a body of cap + 1 bytes is refused, and the client reads at most cap + 1 bytes (server counts bytes written before the client closes; or a `Content-Length` over the cap refused without reading); exactly cap bytes accepted | same | no `LimitReader`; `ReadAll` then check | W |
| CHK-M4-084 | CODE | Time limits: a server that accepts and never answers → error within the request limit (fake: limit made small through the client's options, or the real 60 s bounded by a test deadline); a server that stalls mid-body → error; a context cancel aborts at once (< 200 ms) | same | no timeout on the transport | W |
| CHK-M4-085 | CODE | `Classify` table over every status 100..599 and every problem type, plus network errors (refused connection, reset, DNS failure, timeout) and TLS verification failure: exactly the class table (expected values); 403 with an unknown or missing type is Drop; 401 with any or no type is Stop; 2xx all Success; 3xx Drop; 1xx and other 4xx (402, 405, 410, 418) Drop; every 5xx Retry; 429 Retry | same | CHK-M4-336 (403 `pending_approval` Drop), CHK-M4-337 (409 Retry) | W |
| CHK-M4-086 | CODE | No secret in errors or logs: a canary `bsa_` and `bse_` token and a canary body through every error path (TLS failure, 5xx, oversize, timeout, redirect) appear in no returned error string and no captured log output (slog handler captured at debug level) | same | CHK-M4-339 (Authorization logged at debug) | W |
| CHK-M4-087 | CODE | The token is read from the token source at request time (a token swapped between two calls is used by the second call), so rotation affects every loop | same | token captured at client construction | W |
| CHK-M4-088 | CODE | `{id}` and `{job_id}` in paths are the lowercase UUIDs; a `job_id` with path characters cannot alter the path (escaped, or refused before the call) | same | `fmt.Sprintf` of an unchecked id | W |
| CHK-M4-089 | CODE | The client refuses an `http://` base URL at construction (defence in depth behind TASK-087) | same | none | W |

## TP-M4-09 `os_info` and commands (TASK-094; REQ-100; `ag/internal/inventory/osinfo_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-095 | APP | On Ubuntu 24.04 (W), Ubuntu 22.04 and Debian 12 (W-c, PD-27), the collected `os_info` validates against `InventoryBody.os_info` (through the TP-M4-01 validator) and each field equals the value the test computes independently: `/etc/os-release` parsed by the test, `uname -r`/`-m` run by the test, `nproc` run by the test, `/proc/meminfo` `MemTotal` ÷ 1024, `/proc/uptime` (within 2 s), and the address set equals `ip -j addr` parsed by the test (with `/prefixlen`, loopback and link-local included) | `go test ./internal/inventory/ -run OSInfo -count=1 -timeout 120s` (in each container) | `memory_mb` rounded up; loopback dropped; prefix dropped | W, W-c |
| CHK-M4-096 | CODE | `raw` has exactly the keys `os_release`, `hostnamectl`, `meminfo` (`{MemTotal_kb}`), `ip_addr`, `errors`; serialised compactly it is ≤ 262,144 bytes, nests ≤ 32 containers from the body root, has no U+0000 | same | an extra key with full `/proc/meminfo` | W |
| CHK-M4-097 | CODE | A hanging command (fixture command path pointing at a script that sleeps 600 s, through the package's injectable command table in the test) is killed at its limit (fake or shortened limit; real elapsed < limit + 1 s), the process and its children are gone (no orphan in `/proc`), and the collection returns with that source's fields null and a fixed reason under `raw.errors` | same | `exec.Command` without context; child left running (no process-group kill) | W |
| CHK-M4-098 | CODE | A missing `hostnamectl` or `ip` (no candidate path exists) gives null fields and a reason, not an error for the whole collection | same | none | W-c |
| CHK-M4-099 | CODE | Over-contract values: an `os-release` with a 200-character `PRETTY_NAME`, a NUL in `ID`, a 300-address host (synthetic `ip -j addr` output through the injectable source) → the string fields null and `ip_addresses` `[]` (lead, 2026-10-24: the contract allows no null there), each with a fixed reason in `raw.errors`; a `raw` entry over the size or depth limit dropped with a reason; the body still validates | same | over-long value sent as is | W |
| CHK-M4-100 | CODE | Static check (REQ-100 (2)): over all non-test `.go` files in `ag/` the only `exec.Command`/`exec.CommandContext`/`os.StartProcess`/`syscall.Exec`/`syscall.ForkExec` uses are in `ag/internal/inventory/command.go`, their argv come from constants equal to the #35 list, and no file contains `"sh"`, `"bash"`, `"/bin/sh"` or a `"-c"` argument; the executed environment is exactly `PATH=/usr/sbin:/usr/bin:/sbin:/bin` and `LC_ALL=C` (checked by running a fake command that prints its environment) and stdin is `/dev/null` | `go test ./internal/inventory/ -run Static` plus `go vet`-style AST walk in the test | CHK-M4-344 (`sh -c`), CHK-M4-345 (argument from a job field) | W |
| CHK-M4-101 | CODE | REQ-100 (5): the collection function takes no job, heartbeat or manager-answer value; a planted job with `execute: "touch /tmp/CANARY"` passed through the inventory job path creates nothing and no argv contains the canary (exec counter records argv) | same and TP-M4-19 | CHK-M4-345 | W |
| CHK-M4-102 | CODE | Output caps: a fake command printing 2 MiB to stdout is cut or refused at its cap and the collection still returns | same | no cap | W |

## TP-M4-10 dpkg parsing, hash and body (TASK-095; REQ-100, REQ-101; `ag/internal/inventory/dpkg_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-110 | APP | Real `dpkg-query` output with the TS §3.4 format, captured on Ubuntu 24.04 (W), Ubuntu 22.04 and Debian 12 (W-c), parses to one item per line, the count equals `dpkg-query -W | wc -l`, and every field equals the line's fields; empty `Source` → null, empty `Installed-Size` → null, otherwise the integer | `go test ./internal/inventory/ -run Dpkg -count=1 -timeout 120s` | empty `Source` sent as "" | W, W-c |
| CHK-M4-111 | CODE | Edge lines: a line with 5 or 7 fields (refused for that line, counted as the plan says); a `Source` with a version in parentheses (`src (1.2-3)`) kept exactly as printed; `Installed-Size` non-numeric; non-ASCII names; a final line without `\n`; CRLF (built in code) | same | 7-field line accepted silently | W |
| CHK-M4-112 | CODE | `list_sha256` equals the manager oracle: for every valid inventory fixture (including the generated 50,000) the Go hash of its packages equals the fixture's `list_sha256` (Python `loader.list_sha256`), including the byte-order case (`Zz` before `apt`), non-ASCII names, multi-arch duplicates by name; plus `e3b0c442…b855` for the empty list | same | CHK-M4-350 (unsorted; sorted by string with a locale; `source` in the line; no final `\n`) | W |
| CHK-M4-113 | CODE | The body builder gives compact JSON, gzip-compressed; decompressed it validates against `InventoryBody` (TP-M4-01 validator) and decodes back to the same packages; duplicates are not removed (#77 (d)) | same | duplicates de-duplicated | W |
| CHK-M4-114 | CODE | A 50,000-row list builds in under 5 s and the gzip body is under 10,485,760 bytes; 50,001 rows are still sent as printed (the manager's 422 decides, #77 (d)) | same | silent truncation at 50,000 | W |

## TP-M4-11 Debconf (TASK-096; REQ-107, REQ-106; `deploy/tests/test_debconf.sh`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-120 | APP | `templates` declares the four questions; `bitscan/enrol_token` has `Type: password`; the others `string`; descriptions present | `deploy/tests/test_debconf.sh` (root, in a scratch debconf database via `DEBCONF_DB_*` overrides or a W-c container) | token as `string` | W-c |
| CHK-M4-121 | APP | A preseeded non-interactive configure (`DEBIAN_FRONTEND=noninteractive`, `debconf-set-selections`) runs `config` without prompting and leaves all four values set; the token is found only in `passwords.dat` (grep of every debconf database file for the canary token: only `passwords.dat`), and `passwords.dat` is root 0600 | same | CHK-M4-358 precursor (token in `config.dat`) | W-c |
| CHK-M4-122 | CODE | `bitscan-agent.install` maps `bitscan-agent`, `bitscan-runner`, `bitscan-capread` to `usr/sbin/` and the policy to `etc/dbus-1/system.d/`; `source/format` is `3.0 (native)` or `3.0 (quilt)` per PD-26 (one line) | `deploy/tests/check_debian_meta.py` | policy to `/usr/share/dbus-1` | L, W |

## TP-M4-12 Agent CI (TASK-097; REQ-111, REQ-105; evidence only)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-130 | CODE | `agent.yml` runs `go test ./...` on linux/amd64, runs the contract test with the shared fixtures checked out (path to `manager/tests/contract/fixtures` present in the job), keeps the stub check for `bitscan-runner` and `bitscan-capread` only, pins every action by commit and every tool by version and checksum, and `grep -n arm64 .github/workflows/agent.yml` prints nothing | `actionlint`, `grep`, reading | an arm64 line | L |
| CHK-M4-131 | CODE | Each plant turns the job red: a failing test; an altered `go.sum` line; a non-test `import "C"`; on a PR (CI, NOT RUN locally) and locally by running the job's commands in W | W: the job's `run:` lines in a copy | listed | W, CI |

## TP-M4-13 Enrolment (TASK-098; REQ-096; `ag/internal/agent/enrol/enrol_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-140 | CODE | Fake manager answering 200 `enrolled`: exactly one enrol call with body keys exactly the six, `machine_id` from the test's machine-id file, `os_*` from the test's os-release (absent → `null`), header `Authorization: Bearer <bse_>`; then `agent_id`, `token`, times written as REQ-093 (1) and `enroll.token` gone | `go test ./internal/agent/enrol/ -count=1 -timeout 120s` | CHK-M4-341 | W, W-u |
| CHK-M4-141 | CODE | Answering 200 `awaiting_approval`: files written and `enroll.token` removed the same way; the result tells the caller to start the loops (heartbeats then wait on 403, TP-M4-16) | same | `awaiting_approval` treated as failure | W |
| CHK-M4-142 | CODE | 401 (`enrollment_rejected`, `unauthorized`, none): `enroll.token` kept byte-identical, nothing written, result "stop" with the exact log line "enrolment refused; the host needs a new enrolment token" (no token in it) | same | token deleted on 401 | W |
| CHK-M4-143 | CODE | 429, 503 and a network error: retried with back-off (fake clock, delays 10, 20 …), then 200 → enrolled; the same `bse_` and body each time (#76); 400/403/409/413/422 → no retry (drop, reported) | same | no retry on 429 | W |
| CHK-M4-144 | CODE | `/etc/machine-id` (injected path) values refused before any call: 31 and 33 characters, uppercase, a UUID with hyphens, empty, missing file, trailing spaces; accepted: 32 lowercase hex with one trailing newline | same | uppercase accepted | W |
| CHK-M4-145 | CODE | Start-up decision (#81 (c)): `enroll.token` and `token` both present → enrol, then the new files replace the old ones; only `token` → no enrol; neither → refused with a message naming both files, no network call | same | `token` preferred over `enroll.token` | W |
| CHK-M4-146 | CODE | Lost response (#76): the fake drops the first response after consuming it; the retry sends the same token; a later 401 → stop with the message; a 200 `awaiting_approval` (held re-enrolment) → files written | same | none | W |
| CHK-M4-147 | CODE | Crash order (plan): a crash after writing the state and before deleting `enroll.token` leaves both; the next start enrols again (re-enrolment), never runs with a half state | same with the state fault hook | delete before write | W |
| CHK-M4-148 | CODE | A response with a `bse_` or malformed `agent_token`, an extra key, a naive time → refused, nothing written, `enroll.token` kept | same | response not strictly decoded | W |

## TP-M4-14 Token holder and rotation (TASK-099; REQ-099; `ag/internal/agent/token/rotate_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-150 | CODE | TTL 365 d, fake clock: no rotate call at day 334 23:59:59; one call on the first check at or after day 335; TTL 60 d → day 30; TTL 100 d → day 70 (TTL − 30 > TTL ÷ 2); the window is computed from the token's own times, not from settings | `go test -race ./internal/agent/token/ -count=1 -timeout 120s` | CHK-M4-348 | W |
| CHK-M4-151 | CODE | On 200: `token` and the times persisted before the holder swaps (a hook in the fake state asserts that at persist time `Current()` is still the old token, and the first request after uses the new one); every later call (heartbeat, pull, upload) uses the new token | same | CHK-M4-349 | W |
| CHK-M4-152 | CODE | Dropped response (fake closes the connection after issuing): the next attempt uses the old token and the fresh token it returns is kept; 5xx the same | same | retry with a token never received | W |
| CHK-M4-153 | CODE | Crash after the response and before the state write: on restart the old token is current and the next check rotates again (window still open) | same | none | W |
| CHK-M4-154 | CODE | Race: 2 to 16 goroutines calling `MaybeRotate` at the same instant make exactly one rotate call (fake counts), under `-race`, repeated 200 times | same | CHK-M4-347 | W |
| CHK-M4-155 | CODE | 429 with `Retry-After: 3600`: no attempt before 3,600 s; the first check after → one attempt; 403 `forbidden`: no attempt for 24 h, one after; 401 `token_expired`, `token_revoked`, `unauthorized`: stop, no further call | same | 429 retried at once; 403 retried at the next heartbeat | W |
| CHK-M4-156 | CODE | A token past `expires_at` is still sent (no local refusal) and its 401 stops the loops (REQ-099 (6)) | same | local expiry check that stops sending | W |
| CHK-M4-157 | CODE | The rotate request body is `{}` (or empty), never the token in the body; the token never appears in a log line or error (canary) | same | token logged on persist failure | W |
| CHK-M4-158 | CODE | Only a successful heartbeat triggers `MaybeRotate` (checked in TP-M4-16); a failing persist leaves the old token current and logs one fixed line | same | swap on persist failure | W |

## TP-M4-15 Maintainer scripts (TASK-100; REQ-108, REQ-107; `deploy/tests/test_maintainer_scripts.sh`)

Runs on a systemd host: W (Ubuntu 24.04, systemd on) with the built `.deb`, and W-c `debian:12` with systemd for the Debian half; each run starts from a purged state and asserts with `stat -c '%U:%G %a'`, `systemctl is-enabled/is-active`, `getent passwd`, `debconf-show`, `grep` on the debconf databases.

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-165 | APP | Fresh install with preseed: users `bitscan`, `bitscan-runner` exist, system uids, shell `/usr/sbin/nologin`, home not created; `/etc/bitscan/agent.yaml` root:bitscan 0640 with the URL and no token; `/var/lib/bitscan-agent` bitscan:bitscan 0700; `enroll.token` bitscan:bitscan 0600 holding the token | `deploy/tests/test_maintainer_scripts.sh install` | CHK-M4-357 | W, W-c |
| CHK-M4-166 | APP | After install: `db_get bitscan/enrol_token` empty and the canary token in no debconf file | same | CHK-M4-358 | W, W-c |
| CHK-M4-167 | APP | Unit states after install: `bitscan-runner.socket`, `bitscan-agent.service` enabled and active (the agent may be active in back-off against no manager); `bitscan-runner.service` not enabled; both capread units neither enabled nor active | same | CHK-M4-361 | W, W-c |
| CHK-M4-168 | APP | Missing URL, then missing token (each separately): `apt install`/`dpkg -i` exits non-zero, stderr has one line naming the missing input, `dpkg -s` shows `half-configured` (or `unpacked`), no bitscan service active, no `agent.yaml` with partial content | same `missing` | `set -e` removed and the failure ignored (G38 plant) | W, W-c |
| CHK-M4-169 | APP | `install.env` route: a root:root 0600 file with the inputs → installs, the file is gone; the same file at 0644 or owned by a user → refused with a clear message, package unconfigured, the file left or removed per the plan (question 10) | same `installenv` | 0644 accepted | W |
| CHK-M4-170 | APP | `BITSCAN_ENROL_TOKEN=…`, `BITSCAN_MANAGER_URL=…` and the debconf-style names exported in the environment of `apt install` without a preseed: ignored, the install fails as "missing" | same | CHK-M4-359 | W |
| CHK-M4-171 | APP | Reinstall (`apt install --reinstall`) twice: no error; config, token and agent id unchanged | same `reinstall` | non-idempotent `adduser` | W, W-c |
| CHK-M4-172 | APP | Upgrade to a newer 0.x build twice (same tree, changelog bumped in the test copy): no input asked; `agent_id`, `token`, `agent.yaml` byte-identical (sha256); services restarted (new `ActiveEnterTimestamp`) | same `upgrade` | upgrade rewrites `agent.yaml` | W, W-c |
| CHK-M4-173 | APP | `apt remove` twice: units stopped and disabled, config and state kept; `apt purge` twice: `/var/lib/bitscan-agent`, `agent.yaml`, `install.env` gone, a planted `/etc/bitscan/manager.env` and `/etc/bitscan/secrets/x` survive (and `/etc/bitscan` stays); without them `/etc/bitscan` is removed; debconf answers purged; users kept | same `purge` | CHK-M4-360 | W, W-c |
| CHK-M4-174 | APP | #81 re-enrolment: `dpkg-reconfigure bitscan-agent` with a new preseeded token writes `enroll.token` (0600) and restarts the agent; `agent.yaml` unchanged | same `reenrol` | none | W |
| CHK-M4-175 | APP | Input validation in `postinst`: `http://` URL, a token not of the `bse_` form, a missing `ca_file` path, a 63-hex pin → refused with a clear line, package unconfigured | same `invalid` | URL not validated | W |
| CHK-M4-176 | CODE | `shellcheck` clean on `postinst`, `postrm`, `config` (if available in W); `set -e` present; no variable path in `rm -rf` | `shellcheck`, `grep` | `rm -rf "$DIR"` | W |
| CHK-M4-177 | APP | The token never appears in the `postinst` output, `/var/log/dpkg.log`, `journalctl` of the install, or `ps` during install (a probe sampling `/proc/*/cmdline` while installing) | same | token passed as an argument | W |

## TP-M4-16 Run state and heartbeat (TASK-101; REQ-097, REQ-095, REQ-103; `ag/internal/agent/loops/heartbeat_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-185 | CODE | Fake clock, fake manager: the first heartbeat at start, then 20 more, each interval in 270..330 s; each body validates against `HeartbeatRequest` and has the #78 values (`spool_bytes` 0, `clock` = fake now, `uptime_s` = fake now − start, `last_pull_at` null before any 200 pull, `current_job_id` null) | `go test -race ./internal/agent/loops/ -run Heartbeat -count=1 -timeout 120s` | `last_pull_at` set on a failed pull | W |
| CHK-M4-186 | CODE | `runner_helpers`: with a planted socket file at the injected `capread.sock` path → `["capread"]`; removed → `[]` in the next heartbeat; a regular file there? (question 11) | same | helpers constant | W |
| CHK-M4-187 | CODE | A heartbeat response with `job_pull_seconds` 60 makes the next pull 30..90 s later; 3,601 clamps to 3,600 at the agent (fake manager sends out-of-contract values only if decoding allows: the decoder refuses 3,601, so the clamp is tested on the Run API); `max_parallel_plugins` stored | same | interval not applied | W |
| CHK-M4-188 | CODE | A heartbeat response never triggers any other call: over 50 heartbeats with varied responses the fake sees only heartbeats (and rotate when the window is open, which is the rotation rule), and pulls only at their own timer | same | CHK-M4-355 | W |
| CHK-M4-189 | CODE | A 401 on the heartbeat, and a 401 on a pull, each stop both loops within 1 s (fake clock advanced by hours afterwards: zero further calls); the re-enrol line logged once; the process (Run) stays up and idle (no exit) | same | CHK-M4-335 | W |
| CHK-M4-190 | CODE | 403 `pending_approval`: heartbeats continue with back-off 10, 20 … s (not the 300 s timer, question 12); once the fake answers 200, the next heartbeat succeeds without restart and the normal interval resumes; the pull loop waits too | same | `pending_approval` dropped | W |
| CHK-M4-191 | CODE | 503 and network errors: back-off 10, 20, 40 … s capped at 300 s, reset after a success (REQ-095 (2)); 429 the same, never a tight loop (≥ 10 s between calls) | same | CHK-M4-338 | W |
| CHK-M4-192 | CODE | `last_error`: a drop (for example 409 on an upload) appears in the next heartbeat as `"<route> <status> <type>"` (≤ 1,024 characters) and is null in the one after | same | not cleared | W |
| CHK-M4-193 | CODE | Context: cancelling the run context stops both loops within 1 s real time with no goroutine left | same | none | W |

## TP-M4-17 `.deb` build (TASK-102; REQ-106, REQ-109; `deploy/tests/test_build_deb.sh`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-200 | APP | Two builds in fresh work folders (separate `GOCACHE`, `GOPATH`, clean copies at different absolute paths) give identical `sha256sum` for the three binaries and the `.deb` | `deploy/tests/test_build_deb.sh repro` | CHK-M4-363 | W |
| CHK-M4-201 | APP | `dpkg-deb -c` lists exactly the REQ-106 files plus `/usr/share/doc/bitscan-agent/{changelog.Debian.gz,copyright}`; binaries 0755 root:root, units and the policy 0644; the units and the policy inside the `.deb` (`dpkg-deb -x`) pass the verbatim check | same `contents` | a unit at 0755 | W |
| CHK-M4-202 | APP | `file` on each binary: ELF 64-bit LSB, x86-64, statically linked; no `.interp`; no arm64 artifact anywhere in the output folder; `dpkg-deb -f … Architecture` = `amd64` | same | `CGO_ENABLED=1` | W |
| CHK-M4-203 | APP | The SBOM (CycloneDX JSON) lists every module `go version -m` prints for each binary, with the same versions, and the Go version | same `sbom` | CHK-M4-364 | W |
| CHK-M4-204 | APP | The `.sha256` file passes `sha256sum -c` against the `.deb`; a one-byte change to the `.deb` fails it | same | none | W |
| CHK-M4-205 | APP | `lintian` on the `.deb`: no error and no warning; every override listed in the package with a reason | `lintian --fail-on error,warning` | G37 plants (unit 0755; copyright missing) | W, CI |
| CHK-M4-206 | APP | `go version -m` shows `-trimpath`, `CGO_ENABLED=0`, `-buildvcs=false`, and the version string from the changelog; `strings` on the binaries finds no absolute path of the build folder | same | `-trimpath` removed | W |

## TP-M4-18 Pull and job checks (TASK-103; REQ-098, REQ-104; `ag/internal/agent/loops/pull_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-215 | CODE | Fake clock: 20 pulls each `job_pull_seconds` ± 30 s apart; an empty `jobs` list causes no other call (no results, no upload, no extra pull) and no collection (exec counter 0) | `go test -race ./internal/agent/loops/ -run 'Pull|Job' -count=1 -timeout 120s` | an extra pull after an empty list | W |
| CHK-M4-216 | CODE | Refused and not run (no upload, no results call, exec counter 0), each logged with a fixed reason and recorded as seen: a job for another `agent_id` (also the same id in uppercase is **not** foreign, question 13); `pickup_by` = now, now − 1 s; `pickup_by` = now + 25 h + 1 s (now + 25 h exactly accepted); a job id seen before (same pull, earlier pull, and after closing and re-opening the state: restart) | same | CHK-M4-330, -331, -332, -333 | W |
| CHK-M4-217 | CODE | Seen after 7 days: a job id seen at t0 and pulled again at t0 + 7 d + 1 s is accepted (forgotten), at t0 + 7 d − 1 s refused | same | CHK-M4-334 | W |
| CHK-M4-218 | CODE | The id is persisted as seen before the job is acted on (a fault hook that fails the action leaves the id seen; a crash injected after the seen write and before dispatch does not run it on restart) | same | seen written after dispatch | W |
| CHK-M4-219 | CODE | An accepted inventory job leads to exactly one `RunJob(job_id)` on the inventory runner, at once (before the next compliance job finishes), alongside a compliance job | same | inventory queued behind compliance | W |
| CHK-M4-220 | CODE | An accepted compliance job (#74) produces exactly one results POST to `/jobs/{job_id}/results` with `final: true` and one item per plugin with `error` `runner_unavailable`, `exit_code` null, `stdout`/`stderr` "", `timed_out`/`truncated` false, `started_at` = `finished_at` = fake now (the body validates against `ResultsRequest`); no other call; the exec counter is 0; no connection to `runner.sock` (path injected, a listening test socket there sees no connection); the M3 409 answer is dropped and becomes `last_error` | same | CHK-M4-356 (exec), a start-notice-only post | W |
| CHK-M4-221 | CODE | A compliance job with 5,000 plugins yields results batches of at most 50 items and 1.5 MB each, the last with `final: true` (question 14: one batch per #74 versus TS §3.5 batches) | same | one 5,000-item batch | W |
| CHK-M4-222 | CODE | Jobs are handled in pull order, compliance one at a time; at most 10 per pull (the decoder refuses 11) | same | none | W |
| CHK-M4-223 | CODE | No job from any other source: the only producer of jobs is the pull response (static: `ComplianceHandler.Handle` and `RunJob` are called only from `jobs.go`); a heartbeat response with extra fields is refused by the decoder (TP-M4-01) | grep plus same | CHK-M4-345 (an argument from a job field) | W |
| CHK-M4-224 | CODE | Job `execute` canaries never appear in any log, error, state file or upload body; the agent stores no plugin command (state directory listed after the job: only the seen-ids file changed) | same | job body persisted | W |

## TP-M4-19 Inventory jobs and watcher uploads (TASK-104; REQ-101, REQ-102, REQ-100; `ag/internal/agent/loops/inventory_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-235 | CODE | A job upload is `PUT /api/v1/agent/{id}/inventory?job_id=<id>` with `Content-Encoding: gzip`; the fake decompresses, validates against `InventoryBody`, recomputes `list_sha256` from the body and it matches (also with non-ASCII and multi-arch packages) | `go test -race ./internal/agent/loops/ -run Inventory -count=1 -timeout 120s` | CHK-M4-350, -351 | W |
| CHK-M4-236 | CODE | 503 then 204: retried with back-off (10 s, then 20 s …) with the same `job_id` and the same body bytes; succeeds; no retry after 204 | same | no retry on 503 | W |
| CHK-M4-237 | CODE | 409, 413, 422: no retry, `last_error` in the next heartbeat (`"inventory 422 about:blank"` form) | same | CHK-M4-337 (409 retried) | W |
| CHK-M4-238 | CODE | Watcher signals → unscheduled uploads without `job_id`, never closer than 10 min 30 s (fake clock, 30 signals over 2 h); a 429 on an unscheduled upload is retried with back-off and the retries also never make two accepted uploads within 10 min; a newer signal replaces a pending one (the latest state sent) | same | CHK-M4-352 | W |
| CHK-M4-239 | CODE | A job upload's retries stop 30 minutes after the job was received (fake clock), with one log line | same | endless retry | W |
| CHK-M4-240 | CODE | A watcher that fails to start leaves scheduled inventory jobs working (REQ-102 (4)) | same | none | W |
| CHK-M4-241 | CODE | 401 on an upload stops all loops (as CHK-M4-189) | same | none | W |

## TP-M4-20 Package CI (TASK-105; REQ-111, REQ-109; evidence only)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-250 | CODE | `package.yml` has the build twice, lintian, install tests on `ubuntu-22.04`, `ubuntu-24.04` and a systemd `debian:12` container, SBOM, SHA-256, verbatim and `systemd-analyze verify` steps; pinned actions and tools; no arm64 (`grep -n arm64 .github/workflows/` empty) | `actionlint`, `grep` | an arm64 matrix entry | L |
| CHK-M4-251 | CODE | Each planted failure (a lintian error, a build timestamp, an altered unit, a failing install test, a module missing from the SBOM) turns the job red: locally by running the job's steps in W on copies; on a PR in CI (NOT RUN until pushed) | W | listed | W, CI |

## TP-M4-21 Binary-level run (TASK-106; REQ-103, REQ-096; `ag/cmd/bitscan-agent/main_test.go`, `e2e/agent_unit.sh`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-260 | APP | The built binary (paths injected by test-only flags or environment that the production unit does not set, question 15) against the fake manager: enrols, heartbeats, pulls, uploads inventory for an inventory job | `go test ./cmd/bitscan-agent/ -count=1 -timeout 300s` | none | W, W-u |
| CHK-M4-261 | APP | `SIGTERM` during a heartbeat, a pull and an upload (the fake holds each request open): exit 0 within 5 s real time; no `.tmp` or partial state file left; state files complete | same | context not passed into the request | W |
| CHK-M4-262 | APP | Canary sweep: a run that enrols, rotates and uploads with canary tokens, package names and `raw` values: no canary in stdout, stderr or (W, under the unit) `journalctl -u bitscan-agent` | same, `e2e/agent_unit.sh` | CHK-M4-339 | W |
| CHK-M4-263 | APP | Start-up refusals exit non-zero before any network call (fake sees nothing) with one line naming the key or file: bad `agent.yaml`, bad machine-id, neither `token` nor `enroll.token` | same | none | W |
| CHK-M4-264 | APP | Under the verbatim `bitscan-agent.service` (W, systemd, user `bitscan`, `ProtectSystem=strict`) against the fake manager on loopback with a test CA in `ca_file`: the run enrols, heartbeats and uploads; files changed only under `/var/lib/bitscan-agent` (a `find / -xdev -newer` sweep of writable paths, excluding `/proc`, `/sys`, `/run/systemd`, journal); `ss -ltnup` shows no socket owned by the agent; the process has no capabilities (`CapEff` 0) | `e2e/agent_unit.sh` | CHK-M4-346 (`net.Listen`) | W |
| CHK-M4-265 | APP | `--version` (or the start log line) shows the build version from `-ldflags -X main.version`; no secret in it | same | none | W |
| CHK-M4-266 | APP | Idle cost measured (no gate): CPU over 30 min idle and RSS after 1 h with an empty job list, recorded in the report | `e2e/agent_unit.sh idle` | none | W |

## TP-M4-22 Runbook (TASK-107; REQ-110; evidence only)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-275 | APP | Every runbook step followed on a clean Ubuntu 24.04 (fresh WSL distro or `ubuntu:24.04` systemd container) against the real M3 manager: `sha256sum -c`, preseed and install, deleting the preseed, NTP check, cloned image (`/etc/machine-id` regenerated → new agent), pinning and private CA, #81 re-enrolment, uninstall and purge; each behaves as written | manual walk-through, commands logged | none | W |
| CHK-M4-276 | CODE | The runbook holds no real token or secret (TS §8.6 patterns, `bse_`/`bsa_` with a 43-character body), no process notes (task ids, agent names), and states 0.x is a pre-release | `grep` | none | L |

## TP-M4-23 M4 gate against the real manager (G41; `e2e/agent_manager.sh`, `ag/internal/agent/security_test.go`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-311 | APP | The installed `.deb` against the real M3 manager in WSL: `bse_` created with a TOTP session → install with preseed → enrolment held → approve → heartbeat → inventory job → upload → `GET /api/v1/agents/{id}` shows `os_info` and the snapshot → a `dpkg` change → unscheduled upload (≥ 10 min 30 s after the previous one, fake time not available: the test waits or uses a manager-side setting only if one exists) → revoke → 401 stops the loops (journal line; no call afterwards in the manager access log) | `e2e/agent_manager.sh` | the agent sending `list_sha256` unsorted (manager 422, chain stops) | W |
| CHK-M4-312 | CODE | `security_test.go` gathers the TS §8.3 Security agent rows: expired, foreign and replayed jobs (also across restart), a certificate that fails verification or its pin; G36 = `go test ./internal/agent/... -run 'Security|TLS|Job'` | `go test ./internal/agent/... -run 'Security|TLS|Job' -count=1` | the G36 mutation rows | W |

## TP-M4-24 Manager carry-over (TASK-085; REQ-112; `manager/tests/test_inventory_upload_unit.py`)

| Check | Type | What | Command | Planted violation | Where |
| --- | --- | --- | --- | --- | --- |
| CHK-M4-280 | CODE | Unit tests with fake stores cover every `upload.py` branch with no database: the #72 (d) `job_id` cases (dispatched → completed; failed and completed → unscheduled; unknown, foreign, compliance, queued, expired, cancelled → 409 with an audit entry and nothing stored), 413 and 422 failing a dispatched job with one `agent.inventory_refused`, 400 leaving the job, the 10-minute window | W `pytest tests/test_inventory_upload_unit.py` (`CI=true`) | CHK-M4-366 | W |
| CHK-M4-281 | APP | The TASK-074 inventory route suites pass unchanged (PostgreSQL, W, coordinated with `tester-h`) | W targeted pytest | CHK-M4-366 | W |
| CHK-M4-282 | CODE | `manager/openapi.json` byte-identical (G6) | export and `cmp` | none | W |
| CHK-M4-283 | CODE | The two README sentences: old token after an approved re-enrolment → 401 `unauthorized`; operator calling approve → 403 `totp_session_required`, matching the M3 route tests that assert those answers | `grep` plus the named tests | none | L |
| CHK-M4-284 | CODE | ruff, ruff format, `mypy --strict` on the changed files | L | none | L |

## Gate checks (M4 gate)

| Check | Gate | Command | Planted violation | Where |
| --- | --- | --- | --- | --- |
| CHK-M4-300 | G7 | `gofmt -l agent` prints nothing | one misformatted line in `ag/internal/agent/loops/run.go` | W, L |
| CHK-M4-301 | G8 | `cd agent && golangci-lint run ./...` plus the nolint grep, on Linux | `net.Listen` in `run.go` (CHK-M4-346); `InsecureSkipVerify` in `tls.go` (CHK-M4-321); a `//nolint` | W |
| CHK-M4-302 | G9 | `cd agent && go mod verify` | CHK-M4-365; a modified module-cache file | W |
| CHK-M4-303 | G10 | `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/...`, `file` static check, cgo listing | a non-test file with `import "C"` | W, CI |
| CHK-M4-304 | G11 | `cd agent && go test ./...` on linux/amd64, reported as passed/total | a planted failing test | W, CI |
| CHK-M4-305 | G17 | the verbatim check (units and D-Bus policy), then `systemd-analyze verify` | CHK-M4-362; `ProtectHome=yes` removed from the agent unit | W, CI |
| CHK-M4-306 | G36 | `go test ./internal/agent/... -run 'Security|TLS|Job'` | every G36 row of the mutation table | W, CI |
| CHK-M4-307 | G37 | `lintian` | unit file 0755; missing `copyright` | W, CI |
| CHK-M4-308 | G38 | `deploy/tests/test_maintainer_scripts.sh` | `set -e` removed with a failing step ignored; purge of all of `/etc/bitscan` | W, CI |
| CHK-M4-309 | G39 | two clean builds, identical hashes | a timestamp in the version; `-trimpath` removed | W, CI |
| CHK-M4-310 | G40 | SBOM equals `go version -m` | a module dropped | W, CI |
| CHK-M4-311 | G41 | `e2e/agent_manager.sh` | unsorted `list_sha256` | W |

## Security mutation table

As `work/tasks.md` CHK-M4-320 to -366 (plant, red in, owner); each row is planted in `/root/bitscan-m4-mut/<chk>` against the code of its owning task when that task is under TEST, run with `-count=1` against only its covering test files, and recorded with the failing test name. Rows are re-planted at the gate only if their target code changed after they were proven red. Mapping to the checks above:

| CHK | Covering checks |
| --- | --- |
| 320 | CHK-M4-021 (and the binary refusal CHK-M4-263) |
| 321 | CHK-M4-301 (lint), CHK-M4-045 |
| 322, 323, 325, 326 | CHK-M4-040, -045 |
| 324 | CHK-M4-042 |
| 327, 328, 329 | CHK-M4-081, -082, -080 |
| 330 to 334 | CHK-M4-216, -217, -034 |
| 335 | CHK-M4-189 |
| 336, 337 | CHK-M4-085, -237 |
| 338 | CHK-M4-050, -191 |
| 339 | CHK-M4-086, -262 |
| 340 | CHK-M4-030 |
| 341 | CHK-M4-140 |
| 342 | CHK-M4-023 |
| 343 | CHK-M4-021 |
| 344, 345 | CHK-M4-100, -101, -223 |
| 346 | CHK-M4-301, -264 |
| 347, 348, 349 | CHK-M4-154, -150, -151 |
| 350 | CHK-M4-112, -235, -311 |
| 351 | CHK-M4-235, -311 |
| 352 | CHK-M4-062, -238 |
| 353, 354 | CHK-M4-013, -017, -012 |
| 355 | CHK-M4-188 |
| 356 | CHK-M4-220 |
| 357 to 361 | CHK-M4-165, -166, -170, -173, -167 |
| 362 | CHK-M4-070, -305 |
| 363, 364 | CHK-M4-200, -206, -203 |
| 365 | CHK-M4-027, -302 |
| 366 | CHK-M4-280, -281 |

## Questions for `main` (asked 2026-10-24)

All answered on 2026-10-24: 1, 3 and 5 as noted below; 2, 4, 6 to 15 ruled as proposed (`work/decisions.md` 2026-10-24 "M4 W1 lead rulings"; 7 = fail closed). The checks use the proposed values.

1. **Answered (main, 2026-10-24, decisions G35 rulings (2)):** the three schema-valid fixtures the manager decoder refuses (hash mismatch, duplicate package, raw 256 KiB + 1) decode and re-encode like valid ones; the Go `Validate()` accepts the first two; nothing is asserted on the third.
2. TASK-090: the back-off jitter bound is not in the spec or the plan. Proposed: each delay within ±10 % of its nominal value (10, 20, 40, 80, 160, 300), never above 330 s. To confirm with the TASK-090 implementation's documented bound before the TEST.
3. **Answered (main, 2026-10-24, G35 rulings (3)):** `lone surrogate` fixtures: assert nothing; `nan_inf` fixtures: assert the parse error, as the manifest says.
4. `agent.yaml`: is `HTTPS://` (uppercase scheme) accepted, and are `log_level` values case-sensitive (`INFO`)? Proposed: scheme case-insensitive per RFC 3986, `log_level` exact lowercase.
5. **Answered (main, 2026-10-24, G35 rulings (1)):** impl-agent adds the test-only validator `santhosh-tekuri/jsonschema/v6` (pinned) in TASK-087; the stdlib fixture half of TP-M4-01 is written now and the schema half (CHK-M4-015) lands behind it (NOT RUN until TASK-087's `go.mod` has it).
6. Seen ids: forgotten at exactly 7 days or after (`>` vs `≥`)? Proposed: the boundary second is not asserted; 7 d − 1 s seen, 7 d + 1 s forgotten.
7. A corrupt or unreadable seen-ids file at start-up: refuse to start, or start with an empty set (which would allow a replay)? Proposed: refuse at start-up (fail closed).
8. Watcher: an inotify queue overflow (`IN_Q_OVERFLOW`): proposed: treated as a change.
9. More than 256 addresses on a host: cut to 256 with a reason, or `ip_addresses` null with a reason (#77 (d) says "sent as null")? Proposed: per #77 (d), null plus a reason. **Superseded (lead, 2026-10-24):** `[]` with a fixed `raw.errors` reason, because the contract does not allow null.
10. `install.env` with wrong mode or owner: leave the file in place (so the admin can fix it) or delete it? Proposed: leave it.
11. #30 detection: does a regular file (not a socket) at `/run/bitscan/capread.sock` count? Proposed: "the path exists" as #30 says, so yes.
12. 403 `pending_approval` on the heartbeat: back-off from 10 s (REQ-095) rather than the 300 s timer? Proposed: back-off, as REQ-095 and REQ-096 (2) say.
13. A job whose `agent_id` is the agent's own id in uppercase: same id (UUIDs either case on input), so accepted? Proposed: accepted.
14. #74 with more than 50 plugins: "one final results batch" versus TS §3.5's 50-result batches; proposed: batches of ≤ 50, only the last with `final: true` (the 5,000-plugin job could not be one valid batch).
15. TASK-106 binary-level tests need injectable paths (`/etc/bitscan/agent.yaml`, `/etc/machine-id`, `/run/bitscan/capread.sock`): through test-only flags, environment variables, or only under the unit with real paths? A production environment override would be a new input; proposed: real paths only in W under the unit (CHK-M4-264), and package-level tests elsewhere.
