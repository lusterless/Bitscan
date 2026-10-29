# TASK-159 REVIEW: folder watcher (inotify binding, events, #102 (c) record)

Verdict: APPROVED (revision 1)

Reviewer: reviewer-m7, 2026-10-28. REQ-164. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed, per `work/reports/TASK-159-impl.md` including "Revision 1":
- `manager/bitscan_manager/services/importer/inotify.py`: 73 non-blank lines.
- `manager/bitscan_manager/services/importer/watcher.py`: 158 non-blank lines.
- `manager/bitscan_manager/services/importer/own_changes.py`: 51 non-blank lines.

The size and the neutral module were accepted by the lead (decisions 2026-10-28, "#102 (c) wiring").

**Round 0, should-fix (my pre-read; the lead ruled it in "W6 pre-read rulings" (2)), fixed in r1.** `mv a.bit c.bit` in one batch was handled in event order. So the policy was soft-deleted first, which cancelled its queued jobs and disabled its schedules (TS §4.3), and then revived from `c.bit`. The r1 fix in `watcher.py:145` handles incoming paths before outgoing ones with a stable sort. `c.bit` then becomes a `move_server`, and the `a.bit` removal finds no policy.

TEST: PASS on r1 (`work/reports/TASK-159-test.md`, tester-m7).
- 20/20 on Linux against a real watcher thread and PostgreSQL, after the tester's deterministic race rows. Whole-tree gates are clean.
- Plants:
  - w1–w8, h1 and h2 are red. w3, w8 and h2 went red only after the tester added detecting rows.
  - w7 (the incoming-first order removed) is red on the `mv` row: same id, one `policy.move`, the job still `queued` and the schedule still enabled.
  - o1 (a synthetic `IN_Q_OVERFLOW` ignored) and o2 (the own-change check made before taking the lock) are red.
- **o3 (a writer records just after its call, not before): the equivalence claim holds.** Every writer records under the catalog lock it already holds, and the watcher checks only after taking that lock. So the record exists before any check can run, whichever side of the call it was written on. o3 can matter only if that lock order breaks, which is what o2 plants, and o2 + o3 is red. Recording before the call stays the rule, as defence in depth.
- A real `IN_Q_OVERFLOW` (more than 16,384 queued events) is NOT RUN. The synthetic overflow row covers its handling.

Spec read: TS §4.1 L526, L528, §4.3 L550, §4.6; #102 (a)–(d); PD-33 (b); decisions "#102 (c) wiring" and "W6 pre-read rulings" (2).

## Checks
1. **Binding (PD-33 (b)).**
   - `inotify_init1(IN_NONBLOCK | IN_CLOEXEC)` and `inotify_add_watch` are called through `ctypes`; events are read with `select` and `os.read` and parsed with `struct`.
   - It is Linux only. Elsewhere `available()` is False, so the watcher logs one line and returns (REQ-164 (5)).
   - It adds no dependency and runs no subprocess.
2. **Events (#102 (a)).**
   - `IN_CLOSE_WRITE` and `IN_MOVED_TO` import the file in `auto` mode through `folders.import_path`.
   - `IN_DELETE` and `IN_MOVED_FROM` delete the live policy at that path with `delete_in_tx(reason="file removed")`, which raises its alert. If the file is back by the time the lock is held, it is imported instead.
   - An overflow, an ignored watch, a moved or deleted folder, an unknown watch descriptor, or `uploaded/` created triggers a rewatch and a full reconcile.
   - Watches use `IN_ONLYDIR | IN_DONT_FOLLOW`, so a symlinked folder isn't followed.
3. **Names (#102 (b)).** A name counts only if it ends in `.bit` and doesn't start with `.`, so `.tmp-` files are ignored. Directories other than `uploaded/` are ignored, and an unstorable name gets one fixed line.
4. **Lock (TS L526).** Each path is handled in its own session under the catalog lock. The own-change check is made only after taking the lock (plant o2), so a writer's record, made under that lock, always precedes the check.
5. **#102 (c) record.**
   - A write is dropped only when the file's current hash equals the recorded one, so an admin edit within 60 s is still imported (plant w4).
   - Each record is used up once (plant w5) and expires after 60 s.
   - The accepted residual: a record before a call that then fails can drop one real event at that path within 60 s. The next start-up reconcile covers it.
6. **Failure and stop.** A failed event logs only its exception type and is followed by a reconcile retried every 10 s (#102 (d)). `run` checks `stop` once per poll. The lock wait without a timeout is carried to TASK-160.
7. **Security invariants.** The watcher never follows a symlink: the read goes through `folders.read_file` (`O_NOFOLLOW`). No file names or content are logged, and there is no SQL text.

## Findings
None blocking or should-fix (the round 0 should-fix is fixed in r1 and proved by plant w7).

1. nit, `watcher.py:135`: a file that appears only through `IN_CREATE`, such as a hard link made with `ln x n.bit`, gives no `IN_CLOSE_WRITE` or `IN_MOVED_TO`, so it isn't imported until the next start-up or reconcile. #102 (a) doesn't list `IN_CREATE`, so this matches the approved answer. A README line in TASK-167 ("copy or move files in; don't hard-link them") would cover it.
2. Carried to TASK-160: open the watcher before the start-up reconcile and run it after (impl suggestion). Also, `stop` takes effect only after a handler's catalog-lock wait ends.
