# Reviewer audit (rounds 1–3, merged)

Lens: every claim in `.claude/CLAUDE.md`, `.claude/rules/**`, `.claude/agents/*.md` and `SKILL.md`, checked against TS and SR, with the reviewer's slice TS §3.3–§3.7 and §8.1–§8.4 read in full. The per-round originals are `work/audit/archive/round1-reviewer.md`, `round2-reviewer.md` and `round3-reviewer.md`. `L###` refers to a spec file line.

## Done

Everything in this section is applied in the working tree (uncommitted) and verified against the cited spec line in round 3. I reviewed every changed hunk. None is stricter than the spec, and none weakens `security-invariants.md`.

- **Security invariants (5):** signing and the approval workflow restated as owner decisions, and ad-hoc commands, push and inventory-disable as spec prohibitions (R-08/R3-R-11, TS L210, L213, L1129). Viewers "never receive `stdout` or `stderr`" (R-11/R3-R-10, L1121). Plugin-socket accepted risk (R2-R-16, L276, L365). Citation fixes R-07 and R-09.
- **Agent and runner (9):** state holds `issued_at`/`expires_at`, and a rotate replaces them (R2-R-10, L183, L1188). NTP prerequisite (R2-R-06, L212). `spool_overflow` goes in the results `error` field (R2-R-07 part, L1184). The agent, not the runner, reports `runner_unavailable` (R3-R-06, L152). Agent-test OS matrix (R3-R-07, L1279). 401 log wording "with a new enrolment token" applies only to `token_revoked`/`token_expired` (R3-I-06 narrowed, L191).
- **Jobs and scans (6):** offline_sweep has four tasks and applies the 24 h never-started and 30 min inventory timeouts (R-01, R2-R-05, L218, L575, L244). Job-state transitions (R-02/R3-R-12), including inventory `dispatched → completed | failed` (R3-P-51, L230, L244). Cancel of dispatched and running jobs (R3-P-20). Pickup bound (R3-P-16). A scan never takes `dispatched`/`expired` (R3-P-50, L580).
- **Format, importer and evaluator (8):** Sandbox on the bit-format Tests line (R2-R-09, L1280). Lengths are in characters (R3-P-12a). Display name vs `plugin_name_snap` (R3-P-40). Start-up order split into TS §4.1 and §4.2 (R3-P-15/-41). Host compliance score (R3-P-14). Re-evaluation route, TOTP and recorded columns (R3-P-17). Trimmed `eval_detail` (R3-P-21).
- **API, enrolment, deploy and UI (9):** `/api-tokens` and the auth routes in RBAC (R-05). My round-1 wording "session or API token" was replaced by the #8 marker (R2-R-01). Config-and-cli DSN heading (R-04). Load level on the enrolment Tests line (R3-R-08). Runner helpers in the UI (R2-R-11, L484). Migrate unit started by the runbook (R3-I-05, L1346). Purge leads to offline, with no deregistration (R2-I-15). Cloned-image and pinning runbook lines (R2-I-13 trimmed, R2-I-14). `serve` in ExecStart (R3-R-09).
- **Markers and pointers:** 44 `**Open spec question:**` lines, each on its own line (R3-R-04). Wording fixed for #2, #4 and #5 (R3-R-01, R3-R-02, R3-R-03). New markers #28–#31 for R2-R-07/-08/-12/-13. Markers for #2–#7 (R2-R-02). Every pointer resolves to an agreed entry.
- **Team docs and Tests lines:** `impl-<area>` naming, `bits/samples/` vs `bits/tests/`, `work/reports/` ownership, `main` addressing, the testing.md `bits/tests/**` glob, and the G1 citation (R-03, R-06, R-12, R2-R-03, R2-R-04). Tests-line items now cite their real source, not only TS §8.3 (R-10). Implementer-report status corrections (R2-R-17/-18).
- **Teammates' items reviewed and verified:** the planner's A1–A5 batches, the tester's R2-T-01..06 and R3-T-01, and the implementer's R2-I-01..20 and R3-I-01..07.

## Open items

DECIDE (user; `work/open-questions.md` §4):
- PD-3: the second approver for importer, auth, agent and runner changes (TS §8.2 L1268). From R2-R-14.
- PD-5: test and coverage commands. TS §8.2/§8.3 name no test runner; only the ≥ 85 % gate comes from the spec. From R2-R-15.
- PD-11: the memory file outside the repo still says "Go 1.22" (and its index once said "src/"). From R2-R-19 = planner P-41.
- PD-1: re-test before re-review. reviewer.md:30 re-reviews directly, while SKILL.md:47 has the tester re-run first.
- PD-2, PD-4, PD-6..PD-10, PD-12: raised by others; the reviewer has no objection.

ASK (spec owner; entries in `work/open-questions.md`):
- Mine:
  - #28 (R2-R-07): what the agent sends when the runner is down or restarts mid-job, and how `runner_unavailable` is reported.
  - #29 (R2-R-08): the agent–runner socket format and `max_parallel_plugins`.
  - #30 (R2-R-12): how the agent detects an enabled helper.
  - #31 (R2-R-13): how a plugin finds its temp directory.
- Confirmed by me (others' entries): #1–#18, #20–#27, #32, #33. #8 comes from my R-05/R2-R-01: the TS §6.2 L1099 row has no "session only" marker, but the owner could restrict it. For #13, only exponents, `.5` and `5.` are genuinely open, because `nan`, `inf` and `_` are not decimal numerals. For #17, only the trimming half is open. For #22, only the queued→running half is open.

Spec-internal inconsistencies (report only; never edit the spec):
- S-01: TS §6.2 sensitive actions ("approving enrolment requests, revoking agents, rebuild, re-evaluation, and managing users, enrolment tokens and settings") omit `DELETE /policies/{id}`, which the route table (L1104 "admin, TOTP session") and §4.3 L550 put behind a TOTP session. So it is unclear whether policy delete is refused during an audit-sink outage (#1).
- S-02: the TS §5.1 table map (Fleet: `agent`, `agent_tag`, `enrollment_token`, `enrollment_request`; System: `system_schedule`, `setting`, `app_user`, `user_token`, `audit_log`) omits `agent_ip_seen` and `task`, which the §5.2 DDL creates.
- S-03: the TS §2.1 component table says "PostgreSQL 16 (`pg_trgm`, `debversion`)", but Figure 1, the §5.2 DDL and the Bootstrap also use `pgcrypto`.
- S-04: TS §2.3 flow A says "configuration (`job_pull_seconds`) out". TS §3.3 L202 says the response "carries only configuration (`job_pull_seconds`, `max_parallel_plugins`) and the server time".
- S-05: TS §4.5 L593 "runner error (`spool_overflow`, `runner_unavailable`)" and SR §2.4 L149 "runner lost the plugin". But the spool belongs to `bitscan-agent` (TS §3.3 L226).
- S-06: TS §2.3 step 4 ("before its deadline") and §8.1 L1239 ("past their deadline") use "deadline" for the `pickup_by` check (TS §3.3 L212). Elsewhere, "deadline" means `deadline_at`, which is set at `running` (TS §4.4 L575).
- S-07: TS §4.4 L571 defines `failed` only as "Deadline passed with no results". That leaves out the dispatched-never-started case (L575, 24 h) and the inventory cases (§3.4 L244).
- S-08: TS §1.1 G6 says scans run "per host, group or fleet", but the spec has no groups; targets are tags (§4.4 L555).
- S-09: TS §6.3 L1136 lists `/agent/enroll` among the "unauthenticated routes", yet §6.1 L1062 requires a `bse_` enrolment token.
- S-10: the SR §4.1 rules table lists BIT101, BIT103, then BIT102.
- S-11: TS §3.1 L162 (State row) and §3.6 L261 (`state_dir` comment) omit the `issued_at`/`expires_at` that TS §3.2 L183 says the agent stores.
- S-12: TS §4.5 L600 gives a six-parameter `evaluate()` "with unit tests for every … ERROR case", but its ERROR cases include a runner error and output over the caps (L593, L599), which it has no input for (#12).
- S-13: TS §4.3 L550 says a revived policy comes back "as a new version". SR §3.6 L240 adds 1 to `version` only "if the file hash differs from `source_sha256`" (#14).
- S-14: in TS §3.5 L249 the runner applies `max_parallel_plugins`, but the §6.5 Job (L1165–1180) does not carry it (#29).
- S-15: TS §3 L152 says "the agent reports `runner_unavailable`", but the heartbeat (L1163) has only `last_error`, and the results `error` (L1184) is per plugin (#28).
- S-16: the "missing" halves of BIT010 and BIT011 (SR §4.1 L263–264) can never fire, because BIT002 fails first and the content rules are skipped (L250) (#2).

## Decisions

Verification stance (binding for future reviews of rule text):
- The spec is the only authority. A rule line must restate a spec sentence and cite `TS §x.y`/`SR §x.y` with the line. If a wording says more than the spec, trim it. If the owner could answer differently, write a marker, not a rule.
- Wording must never be stricter than the spec. Example: R3-I-06 was narrowed to the two token errors that TS §3.2 step 8 names.
- A marker states the gap and must not pre-answer it. Example: the agent.md:34 `error`-field half of R2-R-07 was rejected and reverted, because it would have answered #28.
- A self-check is not a confirmation. Every applied item needs its author plus one other agent (brief rule 4).
- Never weaken `security-invariants.md`. A restatement that matches the spec more exactly (R3-R-10, R3-R-11) is not a weakening. Accepted risks are recorded, never "mitigated" with signing.

Rulings that still bind:
- The redaction fixture superset in runner-sandbox.md is acceptable (from R-10/T-07): AKIA/ASIA come from TS §8.6 pattern 4, and testing.md follows it.
- The coverage path note stays (from P-28): annotate `manager/services` = `manager/bitscan_manager/services/`, and keep the 85 % gate.
- The rotation window ends at `expires_at` (from P-34, TS §3.2 steps 6 and 8).
- web-ui.md's *Deleted* policy state is valid (from P-20): TS §4.3 and SR §3.2 `deleted_at` support it. "GET /policies omits deleted policies" is unsupported and became #9.
- docs/agent-teams-reference.md:208 (`src/auth/`) stays as an upstream quote (from I-13).
- The `float()` sentence I offered for R2-P-08 is not applied: `nan`/`inf`/`_` are now asked in #13, and a rule must not pre-answer it.

Rejected, with reason:
- R2-R-15 as a FIX: TS §8.2/§8.3 name no test runner, so the command text is not from the spec. It became PD-5.
- R2-P-04 (resolve #8 from the spec): the owner could reasonably restrict tokens, so it stays ASK.
- #19 (scan-level score): TS §4.5 L602 defines only the host score, so there is nothing to build or decide.
- #17 "chars or bytes" half: SR says "chars" and the DDL uses `VARCHAR(n)`, so the spec answers it (R3-P-12a).
- #22 "dispatched/expired" half: TS §4.4 L580 derives scan state exhaustively, so the spec answers it (R3-P-50).
- R2-I-09: `docs/agent-teams-patterns.md` is the lead's file and out of scope.
- R3-P-23(c) (import history in the UI): TS §2.1 L101 limits the UI to profiles, hosts, scans, results and package search.
- R3-I-06 as first proposed (all three 401 types): stricter than TS §3.2 L188 and L191.
- R3-P-51 extras ("no `running` state", "a late upload does not change the job"): inference, so they were left out.
