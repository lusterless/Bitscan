# Round 3 brief (shared by planner, reviewer, tester, implementer)

Written by the lead (you address it as `main`). Read this file completely before you start.

## Goal from the user
Clean up the workspace, apply the round-2 fixes that are right, and make sure every document is accurate and has no holes. Documents in scope: `.claude/CLAUDE.md`, `.claude/rules/**`, `.claude/agents/*.md`, `.claude/skills/bitscan-team/SKILL.md`, `.claude/settings.json`, `README.md`, `.gitignore`, `.gitattributes`, `docs/agent-teams-reference.md`, `work/open-questions.md`, `work/audit/*.md`. Out of scope: `docs/spec/**` (never edit; report spec-internal problems only), all product code (none exists yet), `docs/agent-teams-patterns.md` (the lead writes it after you finish).

## State of the tree
- HEAD is commit 01748b2. The working tree holds uncommitted edits (`git diff`, `git status`). They apply some round-2 findings already: `main` addressing in the four role files, CLAUDE.md and SKILL.md; **Open spec question** lines for open questions #2 to #8 in the rules; `bits/tests/**` in testing.md paths; `*.preseed` and `install.env` in `.gitignore`; `bits/samples/` in SKILL.md and implementer.md. Check these first; they are not yet verified.
- Round-2 reports: `work/audit/round2-planner.md`, `round2-reviewer.md`, `round2-implementer.md`. The tester never delivered `round2-tester.md` (it stopped to wait for the user, which it must not do). Round-1 reports: `planner.md`, `reviewer.md`, `tester.md`, `implementer.md`. Most round-2 findings are still UNVERIFIED.

## Hard rules
1. The spec wins. Do not edit `docs/spec/**`. If code and spec disagree, or the spec is silent, do not guess.
2. Quote the spec. Every finding and every proposed wording carries the spec sentence (`TS §x.y` or `SR §x.y`, with the line number in the spec file) that supports it. A rule line must restate the spec; if your wording says more than the spec does, trim it.
3. Classify every item you touch as exactly one of:
   - **FIX**: the spec states it clearly; the rule or doc is wrong, stale or missing it. Give the exact before/after text.
   - **ASK**: the spec is silent, ambiguous or conflicts with itself, or the owner could reasonably answer differently. The rule gets one line starting `**Open spec question:**` that ends with a pointer `(work/open-questions.md #N)`; the planner adds the matching numbered entry. No behaviour is chosen. This is the default for anything inferred.
   - **DECIDE**: a team-workflow or repo-process choice for the user (for example a second approver, a review baseline, a loader fallback). It goes to the "Process decisions for the user" section of `work/open-questions.md`; nothing is applied.
   - **REJECT** or **DUP**: wrong, already fixed, or the same as another id. Say why in one line.
4. Nothing is applied until a second agent (not the author) has CONFIRMED it. The tester also confirms mechanically that every quoted spec sentence exists verbatim at the cited line and that every cited file:line exists.
5. Never add anything listed as out of scope or as an owner decision in `.claude/CLAUDE.md`, and never weaken `.claude/rules/security-invariants.md`.
6. Nobody commits, pushes or changes branches. The user is not reachable: never stop to wait for the user. Anything that needs the user goes to `main` in a message and into your report; then continue with your other items.

## Who writes which file (single writer per file)
| File or area | Only writer |
| --- | --- |
| `.claude/**`, `README.md`, `.gitignore`, `.gitattributes`, `docs/agent-teams-reference.md` | `implementer` (the lead authorises this for the current task even though these are not under `manager/`, `agent/`, `web/`, `bits/samples/` or `deploy/`; no other file outside `work/`) |
| `work/open-questions.md` | `planner` |
| `work/audit/round3-planner.md`, `round2-planner.md` and `planner.md` | `planner` |
| `work/audit/round3-reviewer.md`, `round2-reviewer.md` and `reviewer.md` | `reviewer` |
| `work/audit/round2-tester.md`, `round3-tester.md` and `tester.md` | `tester` |
| `work/audit/round3-implementer.md`, `round2-implementer.md` and `implementer.md` | `implementer` |
| `work/status.md`, `work/decisions.md`, `work/audit/round3-brief.md`, `docs/agent-teams-patterns.md` | the lead (`main`) |
Everyone else asks the owner by message. Use `Write`/`Edit` only on your own files. The reviewer and tester use Bash read-only (`git`, `grep`, `node`, no redirects into repo files).

## Messaging protocol
- Teammates: `planner`, `reviewer`, `tester`, `implementer`. The lead is `main`. Use SendMessage. Put a one-line self-contained summary first (the recipient sees only that line as a preview).
- Mandatory exchange: send each of the other three teammates at least one message (a request, an answer, a confirmation, or a challenge), and answer every request addressed to you. Record each exchange in an "Exchange log" section of your report.
- If you have no SendMessage tool, say so in your report and in your last text output, and write the exchange into the report instead.
- Patch hand-off: when an item has the author plus one confirmer, the author (or confirmer) sends `implementer` a message beginning `APPLY:` with the ids, the file:line, the exact before/after text and the spec quote. If two patches touch the same lines, the implementer merges them and tells both senders.
- After applying, the implementer sends `APPLIED: <ids>` to `reviewer` and `tester`, who reply `VERIFIED: <ids>` or `REJECTED <id>: reason` to the implementer, copying `main` only for rejections. The reviewer checks the changed lines against the spec; the tester checks mechanically (citations resolve, front matter, balanced fences, `paths:` globs, `(work/open-questions.md #N)` pointers match real entries, no stale `lead` addressing, line counts, `git diff --stat`).
- When the implementer's queue is empty and all its batches are verified, it sends `IMPLEMENTER-DONE` to the other three. Do not send your `FINAL:` message until you have seen it and have verified or answered everything before it.
- End with exactly one message to `main` beginning `FINAL:` (at most 200 words): counts by class (FIX applied, ASK logged, DECIDE logged, REJECT, DUP), files changed, report path, anything that needs the user. A completion notice is not a FINAL.

## Finding format (all reports)
`R3-<role letter>-## | class | file:line or spec § | what is wrong or missing | spec quote (§ and spec line) | exact wording or patch | status (UNVERIFIED, CONFIRMED by <agent>, APPLIED, VERIFIED, REJECTED)`.
Reuse the round-1/round-2 id in the first column text when you rule on an existing finding (for example "rules on R2-P-07"). Keep reports short; no praise padding.

## Slices for hunting holes (read your slice of the spec in full, not from memory)
- planner: SR §1 to §4 and TS §4.
- reviewer: TS §3.3 to §3.7 and §8.1 to §8.4.
- implementer: TS §1, §2, §3.1, §3.2, §8.5 to §8.7, plus workspace hygiene (stray files, stale paths, ignore rules).
- tester: TS §5, §6, §7 and the "Tests" lines of every rule against TS §8.3, plus all mechanical checks.
