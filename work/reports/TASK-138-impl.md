# TASK-138 IMPL: `RemoveOnStop=yes` on the capread socket (recorded spec deviation)

Implementer: impl-deploy. Worktree `Bitscan-m6`, branch `m6-release`. Not committed.

## Why

CHK-M6-261 "off again" FAIL (decisions 2026-10-26): after `systemctl disable --now bitscan-capread.socket`, `/run/bitscan/capread.sock` stays on disk, because the verbatim TS §3.7 unit has no `RemoveOnStop=` and the systemd default is `no`. The agent reports `["capread"]` while that path exists (agreed #30), so the disable was never reported and TS §3.7 L484 ("the manager shows and audit-logs any change") was unmet for a removal. User decision 2026-10-26: add `RemoveOnStop=yes`, so systemd deletes the socket file when the socket stops and the next heartbeat reports `[]`.

## Spec deviation

TS §3.7 L437–L449 gives the `bitscan-capread.socket` unit verbatim; its `[Socket]` section (L441–L445) has no `RemoveOnStop=`. The shipped unit now has one extra line, `RemoveOnStop=yes`, after `SocketMode=0660`. Every other line of this unit, and every other unit, is unchanged and still byte-identical to TS. The TS is not edited. The PR must name this deviation (decision (6)).

## Changes

| File | Change |
| --- | --- |
| `deploy/systemd/bitscan-capread.socket` | Added `RemoveOnStop=yes` as the last line of `[Socket]`, after `SocketMode=0660`. LF endings kept. `ListenStream`, `SocketUser`, `SocketGroup`, `SocketMode` and `[Install]` are untouched. |
| `deploy/debian/rules` | Comments only (2): the header said the five units were "verbatim TS 3.7" and the install step said they stay "byte-identical to TS 3.7". Both claims are now false for this unit, so the header names the one exception (decisions 2026-10-26) and the install comment says the units are copied unchanged from `deploy/systemd/`. No recipe, target or `dh_installsystemd` flag changed. `rules` is not shipped in the binary `.deb`. |

Checked and not changed:
- `deploy/debian/build-deb.sh` and `bitscan-agent.install`: they list unit names only, no contents or hashes. `build-deb.sh` hashes the `.deb` and the binaries at build time, so the new `.deb` SHA-256 comes from a rebuild (decision (2)); nothing hard-codes it.
- `deploy/debian/changelog`: no entry, as instructed. The version stays 0.1.0-1 (not yet released).
- `deploy/runbooks/agent-install.md`: says only that the capread units are installed disabled (L3, L141). It does not say how enabling or disabling the helper is reported, so there was nothing to correct.
- `README.md` L411 ("A change in `runner_helpers` writes a `runner_helper_changed` alert") was already accurate, and with this change it also holds for a disable. Not edited (outside my area in any case).

No files outside the task's scope were changed.

## Checks run

| Check | Result |
| --- | --- |
| `systemd-analyze verify ./bitscan-capread.socket` (WSL Ubuntu 24.04, systemd 255.4-1ubuntu8.18, on a 0644 copy of the unit in a temp dir) | PASS: no output, rc 0. `RemoveOnStop=` is accepted. |
| `systemd-analyze verify ./bitscan-capread.socket ./bitscan-capread.service` (same setup) | Only `bitscan-capread.service: Command /usr/sbin/bitscan-capread is not executable: No such file or directory`, rc 1. This is the "not executable" error that `.claude/CLAUDE.md` accepts locally, before binaries are installed. There is no other diagnostic. |
| `file deploy/systemd/bitscan-capread.socket` | ASCII text, LF endings. |
| `git diff deploy/systemd/` | One added line, in this unit only. |

Not run (tester-m6c, decision (4)): `deploy/tests/check_units_verbatim.py`, which is expected to FAIL on this unit until the tester adds the documented single-line exception; the `.deb` rebuild with lintian; the maintainer-script suite; and the new RC SHA-256.

## Notes for the tester and reviewer

- The behaviour to check on a VM: `systemctl enable --now bitscan-capread.socket` creates `/run/bitscan/capread.sock` (`root:bitscan-runner`, 0660). `systemctl disable --now bitscan-capread.socket` removes it, and the next heartbeat reports `runner_helpers: []` with one more `runner_helper_changed` entry (CHK-M6-261 re-run, decision (3)).
- `RemoveOnStop=yes` also removes the socket file whenever the socket unit is stopped for any other reason (for example on package remove, where the debhelper snippet stops the units). That is the intended effect: the helper is not listening then.
- The unit is part of the helper sandbox (TS §3.7), so this task needs the reviewer and the user's second approval (TS §8.2; decision (5)).
