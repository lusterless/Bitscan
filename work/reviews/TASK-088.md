# TASK-088 REVIEW: state directory

Verdict: APPROVED

Reviewer: reviewer, 2026-10-24. Full rigor (agent). **Two approvals (TS §8.2): the user's second approval is still needed.**

Scope reviewed: `agent/internal/agent/state/state.go` and `agent/internal/agent/state/seen.go` (`work/reports/TASK-088-impl.md`). Sources: TS §3.1 L162, §3.2 steps 3–4, §3.3 L212, REQ-093, the TASK-099 plan's state-file table, and the lead ruling of 2026-10-24 that a corrupt seen-ids file refuses start-up.

TEST: PASS (`work/reports/TASK-088-test.md`): 47/47 as root, 47/47 as `bstester` after one test bug was fixed, `-race` 2/2, and 19 of 22 plants red, including all three security rows. The tester asked me to check the 3 survivors by reading, below.

## Checks
1. Spec:
   - The modes are `agent_id` 0644, and `token`, `token.json` and `seen_jobs.json` 0600, set with `Chmod` after create so the umask has no effect.
   - The state directory is not created here: `postinst` creates it 0700 `bitscan:bitscan`.
   - Seen ids are kept 7 days and persisted before `Add` returns. When the write fails, the id still counts as seen in memory (fail closed).
   - A missing seen-ids file is an empty set. A corrupt, `null` or unreadable one is an error, so the agent refuses to start (lead ruling).
   - `enroll.token` is removed only after the enrolment state is written, and a missing file is not an error.
2. Security:
   - Every path operation goes through `os.Root`, so `../` and symlinks out of the directory are refused (CHK-M4-032 and -036).
   - Error text is fixed and holds no file content. A `Token` prints its value as `bsa_[redacted]`.
   - The crash hook is an unexported field that is nil in production. No flag or environment value reaches it.
3. Scope: 2 new files, about 265 lines.
4. The three plant survivors, checked by reading:
   - **fsync.** `writeFile` runs `f.Sync()` (`state.go:199`) before `Close` and `Rename` (`:211`), then `syncDir()` after the rename (`:217`). `DeleteEnrolToken` also syncs the directory (`:159`). The order is correct for crash safety: data is durable before the rename, and the rename is durable before the function returns. The unit suite cannot observe fsync; a syscall trace would be the only test. I accept the survivor.
   - **`O_EXCL`.** It is equivalent in a single-writer process, because the stale `.tmp` is removed first under `s.mu`. It is kept as defence in depth: `O_EXCL` does not follow a symlink planted at the temporary name between the remove and the create. Accepted as an equivalent mutant.
   - **Prune on load.** `Has` checks the age itself, so pruning at load changes only memory and the next write. That is not observable from outside. Accepted.
5. **The `token.json` binding by SHA-256 (impl choice; main asked me to check it).** `token.json` stores `sha256(token)` to detect a crash between the `token` and `token.json` writes. I accept the choice:
   - The value reveals nothing beyond the 0600 `token` file next to it. It is a one-way hash of a 256-bit random value.
   - It equals the manager's own stored `token_hash`, which is no secret beyond the token itself.
   - A mismatch, or a missing hash, gives `TimesKnown = false`, and TASK-099 then lets the manager decide. That is the safe direction.
   - The comparison is not constant-time, but both sides are local files, so timing is not a channel.
6. Re-run by the reviewer (Windows):
   - `gofmt -l agent`: prints nothing.
   - `GOOS=linux go vet` and golangci-lint on `state`, `transport` and `schedule`: 0 issues.

## Findings
1. nit, `seen.go:81-85`. Every `Add` rewrites the whole set. In the worst case (10 jobs per pull, pulls every 60 s for 7 days) that is about 100,000 ids, roughly 7 MB, rewritten per job. Real fleets pull far fewer jobs, and an inventory job every 6 h adds about 28 ids a week. No change now. If M10 compliance volumes grow, consider an append log.
2. nit, `seen.go:64`. An id whose stored first-seen time is in the future (the clock moved back) stays "seen" until that time plus 7 days. That fails closed (no replay), and I record it only so it is not mistaken for a bug.
