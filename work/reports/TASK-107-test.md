# TASK-107 TEST: agent install runbook (r0, r1, r2, r3)
**Verdict: PASS** (after revision 3; round 0–2 was FAIL on one should-fix finding, kept below). REQ-110; TS §3.1 L165–L166, §3.2, §3.3. Tester: tester-m4b. One review round (docs).

Commands: the CHK-M4-276 grep; the CHK-M4-275 walk (e2e/runbook_walk.py) against the real M3 manager on fresh Ubuntu 24.04 systemd hosts: 56/57 steps as written on r0–r2.

Criteria:
- (1) Every step behaves as written: FAIL on r0–r2, 56/57; PASS after r3 (CHK-M4-275-r3). The failing step was the §1 cloned-host regeneration on an image whose /var/lib/dbus/machine-id is a separate file. systemd-machine-id-setup copied the old id back, so the clone stayed a re-enrolment of the first host. On the stock Ubuntu layout (a symlink) the step worked.
- (2) No real secret and no process notes: PASS (CHK-M4-276).
- r1 (string-preseed warning) and r2 (CA under /etc, purge keeps it): PASS.

Diagnosis and suggested fix (sent to impl-deploy): remove /var/lib/dbus/machine-id as well before systemd-machine-id-setup, then optionally relink it, and check that the new id differs. Nit: §4 L138, the agent_id and token files appear at the first enrolment call while it is still held, not only once enrolled.

## Revision 3
The cloned-host step removes both /etc/machine-id and /var/lib/dbus/machine-id, regenerates, restores the link, and shows the old and new ids. Re-run of the cloned-host rows only (they read the commands from the runbook): 9/9 on both image layouts (CHK-M4-275-r3). The §4 nit is fixed and matches the walk's observation. The other 56 rows of the r0–r2 walk are unaffected (§1 cloned hosts and §4 text only changed). The NOT RUN items stay as listed.
