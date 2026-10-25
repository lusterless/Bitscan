# TASK-112 plan: serve the built web UI from the manager's own origin

Covers TASK-112. REQ: REQ-118. Owner: impl-manager. One review round; the reviewer is asked for a second look (unauthenticated file serving). Tests: TP-M5-05 (and the served-bundle check in TP-M5-22); mutation rows CHK-M5-337 to -341. Starts after the M3 gate verdict (`bm/app.py` and `bm/cli/serve.py` are M3 files).

**Blocked on #6 (M5 half)**, including its (f) spec conflict (static files without a token), and **PD-28 (b)** (where the build lands). This plan builds the recommended answers; PD-28 (b)'s alternative changes one path constant.

In this file `bm/` is `manager/bitscan_manager/`; L… are lines of `docs/spec/Technical_Specification.md`.

## Spec quotes

- TS §6.3 L1140: "Every response carries HSTS, `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. There is no CORS: the API serves only its own web UI origin."
- TS §2.1 L101: the Web UI is a component of the manager (React + TypeScript). TS §8.7 L1343: one manager instance, HTTPS only on `BITSCAN_LISTEN`.
- TS §2.3 L118: "Every call into the manager carries a bearer token over HTTPS (TLS 1.2+)." A browser cannot attach one when it loads a page, so the page and its assets are served without a token: **#6 (f), a spec conflict for the owner**, the same reading as the health routes (#5). The files hold no data; every API call the page then makes carries the `bsu_` token (REQ-120).
- TS §8.6 lists the start-up variables; none is added (#6 (e)).

## What is served (#6 (a) to (d))

| Request | Answer |
| --- | --- |
| `GET /` | the build's `index.html`, 200, `text/html; charset=utf-8` |
| `GET /assets/{name}` | a file directly inside the build's `assets/` folder that was present when the app was created, 200, content type by extension |
| anything else outside `/api/v1`, `/healthz`, `/readyz` (including `/index.html`, `/assets/`, `/assets/x/y`, `/favicon.ico`) | the existing problem+json 404 (Starlette's 404 through `api/problems._on_http`); no catch-all, because the UI uses hash routes (`/#/hosts/<id>`, TASK-116) |
| `/` or `/assets/…` when there is no build | the same 404 |

Extension map (a constant; any other extension is not loaded, so it is 404):

| Extension | Content-Type |
| --- | --- |
| `.js` | `text/javascript; charset=utf-8` |
| `.css` | `text/css; charset=utf-8` |
| `.svg` | `image/svg+xml` |
| `.png` | `image/png` |
| `.ico` | `image/x-icon` |
| `.woff2` | `font/woff2` |

No `.map` (the TASK-115 build writes no source maps), `.html` under `assets/`, or `.json`.

## Where the build is (PD-28 (b))

Recommended: Vite writes straight into `bm/webui/` (`manager/bitscan_manager/webui/`, gitignored; TASK-115 sets `build.outDir` and `emptyOutDir: true`). The module constant is

```python
DEFAULT_WEBUI_DIR: Final = Path(__file__).resolve().parents[1] / "webui"   # bm/webui
```

so `serve` from a source checkout finds the build with no new start-up variable. `bm/webui/` has no `__init__.py` and holds no Python. Under PD-28 (b)'s alternative (`web/dist/`, copied into the package at packaging time in M6) only this constant changes. M6 note: hatchling leaves VCS-ignored files out of a wheel by default, so the M6 packaging work must include the folder explicitly.

## Interfaces

```python
# bm/api/webui.py (new)
@dataclass(frozen=True)
class Asset:
    body: bytes
    content_type: str

@dataclass(frozen=True)
class WebUi:
    index: bytes | None                # None: not built
    assets: Mapping[str, Asset]        # file name -> content, fixed at load

def load(folder: Path) -> WebUi: ...  # never raises for a missing or unreadable folder
def build_router(ui: WebUi) -> APIRouter: ...

# bm/app.py
def create_app(runtime: Runtime | None = None, *, webui: WebUi | None = None) -> FastAPI:
    """webui None: load(DEFAULT_WEBUI_DIR). Tests pass load(<fixture folder>)
    or load(<empty tmp folder>)."""
```

`load(folder)`:
1. Reads `folder / "index.html"` if it is a regular file and not a symlink (`Path.lstat`, `stat.S_ISREG`).
2. For each entry directly in `folder / "assets"` (one level, no recursion): keep it only if it is a regular file, not a symlink, its name is 1 to 128 characters, starts with an ASCII letter or digit and has only ASCII letters, digits, `.`, `_` and `-` (plain character checks, no regular expression), and its extension is in the map. Sub-folders, hidden files, `..`, other extensions and symlinks are skipped.
3. Reads every kept file into memory. If the total exceeds 32 MiB the UI is not loaded at all (`WebUi(None, {})`) and one error line is logged; a Vite bundle is a few hundred KiB.
4. Any `OSError` (missing folder, permission) gives `WebUi(None, {})`; the message is not logged (it can name paths outside the folder).

Because the content is in memory from app creation, a file added, changed or replaced by a symlink after start is never served (REQ-118 (2), CHK-M5-337), and no request ever touches the file system.

`build_router(ui)`: both routes are **always registered** (with or without a build), so the route table and the M3 route walk (G34) are the same on every machine:

```python
router = APIRouter(include_in_schema=False)       # not in the document (CHK-M5-341)

@router.get("/")
def index() -> Response:
    if ui.index is None:
        raise HTTPException(404)                   # the normal problem 404
    return Response(ui.index, media_type="text/html; charset=utf-8")

@router.get("/assets/{name}")
def asset(name: str) -> Response:
    found = ui.assets.get(name)                    # a dict lookup, never a path join
    if found is None:
        raise HTTPException(404)
    return Response(found.body, media_type=found.content_type)
```

Neither handler reads a query parameter, a header or the request body. No `HEAD` route is added (FastAPI's `GET` route does not add one; the walk lists `GET` only).

`create_app`: `app.include_router(build_router(webui if webui is not None else load(DEFAULT_WEBUI_DIR)))` next to the health router, before the user and agent routers. Paths do not overlap, so order has no effect on matching.

`serve` (`bm/cli/serve.py`): `ui = webui.load(DEFAULT_WEBUI_DIR)`; if `ui.index is None`, one INFO line `web ui not built; serving the API only`; then `create_app(runtime, webui=ui)`. Nothing else in `serve` changes.

## Headers, CORS and the CSP

- The routes sit inside `BitscanApp`, so `SecurityHeaders` (outermost but one, `bm/app.py`) sets the four TS §6.3 headers on every static response, 404s included, and strips any `access-control-allow-*` (CHK-M5-338, -340). The routes must not be mounted as a separate ASGI app or `StaticFiles` mount outside `BitscanApp.build_middleware_stack()`.
- No CORS middleware. An `OPTIONS` request with an `Origin` header gets the normal 405 problem with no `Access-Control-Allow-*` (REQ-118 (3)).
- The CSP `default-src 'self'` holds for the bundle because TASK-115's build loads only same-origin files (G42): Vite writes `<script type="module" crossorigin src="/assets/…js">` and `<link rel="stylesheet" crossorigin href="/assets/…css">`, both same origin. Screens do not use `style=` attributes (CSP blocks inline style attributes); styles live in the bundled CSS file.
- No caching headers are added (the spec names none; the M6 install work may revisit).

## Edge cases

| Probe (REQ-118 (2)) | Why it is 404 |
| --- | --- |
| `/assets/../app.py`, `/assets/..%2Fapp.py`, `/assets/%2e%2e%2fapp.py` | uvicorn decodes the path before routing; `{name}` (Starlette `str` convertor) never matches a `/`, and `..` or `app.py` is not a key of `ui.assets` |
| `/assets/a%5Cb.js` (backslash), `/assets/%2Fetc%2Fpasswd` | not a key |
| `/assets/sub/x.js` | two segments: no route matches |
| a file written into `assets/` after start | not loaded at creation |
| `/assets/x.map`, `/assets/x.txt` | extension not in the map |
| `/index.html` | only `/` serves the index |
| `/api/v1/unknown` | the API's own 404, never `index.html` (CHK-M5-339) |

- Query strings on `/` or `/assets/…` are ignored.
- The static routes are not rate limited and need no token (#6 (f)), like `/healthz`; they read no database.
- `RequestLog` logs these requests like any other (path, status; never a query string).
- The OpenAPI export (`python -m bitscan_manager.app`) calls `create_app()`, which loads the default folder; with `include_in_schema=False` the document is byte-identical whether or not a build exists (G6, REQ-118 (4)).

## Tests the plan expects (tester owns them)

TP-M5-05 (`manager/tests/test_webui_serving.py`) builds a fixture folder in `tmp_path` (`index.html`, `assets/app-1a2b.js`, `assets/app-1a2b.css`, a `.map`, a sub-folder, a symlink where the OS allows, a dot file) and passes `create_app(webui=load(folder))`: every row above, the exact headers, no `Access-Control-Allow-*` (also to `OPTIONS` with `Origin`), a file added after creation, G6 unchanged, and `create_app(webui=load(empty))` with `/` 404 and the API routes unaffected. The route-walk allow-list in `manager/tests/test_invariants_m3.py` gains exactly `GET /` and `GET /assets/{name}` (an M3 test file: that edit also waits for the M3 gate verdict). The served-bundle check against a real `serve` in WSL with the TASK-115 build is TP-M5-22.
