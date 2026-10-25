# TASK-128 IMPL: README user guide for M5

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-135. Released by the lead on 2026-10-25, after M4 TASK-085 got TEST PASS and REVIEW APPROVED. TS §3.2 (L181), §6.3, §7.1–§7.3; #6 (M5 half), #32, #83, #84, #85, #86.

## Files

- `README.md` only: 87 lines added and 7 changed (`git diff --stat`), LF line ends. No other file changed.

## What changed

| Where | Change |
| --- | --- |
| Status | Now M5. `serve` also has package search with CSV export and the web UI. "The web UI … do not run yet" is gone. |
| Prerequisites | Node.js 24 and npm, for the UI build (`web/package.json` `engines`). |
| **Web UI** (new, after "Starting the app") | Building (`npm ci --ignore-scripts`, `npm run build` into `manager/bitscan_manager/webui/`, read once at start-up, the "not built" log line, the 32 MiB limit). How it is served: `/` and `/assets/<file>` need no token, the six served types, and every other path is a problem+json 404 (`/index.html` and `/favicon.ico` too). Hash routes. The token is held in memory only. Then sign-in, the TOTP required and offer flows, TOTP replacement, password change, the page-by-role table, enrolment tokens (defaults, shown once, Copy, revoke), enrolment requests (pending/decided, matching agents, confirm, "already decided"), hosts and host detail, and package search (type-ahead, View, version drill-down keeping the filters, Export CSV). |
| API intro | One sentence: a trailing slash is not redirected and gets 404 (TASK-112 r1, user ruling 2026-10-25). |
| API list | A "Package search" bullet pointing to the new section. |
| **Package search** (new, after "API") | The eleven TS §7.1 parameters with the implemented rules (#83: `status=installed` covers the three installed states, `os` with or without a version, substring `host`, literal `%`, `_` and `\`), the 400s naming only the parameters, the three item shapes, the order, cursor binding, and a `curl` example. CSV export: same parameters without `limit` and `cursor`, the headers, the 100,000 cap and its exact 400 detail, and the formula escaping with the `=HYPERLINK` example. |
| Enrolling agents | The intro and "Approving enrolments" now name the UI pages first. The `curl` API path stays as the scripted alternative (#37, REQ-090). |
| **M4 TASK-085's two sentences** | Copied word for word from `Bitscan-m4/README.md` L252 and L258, as the lead asked, so the two trees agree at merge: "A call with the old token then gets 401 `unauthorized`." (end of the re-enrolment approve bullet) and the bullet "An operator who calls approve or reject gets 403 `totp_session_required` with an API token or a session not verified with TOTP, and 403 `forbidden` with a TOTP-verified session." (after "Deciding a request twice gets 409 …"). |

After this change, `diff Bitscan-m5/README.md Bitscan-m4/README.md` shows only the M5 additions. The two sentences above are identical in both trees.

## Sources for each statement

- UI behaviour: the impl reports for TASK-115, 116, 118 to 126 (labels checked against `web/src/screens/*.tsx` and `web/src/app/App.tsx`: "Sign out", "Not now", "Search", "Export CSV", "Show").
- Serving: `manager/bitscan_manager/api/webui.py` (`CONTENT_TYPES`, `MAX_TOTAL_BYTES`), `cli/serve.py` L261–L263 (the log line), and `app.py` (`redirect_slashes=False`).
- Search and CSV: `services/packages/query.py` (rules, lengths), `repositories/packages.py` (`INSTALLED_STATUSES`, the `_SHAPES` orders, `like_escape`, `version` versus `version_op`), `services/packages/search.py` (`CSV_HEADERS`, `CSV_MAX_ROWS`), `services/packages/csv_export.py`, and `api/user/packages.py` (`_TOO_MANY`, the response headers).

## Checks

- No task id, REQ id, open-question number, real secret or process note in `README.md` (grep for `TASK-`, `REQ-`, `PD-` and `#8x` finds nothing). Token values in examples are placeholders (`<token>`).
- No code changed, so no lint or type run was needed. No tests run.

## For the tester (TP-M5-21)

- Walk the "Web UI" section against a WSL manager serving the built UI: build, start, `/` and an asset with no token, the 404 cases (`/index.html`, `/favicon.ico`, `/assets/<file>/`), sign-in, the TOTP required and offer flows, an enrolment token, an approval, the host pages, a search with each View, a version drill-down and Export CSV.
- Walk "Package search": each 400 named, the `curl` example, the CSV headers and the escaping example.
- After a new `npm run build`, restart `serve`: the UI folder is read only at start-up.

## Revision 1 (lead ruling 2026-10-25, from the user's 2026-10-24 scope decisions)

- `README.md` line 3 only. Debian 12 and arm64 were dropped from v1, so the line now reads: "Bitscan is a manager + agent platform that inventories Ubuntu endpoints and runs compliance checks defined in XML `.bit` policy files. Agents are pull-only: the manager never pushes commands. Supported hosts are Ubuntu 22.04 and Ubuntu 24.04 (amd64, cgroup v2)."
- Nothing else changed. The same line was changed to the same text in `Bitscan-m4/README.md` (recorded as TASK-085 r1 there), so line 3 is identical in both trees. `diff` shows the first difference at line 5, the M5 status line.
- `.claude/CLAUDE.md` still lists Debian 12 under "Supported hosts". That is the user's file and the user's edit to make; I did not touch it.
- For the tester: re-run only the README walk's hygiene row (no secret, task id or process note; text matches scope).
