# TASK-099 plan: enrolment, token holder and rotation on the agent

Covers TASK-098 (enrolment) and TASK-099 (token holder and rotation). REQ-096, REQ-099, REQ-093. Owner: impl-agent. **Two approvals.** Tests: TP-M4-13, TP-M4-14; mutation rows CHK-M4-333, 340, 341, 347 to 349. Blocked on **#76**, **#81**; rotation rules are agreed (#62, decisions 2026-10-23).

## Spec quotes

- TS §3.2 L183–L184: the manager returns `agent_id`, the agent token, `issued_at` and `expires_at`, "which the agent stores in its state directory"; "The agent writes the token to `/var/lib/bitscan-agent/token` (0600) and the id to `/var/lib/bitscan-agent/agent_id` (0644), both owned `bitscan`, and deletes `enroll.token`."
- TS §3.2 L190: "The agent rotates at `issued_at + max(TTL − 30 days, TTL ÷ 2)` … If the response is lost, the agent retries with the old token; the manager then issues a fresh new token and discards the unused one."
- TS §3.2 L191: "On 401 `token_revoked` or `token_expired` the agent stops all loops and logs that the host must be re-enrolled with a new enrolment token."

## State files (TASK-088, in `/var/lib/bitscan-agent/`)

| File | Mode | Content |
| --- | --- | --- |
| `agent_id` | 0644 | the UUID, one line |
| `token` | 0600 | the `bsa_` token, one line |
| `token.json` | 0600 | `{"issued_at", "expires_at"}` (TS §3.2 L183 names no file; the agent's own choice) |
| `enroll.token` | 0600 | written by `postinst`, deleted after enrolment |
| `seen_jobs.json` | 0600 | job id → first-seen time, entries older than 7 days pruned on load and on write |

Every write: create `.<name>.tmp` with `O_EXCL|O_NOFOLLOW` and the final mode, write, `fsync`, `rename`, `fsync` the directory. The token is written before `token.json`; a reader that finds a token newer than `token.json` (crash between the two) treats the window as open, so rotation is attempted and the manager decides.

## Enrolment (TASK-098)

1. If `enroll.token` exists (#81: also when a `token` exists, which is how re-enrolment works): read `/etc/machine-id` (must be 32 lowercase hex characters, else refuse at start-up), `os.Hostname()`, and `ID`, `VERSION_ID`, `PRETTY_NAME` from `/etc/os-release` (absent → `null`), then call enrol.
2. Success: write `agent_id`, `token`, `token.json`, then delete `enroll.token` (in that order, so a crash before the delete re-enrols, which the manager treats as a re-enrolment, #76).
3. 401: keep `enroll.token`, write nothing, report "stop" with the log line "enrolment refused; the host needs a new enrolment token".
4. 429, 5xx, network error: back-off and retry (#76 for the lost-response case).

## Token holder and rotation (TASK-099)

```go
type Holder struct{ mu sync.RWMutex; tok string; issued, expires time.Time; prev string; ... }
func (h *Holder) Current() string                 // every request reads this under RLock
func (r *Rotator) MaybeRotate(ctx context.Context, now time.Time) error // single-flight (a mutex held for the whole call)
```
- Window start = `issued + max(ttl − 30 d, ttl / 2)` with `ttl = expires − issued`. The heartbeat loop calls `MaybeRotate` after each successful heartbeat; nothing else triggers it.
- Call with the current token. On 200: persist (`token`, `token.json`) first, then swap the holder; the old token is kept in memory only for the retry case. On a network error or 5xx (response possibly lost): the next attempt uses the **old** token (the manager answers with a fresh token, decisions 2026-10-23); the holder is not swapped until a 200 is persisted.
- 429: no attempt before `Retry-After` has passed (the 24 h rule); 403 `forbidden` (outside the window per the manager's clock): next attempt after 24 h; 401: "stop".
- Never two rotate calls at once, also not from a restart racing a running process (one process; the unit runs one instance).

## Edge cases

- Agent clock behind the manager's: the agent rotates late; the manager's window check governs and 403 is handled.
- A token past `expires_at` on the agent clock is still sent; the manager's 401 `token_expired` stops the loops (REQ-099 (6)).
- After an unused rotation the old token works only until `last_rotation_at + 30 days` (decisions 2026-10-23); the agent always prefers the persisted new token, so this only matters if persisting failed and is logged loudly.
