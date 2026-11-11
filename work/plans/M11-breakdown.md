# M11 breakdown: results and end-to-end (planner-m11, 2026-11-08)

Worktree `Bitscan-m11`, branch `m11-results`, from main `6efe0fb` (M10 closed 2026-11-07). Full text: `work/requirements.md` "M11", `work/tasks.md` "M11", `work/open-questions.md` "M11", and the design plans `work/plans/TASK-232.md` (API contract), `TASK-235.md` (results SQL and the role rule), `TASK-242.md` (retention).

## 1. Counts

- **29 REQ** (REQ-264 to REQ-292), **23 TASK** (TASK-232 to TASK-254), **25 test-plan items** (TP-M11-00 to TP-M11-24), **4 waves** plus the gate, **8 new gates** (G80 to G87), **55 mutation rows** (CHK-M11-320 to CHK-M11-374; 32 security rows, 5 end-to-end plants).
- **11 open questions** (#144 to #154) and **6 process decisions** (PD-46 to PD-51), each with a recommended answer; **none is a spec deviation**. Reused as agreed: #3, #9, #12, #28, #74, #84, #89, #93, #118, #119, #120, #122, #127 (f). Carried for the user: the `CLAUDE.md` N / N−1 marker and #111.
- **No migration, no agent, contract or unit change, no new dependency.** Six user operations are added, all TS §6.2 routes. The agent changelog gets one pre-release entry, `0.2.0~pre2-1` (PD-50).
- Approvals (PD-47): TS §8.2 asks one approval per task (no task edits importer, auth, agent or runner code). Recommended second looks: the user's at TASK-243 (re-evaluate), TASK-233, 235, 241, 244 (verdict and output by role), TASK-236, 237, 238, 242, 245 (retention); the lead's at TASK-232 (contract) and TASK-254 (nightly gate).

## 2. Waves and owners

| Wave | Read path (impl-manager-a) | Retention and re-evaluate (impl-manager-b) | Web (impl-web) | Deploy (impl-deploy) |
| --- | --- | --- | --- | --- |
| W1 | 232 API contract (6 operations, 501 until filled), 233 results view (pure), 234 scan reads repo, 235 result reads repo | 236 retention rules (pure), 237 retention repo, 238 audit retention repo | — | — |
| W2 | 240 scan views service, 241 results service | 242 retention service, 243 re-evaluate route | 239 client regen, `Score`, `ResultBadge`, CSV download | — |
| W3 | 244 read routes (fill) | 245 retention wiring (pool, scheduler job, shipper cursor) | 246 Scans + Run scan, 247 scan detail, 248 results, 249 schedules, 250 host history | — |
| W4 | 252 README | — | 251 routing, navigation, Run scan on the profile page | 253 runbook + changelog, 254 nightly workflow |
| Gate | security suite, N / N−1 rows, grant probes, coverage, mutation table, closing review | | | |

Testers: tester-m11 (manager unit and PostgreSQL, per task), tester-m11w (web, per wave), tester-m11e (the nightly harness and N / N−1 rows from W1, then the gate).

## 3. Dependency spine

`232 → 239 → 246…250 → 251` and `236 → 242 → 245 → 253` are the longest paths (four waves). Interfaces first: W1 fixes the API document (so the web client and every screen build against it from W2), the pure results view, every repository signature and the retention rules. The graph is acyclic and every wave is file-disjoint. Two files are written in two waves, never in one: `scan_views.py` (declared W1, filled W3) and `reevaluate.py` (declared W1, filled W2). G16 is red between TASK-232 and TASK-239, as in M9.

## 4. Top risks

1. **Viewers must never get stdout or stderr** (TS §6.2 L1123). The role rule lives in one pure function; viewer responses use a model without the fields (absent, not null), the viewer SQL variant does not even select them, and the canary runs through every M11 suite (mutation rows CHK-M11-320 to -323, -358 and -360).
2. **Which verdict is shown.** The results query composes M8's frozen CTE (PD-46) instead of copying it; a 200-scan property test checks it against `effective()` and `host_counts`.
3. **Retention deletes data and extends the audit chain.** Only a prefix of the chain is deleted, after a checkpoint in the same transaction, never past the sink's cursor; a clock-doubt guard stops a run with a wrong clock; the per-scan re-evaluation lock keeps it off a scan being re-evaluated; the grants allow nothing else.
4. **Retention cost (#151, owner).** `scan_job.retry_of`, `scan_job.scan_id` and `scan_result_reeval.job_id` have no index and the DDL can't change, so each cascaded delete reads a whole table. M11 measures it; the owner decides.
5. **The nightly run on three VMs.** It needs KVM on a hosted runner (fallback: the local VMs, with your standing approval), and in M10 a safety check stopped the writing of a VM harness twice. If it happens again the rows are NOT RUN and come to you (PD-49); nothing is worked around.
6. **A large re-evaluation runs in the request** (#147): `task.kind` allows only `rebuild`, so there is no background task to follow. Memory is bounded (M8 chunks); time is not.
7. **The 501 scaffolding** (PD-48) must be gone before the merge; TASK-243 and TASK-244 fill every handler, and the gate's route suites would fail on a 501.

## 5. Open questions and recommended answers (short form)

| Item | Recommended answer |
| --- | --- |
| #144 results item | One item per planned plugin per host (Not run = `result` null), effective `result` and `original_result` each with its detail, re-evaluation provenance, snapshots; `stdout`/`stderr` keys only for operator and admin; filters `status` (`PASS`/`FAIL`/`ERROR`/`NOT_RUN`) and `agent_id`; ordered by host, then plugin order. |
| #145 scans | List item with `policy_name`, state, target kind and resolved count; filters policy, host (resolved target), state, created after/before; detail adds the requested target and the whole per-host list (jobs, counts, score); host history from the stored target; no cross-policy host score. |
| #146 results CSV | Same rows and filters; fixed header; stdout/stderr columns for operator and admin only; every cell escaped; 100,000-row cap (400); `scan-<id>-results.csv`. |
| #147 re-evaluate | In the request, no body, 200 with M8's counts; 404 unknown, 409 deleted policy; no Idempotency-Key. |
| #148 alert | No alert: TS §8.4 lists none and #118 (g) was approved (your brief said "alerted"; adding one would be a spec change). |
| #149 score display | Percent with one decimal, rounded down ("100.0 %" only when all rated checks passed), errors beside, "n/a" for null. |
| #150 retention | Ages from `created_at`, `collected_at`, `decided_at`, `expires_at`, `finished_at`; audit 3 calendar years, prefix only, checkpoint first, ≤ 10,000 per chunk, never past the sink cursor; first run 10 min after start-up; counts-only logs; clock-doubt guard; skip scans under re-evaluation. |
| #151 retention cost (owner) | Accept for v1 and measure at the gate; adding indexes would be a TS §5.2 edit. |
| #152 nightly | GitHub scheduled workflow on a hosted runner with KVM: manager container by the runbook + two Ubuntu cloud-image guests; M6's doubles; the SR §1.1 example; one row per step and host. |
| #153 N / N−1 | N = the M11 build, N−1 = v0.1.0; agent 0.1.0 under manager N works and reports every plugin `runner_unavailable`; the upgrade order walked once at the gate; agent N under manager 0.1.0 only if you say yes to the marker. |
| #154 Run scan form | All hosts / tags / chosen hosts; one Idempotency-Key per submission; reached from Scans and from a profile. |
| PD-46 | New module composing `results._EFFECTIVE`; `results.py` stays byte-identical. |
| PD-47 | One approval per task; second looks as in section 1. |
| PD-48 | Contract first: the six operations declared in W1 with 501 bodies until filled. |
| PD-49 | The tester writes the harness; a safety-check refusal is NOT RUN and yours to decide. |
| PD-50 | `0.2.0~pre2-1`, manager stays `0.1.0`; a release checklist for your version bump, re-run and tag. |
| PD-51 | Rewrite only the scheduler job-set checks and the README "M11" sentence check, with an old → new list. |

## 6. Questions that need your decision (whatever is recommended)

1. **`CLAUDE.md` N / N−1 marker:** must agent N also be tested against manager N−1 (TS §8.2 L1269)? Recommended: yes (REQ-288). The marker line is your edit.
2. **#151:** accept the retention cost without indexes for v1 (recommended), or amend TS §5.2 to add three indexes.
3. **#111:** confirm the CIS control numbers in `bits/samples/` (TS §8.5 L1300). Not blocking M11: the nightly uses the SR §1.1 example until then.
4. **#152 (b):** if the hosted runner has no KVM, may the nightly run on the local Hyper-V VMs unattended (a standing approval for those VM actions)?
5. **#148:** confirm "no alert on re-evaluation" (the brief said "alerted").
6. **TASK-146** (the BIT102 review, second approval and r2) is still a named carry-over: r1 TEST PASS in the product, never reviewed; r2 outside the tree. Keep deferring, or schedule a fresh session?

## 7. What M11 leaves ready for a release (no tag)

Every gate green on the M11 head, including the nightly chain (G85), the N / N−1 rows (G86) and G37–G40 (lintian, maintainer scripts, reproducible build, SBOM) on `0.2.0~pre2-1`; README and the manager-operations runbook current; a release checklist in that runbook. Your steps, after M11: authorise the release PR (`0.2.0-1`, manager `0.2.0`), the nightly and N / N−1 re-run on that build, and the `v0.2.0` tag (`release.yml` publishes only on a tag and still refuses `~`).

## 8. Uncovered by design, and carry-overs

- **Deferred by you:** load tests (TS §8.3 L1284) and the CI performance-gate question.
- **Not supported:** Debian 12 and arm64 rows of TS §3.1 and §8.3.
- **Open for you:** #111 (CIS numbers), the N / N−1 marker, #151.
- **Carry-over, not planned into a wave:** TASK-146. Also two post-M10 deploy follow-ups outside this brief (the coverage floor's rounding at 84.99 %, and the M6 runbook placeholder that trips `check_runbook_text.py`); the lead may add either as a one-file task.
- **For you (`.claude/` edits):** the N / N−1 marker in `CLAUDE.md` once answered; `bit-format.md:61` once #111 is answered.
