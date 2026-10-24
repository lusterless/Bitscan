# TASK-073 TEST report: job pull and the M3 results route

**Verdict: PASS** (2026-10-23, tester-e). REQ-072 (1)–(6), REQ-073 (1)–(5), REQ-066 (1)–(4) on the results route, REQ-087 (1), REQ-088; #54 (c), #65 (f), #71. Plan checks CHK-M3-245 to -253, the route walk and agent matrix on both real routes (CHK-M3-169-073), and mutation rows CHK-M3-346 to -351, -359 and -366. Code: `bm/services/jobs/{__init__,pull}.py`, `bm/api/agent/jobs.py`, `bm/api/agent/__init__.py`, the results `RouteCap` and OpenAPI hook in `bm/app.py` (`work/reports/TASK-073-impl.md`). Tree copies: 2026-10-23T08:45:53Z (suite) and about 08:49Z (plants).

## Commands
- W (CI=true): `tester2_m3run.sh t073` over `test_jobs_api_pg.py`, `test_jobs_repo_pg.py`, `test_agent_auth_pg.py`, `test_contract_agent.py`, `test_contract_fixtures.py`, `test_openapi.py`: 818 passed, 3 failed, 0 skipped. **None of the 3 is a TASK-073 failure:**
  - 1 was a defect in my new log test (it looked for the path under a `data` key; the formatter flattens it). Fixed; the file is 93 of 93 green in the plant control.
  - 2 are the `test_agent_auth_pg.py` after-auth probes that the real `PUT /inventory` (TASK-074) shadows. They are fixed in TASK-074 TEST.
- W plants: `tester2_m3mutw2.sh tester2_plants073.json`: control 93 passed; 25 of 25 red (CHK-M3-245-mut).
- L: ruff, format and mypy clean.

## Acceptance criteria
- 12 queued → 10 oldest then 2, each dispatched once, empty pull changes nothing: CHK-M3-245 PASS.
- Concurrent pulls never share a job: CHK-M3-246 PASS.
- Other agents', non-queued, past-`pickup_by` and compliance jobs never returned; no `eval_spec`/`operator`/`expected`: CHK-M3-247 PASS.
- Answers validate against the document and the model: CHK-M3-248 PASS.
- Every well-formed post → 409, one `agent.result_refused` entry without output, nothing stored, no job change: CHK-M3-249 PASS.
- Malformed → 400; 1.5 MiB caps as sent and inflated; 0 bytes before a 401; no body parameter: CHK-M3-250 PASS.
- 409 flood: 20 none, 21 one, once an hour, marked on commit, window built once: CHK-M3-251 PASS.
- No stdout in logs; records carry `agent_id` and `job_id`: CHK-M3-252 PASS.
- Fixtures through the route, OpenAPI, G6 and the contract re-run: CHK-M3-253 PASS.
- Route walk and the 401/403/429 matrix: CHK-M3-169-073 PASS.

## Test changes
- New: `manager/tests/test_jobs_api_pg.py` (93 tests).

## Notes for the reviewer (no FAIL)
1. Two simultaneous 409s that both take the count past 20 can both see the alert as due before either commits, so they could write two `result_409_flood` entries. This follows from the commit-only rule ("errs toward alerting", decisions 2026-10-23); not tested.
2. The route compares `Content-Encoding` with `gzip` exactly, so `GZIP` gets 400. RFC 9110 §8.4.1 says content codings are case-insensitive. The Go agent will send `gzip`; flagged only.
3. `job_id` in the path is parsed with `uuid.UUID`, which also accepts the 32-hex, `{…}` and `urn:uuid:` forms. Such a post gets 409 with the normalised id in the entry, not 400. The W1 ruling (3) names the agent contract bodies; asked of `main` separately.
4. The pull validates the stored payloads as `JobsResponse` after the dispatching transaction commits. A payload that failed validation would leave its jobs `dispatched` behind a 500 (the 30-minute sweep then fails them). Payloads come only from the scheduler, so this cannot happen in M3. The limit-11 plant shows the same path.
