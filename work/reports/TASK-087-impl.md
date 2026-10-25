# TASK-087 IMPL: `agent.yaml` loader and the first Go dependencies

REQ-092, REQ-105. TS §3.6 (L257–L267), §3.1 (L160), §3.3 (L206); #4 as made concrete in the M4 re-check (`work/open-questions.md`); PD-25 (a); lead rulings 2026-10-24 (the scheme is case-insensitive and `log_level` must be exact lowercase; `jsonschema/v6` is added here as a test-only dependency). **Two approvals (TS §8.2, agent).**

No tests were run (that is the tester's job). I checked the behaviour with a throwaway copy of the module outside the tree; it is deleted (results below).

## Files

| File | What |
| --- | --- |
| `agent/internal/agent/config/config.go` (new, about 180 non-comment lines) | `Load(path)`, `Parse(data)`, `Config`, and the constants `Path`, `StateDir` and `HeartbeatSeconds`. |
| `agent/go.mod` | Requires `go.yaml.in/yaml/v3 v3.0.5` (linked into `bitscan-agent` once TASK-106 imports `config`) and `github.com/santhosh-tekuri/jsonschema/v6 v6.0.3` (test-only, for TP-M4-01). `golang.org/x/text v0.14.0` is indirect, from jsonschema. |
| `agent/go.sum` | Hashes for those modules plus `github.com/dlclark/regexp2 v1.11.0` (jsonschema's own test dependency). This is exactly what `go mod tidy` writes once a `_test.go` imports jsonschema (checked in a scratch copy). |

No file outside the task's list changed.

## Rules (#4 and the lead rulings)

| Key | Rule | Default |
| --- | --- | --- |
| `manager_url` | Required. It must parse as a URL with scheme `https` (in any case, because `url.Parse` lower-cases it) and a non-empty host. `http://`, a missing value, `https://:8443` and an opaque URL are refused. The value is kept as written. | none |
| `ca_file` | A path, or empty or null for the system store. `Load` refuses a non-empty path that cannot be opened or is not a regular file (REQ-092 (5)). | `""` |
| `manager_spki_sha256` | Empty, or 64 hex characters in either case, stored lowercase (#79). An all-digit pin, which YAML resolves as an integer, is read as text. | `""` |
| `state_dir` | Only `/var/lib/bitscan-agent`. | that |
| `heartbeat_seconds` | Only `300`. | 300 |
| `job_pull_seconds` | 60–3600, used until a heartbeat gives the manager's value. | 300 |
| `max_parallel_plugins` | 1–8, likewise. | 2 |
| `spool_max_mb` | 1–50. | 50 |
| `log_level` | Exactly `debug`, `info`, `warn` or `error` (lowercase). | `info` |

General parsing rules:

- **Exactly one YAML document**, whose top level is a mapping.
- **Each key at most once.** An unknown key (`inventory: false`) is refused.
- **Values must be scalars.** Sequences, mappings and aliases are refused.
- **Integer keys need a YAML `!!int`**, so `300.0`, `"300"` and `true` are refused.
- **An empty file** loads the defaults and then fails on the missing `manager_url`.

Every refusal is one line, `agent.yaml: <key>: <reason>` (or `agent.yaml: malformed YAML: <the yaml library's one-line message>`), with no value echoed. An unknown key is named only if it is printable ASCII of at most 64 characters, otherwise `(unprintable key)`.

The package only reads: `os.ReadFile` of the given path and `os.Open` of `ca_file`. There is no write call in it (REQ-092 (4), CHK-M4-342). `Load(path)` takes the path so tests can use a temporary file; production passes `config.Path`. The clamping of the manager's heartbeat values (REQ-092 (3)) belongs to TASK-090 and TASK-101, not here.

## Scratch run (evidence, not a test)

- The TS §3.6 example block, comments included, loads to exactly `{https://mgr.example:8443, "", "", /var/lib/bitscan-agent, 300, 300, 2, 50, info}`.
- Each of these was refused with one line naming the key: `http://`, a missing URL, `inventory: false`, `job_pull_seconds: 59`, `job_pull_seconds: 300.0`, `max_parallel_plugins: 9`, `spool_max_mb: 51`, `heartbeat_seconds: 60`, `state_dir: /tmp`, `log_level: INFO`, `log_level: trace`, a duplicate key, a second document, a top-level list, a bad pin, and unclosed `[` (malformed).
- Accepted: `HTTPS://Mgr.Example:8443` with an all-digit 64-character pin, and `ca_file:` (null) as empty.

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l .`: prints nothing.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./...` and `go build ./...`: clean.
- `GOOS=linux golangci-lint run ./...`: `0 issues`. There is no `//nolint` in the tree: gosec G304 is satisfied with `filepath.Clean`.
- `go mod verify`: `all modules verified`.
- Scratch copy with a `_test.go` importing jsonschema: `go vet` was clean and `go mod tidy` left `go.mod` and `go.sum` unchanged.
- `go version -m` of a linux/amd64 `bitscan-agent` build lists no dependency module. The binary is still the M0 stub until TASK-106; after that only `go.yaml.in/yaml/v3` should appear (REQ-105 (3)).

## For the tester

- TP-M4-02: `config.Parse([]byte)` covers the key rules without a file. `config.Load(tmpPath)` covers the read error and the `ca_file` checks (a missing path, a directory, an unreadable file as the non-root `bstester` user).
- G9 plants: changing one `h1:` hash in `agent/go.sum` makes `go mod verify` fail, and so does editing a file under `$(go env GOMODCACHE)/go.yaml.in/yaml/v3@v3.0.5/`, in a throwaway module cache.
- `jsonschema/v6` is ready for `agent/internal/agent/wire/contract_test.go` (TP-M4-01).
- For impl-deploy (TASK-102 SBOM and `copyright`): the linked module is `go.yaml.in/yaml/v3 v3.0.5`.

## Revision 1 (TEST FAIL r1: `TestLoadCAFile/a_FIFO_(must_not_block)`)

Cause: `readableFile()` called `os.Open` before checking the file type, and opening a FIFO for reading blocks until a writer appears, so `config.Load` hung.

Fix, in `agent/internal/agent/config/config.go` only (`readableFile`, plus the `syscall` import):

1. `os.Stat` the cleaned path first (it follows symlinks, so a symlinked CA bundle still works) and refuse anything that is not a regular file before any open: `ca_file: not a regular file`. A missing path still gives `ca_file: cannot open the file`.
2. Open with `O_RDONLY|O_NONBLOCK`, so a path swapped to a FIFO between the stat and the open cannot block.
3. `Stat` the open file again and refuse a non-regular file, so the swap is still refused.

The error texts are unchanged. No other file changed.

Gates (Windows, Git Bash, from `agent/`): `gofmt -l .` prints nothing; `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./internal/agent/config/` clean; `GOOS=windows go build ./internal/agent/config/` clean; `GOOS=linux golangci-lint run ./internal/agent/config/...` 0 issues.

For the tester: re-run only `TestLoadCAFile` (the FIFO subtest and its siblings share `readableFile`: the character device, a directory, a missing path and the unreadable file).

Note outside this task: `transport/tls.go` (TASK-089) reads `ca_file` with `os.ReadFile` at TLS set-up. Since `config.Load` runs first, it can only meet a FIFO if root swaps the file in `/etc/bitscan` after start-up checks; flagged for the reviewer, not changed here.
