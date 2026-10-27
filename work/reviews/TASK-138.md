# TASK-138 REVIEW: `RemoveOnStop=yes` on the capread socket (recorded spec deviation)

Verdict: APPROVED

Reviewer: reviewer, 2026-10-26. Round 1. Two approvals (TS §8.2 L1268): the unit is part of the agent package's helper sandbox (TS §3.7). This is the first approval; the user's second approval follows. No blocking or should-fix finding is open.

Scope reviewed (`git diff 8ad50eb`; `work/reports/TASK-138-impl.md`):
- `deploy/systemd/bitscan-capread.socket`: +1 line.
- `deploy/debian/rules`: comments only.
- The tester-side `deploy/tests/check_units_verbatim.py`: +31 / −1.

Sources:
- the user decision of 2026-10-26 (`work/decisions.md`, the CHK-M6-261 rows: decisions (1)–(6));
- TS §3.7 L437–L449 (the unit) and L484 ("the manager shows and audit-logs any change");
- #30 (the agent reports `["capread"]` while the socket path exists; `agent/internal/agent/loops/heartbeat.go` L90);
- `.claude/rules/deploy/packaging-and-units.md` and the security invariants.

TEST: PASS, full rigor (tester-m6c; `work/reports/TASK-138-test.md`; rows CHK-M6-160..167 in `tests/m6/report.md`).
- 12 plants red.
- `systemd-analyze verify` is clean on 24.04 (systemd 255) and 22.04 (systemd 249).
- New RC `d98ef8c3…`: its diff against `3b5c98a0…` is only this line and its md5sums entry; the binaries are identical.
- Reproducible build 14/14; lintian 93/93; maintainer scripts 567/567 on each release.
- Runtime: with the new RC the socket file is removed on disable and on stop; with the old RC it stays.
- On the real u2404 VM (W4, CHK-M6-261-r): disable gives `[]`, a second `runner_helper_changed` entry and the socket file gone. Both entries reach the sink, and the counter rises.

## Checks
1. **Spec deviation, and only that.**
   - The added line is exactly the one the user approved. It sits after `SocketMode=0660`, so `ListenStream=/run/bitscan/capread.sock`, `SocketUser=root`, `SocketGroup=bitscan-runner` and `SocketMode=0660` keep the values the packaging rule pins. `[Install]` and LF endings are unchanged.
   - The TS is not edited. The decision requires the PR to name the deviation, and `rules` now names it instead of claiming that every unit is verbatim.
   - No other unit and no D-Bus file changed.
2. **Security invariants and the helper sandbox.**
   - `RemoveOnStop=` only deletes the socket file when the socket unit stops. It grants no capability, adds no listener, widens no access and changes nothing in `bitscan-capread.service`, which stays verbatim with no `[Install]`, `UMask=` or `SystemCallErrorNumber=`.
   - Enabling and disabling stay host-side only. No manager route or job changes host settings.
   - The helper still defaults to installed-but-disabled (`dh_installsystemd --no-enable --no-start`, unchanged).
   - The effect is the intended one: a disable is now visible in the heartbeat, so TS §3.7 L484's "audit-logs any change" holds for removals too.
   - A stop for any other reason, such as package remove, also removes the file. That is correct, because nothing listens then.
3. **The verbatim-check exception allows exactly that one line.**
   - `DEVIATIONS` has a single entry keyed by `bitscan-capread.socket`, holding the exact anchor bytes `SocketMode=0660\n` and the exact added bytes `RemoveOnStop=yes\n`.
   - `apply_deviation()` inserts the line right after the anchor, then compares the whole file byte for byte, so any other change, a move, a duplicate, `=no`, a trailing space or CRLF still fails.
   - It aborts if the TS block stops holding exactly one anchor line or already holds the added line, so the exception can't silently outlive a spec change.
   - Every other unit and the D-Bus policy still go through the unchanged byte-for-byte path, and the folder-set check is unchanged.
   - My re-run of `check_units_verbatim.py all` on the tree: 10 files OK; 9 IDENTICAL plus the capread socket with its one printed `DEVIATION` line.
   - My plants, each in a throwaway `/tmp` copy: the line removed, `RemoveOnStop=no`, and the same line added to `bitscan-runner.socket`. All three red (rc 1).
   - CI uses the same script (`units.yml`, `package.yml`, `test_build_deb.sh`), so no other gate needed a change.
4. **Scope.** Three small files, each in its owner's area: the unit and `rules` belong to impl-deploy, the checker to the tester. No changelog entry, because 0.1.0-1 is not yet released (as instructed). The runbook and README needed no change; `README.md` already says that any `runner_helpers` change alerts.
5. **Release follow-through.** The RC hash moves to `d98ef8c3…`. The gate's CHK-M6-319-final, a fresh local release run on the final tree whose `.deb` must equal `d98ef8c3…`, covers the release workflow, whose earlier local run built the old unit.

## Findings
None blocking, none should-fix.

1. nit (owner, not this task's files): `.claude/rules/deploy/packaging-and-units.md` still says to copy the units from the spec verbatim. After this decision that is out of date for one line in `bitscan-capread.socket`. Agents may not edit `.claude/` (decisions 2026-10-26 (5)), so the user should add the exception there when updating the rules.
