# M8 breakdown: the evaluator (result evaluation and scoring)

Planner: planner-m8, 2026-10-29. Worktree `Bitscan-m8`, branch `m8-evaluator`, from main `67a6dfa` (M7 merged). The M8 sections are appended at the end of `work/requirements.md`, `work/tasks.md` and `work/open-questions.md`. Phase A only: no code has been written.

## Counts

| Item | M8 range | Count |
| --- | --- | --- |
| Requirements | REQ-186 to REQ-205 | 20 |
| Micro-tasks | TASK-176 to TASK-185 | 10 (all high risk) |
| Test-plan items | TP-M8-00 to TP-M8-14 | 15 |
| Waves | W1 to W4, then the gate | 4 |
| New gates | G62 to G65 | 4 (plus G1–G6, G18 and G34 re-run) |
| Mutation rows | CHK-M8-320 to CHK-M8-364 | 45 (22 security rows) |
| New open questions | #112 to #120 | 9, plus #11, #12 and #13 reused as agreed |
| New process decisions | PD-38 | 1 |
| Design plans | `TASK-178.md` (with the TASK-176, 177, 179 interfaces), `TASK-182.md`, `TASK-185.md` (with the TASK-183 interface) | 3 |

Owner: impl-manager for all 10 tasks. No web, agent, sample, unit, packaging or workflow change.

**Migrations: none. Routes: none. New dependencies: none.** M8 reads `scan`, `scan_job`, `scan_result` and `scan_result_reeval` as migrated, inserts only into `scan_result_reeval` and `audit_log`, and never updates or deletes a result (TS §5.2 L1005–L1006).

**Spec deviations: none.** Four spec-internal points are reported for the owner (one `truncated` flag for two streams, #113; "keep their original verdict" versus "use the latest row", #118 (b); exit codes the contract allows but L593 does not classify, #114; no index on `scan_result_reeval`).

## What M8 builds (`manager/bitscan_manager/services/evaluator/`)

- **`evaluate()`** with the exact TS §4.5 L600 signature, returning 0, 1 or 2, and `classify()`, the same function returning the code with its `eval_detail` (#112). Total: never raises.
- **Normaliser**: CRLF → LF, trim ASCII whitespace (#115), case-sensitive.
- **The 14 operators**, exactly: text, RE2 (multiline search, through M7's `values.compile_pattern`), numeric (M7's #13 grammar, exact decimals), presence.
- **ERROR rules**: timeout; exit 126, 127, ≥ 128; null or negative exit code (#114); stdout truncated (#113); non-numeric stdout; input that cannot be compared (`cannot evaluate`).
- **Intake verdict** for M9: the server-side caps in UTF-8 bytes (`oversize`, #116) and the runner errors (`spool_overflow`, `runner_unavailable`, #12), decided before `classify()`.
- **`eval_spec` contract** (#117): the JSON M9 writes when it queues a job and intake reads; Operator and ExpectedResult never in the agent payload.
- **Host score** (#120): PASS ÷ (PASS + FAIL), None when 0, with errors and not-run counts, computed when read.
- **Effective verdict** (#119): the latest re-evaluation row (highest `reeval_id`) or the original, as one pure function and one SQL query that are tested to agree.
- **Re-evaluation computation** (#118): one transaction, serialised per scan, current definitions read in one statement, intake errors kept, dropped plugins left alone, rows only added, `scan.reevaluate` audit entry.

## Waves

| Wave | Tasks | What |
| --- | --- | --- |
| W1 | 176, 182, 183 | evaluator model and normaliser (the interface); results read repository; re-evaluation repository; tester plan and PostgreSQL fixture builder |
| W2 | 177, 180, 181 | the 14 operators; `eval_spec` build and parse; score and effective rule |
| W3 | 178, 184 | `classify()` and `evaluate()`; host scores service |
| W4 | 179, 185 | intake verdict (`result_verdict`); re-evaluation service |
| Gate | tester, reviewer | G62 to G65, the mutation table, the closing review |

Files are disjoint within every wave and no file is shared between tasks. A second impl-manager instance can take the repository and service side (182, 183, 184, 185) in parallel with the pure modules.

## Dependency spine

`TASK-176 (model) → 177 (operators) → 178 (classify, evaluate) → {179 (intake verdict), 185 (re-evaluation)}`.

Side chains: `176 → 180 (eval_spec)`; `176 → 181 (score, effective) → 184 (scores service)`; `182 (results repository) → 184`; `183 (re-evaluation repository) → 185`. Acyclic. Interfaces first: the model (176) and both repositories (182, 183) are in W1; the `eval_spec` shape (180) is fixed in W2, before M9 needs it.

## Approvals

The evaluator is not a TS §8.2 two-approval area (importer, auth, agent, runner), and no M8 task edits code in those areas (it imports `importer/values.py` and `importer/model.py` unchanged). PD-38 recommends one reviewer approval per task with full rigor and no second look.

## Top risks

1. **A false PASS.** A check that should be ERROR or FAIL showing PASS is the evaluator's worst failure. Mitigated by the ERROR pre-checks running before any comparison, the negated operators (`not_regex`, `ne`) never PASS on input they cannot compare, a property suite for totality, and 45 plants (exit-code boundaries, flags ignored, float rounding, Unicode trim, `re` instead of RE2, case folding).
2. **Spec readings that decide verdicts** (#113 stderr truncation, #114 null and negative exit codes, #115 the whitespace set, #116 bytes versus characters). Each has a recommendation and an alternative; the choice changes real verdicts, so they come first (W1 to W3).
3. **Re-evaluation consistency.** Version and definitions could disagree under a concurrent import, and two runs could interleave. One definitions statement, a per-scan transaction lock and barrier-driven race tests address it; a late result arriving mid-run keeps its intake verdict (accepted, #118 (h)).
4. **Re-evaluation size.** A fleet-wide scan can hold millions of results in one transaction. Chunked reads and inserts bound memory; the run time and whether M11's route runs it in the background are M11's call.
5. **No index on `scan_result_reeval`.** Every effective-verdict read scans it once (it cannot get an index: TS §5.2 is the schema). Small while re-evaluations are rare; reported to the owner.
6. **Interfaces M9 and M11 rely on** (`Verdict`, `Detail`, `PluginSpec`, `eval_spec`, `result_verdict`, `repositories/results.py`). A change after W2 ripples into two later milestones, so they are frozen once W1 and W2 pass.
7. **Output leaks.** stdout or an expected value in a log, exception or `eval_detail` would break TS §5.3 L1052; a canary suite and an import-graph test guard it.

## Open questions and recommendations

None blocks the planning; the ones needed first are marked with their wave.

| Item | Recommendation | Needed by |
| --- | --- | --- |
| #112 `eval_detail` | Fixed lowercase values (`oversize`, `spool_overflow`, `runner_unavailable`, `timed out`, `no exit code`, `cannot run`, `not found`, `killed by signal`, `stdout truncated`, `cannot evaluate`, `stdout not numeric`); NULL for PASS and FAIL; `classify()` returns code and detail and `evaluate()` returns its code; first match in that order; never raises | W1 |
| #115 whitespace | ASCII whitespace (space, tab, LF, VT, FF, CR); CRLF → LF first; no case folding or Unicode normalisation | W1 |
| #116 caps | UTF-8 bytes, strictly over 65,536 / 16,384; `oversize` before the runner error; M9 stores both streams empty for such a result | W1 |
| #118 re-evaluation | Every result of a plugin in the current version gets a row; dropped plugins get none; deleted policy refused, disabled allowed; intake errors stay ERROR; definitions in one statement; `scan.reevaluate` audit entry; serialised per scan | W1 |
| #119 latest row | Highest `reeval_id` | W1 |
| #117 `eval_spec` | `{"plugins": [{plugin_uuid, name, operator, expected}]}` in payload order; strict parser | W2 |
| #120 score | Per host per scan, the unrounded ratio in [0, 1] or null, with passed, failed, errors and not run; display is M11's | W2 |
| #113 stderr truncation | Not an ERROR: `truncated` means stdout was cut (the runner in M10 sets it only then) | W3 |
| #114 exit codes | Negative is `killed by signal`, null is `no exit code`, both ERROR; M10's runner reports signals as 128 + n | W3 |
| #11, #12, #13 | Reused as agreed: operators as written; intake decides runner errors and oversize; the #13 number grammar from `values.py` | W1 |
| PD-38 approvals | One reviewer approval per task, full rigor, no second look | W1 |

Full text, sections and alternatives: `work/open-questions.md`, section "M8".

## Coverage

Covered: TS §2.1 evaluator row; §2.2 immutable results; §4.5 return codes, ERROR cases, operators, normalisation, exit-code rule, caps (decision), the pure function, re-evaluation computation and the latest-row rule, the score value; §4.4 Not run in the score; §5.2 `eval_spec`, `scan_result` reads, `scan_result_reeval` inserts and the never-change grants; §5.3 L1049 and L1052; §8.1 verdict tampering, sensitive output, SQL injection; §8.3 Unit (normaliser, evaluator) and Integration ("re-evaluation adds rows only"); SR §1.1 PASS and FAIL; SR §2.4 operators and evaluation.

Uncovered by design, with the milestone:
- **M9:** result intake and storing each result with its verdict in one insert (TS §2.3 step 6, §4.5 L587); the result snapshots (L603); writing `eval_spec` when a job is queued; storing an `oversize` result (#116 (d)); first-result-wins under concurrent retries and late results (TS §4.4 L578, §8.3 Security); the TS §8.3 Integration item "verdict uses the queued `eval_spec` after a catalog change" end to end (M8 proves the API-level half); the "plugin ERROR rate" metric (TS §8.4 L1288).
- **M10:** the runner's 64 KB / 16 KB truncation, the `truncated` flag (#113) and the exit code for a signal death (#114); redaction (TS §4.5 L596).
- **M11:** `POST /scans/{id}/reevaluate` (admin, TOTP session, sink gate), `GET /scans/{id}` per-host summary, `/scans/{id}/results` and `.csv` with `result` and `original_result`, the "n/a" display and the error count beside the score (TS §6.2 L1120–L1123, §4.5 L601–L602).

## Files written by the planner

- `work/requirements.md` (section "M8 evaluator")
- `work/tasks.md` (section "M8 evaluator": design notes D1 to D4, tasks, owner notes, test plan, waves, gate, mutation table, open items, coverage)
- `work/open-questions.md` (section "M8")
- `work/plans/TASK-178.md`, `work/plans/TASK-182.md`, `work/plans/TASK-185.md`
- `work/plans/M8-breakdown.md` (this file)
