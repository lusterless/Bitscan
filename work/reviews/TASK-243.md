# TASK-243 REVIEW: re-evaluate route

Reviewer: reviewer-m11, 2026-11-08. Round 1. Second look: the user's, pre-authorised (PD-47).

Verdict: APPROVED

**Scope reviewed:** `manager/bitscan_manager/api/user/reevaluate.py`: the handler body, imports and module docstring, diffed against `69baeaa` (TASK-232). Also the tester's edit of `manager/tests/test_m11_contract_api_pg.py`, which replaces the W1 re-evaluate 501 rows.

**Checked against:**
- TS §6.2 L1086 and L1125; TS §5.3 L1053; TS §4.5 L603; TS §8.1 L1245.
- REQ-270, REQ-271.
- #118 (c), (g), #147, and #148 (no alert, decisions 2026-11-08 (3)).
- Plan `work/plans/TASK-232.md` §6.

**Reports:** `work/reports/TASK-243-impl.md` and `work/reports/TASK-243-test.md`. TEST PASS: 262/262 targeted, G6 byte-identical in WSL, 13/13 plants red.

## Checks

- **Sensitive action (security invariant: TOTP session, refuses API tokens, sink gate):**
  - The decorator, parameters and `TOTP_ADMIN = Depends(require_totp_session())` are byte-unchanged from TASK-232. That gives admin only, a TOTP-verified session, API tokens refused, and 503 after 15 minutes of sink outage.
  - Nothing under `bm/auth/` changed (`git diff 6efe0fb` over `auth/` is empty).
  - Each of the 12 refusal rows leaves the `scan_result_reeval` and `audit_log` checksums unchanged, and a spy sees no statement beyond the token check (CHK-M11-201, -207).
  - The swap plants `require_role("admin")`, `allow_restricted`, `sink_gate=False` and operator-minimum are all red.
- **M8 unchanged, one caller (REQ-271):**
  - The handler calls `reevaluate_scan(runtime.db, UUID(id), user_id=principal.user_id, wake=runtime.sink_gate.wake)`, matching the M8 signature at `services/evaluator/reevaluate.py:96`.
  - `git diff 6efe0fb` over `services/evaluator/` and `repositories/reeval.py` is empty.
  - The tester's AST scan finds no other caller, and the planted second caller is red (CHK-M11-413).
- **Audit and alert:**
  - The route writes nothing itself. M8 writes exactly one `scan.reevaluate` entry in its transaction and runs the wake on commit.
  - There is no alert (#148). The no-alert row checks `detail.alert` and every `bitscan_alerts_total` sample, and the two alert plants are red.
- **Errors:** `ScanNotFound` → 404 `not_found` "No such scan."; `PolicyDeleted` → 409 `conflict` "The policy is deleted.". Both have fixed words and are raised outside the `except`, so they carry no chained driver text. The exact-body rows check for no id, traceback, class or SQL.
- **Input:** no body parameter, so no body is read. The hyphenated id pattern rejects malformed ids, and an upper-case id is accepted.
- **Layering:** the only new import is `services.evaluator.reevaluate`; there is no repository import (CHK-M11-209). Nothing is logged.
- **`test_m11_contract_api_pg.py`:** only the re-evaluate expectations change. The admin TOTP session row moves from 501 to 404 on the file's unknown id. In the sink-gate test, 14:59 and after-drain move from 501 to 404, while the 503 row and the read row are unchanged. The refusal table is untouched, and the change is recorded in the docstring.
- **Re-run (Windows, m9 venv):**
  - `ruff check`, `ruff format --check` and `mypy --strict` on the route and both test files are clean.
  - `test_m11_contract.py` and `test_openapi.py` (G6) give 34 passed.
  - The PostgreSQL API suites run only on Linux, so I relied on the tester's WSL run.

## Findings

1. nit, `manager/tests/test_m11_contract_api_pg.py`: the edited working copy has CRLF line endings (git warns "CRLF will be replaced by LF"). `.gitattributes` (`* text=auto eol=lf`) normalises it at commit, so no change is needed. Writing LF avoids the warning.
