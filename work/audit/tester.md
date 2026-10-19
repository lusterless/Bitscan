# Tester audit (rounds 1–3, merged)

Lens: the docs treated as code and tested mechanically. All commands are read-only, run from the repo root in Git Bash with node v24. The checker scripts live outside the repo, in `%TEMP%\bitscan-audit\`: `check.js`, `final.js`, `quotes.js`, `quotes3.js`. They take the repo root as their only argument. Round-1 original: `work/audit/archive/round1-tester.md`.

## Done

Verified fixes, grouped (all VERIFIED on the final tree):
- Addressing and ownership: `main` addressing; `impl-<area>` naming; `impl-bits` and `impl-deploy`; the `bits/samples/` and `bits/tests/` split; `work/reports/` owners; `.claude/rules/` path prefixes.
- Citation scope: CLAUDE.md out-of-scope and G1 citations; security-invariants remediation and journald; Tests-line sources in 14 rules (lintian, SBOM, Prettier, AKIA, CSV, 500 pairs, `/readyz`, checkpoint, settings, cron, re-evaluation and others).
- Rule content restated from the spec:
  - coverage path annotated;
  - redaction fixture superset;
  - `GET`/`DELETE /api-tokens`;
  - CLI DSN split;
  - offline_sweep duties;
  - agent-route error types plus 409 `policy_managed_on_server`;
  - Bootstrap schema owner and `USAGE`;
  - enrolment tokens created and revoked;
  - list filters;
  - package click-through;
  - the invented "manager recomputes `list_sha256`" removed.
- Markers: every **Open spec question** is on its own line and ends with a pointer to an agreed entry. The `work/open-questions.md` part-2 table matches the grep. This closed R3-T-01 (embedded markers), R3-T-02 (stale part-2 table) and R3-T-03 (TS/SR prefixes); `docs/agent-teams-patterns.md` cites all three.
- Hygiene: README written; `.gitignore` covers `*.preseed`, `install.env`, `.claude/settings.local.json` and the build outputs; `.gitattributes` has `*.gz binary`; `settings.local.json` is untracked.

Mechanical checks that pass on the final tree:

| Check | Command | Final result |
| --- | --- | --- |
| Citations resolve to spec headings | `R1=1 node check.js .` / `node check.js .` | 331 in the round-1 scope (`.claude/**` + agent-teams-reference), 0 missing. Full scope 472, 0 missing (2 unprefixed hits cite report sections, not the spec) |
| Front matter (keys, no duplicates, `paths`, `name` = file) | `node check.js .` | 21/21 |
| Fences balanced; all LF | `node check.js .` | pass |
| No stale `lead` or `implementer-<area>` addressing | `node final.js .` | 0 in `.claude/` and README. The 4 hits in agent-teams-reference.md (:90, :186, :340, :351) describe the lead's role or quote the upstream example; they are not addresses |
| `paths:` globs against the layout | `node check.js .` (60 sample paths) | every layout directory matched, 0 dead globs; 7 build and config files unmatched (PD-12) |
| Spec facts restated in the rules | `grep -cF` of the 8 error types (TS §6.5, agent.md, api.md); the operator enum (TS L645–L646) diffed with evaluator.md; the CSP string (TS §6.3, api.md); `agent_status` (DDL, database.md); `find .claude/rules -type f \| wc -l` | identical in every file; 14 operators; 17 rule files. The BIT codes are SR §4.1's 18 codes, plus the retired BIT006, BIT009 and BIT018–BIT020, named only as retired (bit-format.md:36) |
| Live files that cite round-report paths | `grep -rnE 'work/audit/(round[123]-\|archive)' .claude README.md work/open-questions.md` | 1 hit: open-questions.md:154 "(history: `work/audit/archive/round1-reviewer.md`)", a history pointer in the planner's file, now pointing into `work/audit/archive/`. `.claude/` and README: 0 |
| Markers on their own line; count | `node final.js .` | 44, 0 embedded |
| Pointers resolve to **agreed** entries | `node final.js .` | 35 pointers, 0 bad; #19 withdrawn, nothing points at it |
| Part-2 table matches the markers | diff of the part-2 `file:line` column against `grep -rn '\*\*Open spec question:\*\*' .claude` | match (44 = 44) |
| Ignore rules; nothing tracked is ignored | `git check-ignore -v bitscan.preseed deploy/runbooks/install.env .claude/settings.local.json`; `git ls-files -ci --exclude-standard` | 3 matches; the second command prints nothing |
| Binary attributes | `git check-attr text diff -- bits/tests/bomb.gz x.deb` | text and diff unset for both |
| Spec untouched | `git diff --stat -- docs/spec` | empty |
| Quoted spec sentences at their cited lines | `node quotes.js .`; `node quotes3.js .` | 79/79 round-3 quotes. Round-2: none refuted; 3 are paraphrases (a table row, JSON quotes dropped, a unit-file line) |

Final counts (rounds 1–3): 23 round-1 findings (19 fixed, 4 carried below). Then 8 FIX, 2 ASK, 1 DECIDE and 1 DUP authored. All 8 FIX were applied and verified; nothing was refuted and nothing rejected.

Final-tree re-run, after IMPLEMENTER-DONE and the implementer's 3 appends (jobs-and-scans.md:23, packaging-and-units.md:51, agent.md:25): every check above passes. `git diff --stat`: 33 files changed, 656 insertions(+), 662 deletions(-).

## Open items

- PD-12 (DECIDE, from T-16 and R2-T-07): no rule's `paths:` loads `manager/pyproject.toml`, `manager/requirements*.txt`, `manager/alembic.ini`, `agent/go.mod`, `agent/go.sum`, `agent/.golangci.yml` or `manager/bitscan_manager/services/__init__.py` (7 of 60 layout samples). Options: add the globs to testing.md, or rely on CLAUDE.md and security-invariants, which always load.
- PD-5 (DECIDE, carries T-17): CLAUDE.md "Commands" has no test, coverage, Prettier or OpenAPI-regen command, and no stated place to run the Linux-only suites. The coverage gate must measure `manager/bitscan_manager/services/`.
- PD-8 (DECIDE; R2-T-08 extended it to CSV golden files): how CRLF fixtures and CSV golden files are kept (see Decisions). `*.gz binary` is already applied.
- Other DECIDE items for the user: PD-1 to PD-4, PD-6, PD-7, PD-9 to PD-11 (`work/open-questions.md` §4).
- ASK entries from my slice:
  - #25 (P-18; I confirmed it): heartbeat fields with no column; `agent_ip_seen` writers; the age of a never-heartbeating agent.
  - #32 (R2-T-04, marker at web-ui.md): package type-ahead has no route.
  - #33 (R2-T-05, marker at inventory-and-packages.md): whether the manager recomputes `list_sha256`.
- T-20: agent-teams-reference.md:208–210 keeps the upstream `src/auth/` / httpOnly-cookie example on purpose. It is not a project rule; no action.
- T-23 (spec-internal, report only): the TS §5.1 table map omits `agent_ip_seen` and `task`. Logged in `work/open-questions.md` §5.

## Decisions

- **The spec wins; quotes are checked mechanically.** A finding counts only if its quoted spec sentence exists verbatim at the cited line (whitespace, `**` and backticks normalised; `…` splits segments). A paraphrase of a table row is acceptable when stated as such. Rule sentences with "only", "never", "must", "always" or "omits" need a spec source, or they become an **Open spec question**.
- **Pointer format** is "(`work/open-questions.md` #N)", with backticks. A rule may point only at an entry marked **agreed**. Numbers are never reused.
- **CRLF fixtures.** `.gitattributes` has `* text=auto eol=lf`. This was demonstrated in a throwaway repo: CRLF in a committed text fixture (normaliser stdout, CSV golden file) becomes LF on checkout, so a test of "CRLF becomes LF" (SR §2.4 L151) passes without testing anything. Until PD-8 is decided, testers build CRLF inputs as in-code literals (`"\r\n"`) or compare parsed CSV rows. A file with a lone CR is detected as binary and kept. `.bit` files are unaffected, because XML end-of-line handling normalises them.
- **CSV line endings** are not specified (TS §6.3 L1142 covers escaping only). Do not assert CRLF or LF in export tests without asking.
- **Tests-line labels** (T-08, R2-T-06). A case listed under "Tests (TS §8.3)" that is not in the §8.3 table carries its own TS section in parentheses.
- **Embedded markers are defects** (R3-T-01). Every **Open spec question** is its own bullet starting `- **Open spec question:**`, so a grep finds them all.
