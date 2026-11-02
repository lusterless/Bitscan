# TASK-226 REVIEW: capread client and `bitscan-capread` main

Verdict: APPROVED

Reviewer: reviewer-m10c, 2026-11-01. REQ-253 (1), (2), REQ-252 (the `--serve` wiring). High risk, full rigor. **PD-43: the TS §8.2 second approval is due after this review** (pre-authorised on this approval and the clean TEST PASS).

Scope reviewed, per `work/reports/TASK-226-impl.md`, 109 code lines in 2 files, against an estimate of 120:
- `agent/internal/capread/client.go` (sha256 `777c451b…`): new, portable;
- `agent/cmd/bitscan-capread/main.go` (`385c2d19…`): replaces the M0 stub and carries `//go:build linux`.

TEST: PASS (`work/reports/TASK-226-test.md`).
- WSL `-race`: 20/20.
- Windows: 8/8.
- Plants: 6/6 red, including the lead's "print as it streams".
- WSL helper-unit row: every verbatim `[Service]` and `[Socket]` directive was accepted by `systemd-run`, and the row shows:
  - CapEff `0x40001000`;
  - `nft` output byte-equal to root's;
  - uid 997 (in the group) and root refused.

Spec read: TS §3.7 L276–L277, L437–L484, L493, L500–L501; #142 (f), (g); security invariants (capread takes a name, never a command line; the manager never enables it); decisions row "TASK-226 (capread client and main) accepted as built".

My re-run (Windows host):
- `gofmt` prints nothing.
- `go vet` is clean on Windows and with `GOOS=linux`.
- `golangci-lint run ./...` reports 0 issues on Windows and on GOOS=linux.
- `go test ./internal/capread/` passes (the portable rows).

## Checks
1. **A name only, never a command line (TS §3.7 L484; invariant).**
   - Any argument list other than exactly one `Known` name exits 2 with the usage line, before any dial. The 15 lists tested include `--serve x`, `../nft_ruleset`, `/usr/sbin/nft` and `nft_ruleset;id`, with 0 connections seen (CHK-M10-177a, b).
   - The request is `name + "\n"` only (CHK-M10-176a).
2. **The answer handling fails closed (#142 (f)).**
   - The first line is at most 64 bytes.
   - `ok` reads to EOF up to 1 MiB, then prints. Over the cap gives `too_large`, and nothing is printed until a clean end.
   - A cut-off or timed-out answer prints nothing (CHK-M10-176d, e; the streaming plant is red).
   - An error word must match `^[a-z0-9_ ]{1,40}$` (Go `regexp`, which is RE2), otherwise the client prints `bad answer`. No control bytes from the socket reach the plugin's stderr (CHK-M10-176c).
3. **Helper off (REQ-253 (3) at unit level).** A missing socket or a refused one gives `bitscan-capread: not enabled`, exit 1 (CHK-M10-176f).
4. **`--serve` wiring.**
   - Only the exact argument `--serve` reaches `serve()`.
   - `serve()` gets the uid of `bitscan-runner` from `LookupUID` (pure Go), then `FromSystemd` (the `LISTEN_*` checks, close-on-exec, the per-connection peer check), then `capread.Serve` until SIGTERM.
   - Start-up refusals are one line and exit 1. The `reason` is sdsock's fixed-word text.
   - The unit's `ExecStart=/usr/sbin/bitscan-capread --serve` matches.
   - A plugin running `--serve` itself has no `LISTEN_*` from systemd and no capabilities, so it gets nothing.
5. **Nothing enables a unit.** Neither file calls `systemctl` or D-Bus (REQ-254 (2)).

## NOT RUN rows and cover
- **REQ-253 (3) on a sandbox host, and REQ-252 (5), (6) on a VM:** NOT RUN under the VM hold, now the named gate exception (decisions 2026-11-01 (1)).
- **`auditctl -l` through the helper in WSL:** NOT RUN. The WSL kernel refuses audit netlink even to root. Through the helper the client gets `failed 255`, the same status root gets.
- **Cover:** CHK-M10-217w covers most of what reviewer-m10 asked for at TASK-222: the verbatim helper unit's properties, real `nft`, CapEff `0x40001000`, and the peer and group refusals. That is adequate for the client and the wiring.
- **Unproven on a real host:**
  - that `auditctl -l` works under the verbatim helper unit with `CAP_AUDIT_CONTROL`;
  - that a plugin under the real runner unit sees `not enabled` when the helper is off.

## Findings
None blocking or should-fix.

1. nit, `client.go:72-82`: a helper that closes cleanly after part of an `ok` answer can't be told from a complete answer, because #142 has no length field. The tester recorded it (CHK-M10-176e). TASK-222's server only sends `ok` and output after the command has finished within the cap, so this needs a faulty helper. A length or end marker would be a #142 protocol change: listed only, no change asked for.
