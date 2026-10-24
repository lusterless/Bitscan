# TASK-078 REVIEW: `GET /api/v1/audit-log`

Reviewer: reviewer. Date: 2026-10-23. REQ-085. Spec: TS §6.2 L1127 (`GET /audit-log`, admin), §5.3 L1051 (append-only, hash-chained), §5.2 L981–L990; #38 (what is hashed: `detail::text`, the UTC `at` text), #68 (newest first, the eight columns, no filters). Ruling (`work/decisions.md`, 2026-10-23, "Audit-log items carry `detail_text`", option (b); revision 1). Inputs:
- `work/reports/TASK-078-impl.md`, including revision 1;
- `work/reports/TASK-078-test.md` (PASS on r1: `manager/tests/test_audit_log_api_pg.py`, including `compute_row_hash` re-verification on real rows; 4 of 4 plants red).

Files reviewed:
- `manager/bitscan_manager/repositories/audit_log.py` (`page_newest_first`);
- `manager/bitscan_manager/api/user/audit_log.py` (new, 72 lines);
- `manager/bitscan_manager/api/user/__init__.py`;
- `manager/openapi.json`;
- the r1 README lines (TASK-080's file);
- the tester-e tests.

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Spec conformance (REQ-085).**
  - `require_role("admin")`: an admin session or `bsk_` is allowed, and operators and viewers are refused.
  - Newest first by `audit_id`, with keyset paging (`audit_id < cursor`, HMAC cursor), so each entry is returned exactly once. There are no filters.
  - Items have the eight columns plus `detail_text`, PostgreSQL's own `detail::text`, which is the exact string the chain hashed (#38). `at` is serialised as the hashed UTC text form.
  - A reader can therefore re-verify every `row_hash` with `compute_row_hash` from `detail_text`, even where jsonb rewrites floats (`1e-07` → `0.0000001`). That is the point of r1; the tester re-verified real rows.
- **Read-only.** The repository function is one parameterised `SELECT … ORDER BY audit_id DESC LIMIT %s`, and the route writes nothing (REQ-085 (3)). The app still has no UPDATE or DELETE on `audit_log`.
- **Layering.** The route calls a repository function directly, because the read has no logic and the task's file list has no service. That matches the M2 health route pattern. Accepted.
- **README (r1, TASK-080's file).** The audit-log bullet now lists `detail_text`, and the re-verification steps hash `detail_text` and `at` as returned, never a re-serialised `detail`. This is checked in the TASK-080 review.
- **OpenAPI (G6).** My re-export is byte-identical. The operation lists 200, 400, 401, 403, 429 and 503, and `AuditItem` requires `detail_text` (`string | null`).
- **Tests (my run, Windows).** See the TASK-077 review: 80 passed, 128 skipped; ruff, format and `mypy --strict` (209 files) are clean.

## Findings

None.

## Note

Audit `detail` is admin-only and never holds tokens, passwords, codes, seeds, stdout or stderr (#50, #71), so returning it raw is within the security invariants. Every M3 writer was checked in its own review.
