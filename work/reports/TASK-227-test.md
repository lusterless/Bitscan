# TASK-227 TEST: PASS

Tester: tester-m10c, 2026-11-01. Full rigor (agent, TS §8.2 second approval). REQ-245, REQ-246, REQ-247, REQ-249, REQ-251 (1); TS §1.1 G2, §2.2 L111, §3.3 L222, L226, §3.5. Decisions rows: "TASK-227 (agent main) spool-open failure accepted (safer option)" and the reviewer's confirmation row.

Code under test: `agent/cmd/bitscan-agent/main.go` (`work/reports/TASK-227-impl.md`).

## Test files (new, tester-owned)

- `e2e/agent_binary_m10.sh`: the binary walk. It follows the M4 `e2e/agent_binary.sh` pattern: root in WSL, each scenario in a private mount namespace with overlayfs on `/etc` and `/var/lib` and tmpfs on `/tmp` and `/run`, so nothing on the host changes. The agent's paths are fixed (`/etc/bitscan/agent.yaml`, `/var/lib/bitscan-agent`, `/run/bitscan/runner.sock`), so this walk was used instead of a `cmd/bitscan-agent/main_test.go`.
- `e2e/agent_binary_m10_analyse.py`: the per-scenario checks.
- `e2e/fake_manager_m10.py`: TS §6.5 over TLS on 127.0.0.1. It hands out compliance and inventory jobs, accepts batches, and can answer 503 to non-empty batches while a file exists. The M4 `e2e/fake_manager.py` is unchanged.
- `e2e/fake_runner_m10.py`: the #130 protocol on `/run/bitscan/runner.sock`, with modes `normal`, `hold:N`, `slow:N:S` and `refuse:W`.
- `agent/internal/boundary_test.go`: REQ-251 (1), G75, `go list -deps` for linux/amd64.

The built binary is `CGO_ENABLED=0 GOOS=linux`, `-X main.version=0.2.0~pre1-1`.

Canaries:
- `touch /tmp/EXECCANARY-n; cat /etc/shadow` in every `execute`;
- `PATTERNCANARY[0-9]+` as the pattern;
- `M10RUNNERCANARY` in the runner's stdout;
- `bsa_CANARY…` and `bse_CANARY…` as the tokens.

## Runs

| Run | Command | Count |
| --- | --- | --- |
| W, walk (7 scenarios) | `e2e/agent_binary_m10.sh <worktree> /root/m10c/abw3` | **120/120 passed**, 0 failed, 0 errors, 0 skipped |
| L and W | `go test ./internal/` (`TestImportBoundary`) | 1/1 passed on Windows; 1/1 passed in WSL |
| plants | 7 (exit on spool error; 4 × CHK-M10-380; 2 × CHK-M10-381) | **7/7 red** |

## Report rows (for tests/m10/report.md)

| Check | Type | Where | Command | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| CHK-M10-182 | APP | W | walk `e2e` | PASS | A 3-plugin compliance job end to end:<br>• the first post is `{"results": [], "final": false}`;<br>• the final is last and the only one;<br>• each plugin is posted once, as the runner's result;<br>• every body is gzip;<br>• the fake runner got exactly one request, `v` 1, whose `job` equals the pulled job (all fields but `pickup_by`, which the manager fills), and `max_parallel_plugins` 2, the heartbeat's value.<br>Nothing executed (no `EXECCANARY` file), no command or pattern in any state file, no canary in the agent's stdout or stderr. `/etc` changed only by the test; `/var/lib` only under `bitscan-agent`. No listening socket. SIGTERM: exit 0 within 5 s |
| CHK-M10-183 | APP | W | walk `sigterm` | PASS | The runner holds after 1 result, and SIGTERM goes in mid-job. Phase 1 exits 0 in 0.02 s. The fake runner saw the agent close. The spool kept `job.json` with `finished: false` and the 1 item. After a restart, the item is posted, **no final batch ever follows**, there is no `runner_unavailable` fill, and the job is **not resent** to the restarted runner (CHK-M10-358 at binary level; #131 (d)) |
| CHK-M10-184 | APP | W | walk `overflow` (`spool_max_mb: 1`) and `dropped` | PASS | The bound is 1,048,576 bytes; 165 samples of the spool's file bytes, max 991,038 (detail in TASK-212 r1 / 220 r1 / 223 r1). `dropped`: an unreadable `spool/<id>/job.json` at start gives first-heartbeat `last_error` = `spool: results dropped at start (unreadable)`, one log line naming the job, and the entry removed; compliance still runs |
| CHK-M10-185 | APP | W | walks `invheld`, `absent` | PASS | REQ-249 (3), (5), CHK-M10-370 at binary level. With the runner holding the compliance job, the inventory job of the same pull is uploaded (`PUT …/inventory?job_id=…`) **while the runner still holds**. With no runner at all:<br>• every plugin is posted `runner_unavailable` in a final batch (exit null, empty streams);<br>• inventory still uploads;<br>• the log says the runner is unavailable |
| Spool can't be opened (lead's row; decisions "TASK-227 … accepted") | APP | W | walk `nospool` (a regular file at `/var/lib/bitscan-agent/spool`) | PASS | The agent starts and enrols. The first heartbeat carries `last_error` = `spool: not opened; compliance jobs refused`. The inventory job is uploaded (G2). The compliance job is refused ("no compliance handler", job id logged), the runner is **never contacted**, and there is **no results post**. The `spool` file is unchanged and nothing is written under `/var/lib` outside `bitscan-agent`. "Writes no result anywhere": no results post, and no result in any state file |
| plant "exit on spool error" (lead's row) | CODE | W | `main` returns `refuse()` when `spool.Open` fails | PASS (red) | `nospool` 12/18: inventory not uploaded, no heartbeat, no refusal line, the wait timed out, exit 1 (not 0 on SIGTERM). Inventory is lost, the G2 breach the choice avoids |
| CHK-M10-196 | CODE | L, W | `TestImportBoundary` | PASS | linux/amd64 `go list -deps`. `cmd/bitscan-agent` links `internal/runner/proto`, `runnerclient` and `spool`, and no other `internal/runner*`, no `internal/redact`, `capread` or `sdsock`, and no `golang.org/x/sys` (PD-41). `cmd/bitscan-runner` and `cmd/bitscan-capread` link no `net/http*`, `crypto/tls`, `internal/agent/transport`, `enrol` or `loops`. The test fails if its own walk lists too few packages |
| CHK-M10-380 | CODE | W | plants: `cmd/bitscan-agent` imports `internal/redact`, `internal/runner`, `internal/capread`, `golang.org/x/sys/unix` | PASS (red ×4) | Each named, e.g. "bitscan-agent links bitscan.local/agent/internal/redact (REQ-251 (1), CHK-M10-380)"; the runner plant also shows `x/sys` (PD-41) |
| CHK-M10-381 | CODE | W | plants: `net/http` into `cmd/bitscan-runner`, `crypto/tls` into `cmd/bitscan-capread` | PASS (red ×2) | "./cmd/bitscan-runner links net/http (CHK-M10-381)" and the others |

## Acceptance (TASK-227: "against a fake manager and a fake runner the binary runs a compliance job end to end, SIGTERM mid-job exits 0 within 5 s with the spool intact, and REQ-251 (1) holds for `cmd/bitscan-agent`")

| Criterion | Rows | Verdict |
| --- | --- | --- |
| end to end | CHK-M10-182 | PASS |
| SIGTERM mid-job, exit 0 < 5 s, spool intact, no final after restart | CHK-M10-183 | PASS |
| REQ-251 (1) | CHK-M10-196, -380 | PASS |
| G2 kept when the spool can't open | nospool row and its plant | PASS |
| The same against the real manager (G79) | — | NOT RUN: VM hold (the named gate exception). Cover: the walk above, plus G41 (inventory chain against the real manager) at the gate |
