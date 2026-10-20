# TASK-002 plan: manager package skeleton

REQs: REQ-003 to REQ-008. Owner: impl-manager. Depends on: TASK-001.

## Spec quotes

- TS §6 L1056: "One versioned REST API at `/api/v1`, JSON over HTTPS (TLS 1.2+), described by an OpenAPI 3.1 document generated from code. … Each route group is a separate router with its own token check."
- TS §2.3 L118: "Every call into the manager carries a bearer token over HTTPS (TLS 1.2+)."
- TS §6.3 (api.md "Conventions"): CSP `default-src 'self'`; "No CORS: never send `Access-Control-Allow-*`."
- TS §8.7 L1359: `ExecStart=/usr/bin/bitscan-manager serve`; L1347: server CLI commands run as root.

## Interfaces (fixed contract for testers and later tasks)

```python
# manager/bitscan_manager/__init__.py
__version__: str            # SemVer (TS §8.2); initial value PD-14 (m)

# manager/bitscan_manager/app.py
def create_app() -> fastapi.FastAPI: ...
def openapi_document() -> dict[str, object]: ...
def write_openapi(path: pathlib.Path) -> None: ...
# `python -m bitscan_manager.app <path>` calls write_openapi(Path(<path>))

# manager/bitscan_manager/cli/__init__.py
def main(argv: collections.abc.Sequence[str] | None = None) -> int: ...
# console script: bitscan-manager = "bitscan_manager.cli:main"
```

## Approach

- `create_app()` builds `FastAPI(title=..., version=__version__, openapi_url=None, docs_url=None, redoc_url=None)`. No routers, middleware or exception handlers in M0 (they are M3). `openapi_url=None` removes the route but `app.openapi()` still builds the document, which `openapi_document()` returns.
- The default doc routes are disabled because TS §6.2 lists no such route, TS §2.3 needs a bearer token on every call, and Swagger UI loads assets from another origin, which the TS §6.3 CSP forbids. Whether the document is ever served at runtime is #34; until it is answered, nothing is served.
- `write_openapi(path)` writes `json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"` with `encoding="utf-8", newline="\n"`, so the bytes are the same on Windows and Linux. Do not use shell redirection (`>`), which on Windows can produce CRLF or a different encoding.
- `manager/openapi.json` is the committed output of `python -m bitscan_manager.app manager/openapi.json` (run from the repo root, with the package installed). Its location is PD-14 (f).
- `cli.main`: an `argparse` parser with `prog="bitscan-manager"` and no subcommands in M0. `--help` exits 0. Any other input, including no arguments, prints usage and a "not implemented" line to stderr and returns 2. It must not read the environment, open sockets or import database code. Subcommands (`serve`, `db migrate`, `db maintain`, `users …`, `bits rebuild`) are added by the milestone that implements each.
- `services/__init__.py` is empty, so the coverage source exists.

## Edge cases

- Coverage of an empty `services/` package is 100 % (0 statements); the gate must still be shown red with a planted module (REQ-005 (3)).
- `mypy --strict` needs the return type of `openapi_document()`; FastAPI's `openapi()` returns `dict[str, Any]`. Keep `Any` out of the public signature only if mypy allows it without casts; otherwise use `dict[str, Any]` and say so in the impl report.
- FastAPI versions before 0.99 emit OpenAPI 3.0; the pinned version must emit 3.1 (REQ-007 (2)).

## Not in this task

Routers, auth, middleware (headers, size and rate limits), health routes (#5), config loading, any database code.
