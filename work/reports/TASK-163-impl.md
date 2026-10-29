# TASK-163 IMPL: `DELETE /api/v1/policies/{id}`

Owner: impl-manager-m7b. REQ-171, REQ-174, REQ-177. Risk: high (sensitive route). Depends on TASK-160 (`CatalogService.delete`, `Runtime.catalog`) and TASK-161 (the policies router).

Spec and rulings: TS §6.2 L1104 (route table: admin, TOTP session), L1084 (sensitive actions), §4.3 L550; #1 (agreed: also refused during an audit-sink outage); #98 (e), (j), (k); #102 (d); decisions row "Speed-up" (2026-10-28).

## What changed

| File | Change | Lines |
| --- | --- | --- |
| `manager/bitscan_manager/api/user/policies.py` | the `DELETE /{id}` route on the existing policies router; docstring and imports | +49 −6 |

- **`manager/openapi.json` is not edited**, per the Speed-up row: impl-manager-m7 regenerates it once after TASK-162, 163 and 164.
- **`api/user/__init__.py` needs no change:** the policies router is already registered.

## Route

`delete_policy(id, principal, runtime) -> Response(204)`. It mirrors the approved TASK-161 routes in the same file and the approved revoke route in `agents.py`:
- **Authentication and authorisation:** `require_totp_session()`, which applies the admin minimum, a TOTP-verified session and the sink gate. This is the dependency the approved sensitive routes use, so:
  - an admin `bsk_` gets 403 `totp_session_required`;
  - an operator or viewer gets 403 `forbidden`;
  - after 15 minutes of audit-sink outage the answer is 503 `audit_sink_unavailable` (#1);
  - `bsa_`/`bse_` get 401 at the user router.
- **Id:** the same `POLICY_ID` path pattern (`^[0-9]{1,20}$`, so `+1` and `1.0` get 400) and the same `_policy_id` check: 0, or a value above 2^63 − 1, gives 404.
- **Body:** `runtime.catalog.delete(policy_id, "user:<id>")` (`CatalogService.delete`). It runs `delete_policy` under the catalog lock in one transaction, then removes the uploaded copy, and the service wakes the audit shipper. The handler is a sync `def`, as in this router, so FastAPI runs it in its thread pool.
- **Answers (#98 (e), (k), #102 (d)):**

  | Status | Type | When |
  | --- | --- | --- |
  | 204 | (no body) | deleted |
  | 404 | `not_found` "No such policy." | unknown id |
  | 409 | `conflict` "The policy is deleted." | already deleted |
  | 409 | `policy_managed_on_server` (same text as the import route) | the policy's file is in the server folder |
  | 503 | `about:blank` "The catalog is starting; retry shortly." with `Retry-After: 10` | `CatalogStarting` |
  | 503 | `about:blank` "The service is not ready." | `runtime.catalog` is None |

  A database error propagates to the app's existing 503 handling (#98 (j)). Every detail is fixed text.
- **OpenAPI:** `status_code=204`, with `problem_responses` for 401, 403, 429, 503, 404 and 409; FastAPI adds 400.

## Checks run here (scratch, outside the tree; the tests are the tester's)

- **Gates:** `ruff check manager/bitscan_manager` and `ruff format --check manager` (302 files) are clean, and so is `mypy --strict --config-file manager/pyproject.toml manager/bitscan_manager`. The whole-tree mypy currently flags only `manager/tests/test_catalog_service_pg.py:286`, a test file.
- **Schema** (`create_app().openapi()` in memory; `openapi.json` not written): `DELETE /api/v1/policies/{id}` has responses 204 (no content), 400, 401, 403, 404, 409, 429 and 503, tag `policies`.
- **Handler smoke** (`C:\Users\kaiquan.koh\scratch\task163\smoke.py`, fake runtime and catalog), all matching the table above:
  - a delete gives 204, and the catalog gets `(12, "user:7")`;
  - `CatalogStarting`, an unknown id, an already deleted policy and a server-folder policy each give their row's answer;
  - ids `0` and `9223372036854775808` give 404;
  - no catalog gives 503.

## For the tester (REQ-171 (1)–(4), REQ-167 (1) through the route, REQ-174 (2))

- **Plants:**
  - Use `require_role("admin")` instead of `require_totp_session()`: REQ-171 (1) `bsk_` and REQ-171 (2) the sink gate.
  - Pass `sink_gate=False`: REQ-171 (2).
  - Drop the `CatalogStarting` branch: 500 instead of 503 with Retry-After.
  - Map `PolicyAlreadyDeleted` to 404: REQ-171 (4).
  - Swallow `PolicyManagedOnServer`: REQ-171 (3).
