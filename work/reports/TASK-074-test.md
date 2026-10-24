# TASK-074 TEST report: inventory upload route

**Verdict: PASS** (2026-10-23, tester-e). REQ-076 (1)–(6), REQ-066 (1)–(3) on the real route, REQ-087; #72 (a)–(f). Plan checks CHK-M3-255 to -263, the route walk and matrix (CHK-M3-169-074), the CHK-M3-016 carry-over, and mutation rows CHK-M3-358, -360 and -361. Code: `bm/services/inventory/upload.py`, `bm/api/agent/inventory.py`, `bm/api/agent/__init__.py`, and the inventory `RouteCap` and 422 hook in `bm/app.py` (`work/reports/TASK-074-impl.md`). Tree copies: 2026-10-23T09:11:47Z (suite) and about 09:55Z (plants). Both copies already held the TASK-083 edits to `inventory.py` (`agent_uuid`, case-insensitive `content_coding`). No TASK-074 check depends on them; TASK-083's own rules are tested in TASK-083 TEST, as ruled.

## Commands
- W (CI=true), 10 files: 1124 passed, 3 failed, 0 skipped.
  - 2 failures were my own test expectations. A top-level JSON array is 422 per the approved TASK-060 mapping, not 400. The 50,000-package fixture also writes the `new_packages_burst` alert. Both are corrected, and the file is 148 of 148 green in the plant control.
  - 1 failure is **TASK-083's**, not TASK-074's: `test_agent_auth_pg.py::test_foreign_id_is_403_not_counted`. A `not-a-uuid` `{id}` now gets 400 instead of 403, as ruled for TASK-083. That test is updated in TASK-083 TEST.
- W plants: `tester2_m3mutw2.sh tester2_plants074.json`: control 148 passed; 22 of 22 red.
- L: `test_body_caps.py` 38 passed, `test_login.py` 18 passed, `test_contract_agent.py` 569 passed; ruff, format and mypy clean.

## Acceptance criteria
- Dispatched job completed in the ingest transaction; `AgentGone` → 401 `token_revoked`: CHK-M3-255 PASS.
- Failed or completed job id stored as unscheduled, job unchanged: CHK-M3-256 PASS.
- One unscheduled upload per 10 min (429 + `Retry-After`), asked before decoding, started at decoding, dispatched exempt: CHK-M3-257 PASS.
- 413/422 naming a dispatched job fails it with one entry; 0 bytes before a 401: CHK-M3-258 PASS.
- The #72 (d) 409 cases: CHK-M3-259 PASS.
- Non-UUID 400; gzip required; malformed → 400, audit-logged, job left; `type` never `reason`: CHK-M3-260 PASS.
- 2 MiB and exactly 10 MiB accepted, +1 refused: CHK-M3-261 PASS.
- No package name, raw or token in logs: CHK-M3-262 PASS.
- Fixtures through the route; OpenAPI; RawValue with the whole document as root (CHK-M3-016): CHK-M3-263 PASS.
- Route walk and matrix; burst window built once: CHK-M3-169-074 PASS.
- The 11 broken tests fixed and the 422 contract narrowed: CHK-M3-255-fix PASS.

## Test changes
- New: `manager/tests/test_inventory_api_pg.py` (148 tests).
- Changed:
  - `test_body_caps.py`: the inventory cases use a test-only template.
  - `test_agent_auth_pg.py`: the after-auth probes use a test-only template.
  - `test_login.py`: the 422 contract is narrowed per the ruling.
  - `test_contract_agent.py`: new `test_raw_fixtures_against_the_rawvalue_component` (CHK-M3-016).

## Notes for the reviewer (no FAIL)
1. #72 (e) is read literally: an upload refused before decoding (no gzip, or over 10 MiB as sent) does not start the 10-minute window, because nothing was decompressed. The plan's draft wording ("a refused 413/422/400 unscheduled upload also starts the window") is narrowed to refusals at decoding.
2. The job is classified in its own short transaction before the ingest, and completed inside the ingest transaction only while still `dispatched`. If the sweep fails the job in between, the upload is stored (and was exempt from the window) but the job stays `failed`. This is consistent with the "late upload stored as unscheduled" rule.
