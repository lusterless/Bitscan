# Planner audit report (rounds 1–3, merged)

My slice: SR §1–§4 and TS §4, plus coverage and workflow. Live questions are in `work/open-questions.md`; the round-by-round history is in `work/audit/archive/round1-planner.md`, `round2-planner.md` and `round3-planner.md`.

## Done

- **Team naming and ownership (6 fixes):**
  - `impl-<area>` naming is used everywhere.
  - `impl-bits` and `impl-deploy` are spawned.
  - `bits/` is split into `bits/samples/` and `bits/tests/` (CLAUDE.md, SKILL.md, implementer.md, tester.md; testing.md `paths:`; bit-format.md fixture note).
  - `work/reports/` ownership is defined.
  - `main` addressing is used throughout.
  - `docs/spec/` and `work/` are in the CLAUDE.md layout.
- **Workspace (5 fixes):**
  - `.gitignore` and `.gitattributes` exist, including preseed, `install.env` and `*.gz binary`.
  - README is written.
  - The out-of-scope citation is completed.
  - The coverage path is annotated, with the gate kept.
  - The redaction fixture lists match.
- **bit-format.md (5 fixes):**
  - Lengths are counted in characters (`VARCHAR(n)`).
  - The display name is read from `v_plugin` and the run-time copy is kept in `plugin_name_snap`.
  - The "one Family per file" assumption is carried with pointer #10.
  - BIT010 is quoted in full.
  - The Sandbox line was added to its Tests.
- **importer.md (2 fixes):**
  - Start-up is now "before anything else: finish uploads, then reconcile", and the TS §4.2 steps are listed without an order (R3-P-15/-41).
  - Each marker is on its own line.
- **evaluator.md (4 fixes):**
  - "Host compliance score" (R3-P-14).
  - Re-evaluation route, TOTP, audit logging and recorded columns (R3-P-17).
  - The `eval_detail` line, in the reviewer's trimmed wording (R3-P-21).
  - The TS §8.5 normalisation and operator caveats, pointer #11.
- **bit-format.md ids:** lengths in characters is R3-P-12a; the display name is R3-P-40.
- **jobs-and-scans.md (5 fixes):**
  - Pickup bound "≤ `job_pull_seconds` + 30 s" (R3-P-16).
  - Cancel covers dispatched and running jobs (R3-P-20).
  - A scan never takes `dispatched` or `expired` (R3-P-50).
  - The sweep's 24 h and 30 min timeouts.
  - The state-transition line (R3-R-12), plus the inventory transitions (R3-P-51, TS §3.4 L230 and L244). R3-P-51 has since been applied and verified.
- **api.md and web-ui.md (2 fixes):**
  - The TS §6.2 list filters (R3-P-22).
  - The package-search click-through to the host list (R3-P-23(b)).
- **Pointers:**
  - #1 and #9 in api.md and auth-and-users.md.
  - #7 as a cross-reference in config-and-cli.md.
  - #10 and #11 (R3-P-42, R3-P-43).
- **NTP prerequisite:** in the runbook and in agent.md.
- **Teammate FIX items:**
  - I confirmed 22. The round-3 figure of 26 also counted R3-T-02..04 and the trimmed R3-P-21. The 22 are R3-R-01..04, R3-R-06..12, the `spool_overflow` part of R2-R-07, R2-R-11, R2-R-16, R3-P-12a, R3-P-50, R2-T-01..03, the FIX half of R2-T-05, R2-T-06 and R3-T-01.
  - I rejected 1 (see Decisions).
  - I applied R3-T-02..04 to my own file.
  - The reviewer, tester and implementer verified everything applied.
- **Audit ids cited in `work/open-questions.md` (history only):**
  - P-05..P-09, P-36, P-37, P-41 and R2-P-25 are PD-1..PD-8 and PD-11.
  - P-10..P-20 and P-12 are #2..#9 and #22.
  - P-17, P-18, P-19 and P-38 are #24, #25, #26 and #23.
  - P-24, R2-P-07..R2-P-19 and R3-P-41 are #12..#21 and #27.
- **`work/open-questions.md`:**
  - 33 numbered entries: 32 agreed, #19 withdrawn.
  - A marker table generated from grep: 44 markers (30 numbered, 14 own questions) and 35 pointers. Every pointer resolves to an agreed entry.
  - The TS §8.5 table.
  - Twelve process decisions (PD-1 to PD-12).
  - The spec-internal inconsistencies list.
- **Checked complete against the spec:**
  - The SR element tree, limits, all BIT codes and severities, the retired codes, the BIT102 lists, and SR §3.6 steps 1–6.
  - TS §4.1 to §4.6: pipeline, uploads, folders, locking, watcher, modes, rebuild, status override, rename, delete, targets, schedules, job states, deadline, retry, late results, scan state, the 14 operators, normalisation, caps and score.

## Open items

- **Process decisions for the user:** PD-1 to PD-12 (`work/open-questions.md` §4).
- **Spec questions for the owner:**
  - #1–#18 and #20–#33 (§1).
  - The 14 own-question markers (§2).
  - The TS §8.5 CIS-numbers question (§3).
  - With the most impact: #12, #14, #18, #28, #29 and #33.
- **Spec-internal inconsistencies to report to the owner (§5):**
  - S-01 (carried as #1) and S-02 to S-16.
  - The `cancelled` definition (TS §4.4 L573) omits policy delete (TS §4.3 L550).
  - The `/scans/{id}/cancel` row (TS §6.2 L1122) omits dispatched jobs (TS §4.4 L581).
  - Type-ahead has no route (#32).
  - There is no user-route error `type` list.
- **FIX still unconfirmed:**
  - P-40: CLAUDE.md "Terms" never expands TOTP, RE2, SPKI, SBOM, CIS, XXE, RBAC or DSN. This is a nit, not a spec item. R2-I-19 added only the Policy, Family and Plugin terms. It needs a confirmer before anything is applied.

## Decisions

- **Classes for every audit item:**
  - **FIX:** the spec states it; give the exact before and after text and a spec quote with its line number.
  - **ASK:** the spec is silent, ambiguous or contradicts itself. The rule gets one line starting `**Open spec question:**` with a pointer to `work/open-questions.md` #N, and no behaviour is chosen.
  - **DECIDE:** a process or repo choice for the user (a PD entry).
  - **REJECT** or **DUP:** give a one-line reason.
  - Nothing is applied until a second agent confirms it. Rule wording restates the spec and never extends it.
- **Numbering rules for `work/open-questions.md`:**
  - Only the planner edits it.
  - Numbers are never renumbered or reused, and a withdrawn entry keeps its number.
  - A rule marker may point only at an **agreed** entry (author plus one confirmer), never at a proposed or withdrawn one.
  - The next free number is #34.
  - When the owner answers an entry, the decision goes to `work/decisions.md`, the marker is replaced with the decided behaviour, and the entry is marked "answered, D-##".
  - Regenerate part 2 from `grep -rn "Open spec question" .claude` after any rule edit.
- **Rejected or withdrawn items, with reasons:**
  - #19 (scan or fleet score): withdrawn. TS §4.5 L602 defines only the host score, and nothing may be invented.
  - The "chars or bytes" half of #17: answerable. SR says "chars", and the DDL uses `VARCHAR(n)`.
  - The "does a scan use `dispatched`/`expired`" half of #22: answerable. TS §4.4 L580 derives scan state exhaustively.
  - Writing "in the results `error` field" for `runner_unavailable` at agent.md:34–35: rejected. TS §3 L152 says only "the agent reports"; #28 holds the question.
  - Import history in the UI: rejected. TS §2.1 L101 limits the UI scope; `/imports` is an API route only.
  - Requiring `ix_agent_hostname_trgm` in the package-search rule: rejected. TS §7.1 does not tie the filter to that index, and the DDL is already required exactly.
  - Planning note on expected 429s for large jobs: rejected. TS §3.3 L224 already says only 429, 5xx and network errors are retried; it is a load-test note only.
  - Removing #8 as "answered from the spec" (R2-P-04): withdrawn. The owner could restrict tokens, so it stays an ASK.
  - Audit-method advice to grep "only", "never" and "must" (R2-P-24): rejected. It is superseded by the rule that every rule wording carries a spec quote.
- **Rulings that still bind on entries:**
  - #13 keeps `nan`, `inf` and `_` in the question, because "floats" can be read as IEEE floats. The reviewer thinks only exponents, `.5` and `5.` are open. Either way no behaviour is chosen, and the owner decides.
  - Every marker states the gap only and never pre-answers it. This is why the `runner_unavailable` wording above was rejected.
- **Owner-decision guards:**
  - No signing, no approval workflow, no ad-hoc or push path, and no way to disable inventory.
  - Viewers never receive `stdout` or `stderr`.
  - Every item above respects these, and none weakens `security-invariants.md`.
