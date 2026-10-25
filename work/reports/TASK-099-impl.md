# TASK-099 IMPL: token holder and rotation

REQ-099. TS §3.2 steps 3, 7 and 8 (L183, L190–L191), §6.5 Rotate (L1188); #62; decisions 2026-10-23 (lost-response retry, the 24 h rule, the 30-day cap); plan `work/plans/TASK-099.md`, section "Token holder and rotation". **Two approvals (TS §8.2, agent).** Depends on TASK-086 (wire), TASK-088 (state) and TASK-093 (client).

No tests were run (that is the tester's job). I ran a throwaway copy outside the tree with a fake `Doer` and `Saver`; it is deleted (results below).

## Files (new; no other file touched)

| File | What |
| --- | --- |
| `agent/internal/agent/token/holder.go` (about 20 non-comment lines) | `Holder`, `NewHolder(state.Token)`, `Current()`, and the unexported `set` (rotator only). |
| `agent/internal/agent/token/rotate.go` (about 85) | `Rotator`, `NewRotator(client Doer, store Saver, holder, agentID)`, `MaybeRotate(ctx, now)`, `WindowStart(t)`, `ErrStop`, and the `Doer` and `Saver` interfaces (production: `*transport.Client` and `*state.Store`). |

## Behaviour

- **One token for every loop:** each request builds its `Authorization` from `holder.Current().Value` (`string(...)`), read under an `RWMutex`. A rotated token reaches every loop the moment `set` runs.
- **Window:** `WindowStart = issued_at + max(TTL − 30 d, TTL ÷ 2)`, with `TTL = expires_at − issued_at` of the current token. A 365-day token from 2026-01-01 opens on 2026-12-02 (day 335). When `TimesKnown` is false (a crash between the `token` and `token.json` writes, TASK-088), the window counts as open and the manager decides, as the plan says.
- **Trigger:** `MaybeRotate(ctx, now)` is called only by the heartbeat loop after a successful heartbeat (TASK-101). It uses only the `now` it is given.
- **One call at a time:** `TryLock` on a mutex held for the whole call. A second trigger while a call runs returns nil at once, and never waits to make a second call.
- **200:** the body is decoded strictly as `RotateResponse`, then `SaveToken` runs (`token`, then `token.json`), then the holder is swapped. If the decode or the save fails, the holder keeps the old token and an error is returned. The next attempt (next heartbeat) then sends the old token, which is the manager's lost-response retry: it issues a fresh token. A crash after the answer and before the save leaves the old token on disk, and the next run rotates again.
- **Network error or 5xx:** an error. The holder is unchanged, so the next attempt sends the old token.
- **429:** no attempt before `now + Retry-After` (the 24 h rule). The first heartbeat after that tries again.
- **403 (Drop class, for example `forbidden` outside the manager's window):** no attempt for 24 hours.
- **401 (any type):** returns `ErrStop`, and the rotator latches. Every later call returns `ErrStop` without contacting the manager, so the loops stop (#81).
- **Other answers (3xx, 400, 404, 409, 422, 403 `pending_approval`):** an error with the fixed text `token: rotate <status> <type>`, tried again at the next heartbeat. The spec gives no special wait for these. **Reviewer:** flag it if a 24 h wait should apply to every drop answer.
- **Expired tokens are still sent:** a token past `expires_at` on the agent's clock is still sent (REQ-099 (6)). The manager's 401 `token_expired` gives `ErrStop`.
- **No secrets in output:** the error text has fixed words, the status and the problem type, never a token. `%+v` of `holder.Current()` shows `bsa_[redacted]`.

## Scratch run (evidence, not a test)

| Case | Result |
| --- | --- |
| Day 334 | no call |
| Day 335, connection reset | error, holder still on token A |
| Next heartbeat | call made with **A** again (the fake recorded `bsa_A`, `bsa_A`); its token B persisted and swapped in |
| Day 336 | no call (the new token's window is closed) |
| 200, but `SaveToken` fails | error, holder still on A |
| 20 goroutines trigger at once | exactly 1 call |
| 429 with `Retry-After: 3h` | first call, nothing at +2 h, the next call at +23 h |
| 403 `forbidden` | first call, nothing at +2 h and +23 h, the next call at +25 h |
| 401 | `ErrStop`, and latched (added after this run; built and linted, the latch itself not re-run) |

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l internal/agent/token`: prints nothing.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet` and `go build ./...`: clean.
- `GOOS=linux golangci-lint run ./internal/agent/token/... ./internal/agent/transport/...`: `0 issues`.

## For the tester (TP-M4-14; CHK-M4-347 to 349)

- The fake manager can be an `httptest.NewTLSServer` through the real `transport.Client`, or a fake `Doer`. A fake `Saver` can make `SaveToken` fail, for the crash-before-save case.
- For the race case, run 20+ goroutines against a fake that sleeps, under `-race`, and expect exactly one call.
- Whether the old token is used comes down to the `Authorization` header the fake receives.

## Revision 1 (user ruling 2026-10-25: Drop answers wait 24 h)

Ruling: every rotate answer in the Drop class waits 24 h before the next rotate attempt, as 403 `forbidden` already did. The Drop class is 3xx, 400, 403 other than `pending_approval`, 404, 409, 413, 422, an oversized answer, and any other answer that is not retried. The old token stays in use. This replaces the "Other answers" bullet above, which retried at the next heartbeat.

Change, in `agent/internal/agent/token/rotate.go` only:
- The condition `resp.Status == http.StatusForbidden && resp.Class == transport.Drop` became `resp.Class == transport.Drop`, which sets `notBefore = now + 24 h`.
- The `forbiddenWait` comment now says it covers every Drop answer. The name is unchanged, so in-package references still hold.

Unchanged:
- 429 (`Retry-After`) and 401 (`ErrStop`, latched) behave as before.
- Retry answers (5xx, network) are still tried at the next heartbeat.
- A 403 `pending_approval` (Wait class, which the manager does not send on rotate) is still tried at the next heartbeat.
- A 200 whose body fails strict decoding, or whose save fails, is not a Drop answer: it is still retried at the next heartbeat with the old token, which is the lost-answer path.

Gates (Windows, Git Bash, from `agent/`): `gofmt -l internal/agent/token` prints nothing; `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go vet ./internal/agent/token/` clean; `GOOS=linux golangci-lint run ./internal/agent/token/...` 0 issues.

For the tester:
- Re-run `TestRotationOtherAnswersKeepOldToken` and `TestRotationRefusals` (the 403 `forbidden` 24 h case shares the changed line).
- `TestRotationOtherAnswersKeepOldToken` currently asserts only that nothing is persisted or swapped. Per the ruling it should also assert, for each of 301, 400, 404, 409, 413 and 422: no call at +23 h, and one call (with the old token) at +24 h or later.
- Plant: restore the old condition (`resp.Status == http.StatusForbidden && …`), so a Drop answer is retried at the next heartbeat; that test must go red.
