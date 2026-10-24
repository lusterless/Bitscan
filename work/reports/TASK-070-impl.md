# TASK-070 IMPL report: enrolment requests (list, approve, reject)

REQ: REQ-069, REQ-077. Spec: TS §3.2 L185–L188 and L192, §6.2 L1084 and L1114–L1115, §8.4 L1290; #26, #36, #64, #68, #71. Plan: `work/plans/TASK-067.md` ("Decisions", "Matches"). It depends on TASK-052, 056, 061, 066 and 067, all approved. **Two approvals** (TS §8.2).

Carry-overs applied:
- re-enrolment approval re-links with the request's token and times;
- an approval queues the first inventory job;
- approving a request whose token has expired gives 409;
- reject-new decommissions the agent and revokes its token, and reject-re-enrolment changes nothing (#26);
- `new_token_hash` never appears in a response;
- approve and reject need an admin TOTP session and pass the sink gate; the list allows an admin session or API token.

## Files (3)

- `manager/bitscan_manager/services/enrolment/requests.py`: new, 169 lines.
- `manager/bitscan_manager/api/user/enrolment.py`: the request routes are added (now 291 lines). The module's `router` is now a parent that includes the `tokens` router (TASK-066, unchanged) and the new `requests` router, so `api/user/__init__.py` needs no edit.
- `manager/openapi.json`: re-exported after TASK-048 r2's export, and byte-stable. It adds `GET /api/v1/enrollment-requests`, `POST …/{request_id}/approve` and `POST …/{request_id}/reject`, plus `RequestItem` and `MatchItem`. The string `new_token_hash` appears nowhere in the document.

## Routes

- **`GET /enrollment-requests`** uses `require_role("admin")`, so an admin session or an admin API token works.
  - `?state=pending` (the default), `decided` or `all`, with keyset paging `{items, next_cursor}`. A cursor's scope includes the state, so a cursor cannot be reused across states.
  - Each item has the #68 fields `{request_id, kind, agent_id, hostname, machine_id, os_pretty_name, agent_version, source_ip, requested_at, token_expires_at, decision, decided_by, decided_at, matches}`.
  - `matches` lists every **other** agent that shares the hostname or machine-id, as `{agent_id, hostname, machine_id, status}` (TASK-052). This is how cloned images show up.
- **`POST /enrollment-requests/{id}/approve`** and **`/reject`** use `require_totp_session()`: admin, TOTP-verified session, sink gate (an admin `bsk_` gets 403 `totp_session_required`).
  - Answers: 200 with the decided item; 404 `not_found` for an unknown id; 409 `conflict` with a fixed reason.
  - On 409 the transaction rolls back and nothing changes.

## Decision (one transaction; the request is locked first, then the agent)

| Request | Approve | Reject |
| --- | --- | --- |
| `new` | `set_status(enrolled, only from awaiting_approval)`; if the agent no longer awaits approval, 409. One `enrollment_request.approve` entry. First inventory job (#36). | `set_status(decommissioned, only from awaiting_approval)` and `revoke` (`token_revoked_at`). The row is kept. One `enrollment_request.reject` entry. |
| `reenrol` | `relink`: the request's `new_token_hash`, `token_issued_at = requested_at`, `token_expires_at` = the request's, `hostname` and `agent_version` from the request; `token_revoked_at`, `prev_*` and `last_rotation_at` cleared; status `enrolled` (#64 (a)–(c)). The old token is now simply unknown. The **one entry is the `reenrolment_approved` alert** (action `enrollment_request.approve`, #71). First inventory job. | The agent row and its old token are unchanged (#26). One `enrollment_request.reject` entry. |
| already decided | 409 | 409 |
| request token expired (`now ≥ token_expires_at`) | 409 (#64 (e)) | allowed |

- Actor `user:<admin id>`, target `enrollment_request:<id>`, detail `{kind, agent_id}`. No token or hash.
- `decide()` re-checks `decision IS NULL`. Together with the `FOR UPDATE` lock, two concurrent decisions give one success and one 409.
- Several pending requests for one agent are decided independently (#64 (d)). Approving a later one re-links again.

## Local gates (Windows)

- ruff, ruff format and `mypy --strict` pass for `bitscan_manager` (90 files).
- `pytest -q`: 2189 passed, 955 skipped. The 1 failure is the known TASK-072 test `test_body_caps.py::test_other_agent_routes_keep_one_mib`, which tester-c is handling.
- OpenAPI: re-exported and stable.
- Service probe with fakes:

  | Case | Result |
  | --- | --- |
  | approve new | agent `enrolled`, one approve entry, first job queued |
  | approve re-enrolment of a decommissioned agent | relinked with the request's hash, `issued_at = requested_at`, the request's `expires_at` and hostname; `enrolled`; one `reenrolment_approved` alert; first job |
  | reject new | agent `decommissioned` and revoked; one reject entry; no job |
  | reject re-enrolment | agent untouched; one reject entry |
  | decided again | 409; nothing written |
  | approve with an expired token | 409; nothing written |
  | reject with an expired token | allowed |
  | unknown id | 404 |
  | approve new when the agent no longer awaits approval | 409 |

- Through the API on PostgreSQL (TP-M3-24): **NOT RUN locally**; WSL.

## Deviations

None. The size is over the guide (169 + about 130 added); the plan expected it close to the limit.

## Revision 1 (lead ruling 2026-10-23, from #64 (d), (f); found by tester-d)

- **Defect.** Agent A is `awaiting_approval` with R1 (`new`). R2 (`reenrol`, same agent) is approved, so A is `enrolled` with R2's token. Two things then went wrong:
  - Rejecting R1 ran `revoke()` anyway, which killed R2's token.
  - Approving R1 answered 409.
- **Fix (`services/enrolment/requests.py`, `decide_request` only).** The locked agent row is read. A `new` request acts on the agent "as new" only while that agent is **still `awaiting_approval`** (`first`).
  - **Approve**, `first`: `awaiting_approval` → `enrolled`, one `enrollment_request.approve` entry, first inventory job (unchanged).
  - **Approve**, otherwise (a `new` request whose agent was enrolled through another request, or any `reenrol`): **relink**. This is the re-enrolment approval: the request's token hash, `requested_at` and `token_expires_at`, its hostname and agent version, old token state cleared, `enrolled`. It writes the `reenrolment_approved` alert and queues the first job (#64 (d), (f)).
  - **Reject**, `first`: the agent becomes `decommissioned` and its token is revoked (unchanged).
  - **Reject**, otherwise: only the request is rejected. The agent and its current token are untouched (#26).
  - 409 stays only for an already-decided or concurrently decided request, and for approval with an expired request token (#64 (e)).
- **Probe** (fakes):

  | Case | Result |
  | --- | --- |
  | reject R1 while A is enrolled | R1 rejected; A stays `enrolled`; no `set_status` or `revoke` call |
  | approve R1 while A is enrolled | relinked with R1's hash and times; `reenrolment_approved` alert; first job |
  | approve or reject a `new` request while still awaiting | as before |
  | approve R1 with an expired token | 409 |
  | every earlier case | unchanged |

  `new`, agent no longer awaiting, previously gave 409 and now relinks, as ruled.
- **Gates:** ruff, ruff format and `mypy --strict` pass.
