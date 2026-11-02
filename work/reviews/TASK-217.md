# TASK-217 REVIEW: systemd socket activation and peer check (`internal/sdsock`)

Verdict: APPROVED

Reviewer: reviewer-m10, 2026-10-30. REQ-235 (1), (2), (5), (6). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-217-impl.md`: `agent/internal/sdsock/listen_linux.go` (sha256 `63d1c4e7…`) and `peer_linux.go` (`1b4e694f…`), both new, inside the estimate.

TEST: PASS (`work/reports/TASK-217-test.md`). 20/20 on WSL with `-race`, and 7/7 plants red (CHK-M10-320, -321, -330, plus 4 extras). Following the lead's ruling, fd 3 is kept open with `O_CLOEXEC`, and REQ-235 (5) is asserted as written.

Spec read: TS §2.2 L111, §3.3 L210, §3.7 L281–L283, L289–L302, L437–L449, L486–L493; #130 (g), (j); plan TASK-209 §5.

My re-run (Windows host): `GOOS=linux go vet` is clean, the tests compile, and `golangci-lint` gives 0 issues. The hashes match. The tests are Linux-only and need root plus `setpriv` peers, so the run evidence is the tester's.

## Checks
1. **No listening socket of its own (TS §2.2 L111, §3.3 L210; security invariant).** The package only adopts fd 3. It never calls `socket`, `bind` or `listen`. The only `net.FileListener` in non-test agent code is here, by AST scan (CHK-M10-122) and by G8 (TASK-211).
2. **Close-on-exec before anything else (TS §3.7 L283).** `cloexecInherited` sets `FD_CLOEXEC` on every descriptor above 2 before the `LISTEN_*` checks. That includes descriptors the process inherited unexpectedly, not only fd 3. `fdinfo/3`, `/4` and `/5` show `O_CLOEXEC`, and a shell exec'd afterwards holds exactly 0, 1 and 2 (plants 330 and 217e red).
3. **Strict adoption (REQ-235 (2)).** `LISTEN_PID` must equal its own pid, `LISTEN_FDS` must be exactly `1`, and fd 3 must be `S_IFSOCK`, `AF_UNIX`, `SOCK_STREAM` and `SO_ACCEPTCONN`. A regular file, a datagram socket, a non-listening socket, a TCP listener and a missing fd 3 are each refused with one fixed line.
4. **Peer check (TS §3.7 L282, L484).** `SO_PEERCRED` is read per connection, and only the uid is compared, so a matching gid isn't enough (plant 321 red). A refused peer is closed before any byte is read or written, and gets one log line naming its uid and nothing else. The check runs inside `Accept`, so a refused peer never even gets the serve loop's `busy` reply.
5. **Uid lookup without CGO.** `os/user` in a static build reads `/etc/passwd`. An unknown user is an error, so the runner refuses to start rather than guessing.

## NOT RUN rows and cover
- **REQ-235 (3) on a sandbox host** (root and a `bitscan` group member are closed without a reply; a non-member gets EACCES), **and the VM halves of CHK-M10-320 and -330:** NOT RUN (safety-classifier refusal, VM sandbox).
- **Cover, adequate for this code:** CHK-M10-118 (uid 0 and another uid closed unanswered) and CHK-M10-120.
- **Unproven on a real host:** the file side, which belongs to systemd and the verbatim unit, not this code:
  - that `bitscan-runner.socket` creates `/run/bitscan/runner.sock` as `root:bitscan` 0660 in a root-owned 0755 directory;
  - that a user outside the group therefore gets EACCES;
  - that a plugin can't replace the socket.

  G17 shows only that the directives are present, not that they take effect.

## Findings
None blocking or should-fix.

1. nit, `peer_linux.go:16-19`: any `AcceptUnix` error, a transient `EMFILE` or `ECONNABORTED` included, ends `Accept`. The serve loop then returns and the runner exits for systemd to restart it. That fails closed and is acceptable. Retrying the transient errors, as `net/http` does, would avoid a restart, if that's wanted.
2. nit, `peer_linux.go:28-31`: refusal lines are logged at Warn for every refused connection, without a rate limit. Only root and members of group `bitscan` can reach the 0660 socket, so a flood needs that access already.
