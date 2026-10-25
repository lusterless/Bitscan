# TASK-098 REVIEW: enrolment and the start-up decision

Verdict: APPROVED

Reviewer: reviewer, 2026-10-25. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/agent/enrol/enrol.go` (`work/reports/TASK-098-impl.md`). Sources: TS §3.2 steps 2–5 and 8, §3.1 L162 and L172, §6.5 Enrol, REQ-096, #76 and #81 (agreed 2026-10-24).

TEST: PASS (`work/reports/TASK-098-test.md`): 53/53 as root and as `bstester`, and 17 of 18 plants red. The survivor is equivalent: `wire.UUID` already lowercases the id.

## Checks
1. Spec:
   - **Start-up decision, #81 (c).** If `enroll.token` exists, the agent enrols, also when a `token` exists, and the answer replaces `agent_id`, `token` and the times. If only `token` exists, the stored identity is used with no call. If neither exists, `ErrNoCredentials` names both files before any call. An unreadable or empty `enroll.token` is an error, never a fallback to `token`.
   - **Request.** It has the six `EnrolRequest` keys: hostname, machine-id, version, and the OS fields from `ReadOSRelease`, null when absent or out of bounds. It is checked by `wire.Encode` and carries no machine-id header (TS §3.2 step 6 applies only to later calls).
   - **Answers.**
     - 2xx: strict decode; persist `agent_id`, `token` and `token.json`, then delete `enroll.token`. A crash in between makes the agent enrol again (#76).
     - Both `enrolled` and `awaiting_approval` start the loops (step 5: the heartbeats then wait on 403).
     - Any 401: `ErrStop` with the agreed text, `enroll.token` kept and nothing written. `main` stays idle (#81 (a)).
     - 429, 5xx and network errors: retried with the TS §3.3 back-off, with the same token and the same body bytes (#76).
     - Any other answer: an error, no retry.
   - **Machine-id.** Exactly 32 lowercase hex characters, with an optional single newline. At most 64 bytes are read (REQ-096 (4)).
2. Security:
   - Nothing here logs. Errors hold fixed words and a status code, never the `bse_` token, a header or a body.
   - The token goes only into the `Authorization` header built by the transport.
   - No configuration or environment input changes the decision.
   - **The `bse_` shape check before any call** (impl asked me to confirm): I accept it. It is the TS §6.2 format (256 bits, base64url, prefix). It stops a value that can never be a valid header from being retried for ever, and it refuses locally, before anything is sent.
3. Scope: 1 new file, about 160 lines.
4. Tests: both statuses, 401 of every type, the retry classes with a check that the token and body bytes are identical, the no-retry classes, the machine-id forms, the four #81 (c) combinations, crash order (save before delete), and strict-decode refusals with nothing written. 17 of 18 plants are red.
5. Re-run by the reviewer (Windows): `gofmt` prints nothing; `GOOS=linux` vet and golangci-lint on `enrol` report 0 issues.

## Findings
1. nit, `enrol.go:153`. A 403 `pending_approval` on enrol is retried with back-off (`transport.Wait`), and each retry spends another use of a multi-use `bse_` token. The manager never gives that answer to enrol: a held enrolment is 200 `awaiting_approval`, and 403 `pending_approval` is a `bsa_` answer (TS §3.2 step 5). So the path is defensive only, and a misbehaving manager could drain `max_uses` at one call per 300 s. Optional: treat a 403 on enrol as a refusal (no retry), like every other 4xx here.
2. nit, `enrol.go:85` (the tester and the implementer asked me to decide). `ReadMachineID` opens the file with no type check, so a FIFO at `/etc/machine-id` would block start-up. That path is root-owned and written by systemd, so only root could plant a FIFO there. No change needed.
3. nit, `enrol.go:203`. If `SaveEnrolment` succeeds but `DeleteEnrolToken` fails, `Start` returns an error and `main` goes idle, although the identity is saved. The next start then enrols again: a re-enrolment that is held for admin approval. It is rare (the directory belongs to `bitscan`) and fails safe. Optional: return the `Result` and log the delete failure, and let the next start's #81 (c) rule handle the leftover file.
