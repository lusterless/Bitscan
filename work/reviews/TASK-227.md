# TASK-227 REVIEW: `bitscan-agent` main for M10

Verdict: APPROVED

Reviewer: reviewer-m10c, 2026-11-01. REQ-245, REQ-246, REQ-247, REQ-249, REQ-251 (1). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-227-impl.md`: `agent/cmd/bitscan-agent/main.go` (sha256 `e35868e1…`), +31 / −3. No other file changed.

TEST: PASS (`work/reports/TASK-227-test.md`).
- The binary walk `e2e/agent_binary_m10.sh` passes 120/120 across 7 scenarios. Each scenario uses a fake manager over TLS, a fake runner on `runner.sock`, and a private mount namespace.
- `TestImportBoundary` passes 1/1 on Windows and in WSL.
- 7/7 plants are red, including the lead's "exit on spool error" plant.

Spec read: TS §1.1 G2; §2.2 L111; §3 L152; §3.3 L222, L224, L226; §3.5; §3.7 L275; §4.4 L575; decisions rows "TASK-227 (agent main) spool-open failure accepted" and "… reviewer-m10 confirms no spec question".

My re-run (Windows host):
- `gofmt` prints nothing.
- `go vet ./cmd/...` is clean on Windows, and `GOOS=linux go vet ./...` is clean too.
- `golangci-lint run ./...` gives 0 issues on Windows and with `GOOS=linux`.

## Checks
1. **Order of start-up.** After enrolment, `main` does these steps in order:
   - `spool.Open(<state_dir>/spool, spool_max_mb << 20, clock.Now)`. `spool_max_mb` is validated 1–50 by the config, so the shift can't overflow.
   - `Deps.SpoolBytes` is set to `sp.Size`.
   - It logs each `Dropped` entry (`job_id`, count, fixed reason) and sets `last_error`.
   - It starts the sender loop next to the heartbeat, pull and inventory loops.
   - It builds the `Compliance` handler with the default `runnerclient.Client{}` (the fixed socket).

   CHK-M10-182 shows the 3-plugin job end to end:
   - the start notice comes first;
   - there is exactly one final, and it is last;
   - every body is gzip;
   - the runner gets one request whose `job` equals the pulled job, with the heartbeat's `max_parallel_plugins`;
   - nothing is executed, and no command or pattern reaches any state file.
2. **A spool that can't be opened** (the lead's ruled choice). `Compliance` stays a nil interface (not a typed nil), so `Puller.compliance` refuses each job, `last_error` is set, and inventory and heartbeats continue (G2).
   - The `nospool` row shows that no results post is made and the runner is never contacted.
   - The "exit on spool error" plant is red because it loses inventory.

   TS §3 is silent here, as reviewer-m10 confirmed, so this is not a spec question.
3. **SIGTERM mid-job (#131 (d)).** The signal context ends `Run.Context()`, so the client cuts the runner connection, and `Handle` returns without `Finish`.
   - CHK-M10-183: exit 0 in 0.02 s, `job.json` has `finished: false` and the item is kept.
   - After a restart the item is posted, no final ever follows, and the job is not resent (CHK-M10-358 at binary level).
4. **Inventory never waits** (REQ-249 (3), (5)). The inventory job of the same pull is uploaded while the runner holds the compliance job. With no runner at all, every plugin goes out as `runner_unavailable` in a final batch and inventory still uploads (CHK-M10-185).
5. **Import boundary** (REQ-251 (1), G75). `cmd/bitscan-agent` links only `internal/runner/proto` from the runner tree. It links no `redact`, `capread`, `sdsock` or `golang.org/x/sys` (PD-41). Plants 380 (×4) and 381 (×2) are red.
6. **Logs.** No canary (execute, pattern, runner stdout, `bsa_`/`bse_`) appears in the agent's output. `spErr.Error()` carries only the spool's own path and errno.

## NOT RUN rows and cover
- **The same walk against the real M9 manager on a VM host (G79):** NOT RUN, under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **Cover:** the binary walk above, plus G41 (the inventory chain against the real manager in WSL) at the gate. That is adequate for `main`'s wiring.
- **Unproven on a real host:**
  - the agent under its verbatim unit (`ProtectSystem=strict`, `ReadWritePaths=/var/lib/bitscan-agent`) creating and writing `spool/`;
  - connecting to the systemd-made `runner.sock` (`root:bitscan` 0660).

## Findings
None blocking or should-fix.

1. nit, `main.go:142-147`: when the 5 s shutdown grace runs out, `run` returns while the sender may still be inside a `Spool` call, and the deferred `sp.Close()` runs alongside it. The process exits at once, and every spool write is tmp → fsync → rename, so nothing on disk is partial. Listed only.
