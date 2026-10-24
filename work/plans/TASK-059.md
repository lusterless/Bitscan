# TASK-059 plan: agent token check, the agent dependency and rotation

Covers TASK-059 (service), TASK-063 (router and dependency) and TASK-075 (rotation). REQs: REQ-062, REQ-064, REQ-065, REQ-071, REQ-087. Owner: impl-manager. **Two approvals (TS §8.2 L1268) for all three.** Tests: TP-M3-13, TP-M3-17, TP-M3-29; mutation rows CHK-M3-320, 321, 338 to 344, 362 to 364.

**Blocked on #59** (statuses, order), **#62** (overlap and reuse), **#63** (missing header), **#26** (rejected re-enrolment), **#25** (IP recording). Values that depend on them are marked.

## Spec quotes

- TS §3.2 L185: "Until then every agent call returns 403 `pending_approval`." L187: "the new token's hash stays in `enrollment_request` until approval, and the token check looks there to answer 403 `pending_approval`." L188: "the agent receives 401 `enrollment_rejected`".
- TS §3.2 L189: "A missing, unknown, revoked or expired token gets 401. A valid token with a different machine-id gets 401 and the token is revoked."
- TS §3.2 L190: rotation window `issued_at + max(TTL − 30 days, TTL ÷ 2)`; "at most once per 24 h, counting only rotations whose new token was then used. The old token stays valid until the new token is first used and for 10 minutes after that (`agent.prev_token_hash`). If the response is lost, the agent retries with the old token; the manager then issues a fresh new token and discards the unused one. Once the new token has been used, any later use of the old one revokes both tokens and alerts (reuse detection). A rotation from a source IP not seen for this agent in the last 7 days also alerts."
- TS §6.1 L1069: "The `{id}` in the path must match the token's agent, otherwise 403." TS §6.3 L1136: failed token checks 20 per minute per IP; agent routes 30 per minute per agent.

## Rotation state on the `agent` row (no new column)

| State | `token_hash` | `prev_token_hash` | `prev_token_expires_at` |
| --- | --- | --- | --- |
| Steady | current | NULL or the last old hash (kept for reuse detection) | NULL or a past time |
| Rotated, new not yet used | new | old | NULL |
| New used (overlap) | new | old | first use + 10 min |
| After overlap | new | old | in the past |

"New token was then used" (the 24 h rule) means `prev_token_expires_at IS NOT NULL` for the latest rotation. `last_rotation_at` is set at each successful rotation.

## Outcome table (TASK-059; order per #59)

Lookup order: `agent.token_hash`, then `agent.prev_token_hash`, then `enrollment_request.new_token_hash` (only the newest request with that hash; the column is UNIQUE).

| # | Found as | Condition | Answer | Side effect |
| --- | --- | --- | --- | --- |
| 1 | nothing | | 401 `unauthorized` (#59) | failed check |
| 2 | request | `decision = 'rejected'` | 401 `enrollment_rejected` | failed check |
| 3 | agent current | agent `decommissioned` and its `kind = 'new'` request rejected | 401 `enrollment_rejected` | failed check |
| 4 | agent current | `token_revoked_at` set (revoke, decommission, mismatch, reuse) | 401 `token_revoked` | failed check |
| 5 | agent current or request | `token_expires_at <= now` | 401 `token_expired` | failed check |
| 6 | agent current or prev | header missing, malformed (#63) or not the row's `machine_id` | 401 `machine_id_mismatch` | revoke (`token_revoked_at = now`, which also stops the prev token) and `machine_id_mismatch` alert; failed check |
| 6b | request (pending) | header mismatch | 401 `machine_id_mismatch` | alert only; the request stays pending for the admin (#63) |
| 7 | agent prev | `prev_token_expires_at IS NULL` (new not used yet) | accepted as the agent | (rotate with it = lost-response retry, TASK-075) |
| 8 | agent prev | `now < prev_token_expires_at` (overlap) | accepted (#62) | none |
| 9 | agent prev | `now >= prev_token_expires_at` | 401 `token_revoked` | revoke both, `token_reuse` alert (#62); failed check |
| 10 | agent current | status `awaiting_approval` | 403 `pending_approval` | not counted |
| 11 | request | `decision IS NULL` | 403 `pending_approval` | not counted |
| 12 | agent current | first use after a rotation (`prev_token_hash` set, `prev_token_expires_at IS NULL`) | accepted | set `prev_token_expires_at = now + 10 min` |
| 13 | agent current or prev | otherwise | accepted | |

Then, in the dependency (TASK-063): `{id}` must equal the resolved agent id, else 403 `forbidden` (#59), not counted; then the 30-per-minute agent limit (429 `rate_limited`, `Retry-After`); then IP recording (#25: `agent.last_seen_ip` and an `agent_ip_seen` upsert), which returns the IP's previous `last_seen_at` so rotation can check the 7-day rule before it is overwritten. A previous token used in the overlap is recorded the same way.

Every 401 calls `limits.record_failed_check(ip)` (and answers 429 instead when `failed_check_blocked(ip)`), exactly as M2 `current_principal` does, and also feeds the per-agent 401 window of #65 (d) when the token resolved to an agent. A pending 403 never counts.

## Interface

```python
# bm/services/enrolment/token_check.py
class AgentRepoP(Protocol): ...         # find_by_token_hash, find_by_prev_hash, revoke, mark_new_token_used
class RequestRepoP(Protocol): ...       # find_by_new_token_hash, find_rejected_new_for_agent
@dataclass(frozen=True)
class AgentCaller:
    agent_id: UUID
    via: Literal["current", "previous", "request"]
    agent: AgentRow | None             # None only for a pending request (which never passes)
class AgentTokenRefused(Exception):
    status: int; type: str; counted: bool; agent_id: UUID | None
def check_agent_token(agents: AgentRepoP, requests: RequestRepoP, audit: AuditRepo,
                      on_commit: Callable[[Callable[[], None]], None],
                      raw: str, machine_id_header: str | None, now: datetime) -> AgentCaller: ...

# bm/api/agent/dependencies.py
def current_agent(request: Request, id: UUID, runtime: Runtime = Depends(get_runtime)) -> AgentCaller: ...
# bm/api/agent/bodies.py
async def read_capped(request: Request) -> bytes: ...   # after-auth cap (TASK-049); raises Problem 413

# bm/services/enrolment/rotation.py (TASK-075)
def rotate(caller: AgentCaller, ..., now: datetime, source_ip: str, ip_last_seen: datetime | None) -> RotateResult: ...
```

Revokes and alerts in the check commit in their own short transaction before the 401 is returned (the request itself is refused, so nothing else is written).

## Rotation (TASK-075)

1. Caller via `current`, TTL = `token_expires_at − token_issued_at` of that token; `window_start = issued_at + max(TTL − 30 d, TTL / 2)`. If `now < window_start`: refuse (#62: 403 `forbidden`) and alert `rotation_outside_window`. (`now >= expires_at` never reaches here: row 5.)
2. If `last_rotation_at > now − 24 h` and that rotation's token was used (`prev_token_expires_at IS NOT NULL`): refuse (#62: 429 with `Retry-After`).
3. Caller via `previous` with `prev_token_expires_at IS NULL`: lost-response retry. Issue a fresh token into `token_hash`, keep `prev_token_hash`, do not move `last_rotation_at`, no 24 h count. Its window check uses the old token's `issued_at`, which is no longer stored once rotated; the retry is allowed because the original rotation passed the window (recorded by `last_rotation_at`).
4. Caller via `previous` after the new token was used: reuse (#62), revoke both and alert (row 9 semantics, even inside the overlap).
5. Otherwise: `prev_token_hash = token_hash`, `prev_token_expires_at = NULL`, new `token_hash`, `token_issued_at = now`, `token_expires_at = now + agent_token_ttl_days` (current setting), `last_rotation_at = now`. Audit `agent.token_rotate`. If the source IP's previous `last_seen_at` is NULL or older than 7 days: alert `rotation_new_ip`.
6. All in one transaction with `SELECT … FOR UPDATE` on the agent row, so two concurrent rotations serialise.

## Edge cases

- A token presented both as one agent's `prev_token_hash` and another's `token_hash` cannot happen (256-bit tokens); the lookup order still makes current win.
- Approval of a re-enrolment copies the request hash into `token_hash` and clears `prev_*` (#64); the old token is then simply unknown (row 1), not `token_revoked`.
- Decommission by the sweep sets `token_revoked_at`; rows 3 and 4 distinguish rejection from decommission.
- The machine-id compare is exact (`CHAR(32)` values; #60 fixes lowercase hex, so no case folding).
- Tokens are compared only by SHA-256 lookups; no raw token is held after hashing, and nothing is logged but the outcome name and the `agent_id` (REQ-087).
