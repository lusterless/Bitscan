# TASK-205 REVIEW: scan routes `POST /scans` and `POST /scans/{id}/cancel`

Verdict: APPROVED

Reviewer: reviewer-m9, 2026-10-30. REQ-212 (1), REQ-220 (2), REQ-221, REQ-222. High risk, full rigor. **PD-39: the user's second look follows this review** (RBAC and the API-token alert). It is applied under the pre-authorisation on this approval and the clean TEST PASS.

Scope reviewed, per `work/reports/TASK-205-impl.md` (with r1):
- `manager/bitscan_manager/api/user/scans.py` (new, 199 lines);
- `manager/bitscan_manager/api/user/__init__.py` (two router includes, shared with TASK-206 in its own wave);
- `manager/openapi.json` (re-exported; still sha256 `74182d35…`, so TASK-207's approval holds).

TEST: PASS on r1 (`work/reports/TASK-205-test.md`). 12/12, and security, invariants, OpenAPI and contract are 622/622 (G6, G34 with the seven operations). Plants CHK-M9-364, -365, -382 and -367 (route) are red.

Spec read: TS §6.2 L1084, L1119, L1122, §6.3 L1133–L1138, §6.4 L1146–L1155, §8.4 L1290, §3.3 L213; #3, #48, #122 (a)–(g), #123, #129 (b).

My re-run (Windows): `ruff check`, `ruff format --check` and `mypy --strict` are clean on `manager/bitscan_manager`.

## Checks
1. **RBAC and token groups (TS §6.2 L1119, L1122, security invariant).**
   - Both routes need `require_role("operator")` on the user router, so `bsu_` and `bsk_` are accepted, a viewer gets 403, and `bsa_`, no token and a revoked token get 401 (CHK-M9-240, -243).
   - Neither is a sensitive action (L1084), so API tokens are accepted.
2. **No ad-hoc command (REQ-212 (1), TS §6.2 L1129).** The body is `extra="forbid"` with `{policy_id: StrictInt, target}`. Extra `plugins`, `execute`, `command`, `payload` or `eval_spec` keys, at the top or inside the target, get 400 with nothing written (CHK-M9-241, -382). The commands come only from `queue_scan`.
3. **Refusals (#122 (f), #3, #48).** 404, 409 (disabled, deleted or no plugin), 422 `about:blank` for zero agents, 400 for a malformed target, 413 over 1 MiB, and 500 with a fixed detail for unstorable text. Every detail is fixed text, and the `InvalidTarget` detail names only the field (builder checklist item 12).
4. **Idempotency (#123, TS §6.3 L1135).**
   - The store is per process, built once on `app.state` under a lock. It works per user and key, and only a 202 is remembered, because refusals raise out of `call()`.
   - r1 parses the target before `store.run()`, so NaN or Infinity can't reach `body_digest`: `{"agents": [NaN]}` gives 400, not 500.
   - A repeat writes no second scan or `scan.create` entry (CHK-M9-245).
5. **All-hosts alert (TS §8.4 L1290, #129 (b)).** `via_api_token` is `principal.kind is TokenKind.API`. `{"all": true}` with `bsk_` gives the alert entry, the counter and the fake sink. A session or a tags target gives none (CHK-M9-242).
6. **Cancel (TS §4.4 L581).** The path id must match the hyphenated pattern (builder checklist item 5). The route answers 200 `{scan_id, state, cancelled_jobs}`, and a repeat answers 0. Nothing is pushed.
7. **Layering (REQ-221 (5)).** The handlers validate, authorise and call services, and the module imports no repository or psycopg (CHK-M9-244).

## Findings
None blocking or should-fix.

1. nit (pre-existing pattern, no change asked): `POST /scans` declares its body, so a malformed body with a bad token gets 400 before the 401 and isn't counted as a failed token check. Every existing user route (users, settings, tokens, tags) does the same. Builder checklist item 4 came from agent and enrolment routes. Nothing leaks, because the 400 carries fixed text only.
