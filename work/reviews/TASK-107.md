# TASK-107 REVIEW: agent install runbook

Verdict: APPROVED (revision 3)

Reviewer: reviewer, 2026-10-25. One review round (runbook, speed rule 6). Not a two-approval task.

Scope reviewed: `deploy/runbooks/agent-install.md` (`work/reports/TASK-107-impl.md`, through r3). Sources:
- TS §3.1, §3.2, §3.3, §3.6, §8.1;
- REQ-110;
- #81, #82;
- decisions 2026-10-24 (supported hosts) and 2026-10-25 (D2: always preseed the token as `password`; the TASK-100 CA nit goes in the runbook).

TEST:
- r0–r2: FAIL on the cloned-host step only (56/57 on the CHK-M4-275 walk). `systemd-machine-id-setup` restores the old id when `/var/lib/dbus/machine-id` is a separate regular file.
- r3: PASS (tester-m4b). The fixed step was re-run against the real M3 manager, 9/9, on the stock layout and on an image with a separate D-Bus copy. The §4 nit is fixed.
- The CHK-M4-276 grep (no real secret, no process notes) passes.

## Checks
1. **Spec coverage (REQ-110).** The runbook covers:
   - supported hosts (Ubuntu 22.04 and 24.04, amd64), NTP and outbound HTTPS only;
   - cloned images, the enrolment-token guidance, a private CA and pinning;
   - the SHA-256 check against a different origin;
   - the three input routes, with environment variables refused;
   - what the install writes, and each refusal line with its fix;
   - upgrade order (manager first), re-enrolment per #81, and remove and purge per #82;
   - the 0.x status.
2. **Cloned hosts (r3).**
   - Both `/etc/machine-id` and `/var/lib/dbus/machine-id` are removed, the id is regenerated, and the link is restored.
   - The step says to compare the old id with the new one, so a failed regeneration shows.
   - It tells you to install after cloning, never in the template.
3. **Secrets.**
   - Every token is a placeholder (`bse_REPLACE_WITH_THE_ENROLMENT_TOKEN`).
   - The preseed file is created 0600 and edited with `sudoedit`, so no token appears on a command line.
   - The D2 warning about a token preseeded as `string` gives both clean-up options.
   - `install.env` is created with its owner and mode before it is edited.
4. **TASK-100 carry-overs.**
   - The CA must be kept under `/etc` and never under `/home`, `/root`, `/run/user` or `/tmp`, with the reason (the agent's sandbox hides those folders).
   - The refusal table matches the postinst messages word for word, including the r1 `/etc/bitscan` line.
5. **Accuracy.**
   - §4 now says that `agent_id` and `token` exist while the enrolment is still held, so they do not prove approval (r3).
   - The pin command reads the leaf certificate on the manager host.
   - Purge keeps the users, a copied CA and any of the manager's files.
6. **Scope.** 1 file, user-guide text only, with no process notes.

## Findings
None.
