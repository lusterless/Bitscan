# TASK-158 REVIEW: integrity check (#103) and the catalog start-up sequence

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-28. REQ-165. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed, per `work/reports/TASK-158-impl.md`. Two new files:
- `manager/bitscan_manager/services/importer/integrity.py`: 71 non-blank lines.
- `manager/bitscan_manager/services/importer/startup.py`: 80 non-blank lines.

TEST: PASS (`work/reports/TASK-158-test.md`, tester-m7).
- 15 start-up tests; 32/32 together with the rebuild file on TASK-157 r2. 11/11 plants red. Whole-tree gates are clean (298 files).
- REQ-165 (5), the #102 (d) route answer during start-up, belongs to TASK-160.

Spec read: TS §4.1 L528, §4.2 L540, L542, §8.4 L1291; #27, #98 (g), #102 (d), (e), #103; the crash-window ruling; decisions 2026-10-28 "TASK-158 readings" and "TASK-158 test questions" (1)–(2).

## Checks
1. **Order (TS L528, L540, L542; #27).** Everything runs in one pinned session under one catalog lock: finish interrupted uploads, mark `running` tasks `failed` (fixed `{error}` text), reconcile in `auto` mode, then the integrity check. The alert is raised only when there is a difference (order row; plants s1, s3, s6).
2. **#103 check.**
   - For each live policy: its file is missing (read with `O_NOFOLLOW`), its hash differs, its plugin count differs (counted by parsing with defusedxml through `parse_bit`, with nothing written), or one of its listed plugins isn't active or isn't owned by it.
   - For each folder file: it is neither a live policy's file nor a rejected import for its current hash.
   - The check texts are fixed, and the check only reads (plants s7, s8, s9).
   - The reconcile's leftovers are added as differences (crash window, plant s2).
3. **Ruling (1).** A changed `source_sha256` is repaired by the reconcile, with its `policy_imported` alert, so the check then finds nothing. That's consistent with `auto` mode importing a changed file (TS §4.2).
4. **Retry (#102 (d)).** Any exception is logged by type only, and the whole sequence is retried from step 1 every 10 s. Every step is idempotent. A partial import pass never reaches the deletion pass (carry row, plant s4). `stop` returns at once (builder checklist 10).
5. **Ruling (2), the CLI race (TASK-157 r2).** The start-up's `fail_running_tasks` can fail a CLI rebuild's freshly written task. The rebuild now re-reads its task under the lock and does nothing if it isn't `running`, so the task row and the audit log can no longer disagree (race rows, plant rr). This closes the nit from my pre-read.
6. **Security invariants.** XML is parsed only through the defusedxml parser. No content or names are logged, and there is no SQL text.

**The lead's question: does a repeated start-up failure need an alert?** No, and one shouldn't be added.
- TS §8.4 lists no such alert, so it would be a new alert kind, which the spec doesn't define (`raise_alert` refuses unknown kinds).
- The main cause is an unreachable database, and then the alert, which is an audit entry, couldn't be written anyway.
- The fail-closed 503 on mutating routes (#102 (d)) plus one log line per attempt is the signal. If the owner wants more, it's an owner question, because the spec is silent.

## Findings
None blocking or should-fix.

1. nit (accepted readings, recorded for the record): a leftover removed in a failed attempt misses the final alert, though it is logged when it is removed (reading 1). A permanent programming error retries forever, failing closed, with one log line per attempt (reading 2).
2. Carried to TASK-160: run `startup.run` on its background thread, keep the catalog routes on the #102 (d) answer until it returns, and start the watcher after it (open it before, as the TASK-159 review notes).
