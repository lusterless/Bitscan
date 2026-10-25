# TASK-128 REVIEW: README user guide for M5

Verdict: APPROVED (revision 1)

Reviewer: reviewer, 2026-10-25. One review round (docs). Not a two-approval task.

Scope reviewed: `README.md`, the M5 diff (87 lines added and 7 changed; `work/reports/TASK-128-impl.md`). Sources:
- REQ-135;
- TS §3.2 L181, §6.3, §7.1–§7.3;
- #6 (M5 half), #32, #83, #84, #85, #86;
- decisions 2026-10-20 (README holds user-guide content only) and 2026-10-25 (trailing slashes are not redirected; the TASK-085 sentences);
- the approved M5 code and reviews.

TEST: PASS (tester-m5, `test_readme_m5_walk_linux.py`). The test walked the README against a real `serve` with the real build.
- Sections walked: Web UI, Package search, API trailing slash, Enrolling agents.
- 103 rows, 0 deviations.
- 4 plants red: 3 README misstatements and 1 product change.

## Checks
1. **Against the code.** I checked the statements against the approved code:
   - Serving rules (`webui.py`): six content types, the 32 MiB limit, the "not built" log line, read once at start-up, every other path 404, and no trailing-slash redirect (`app.py`).
   - UI labels and flows (`App.tsx`, `routes.tsx`, screens): Start/Confirm, Not now, Sign in again, Copy/Done, Show, Export CSV, and the page-by-role table.
   - Search parameters and rules (`query.py`, `repositories/packages.py`): the three installed states, literal `%`, `_` and `\`, the cursor binding, and the order.
   - CSV headers, the 100,000 cap and its exact detail, and the escaping example.
2. **TASK-085's two sentences.** They are word for word the M4 README's, so the two trees agree at merge.
3. **Secrets and process.** Every token is a placeholder. There are no task or REQ ids and no process notes. The token-in-memory and sign-out statements match TASK-116.
4. **Commands.** `npm ci --ignore-scripts` and `npm run build` match `web/package.json` and CI. The `curl` example uses `-G` with `--data-urlencode`.
5. **Scope.** One file, user-guide text only.

## Findings
1. Observation for main, outside this diff: `README.md:3` still says "Ubuntu/Debian endpoints" and "Ubuntu 22.04, Ubuntu 24.04 and Debian 12 (amd64 and arm64, cgroup v2)". That contradicts the user's v1 scope decisions of 2026-10-24, which allow Ubuntu 22.04 and 24.04 on amd64 only. The tester raised it too.
   - The line predates M5 and is not in TASK-128's diff, so it does not block this task.
   - It is a user-facing error in the user guide. It should be corrected in one line before the M5 (or M4) PR, by impl-manager as README owner, as a small follow-up that main assigns.
   - **Closed by r1.** Line 3 now reads "inventories Ubuntu endpoints … Supported hosts are Ubuntu 22.04 and Ubuntu 24.04 (amd64, cgroup v2)". No mention of Debian 12 or arm64 is left in the README. r1 TEST PASS (tester-m5): the walk re-ran 1/1, 103 rows, 0 deviations.
   - The M4 tree's `README.md:3` is byte-identical to M5's, and neither README mentions Debian 12 or arm64 (checked 2026-10-25).
