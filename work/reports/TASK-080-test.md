# TASK-080 TEST report: README (M3)

**Verdict: PASS** (2026-10-23, tester-e). REQ-090 (2); check CHK-M3-295. REQ-090 (1), following each documented request against a manager, belongs to the reviewer. The scan covered the TASK-080 sections and the TASK-078 r1 edit ("Audit log" bullets).
- Scan: no task, requirement or check id, no question number, no process note, and no real token, password or DSN.
- Cross-check: the documented limits and behaviours match what the M3 route tests assert (row CHK-M3-295).
- Nothing in the README is contradicted by a test. One note for the reviewer: "Keep `os_info.raw` a flat set of keys and values" is advice. The rule is the 32-level depth limit, and the decoder tests cover it.

## README walk-through (REQ-090 (1), lead ruling 2026-10-23), r1 text: PASS (tester-f)
- A real `serve` in WSL ran every documented M3 request: 107 requests and 51 checks, 0 deviations, as root and as `bstester` (CHK-M3-296; transcript `tests/m3/readme-walk-080.md`). The README text scan was re-run on r1 (CHK-M3-295-r1).
- New test: `manager/tests/test_readme_walk_linux.py` (1 test, about 100 s). It can be re-run at the gate and in CI.
- "As owner" statements were used only where a real clock cannot reach a documented time rule: the rotation window, the end of the 10-minute overlap, token expiry, an expired request token, and planted hosts for the scheduler.
- Not walked (outside the ruling's list, already proven elsewhere): the M2 README parts (password change, users PATCH and DELETE, API token DELETE, logout; CHK-M2-292), certificate reload, audit-sink outage, and the `db` commands.
- README notes for the reviewer (not deviations; the behaviour is tested elsewhere):
  1. "The old token keeps working until 10 minutes after the new token is first used." This does not mention that a **rotate** with the old token after first use is reuse even inside the 10 minutes, and revokes both (#62, CHK-M3-268).
  2. After an approved re-enrolment, the old token gets 401 `unauthorized`, not `token_revoked`. The README says only "ends the old token", which is consistent.
  3. An operator approving gets 403 `totp_session_required` (operators have no TOTP), not `forbidden`. The README just says an admin TOTP session is needed.
