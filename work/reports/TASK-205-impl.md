# TASK-205 IMPL: scan routes `POST /scans` (with `Idempotency-Key`) and `POST /scans/{id}/cancel`

Implementer: impl-manager-m9. REQ-212, REQ-220, REQ-221, REQ-222. Risk high (lead's second look, PD-39). Spec: TS §6.2 L1119, L1122, L1084, §6.3 L1133–L1138, §6.4 L1146–L1155, §8.4 L1290. Answers applied: #3, #48, #122, #123. Built on TASK-192 (`idempotency`), 198 (`queue_scan`) and 200 (`cancel_scan`).

## Files

| File | Change |
| --- | --- |
| `manager/bitscan_manager/api/user/scans.py` (new, 197 lines) | the two routes, `ScanRequest`, `ScanQueuedItem`, `ScanCancelledItem` |
| `manager/bitscan_manager/api/user/__init__.py` | `scans` imported and its router included (+2 lines) |
| `manager/openapi.json` | re-exported with `python -m bitscan_manager.app manager/openapi.json`, +323 lines, insertions only |

## Routes

**`POST /api/v1/scans`:**
- Access: operator minimum (`require_role("operator")`), `bsu_` or `bsk_`. It is not a sensitive action, so there is no TOTP or sink gate (L1084).
- Body `ScanRequest`: `extra="forbid"`; `policy_id` a strict JSON integer 1 to 2^53 − 1; `target` an object. Any other key, or a non-integer `policy_id`, is 400 through the app's validation handler.
- The target goes through `targets.parse_target`. `InvalidTarget` is 400 `invalid_request` with its fixed detail (`Invalid request: target[.agents|.tags|.all]`).
- 202 `{scan_id, state: "queued", policy_version, jobs}` (TS §6.4).

Refusals from `queue_scan`, each raised before any write:

| Refusal | Answer |
| --- | --- |
| `PolicyNotFound` | 404 `not_found` "No such policy." |
| `PolicyDisabled` | 409 `conflict` "The policy is disabled." |
| `PolicyDeleted` | 409 `conflict` "The policy is deleted." |
| `PolicyHasNoPlugins` | 409 `conflict` "The policy has no active plugin." |
| `NoTargetAgents` | 422 `about:blank` "The target resolves to no host." |
| `UnstorableText` | 500 `about:blank`, logged by exception type only (#125 (g)) |

- The 1 MiB body cap (413) is the app's body-cap middleware (json class); no route cap was added.
- `actor = user:<id>`, `requested_by = user_id`, `trigger = 'manual'`, and `via_api_token = principal.kind is TokenKind.API`, so the `all_hosts_scan_api_token` alert fires only for `bsk_` with `{"all": true}` (REQ-221 (3)).
- `tx.on_commit(runtime.sink_gate.wake)`, as the other audited routes do.

**`Idempotency-Key`** (an optional header, documented as a header parameter):
- With the header, the call goes through `IdempotencyStore.run(user_id, key, body.model_dump(mode="json"), call)`.
- `InvalidKey` is 400 `invalid_request` "Invalid request: Idempotency-Key". `KeyReused` is 409 `conflict` "Idempotency-Key was used with a different request.".
- Only a 202 is remembered: every refusal is a `Problem` raised out of `call()`.
- The store is built once per process on first use, at `request.app.state.scan_idempotency`, under a module lock, with `runtime.clock`. This is the pattern `auth.py` uses for `totp_pending`, so `app.py` is unchanged.

**`POST /api/v1/scans/{id}/cancel`:**
- Operator minimum, no body.
- `{id}` must match the hyphenated 8-4-4-4-12 pattern (either case), else 400 (REQ-221 (4)).
- 200 `{scan_id, state, cancelled_jobs}`; `ScanNotFound` is 404 `not_found` "No such scan.".

The handlers import no repository (REQ-221 (5)). Imports are the `api` helpers, `auth`, `runtime` and `services.jobs.{build, queue, cancel, scan_state, targets}`.

## OpenAPI (G6)

- Two exports are byte-identical. The diff is insertions only.
- Components added: `ScanRequest`, `ScanQueuedItem`, `ScanCancelledItem` (no clash with an existing name).
- Responses: `POST /scans` has 202, 400, 401, 403, 404, 409, 413, 422, 429 and 503; cancel has 200, 400, 401, 403, 404, 429 and 503.
- `policy_id` `maximum` is 9007199254740991 (checklist 3).
- No agent-route component changed (REQ-232 (3)).

## For the tester (tester-m9b)

- Body checks come before authentication for **non-JSON** bodies: FastAPI parses a declared body before it solves dependencies. This follows the existing user-route pattern (`PUT /agents/{id}/tags`, `PATCH /policies/{id}`, `POST /auth/totp/enrol` all declare their bodies). A well-formed JSON body with a bad token still gets 401 first. Checklist item 4 is the reviewer's call; changing it would mean a self-read body, as in `policy_import.py`.
- REQ-221 (3): the `all_hosts_scan_api_token` kind is now registered in `services/audit/alerts.py` (TASK-198, main's ruling), so the alert path works.
- The idempotency store is per app instance. A test app built per test starts empty.

## Plants

- CHK-M9-364: `require_role("viewer")`.
- CHK-M9-365: the route moved onto the agent router; it is not reachable here because the user router's token resolution refuses `bsa_`.
- CHK-M9-382: `extra="allow"` on `ScanRequest`.
- CHK-M9-366: `via_api_token=True` for sessions.
- G34: a planted `POST /scans/{id}/run`.

## Gates

ruff check, ruff format --check, mypy --strict (with and without `--platform linux`) on `manager` (367 files, tests included): pass. OpenAPI export byte-stable.

## Revision 1 (2026-10-30): the target is checked before the idempotency digest

tester-m9 observed (TASK-192 TEST) that `body_digest` raises `ValueError` on NaN. FastAPI's JSON parser accepts `NaN`, and `target: dict[str, Any]` lets it through. So `{"policy_id": 1, "target": {"agents": [NaN]}}` sent with an `Idempotency-Key` would have answered 500 rather than 400.

Fix: `create_scan` now runs `parse_target(body.target)` (400 on `InvalidTarget`) **before** the store, and `_queue(policy_id, target, principal, runtime)` takes the parsed target. After a successful parse, the body holds only a strict integer and validated strings, lists and `true`, so `body_digest` cannot fail. A refused target is never remembered, as before.

`openapi.json` is unchanged: the export is byte-identical. Gates on my files: ruff check, ruff format --check, mypy --strict (with and without `--platform linux`): pass. `ruff check manager` currently also flags an import order (I001) in `api/agent/jobs.py`, which is TASK-204's file; impl-manager-m9b has been told.
