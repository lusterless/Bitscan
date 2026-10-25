# TASK-085 REVIEW: M3 carry-overs (upload.py Protocol seam, two README sentences)

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. One review round (speed rule 6). Not a two-approval task: the refactor changes no behaviour, as in the TASK-084 ruling.

Scope reviewed: `manager/bitscan_manager/services/inventory/upload.py` and `README.md` (`work/reports/TASK-085-impl.md`). Sources:
- REQ-112;
- decisions 2026-10-23: the upload.py seam, and the README nits carried to M4;
- decisions 2026-10-25: the TASK-085 README sentence reading;
- TS §3.4 L239–L244.

TEST: PASS (`work/reports/TASK-085-test.md`).
- The new unit tests with fake stores pass 31/31, covering every branch.
- The TASK-074 route suites pass 1258/1258 on PostgreSQL.
- `openapi.json` is byte-identical.
- CHK-M4-366: 4/4 plants are red.
  - The `pg_stores` wiring plant is caught only by the PostgreSQL suite.
  - The "factory ignored" plant is caught only by the unit suite.
  - So the two suites complement each other.

## Checks
1. **No behaviour change.**
   - `classify`, `refuse_unread`, `store_upload` and `_audit` keep every branch, condition, order and transaction boundary.
   - Each transaction calls `stores(tx)` once.
   - `pg_stores` builds the same four objects as before.
   - The `stores` parameter is a trailing parameter defaulting to `pg_stores`, so the route and every caller are unchanged.
2. **Layering.**
   - The `UploadJobs` Protocol matches `JobRepo`'s three methods.
   - `InventoryStore`, `AgentStore` and `AuditSink` are reused, not duplicated.
   - The pattern is the same as `sweep.py`.
   - This closes the M3 design-rule gap (decisions 2026-10-23).
3. **README.**
   - "A call with the old token then gets 401 `unauthorized`" matches `test_enrolment_requests_api_pg.py` L511.
   - The operator sentence follows the lead's ruling: 403 `totp_session_required` for an API token or an unverified session, and 403 `forbidden` for a TOTP-verified session. It matches `_gate`'s order and the M3 tests, including `test_auth_dependencies.py::test_unverified_session_of_a_non_admin_on_totp_route`.
   - The README holds user-guide text only.
4. **Re-run by the reviewer (Windows).**
   - `ruff check` and `ruff format --check` pass on `upload.py`.
   - `mypy --strict` passes on `bitscan_manager` (103 files).
5. **Scope.** 2 files, about 55 lines.

## Findings
None. The impl report notes that the M4 tree has not yet taken the M3 gate-fix commit (`precision = 2` in `manager/pyproject.toml`). The lead has already planned to merge it before the M4 gate (decisions 2026-10-25). That is not a TASK-085 change.
