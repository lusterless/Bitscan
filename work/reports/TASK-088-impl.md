# TASK-088 IMPL: state directory

REQ-093. TS §3.1 (L162), §3.2 steps 3–4 (L183–L184), §3.3 (L212); the state-file table in `work/plans/TASK-099.md`; lead ruling 2026-10-24 (a corrupt or unreadable seen-ids file refuses start-up; the 7-day boundary second is not asserted). **Two approvals (TS §8.2, agent).**

**Size:** about 265 non-comment lines in 2 files, against an estimate of 170 (state.go 189, seen.go 75). No tests were run (that is the tester's job). I ran a throwaway copy on Windows with the directory fsync patched out (Windows cannot fsync a directory). It is deleted; results below.

## Files (new; no other file touched)

| File | What |
| --- | --- |
| `agent/internal/agent/state/state.go` | `Store`, `Open(dir)`, `Close`, `AgentID`, `Token`, `EnrolToken`, `SaveEnrolment`, `SaveToken`, `DeleteEnrolToken`, and the atomic `writeFile`. |
| `agent/internal/agent/state/seen.go` | `SeenFor` (7 days), `Store.LoadSeen(now)`, `Seen.Has`, `Seen.Add`. |

## Layout (the TASK-099 plan's table)

| File | Mode | Content |
| --- | --- | --- |
| `agent_id` | 0644 | The lowercase UUID and `\n`. |
| `token` | 0600 | The `bsa_` token and `\n`. |
| `token.json` | 0600 | `{"issued_at", "expires_at", "token_sha256"}` (UTC RFC 3339). |
| `enroll.token` | (postinst's) | Read with `EnrolToken`, removed with `DeleteEnrolToken`. |
| `seen_jobs.json` | 0600 | `{"<job_id>": "<first seen, RFC 3339>"}`. |

- **Atomic write:** remove any stale `.<name>.tmp` (left by an earlier crash), create it with `O_CREATE|O_EXCL` at the final mode, then `Chmod` to that mode (so the umask cannot change it), write, `fsync`, close, `rename` over the final name, and `fsync` the directory. A crash at any step leaves the old complete file or the new complete file.
- **Nothing outside the directory:** every open, read, remove and rename goes through `os.Root` (`os.OpenRoot(dir)`). Neither a `../` name nor a symlink that leads out can reach another path. `Open` does not create the directory, which `postinst` creates (0700, `bitscan:bitscan`). There is no chown: the files belong to the running user (`bitscan` under the unit).
- **Token and its times:** `SaveToken` writes `token` first, then `token.json`, under a lock so two saves cannot interleave. `token.json` holds the SHA-256 of the token it belongs to. `Token()` sets `TimesKnown=false` when `token.json` is missing or bound to another token, which is what a crash between the two writes leaves. TASK-099 then treats the rotation window as open and the manager decides, as the plan says. This hash is my mechanism for the plan's "a token newer than `token.json`". It is the agent's own file format, and the token itself is already in `token`.
- **Order for enrolment:** `SaveEnrolment` writes `agent_id`, `token`, `token.json`. TASK-098 calls `DeleteEnrolToken` afterwards (plan step 2), and a missing `enroll.token` is not an error.
- **Reads:** a missing file returns an error that matches `fs.ErrNotExist` (for the #81 start-up rules). A present but malformed `agent_id`, `token` or `token.json` is an error with fixed words. `AgentID` lower-cases the id.
- **Seen ids:** `LoadSeen(now)` uses only the clock it is given. A missing file is an empty set. A corrupt file (bad JSON, `null`, a key that is not a UUID or a value that is not RFC 3339) or an unreadable one is an error, and the agent refuses to start (lead ruling). Entries at least 7 days old are pruned on load and on each `Add`. `Has(id)` is true while `now − first_seen < 7 days`. `Add(id)` lower-cases the id, keeps an existing first-seen time, and returns only after the file is persisted. If the write fails, the id still counts as seen in memory (fail closed), and the caller must not run the job.
- **Tokens never print:** `Token.Value` is a `wire.AgentToken`, so `%v` and `%+v` of a `Token` show `bsa_[redacted]` (checked). No error text contains file contents.

## Crash-injection seam (for TP-M4-03)

`Store` has an unexported field `crash func(file, step string) error`. It is nil in production, and there is no flag or environment input for it. In-package tests set `s.crash = …`. It is called after each step of a file write: `created`, `written`, `synced`, `renamed`. A non-nil error stops the write right there, exactly as a crash would, leaving the temporary file. Scratch results, crashing a rotation from token A (2026-01) to token B (2026-12):

| Crash after | `token` | Times | `TimesKnown` |
| --- | --- | --- | --- |
| `token:created`, `token:written`, `token:synced` | A | 2026-01 | true |
| `token:renamed`, `token.json:created` | B | none | false |
| `token.json:renamed` | B | 2026-12 | true |

After each crash, the next save worked and left no `.tmp` file behind.

Seen ids: an id added at t0 is still `Has` after a reload at t0 + 7 d − 1 s, and gone at t0 + 7 d. An upper-case lookup matches. `{bad` gives `state: seen_jobs.json: unreadable`.

## Gates run (Windows, Git Bash, from `agent/`)

- `gofmt -l .`: prints nothing.
- `go vet ./...` (windows and linux/amd64): clean.
- `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./...`: clean.
- `GOOS=linux golangci-lint run ./...`: `0 issues`. There is no `//nolint`.

## For the tester

- File modes must be checked on Linux (as `bstester` where it matters). Windows ignores them.
- The directory fsync needs Linux. On Windows `syncDir` returns an error, so nothing here runs on Windows.
- The 7-day boundary second is not asserted (lead ruling).
