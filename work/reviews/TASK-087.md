# TASK-087 REVIEW: agent.yaml loader and the first Go dependencies

Verdict: APPROVED

Reviewer: reviewer, 2026-10-24. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed:
- `agent/internal/agent/config/config.go` (revision 1: the FIFO fix), `agent/go.mod` and `agent/go.sum` (`work/reports/TASK-087-impl.md`).
- Checked against TS §3.6, §3.1 L160, §3.3, #4 (agreed 2026-10-24), PD-25 (a), and the lead rulings: a case-insensitive scheme, an exact lowercase `log_level`, and jsonschema as a test-only dependency.

TEST: FAIL in round 1 (the FIFO `ca_file` hung `Load`). PASS on r1 from tester-m4, by message:
- the FIFO subtest re-runs 1/1;
- the package runs 98/98 as root, plus a `bstester` run;
- 15/15 plants are red, including CHK-M4-320, -342 and -343.

## Checks
1. Spec and #4: these match exactly.
   - All nine TS §3.6 keys are present.
   - `state_dir` and `heartbeat_seconds` are fixed; `job_pull_seconds` is 60–3600, `max_parallel_plugins` 1–8, `spool_max_mb` 1–50, and `log_level` must be `debug`, `info`, `warn` or `error`.
   - `manager_url` must be https with a host, and the scheme may be in any case. The pin is empty or 64 hex characters, stored lowercase (#79).
   - Unknown keys, duplicate keys, a second document, non-scalar values, aliases and non-`!!int` integers are all refused.
   - Nothing can turn inventory off: `inventory: false` is an unknown key (G2).
2. Security:
   - The package only reads; the tester has a static check that `OpenFile` is used with `O_RDONLY` only.
   - No environment input (TestNoEnvironmentOverride also covers `Load`).
   - Each refusal is one line that names the key, with no value. A key is named only when it is printable ASCII of at most 64 characters.
   - `ca_file` checks: `Stat` refuses a non-regular file before any open. The open is non-blocking, and `Stat` runs again on the open file, so a FIFO or device swapped in between is refused without blocking.
   - Dependencies: `go.yaml.in/yaml/v3` is the only linked module. `jsonschema/v6` and `x/text` are test-only. `go.sum` matches `go mod tidy`.
3. Scope: 3 files, inside the task.
4. Tests: the TS §3.6 block is read from the spec and loads exactly. There are 63 refusals and 22 accepted boundaries, an alias bomb, CRLF input, a digit-only pin, and the `ca_file` matrix (missing, directory, FIFO, character device, unreadable as `bstester`). 15 plants are red.
5. Re-run by the reviewer (Windows):
   - `GOOS=linux go vet ./internal/agent/config/`: clean.
   - `GOOS=linux golangci-lint run ./internal/agent/config/...`: 0 issues.
   - `go mod verify`: all modules verified.
   - `gofmt` shows no file of this task. The only file it lists is TASK-093's `transport/client_test.go`.

## Findings
1. nit, `config.go:191`. `manager_url` accepts userinfo, a query and a fragment, for example `https://u:p@mgr/?x#y`. No credential is sent from userinfo, because the client always sets its own `Authorization` header. A query or fragment is dropped or mangled by `JoinPath`. Optional: refuse `u.User != nil`, `u.RawQuery != ""` and `u.Fragment != ""` with the existing line, so a typo fails at start-up rather than at the first call. `postinst` (TASK-100) would then match it.
2. Note for the M4 gate (tester-m4's point, not a TASK-087 defect). The G9 plant "an altered hash line in `agent/go.sum`" does not turn `go mod verify` itself red. `go mod verify` checks the module cache against the cache's own recorded hashes, not against `go.sum`. The build, test and download steps do fail with `SECURITY ERROR`, so CI still goes red. To make G9 red on its own command, have `agent.yml` run `go mod download` before `go mod verify` (impl-deploy, TASK-097), or redefine the G9 plant in `work/tasks.md` (planner). The lead decides which.
