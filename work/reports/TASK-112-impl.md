# TASK-112 IMPL: serve the built web UI

Owner: impl-manager. Worktree `Bitscan-m5`, branch `m5-ui`. REQ-118. Plan: `work/plans/TASK-112.md`. #6 (M5 half) and PD-28 (b) as approved (decisions 2026-10-24). TS §6.3 L1140, §2.3 L118 (the recorded deviation: static files need no token).

## Files

- `manager/bitscan_manager/api/webui.py` (new, 142 lines): `DEFAULT_WEBUI_DIR` (`bitscan_manager/webui/`), `CONTENT_TYPES`, `Asset`, `WebUi`, `load(folder)`, `build_router(ui)`.
- `manager/bitscan_manager/app.py`: `create_app(runtime=None, *, webui=None)`. `webui` None loads `DEFAULT_WEBUI_DIR`. The router is included right after the health router, inside `BitscanApp`, so `SecurityHeaders` applies.
- `manager/bitscan_manager/cli/serve.py`: loads the UI once. If there is no `index.html` it logs one INFO line, `web ui not built; serving the API only`, then calls `create_app(runtime, webui=ui)`.
- `manager/openapi.json`: **not changed**. The routes use `include_in_schema=False`; a fresh export is byte-identical to the committed file, with the worktree's TASK-115 build present in `bitscan_manager/webui/`.

## Behaviour (the plan's tables)

- `GET /` serves the build's `index.html` (`text/html; charset=utf-8`).
- `GET /assets/{name}` serves the in-memory file of that exact name, typed by its extension: `.js`, `.css`, `.svg`, `.png`, `.ico`, `.woff2`.
- Anything else gets the normal problem+json 404 from `HTTPException(404)`, the same as Starlette's own not-found. With no build, `/` and every asset are 404 too.
- No catch-all, no CORS middleware, no `HEAD` route (`HEAD /` is 405). The handlers read no query, header or body.

`load(folder)`, hardened beyond the plan where noted:
- `index.html` and each asset must be regular files by `lstat` (symlinks and folders are skipped).
- **Addition:** each file is then opened with `O_NOFOLLOW | O_NONBLOCK` (POSIX; no-ops on Windows) and re-checked with `fstat`. A symlink swapped in after the `lstat` is not followed, and a FIFO cannot hang start-up.
- Asset names: one level only, 1 to 128 characters, first character an ASCII letter or digit, then ASCII letters, digits, `.`, `_` and `-` only, and an extension in the map. Plain set checks, no regex.
- If the total (index plus assets) is over 32 MiB, the UI is not loaded and one fixed ERROR line is logged.
- Any `OSError` means "not built" and is not logged. A missing `index.html` means not built. A missing `assets/` folder keeps the index with no assets.

## Ad-hoc sanity (TestClient on a temp build; not a test file)

- `/`, `.js` and `.css` answered 200 with the plan's content types.
- These all answered problem+json 404 with no file content: `../app.py`, `..%2Fapp.py`, `%2e%2e%2fapp.py`, `a%5Cb.js`, `%2Fetc%2Fpasswd`, `sub/y.js`, a file added after creation, `.map`, a dot file, `/index.html`, `/api/v1/unknown`, `/assets/` and `/favicon.ico`.
- Response headers on `/` were exactly the four TS §6.3 headers plus `content-type` and `content-length`.
- `OPTIONS /` with an `Origin` header gave 405 with no `access-control-*` header.
- An empty folder gave 404 on `/` while `/healthz` gave 200.

## Checks run (from `Bitscan-m5/manager`, M3 venv)

- `ruff check`, `ruff format --check` and `mypy --strict` on `bitscan_manager` all pass (108 files).
- The export compared equal to `openapi.json`.
- No tests run.

## For the tester

- Tests pass `create_app(webui=load(tmp_path))`. `create_app()` with no argument loads `bitscan_manager/webui/`, which exists in this worktree (TASK-115's build). Tests that need "no UI" must pass `webui=load(<empty dir>)` or `webui=WebUi()`.
- The route walk (G34) allow-list gains exactly `GET /` and `GET /assets/{name}` (TP-M5-05, your M3 test file).
- Symlink cases only behave as described on Linux (`O_NOFOLLOW`); run them in WSL.
- `.gitignore` for `bitscan_manager/webui/` is TASK-115's line, not part of this task.

## Revision 1 (user ruling, decisions 2026-10-25: trailing-slash redirects off app-wide)

### Change

- `manager/bitscan_manager/app.py` (outside TASK-112's original file list; already changed by this task for the UI router): `create_app` passes `redirect_slashes=False` to `BitscanApp(...)`, with a 4-line comment. That is the whole code change (+5 lines).
- No other file changed. No `APIRouter` needed it. In the installed FastAPI 0.148.0 / Starlette 1.9.0, `include_router` keeps each included router as an `_IncludedRouter` route in the app's router. Only the app router's `app()` runs the redirect check, after no route matched. An included router is entered only through `_handle_selected`, which on no match calls `default` (the 404) and never runs its own redirect. So the app-level flag covers every path. Setting it on every `APIRouter` would add 20 edits that change nothing.
- `manager/openapi.json`: **not changed**. A fresh export with `write_openapi` is byte-identical to the committed file (`cmp`).

### Behaviour now

- Any path with a trailing slash that matches no route gets the standard problem+json 404 with the four TS §6.3 headers and no `Location`. Previously it was a 307 with `Location: http://<Host header>/<path without slash>`.
- Ad-hoc check (TestClient with `Host: evil.example`, plus a raw ASGI call; scripts in %TEMP%, not test files). All of these gave 404 `application/problem+json`, the 4 headers and no `location`: `GET /assets/x.js/`, `GET /assets/`, `GET /api/v1/agents/`, `GET /healthz/`, `POST /api/v1/auth/login/`, `GET /api/v1/agent/abc/jobs/` and raw `//`. `/assets/x.js` and `/healthz` still gave 200.
- Plant: after `app.router.redirect_slashes = True` on a built app, the same requests gave 307 with `location: http://evil.example/...`. So a test that expects 404 for these paths goes red if the flag is turned back on.

### Checks run (CI commands, from the `Bitscan-m5` root, M3 venv)

- `ruff check manager`: all checks passed. `ruff format --check manager`: 229 files already formatted.
- `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 229 source files.
- No tests run.

### For the tester

- Re-run the M2, M3 and M5 route suites that touch paths. Any test that accepted 307 for a trailing-slash path now must expect the problem+json 404.
- One plant: turn `redirect_slashes` back on (`app.router.redirect_slashes = True`, or remove the kwarg). `/assets/<file>/` and a slashed API path then answer 307, and the 404 tests go red.
