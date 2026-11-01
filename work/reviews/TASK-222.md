# TASK-222 REVIEW: capread helper server (`internal/capread`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-252 (1)–(4). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-222-impl.md`: `agent/internal/capread/capread.go` (sha256 `09b1683a…`) and `serve_linux.go` (`7b55e70f…`), both new, inside the estimate. `client.go` in the same package is TASK-226's.

TEST: PASS (`work/reports/TASK-222-test.md`). 9/9 on WSL with `-race`, and 10/10 plants red: CHK-M10-371 to -377, the lead's write-deadline plant, and 2 extras. The lead's rows (a) (a stalled reader is cut off and the next client served) and (b) (`not_installed`, `failed 126`) are included.

Spec read: TS §3.7 L276–L277, L437–L484, L493, L500–L501; security invariants ("capread has its two requests only; the manager never enables it"); #142 (a)–(e).

My re-run (Windows host): `GOOS=linux go vet` is clean, the tests compile, and `golangci-lint` gives 0 issues. The hashes match. The server is Linux-only and its tests need real processes, so the run evidence is the tester's.

## Checks
1. **Exactly two names, never a command line (TS §3.7 L277, L484; security invariant).** The whole table is `commands` in `capread.go`: `nft_ruleset` → `/usr/sbin/nft -j list ruleset`, and `audit_rules` → `/usr/sbin/auditctl -l`.
   - A request is an exact map key followed by one LF and nothing after it, at most 32 bytes.
   - The argv comes only from the table, and the request text never reaches it (plants 371, 372 red).
   - 15 malformed variants answer `error unknown_request` and run nothing (CHK-M10-138).
   - G204 is lifted only for this file (TASK-211).
2. **The process environment (TS §3.7 L484).**
   - The command runs by absolute path with no `PATH` lookup.
   - `Env` is the empty slice, not nil (nil would inherit); `/usr/bin/env` prints nothing (plant 373 red).
   - `Dir` is `/`, and stdin and stderr go to `/dev/null`.
   - It has a 10 s timeout (`CommandContext`, `WaitDelay` 1 s).
3. **Output cap fails closed (#142 (c)).** Over 1 MiB, the writer cancels the command and the reply is `error too_large`, with none of the output. Exactly 1 MiB is sent (plants 376 a/b red). stderr is never sent.
4. **One at a time, and not held up (#142 (d)).** `Serve` handles connections strictly in order (plant 377 red). The request read has a 5 s deadline and the reply write a 10 s deadline, so a silent or stalled client can't block the next one (lead plant red).
5. **No output in logs.** Log lines carry the fixed argv[0] and the outcome word only.
6. **Peer check.** It's done by `sdsock` (uid of `bitscan-runner`), exercised through the real `sdsock` with fd 3 (plant 374 red). The helper never enables or changes a unit: nothing here calls `systemctl` or D-Bus (REQ-254 (2)).

## NOT RUN rows and cover
- **REQ-252 (5) and (6) on a sandbox host, and the VM halves of CHK-M10-371, -373 and -374:**
  - (5): real `nft` and `auditctl` output equal to `sudo`'s, and the helper's `CapEff` `0000000040001000` under a dynamic uid;
  - (6): the runner and plugins keep `0000000000000004`.

  All are NOT RUN (safety-classifier refusal, VM sandbox).
- **Cover:** CHK-M10-137 to -142 with the table swapped for harmless commands. It's adequate for the request handling, the empty environment, the caps and the ordering.
- **Unproven on a real host:**
  - that the verbatim `bitscan-capread.service` (`DynamicUser=yes`, the two ambient capabilities, `RestrictAddressFamilies=AF_UNIX AF_NETLINK`, `MemoryDenyWriteExecute=yes`, `SystemCallFilter=@system-service`) lets `/usr/sbin/nft -j list ruleset` actually read the ruleset over netlink;
  - that `auditctl -l` works there;
  - that the helper's capabilities are exactly the two.

  A `systemd-run` row in WSL with the helper unit's properties and the real `nft` would cover most of this without a VM. I'll ask for it at TASK-226 (the `--serve` wiring).

## Findings
None blocking or should-fix.

1. nit, `serve_linux.go:161-173`: `exec.CommandContext` kills only the direct child on timeout. `nft` and `auditctl` don't fork, and the unit's control-group kill catches anything left at stop, so it's fine as built. A process-group kill would make the timeout independent of the command's behaviour.
2. nit, `serve_linux.go:143`: `run` stats `argv[0]` before `exec` to tell `not_installed` from a start failure. The window between the two checks only changes which error word is sent, so it's harmless.
