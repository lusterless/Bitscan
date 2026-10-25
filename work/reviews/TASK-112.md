# TASK-112 REVIEW: serve the built web UI

Verdict: APPROVED (revisions 0 and 1). Revision 1 closes the trailing-slash point (Finding 1). It follows the user's ruling of 2026-10-25, and its TEST passed.

Reviewer: reviewer, 2026-10-25. One review round (UI serving). Not a two-approval task.

Scope reviewed:
- `manager/bitscan_manager/api/webui.py` (new);
- `manager/bitscan_manager/app.py`: the `webui` keyword, the router include and, from r1, `redirect_slashes=False`;
- `manager/bitscan_manager/cli/serve.py` (`work/reports/TASK-112-impl.md`).

Sources: REQ-118, TS §6.3 L1140, the #6 M5 half (decisions 2026-10-24: no token, no catch-all, no CORS, a recorded deviation from TS §2.3 L118), PD-28 (b), and decisions 2026-10-25 (trailing-slash redirects off app-wide).

TEST:
- r0: PASS (`work/reports/TASK-112-test.md`, rows CHK-M5-100..112).
  - Includes 52 raw-ASGI traversal and encoding probes, symlink and FIFO cases, the 32 MiB boundary, and the route walk with exactly `GET /` and `GET /assets/{name}`.
  - Plants CHK-M5-337..341 and the G34 query plant are red.
- r1: PASS (tester-m5, 2026-10-25; see Finding 1). Plant CHK-M5-364 is red.

## Checks
1. Spec (REQ-118 (1)–(6)):
   - `/` returns the build's `index.html`, and `/assets/{name}` is a dict lookup, never a path join.
   - Files are read once, when the app is created, and the content type is fixed by extension.
   - The routes are registered with or without a build, so the route table does not change.
   - Both routes have `include_in_schema=False`.
   - No CORS, no catch-all and no `HEAD` route. The handlers read no query, header or body.
   - With no build, `/` gives 404, and `serve` logs one fixed line.
2. Security:
   - Each file is checked with `lstat`, then opened with `O_NOFOLLOW|O_NONBLOCK`, then checked again with `fstat`. This follows checklist item 14: no symlink swap and no FIFO hang.
   - `assets/` must itself be a real directory.
   - Names are checked by character sets with no regular expression. Only the six mapped extensions are kept.
   - Every `OSError` gives "not built" and is not logged, so no path text reaches a log. The 32 MiB refusal logs fixed words.
   - The router sits inside `BitscanApp`, so `SecurityHeaders` covers both routes.
3. Re-run by the reviewer:
   - `ruff check` and `ruff format --check` on `manager` pass.
   - `mypy --strict` passes (110 files).
   - A fresh OpenAPI export is byte-identical to `manager/openapi.json` (G6). That export was made with the TASK-115 build present in the tree.
4. Scope: 3 files as planned, about 160 lines. r1 adds 5 lines to `app.py`.

## Findings
1. **Closed by r1 (user ruling 2026-10-25; r1 TEST PASS).**
   - Location: `app.py:300`. Starlette's `redirect_slashes` answered `/assets/<file>/`, and every slashed API path, with a 307 whose `Location` was built from the client's `Host` header. REQ-118 expects a 404 for every other path.
   - r1 passes `redirect_slashes=False` to the app, which is correct for FastAPI 0.148 / Starlette 1.9: only the app's own router runs the redirect check.
   - r1 TEST shows:
     - 17 slashed paths were sent with `Host: evil.example`: an asset, `//`, health, user, CSV, login, enrol, and the agent jobs, heartbeat and inventory routes. Each answered problem+json 404 with the TS §6.3 headers, no `Location`, no CORS and no Host echo. The real serve over TLS gave the same answers.
     - The slash-less control paths still match.
     - The plant that removes the keyword argument, or sets it to `True`, is red with 307s.
     - The M2/M3 route suites pass 521/522. The one failure was a bug in a control test, re-run 1/1.
     - The traversal test now expects 404 unconditionally.
   - I read the new tests (`test_webui_serving.py:318-375`). They can fail.
2. nit, `webui.py:120`. An `index.html` that exists but cannot be read (EACCES) also gives "not built". So `serve` logs "web ui not built", which is misleading for a permissions mistake. impl-manager kept the planned behaviour, which I accept.
