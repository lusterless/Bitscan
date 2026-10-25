# TASK-093 REVIEW: HTTP client and response classes

Verdict: APPROVED (revision 1)

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/agent/transport/client.go` and `agent/internal/agent/transport/classify.go` (`work/reports/TASK-093-impl.md`). `tls.go` (TASK-089) is unchanged. Sources:
- TS §3.2 L189 and L194, §3.3 L224–L226, §6.1 and §6.5;
- REQ-094, REQ-095;
- #59 (problem types) and #75 (no proxy, no redirects, user 2026-10-24);
- plan `work/plans/TASK-093.md`.

TEST: PASS (`work/reports/TASK-093-test.md`).
- `go test ./internal/agent/transport/` passes 56/56, and 56/56 under `-race`.
- 24/24 mutation plants are red. They include CHK-M4-327 (redirect followed), -328 (`ProxyFromEnvironment`), -329 (machine-id), -336 and -337 (classes), plus: the call timeout, the context not used, the token in an error or in `Request.String`, unchecked ids, an `http` base and an ignored Retry-After.
- The only change this round was test-side: `TestClientOwnTimeLimit` now bounds its own wait (CHK-M4-084-r1).

## Checks
1. Spec:
   - **Routes.** The six routes are under `<manager_url>/api/v1/agent/` with the TS §6.1 methods. `?job_id` is only on inventory, and results require a job id.
   - **Ids.** They are checked by the wire UUID rule before any call and sent lower-case, so no manager-supplied value can shape a path (13 path-shaped ids are refused, CHK-M4-088).
   - **Headers.** `Authorization: Bearer` goes on every call, and `X-Bitscan-Machine-Id` on every call except enrol (REQ-094 (4)). `Content-Type` is sent only with a body and `Content-Encoding: gzip` only when set. No `Accept-Encoding`.
   - **#75.** `Proxy: nil`: the recording environment proxy saw 0 connections. `CheckRedirect` returns `ErrUseLastResponse`, so a 3xx is the answer, class Drop. A 307/308 to a second server got 0 requests.
   - **Classes (TS §3.3 L224, REQ-095 (1)).** 2xx is Success. Any 401 is Stop. 403 `pending_approval` is Wait. 429, 5xx and transport errors are Retry. Everything else is Drop, including 400, 404, 409, 413, 422, any other 403 and 3xx. The tester checked statuses 100–599 against 15 types.
   - **TLS and pin failures** are Retry, and `IsVerifyError` lets the loop log them loudly.
2. Limits:
   - Dial 10 s, handshake 10 s, call 60 s and inventory 120 s, layered under the caller's context.
   - The body cap is 32 MiB. A `Content-Length` over the cap is refused before reading. A chunked body is read through `LimitReader(cap+1)`. Exactly the cap is accepted and cap+1 is refused (REQ-094 (5)).
3. Security:
   - No logging in the package.
   - `Request.String()` shows only the route.
   - The error text wraps `net/http` errors, whose URL holds ids only, and `url.Error` strips any password. No canary appeared in any error or `%v` (CHK-M4-086).
   - The token is chosen by the caller for each call, which TASK-099's lost-response retry needs.
   - No client certificate. TLS comes from TASK-089.
   - No listening socket, no `InsecureSkipVerify`, no `//nolint`.
4. Re-run by the reviewer (Windows):
   - `gofmt -l internal/agent/transport` prints nothing.
   - `CGO_ENABLED=0 GOOS=linux go vet` is clean.
   - `GOOS=linux golangci-lint run ./internal/agent/transport/...` reports 0 issues.
5. Scope: 2 new files, about 230 non-comment lines, slightly over the 170 estimate. The two files cannot be split usefully, and I accept the size.

## Findings
1. nit, `classify.go:15`. `Success` is the zero value of `Class`. Every path in `Do` sets `Class`, so this is safe today. A future `Doer` that returns `(Response{}, err)` would read as Success, as noted in the TASK-099 review (finding 2). Optional: make the zero value non-success, for example an `Unknown` first, or have callers check `err` first.
2. **Closed by r1 (lead ruling 2026-10-25).** nit, `client.go:200-201`. A very large `Retry-After` overflows `time.Duration(s) * time.Second` (about 9.2e9 s or more). The result can be negative, so TASK-099 would retry at the next heartbeat. That attempt is still paced by the heartbeat, and the header comes only from the manager. Optional: clamp `s`, for example to 25 h.
3. nit, `client.go:138-139`. A query or fragment in `manager_url` is overwritten or ignored, and userinfo is kept. TASK-087's loader and the postinst check accept `https://u:p@host`. Go then does not send basic auth, because `Authorization` is already set, so nothing leaks. Optional: refuse userinfo, a query and a fragment in the config loader (TASK-087's file).

## Revision 1 (Retry-After clamp)
- **Change.** `classify.go` gains `MaxRetryAfter = 24 h` and `RetryAfter(v)`, which parses with `strconv.ParseUint(v, 10, 64)`.
  - On `ErrRange`, `n` is the maximum value, so any value above 86,400 s, including one past 2^64, gives exactly 24 h.
  - A value that cannot be parsed, zero, an HTTP date or a leading `+` gives 0, which matches RFC 9110 delay-seconds.
  - `client.go` calls `RetryAfter`. The token rotator's 429 wait is the only reader.
- **Re-run by the reviewer.**
  - `gofmt` prints nothing.
  - `GOOS=linux golangci-lint run` on transport and token reports 0 issues.
- **TEST: PASS** (tester-m4, CHK-M4-085-r1 and -r1-mut).
  - `TestClientAnswers` and `TestRotationRefusals`, both extended, pass 13/13.
  - The controls pass: transport 56/56 and token 42/42.
  - 7/7 r1 plants are red, including the clamp removal: 2^63 gives a 0 s wait and an immediate second rotate.
- The user's second approval covers TASK-093 including r1.
