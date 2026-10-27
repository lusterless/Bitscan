# Builder checklist (read before every hand-off)

Owner: reviewer. Each line is a finding that came back more than once in review. Fix it before handing off, not after. Format: rule | why | how to check.

## Input that reaches the database
1. Validate every client value before PostgreSQL casts it (`inet`, `cidr`, `jsonb`, `text`, `debversion`). | Postgres refuses IPv6 zones (`%eth0`), U+0000, lone surrogates and `NaN`/`Infinity`, so the answer is a 500 instead of a 400 (TASK-048, 066, 067, 069). | Send `fe80::1%eth0`, `"\u0000"`, `"\ud800"` and `NaN` to each new field and expect 400.
2. Never compare Debian versions as text. | Text order puts `1.10` before `1.9` (TASK-053). | Grep the new SQL for `version` in `ORDER BY`, `>` or `<`; each must use `::debversion`.
3. Keep integer bounds in the OpenAPI document at or below 2^53 − 1. | FastAPI writes bounds as floats, so 2^63 − 1 becomes 2^63 (TASK-048 r2). | The re-exported `maximum` equals the model's bound exactly.
16. Any `audit_log.target` is cut to 255 characters (TS §5.2 `target VARCHAR(255)`); keep the full value in `detail`. | A file path used as a target can exceed 255 characters (a 255-byte name under `uploaded/`), and the failed INSERT loses the whole transaction, including the `bit_import` record (TASK-153). | Test each target built from a name or path with a 300-character value: the entry is written, the target is at most 255 characters, and the detail holds the full value.

## Order of checks on a route
4. Run the token check, or the per-IP limit, before FastAPI parses the body. | FastAPI parses a declared body before any dependency, so a bad body is answered uncounted and before authentication (TASK-067, 072, 082, 083). | Either use the `limit_first` route class or read the body yourself after the check. Test: a bad token plus a non-JSON body gets 401 and is counted.
5. Agent path and query ids accept only the hyphenated 8-4-4-4-12 form. | `uuid.UUID` also accepts the 32-hex, `{…}` and `urn:` forms (TASK-073, 083). | Use `agent_uuid()`. Test: the 32-hex form gets 400.
6. Compare protocol tokens (`Content-Encoding`, schemes) case-insensitively. | RFC 9110 says they are case-insensitive (TASK-073). | Test: `GZIP` is accepted.

## Concurrency and state
7. Mark an in-memory alert window as fired only on commit, and build it once per process. | Marking before commit loses the alert when the transaction rolls back. Building it per request resets the count (TASK-063, 064, 067). | Use `count_and_check` (or `due`) and register the mark with `tx.on_commit`. Build the window in `create_app()` or the runner.
8. For "once only" writes, use a conditional UPDATE and write the audit entry only when the UPDATE changed a row. | Two concurrent calls each wrote an entry (TASK-066). | `UPDATE … WHERE <state> RETURNING` or a `rowcount == 1` check. Test with two threads held at a barrier.
9. Decide from state re-read under the row lock, not from what an earlier check returned. | Concurrent rotations and twin enrolment requests acted on stale state (TASK-070, 075). | Ask: what if another request changed this row while I waited for the lock?
10. Every loop that opens database transactions must honour stop. | The scheduler held `SIGTERM` for 46 s on a dead database (TASK-071). | Test: stop with the database refusing returns within the G27 bound.

## Secrets and output
11. Keep tokens, token hashes, header values, request bodies, stdout, stderr and package lists out of logs, audit details, error text and `repr`. | TS §8.4 and the security invariants. | Run a canary test: plant a value and grep the logs, the audit rows and the response bodies for it.
12. Problem `detail` and log text never echo client input. Use fixed words only. | REQ-038 and #59. | Grep the new code for f-strings that build a `detail` from request data.

## OpenAPI
13. Re-export `manager/openapi.json`, keep it byte-stable, and avoid component-name clashes and 422s. A self-read body must still be documented. | G6 and REQ-060 (TASK-067, 073, 076). | Export twice and compare the two files.

## Go agent
14. Check the file type before opening any path the agent reads from configuration or the host (`ca_file`, `/etc/machine-id`, `/etc/os-release`, `/proc` files), and open non-blocking. | Opening a FIFO for reading blocks until a writer appears, so start-up or collection hangs (TASK-087 FAIL r1; same pattern noted in TASK-089 and TASK-098). | `os.Stat` → `IsRegular()`, then `O_RDONLY|O_NONBLOCK`, then `f.Stat()` again (see `config.readableFile`). Test: a FIFO at the path returns an error at once.

## CLI
15. A CLI sign-in with a secret must not print the secret back (for example `bao login -no-print`); a hidden prompt alone is not enough. | M6 review (reported by main, 2026-10-27): the secret must stay out of the command's output, not only out of the prompt. | Run the sign-in step with a canary secret and grep stdout, stderr and any captured output for it.
