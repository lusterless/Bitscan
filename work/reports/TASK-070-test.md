# TASK-070 TEST report: enrolment requests (list, approve, reject)

**Verdict: PASS** (revision 1, 2026-10-23, tester-d). REQ-069 (1)–(6), REQ-077 (6); #26, #36, #64 (a)–(f), #68, #71. Plan checks: CHK-M3-220 to -226; mutation rows CHK-M3-326, -327, -328, -370 and -371. Code: `bm/services/enrolment/requests.py` and `bm/api/user/enrolment.py` (`work/reports/TASK-070-impl.md`, including "Revision 1"). Lead ruling 2026-10-23 (#64 (d), (f)), raised by the tester before the first run: a `new` request decided after its re-enrolment twin was approved is rejected without touching the agent, or approved by re-linking. Round 0 was never reported FAIL: the two cases were tested on r1.

## Commands
- W (CI=true), the 14 files in CHK-M3-220: 435 passed, 4 failed, 0 skipped.
  - 2 failures are `test_login.py::test_openapi_error_contract`. They come from the TASK-074 inventory 422 and are fixed in TASK-074 TEST.
  - 2 failures were my own new TASK-082 check, since replaced (see the TASK-082 report).
  - Every TASK-070 test passes. The enrol, enrolment-token, enrolment-repo, G25 and M2 user suites are green.
- W plant control: `test_enrolment_requests_api_pg.py` 23 of 23.
- L: ruff, format and mypy are clean.
- Plants: 15 of 15 red (CHK-M3-220-mut).

## Acceptance criteria
- The list shows hostname, `source_ip`, OS and matches, including a cloned image and a shared hostname: CHK-M3-220 PASS.
- Approve new: `enrolled`, the token passes, one job: CHK-M3-221 PASS.
- Approve re-enrolment: old token 401, new one works, id, tags, `os_info` and packages kept, #64 token columns, one alert: CHK-M3-222 PASS.
- Reject new is `decommissioned` and kept; reject re-enrolment leaves the row unchanged (#26); r1 twin cases: CHK-M3-223 PASS.
- A decided request gives 409; concurrent decisions give one success; an expired request gives 409: CHK-M3-224 PASS.
- `bsk_`, unverified, operator and sink outage are refused; GET works with an admin `bsk_` and refuses an operator: CHK-M3-225 PASS.
- One audit entry per decision: CHK-M3-226 PASS.

## Test files
- New: `manager/tests/test_enrolment_requests_api_pg.py`.
