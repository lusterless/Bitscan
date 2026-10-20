# TASK-002 IMPL report: manager package skeleton

REQs: REQ-003 to REQ-008. Spec: TS §6 (OpenAPI 3.1 generated from code), TS §2.3 (bearer token on every call), TS §6.3 (no CORS), TS §8.7 (`/usr/bin/bitscan-manager serve`). Plan: `work/plans/TASK-002.md`.

## Files

- `manager/bitscan_manager/__init__.py`: `__version__ = "0.1.0"`. This duplicates the static `project.version` in `pyproject.toml`; a dynamic version would make `uv pip compile` build the project to read its metadata.
- `manager/bitscan_manager/app.py`: `create_app() -> FastAPI` (title `Bitscan`, `version=__version__`, `openapi_url`, `docs_url`, `redoc_url` all `None`; no routers, middleware or CORS). `openapi_document() -> dict[str, Any]`: `Any` is kept because FastAPI's `openapi()` returns `dict[str, Any]` and mypy needs no cast. `write_openapi(path)` writes `json.dumps(indent=2, sort_keys=True, ensure_ascii=False) + "\n"` as UTF-8 with LF. `python -m bitscan_manager.app <path>` writes it, and any other argument count prints usage to stderr and exits 2.
- `manager/bitscan_manager/cli/__init__.py`: `main(argv: Sequence[str] | None = None) -> int`. Exactly `-h` or `--help` prints help (`usage: bitscan-manager [-h]`) to stdout and returns 0. Any other input, including none, `serve` or `db migrate`, prints the usage line plus `bitscan-manager: error: no command is implemented yet` to stderr and returns 2. It returns instead of raising `SystemExit`, so `main([...])` can be unit-tested directly. It reads no environment variable, opens no socket and imports nothing beyond `argparse` and `sys`.
- `manager/bitscan_manager/services/__init__.py`: empty (coverage source).
- `manager/openapi.json`: generated. It contains `{"info": {"title": "Bitscan", "version": "0.1.0"}, "openapi": "3.1.0", "paths": {}}`, pretty-printed, LF, with a trailing newline.

Also touched (TASK-001 files, revision 1): `editables` added to the dev extra in `manager/pyproject.toml` and `manager/requirements-dev.txt` regenerated. See `work/reports/TASK-001-impl.md`.

## Install and export commands

```
python -m venv <venv> && <venv>/Scripts/python.exe -m pip install --require-hashes -r manager/requirements-dev.txt
<venv>/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e manager
<venv>/Scripts/python.exe -m bitscan_manager.app manager/openapi.json      # from the repo root
```

## Checks run (Windows, `manager/.venv`, dev lock + editable install)

| Check | Result |
| --- | --- |
| `ruff check manager/bitscan_manager`, `ruff format --check manager/bitscan_manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` (root) | pass, 6 source files (including the tester's tests) |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | coverage gate reached (100 %, 0 statements, no files listed). The run still exits 1 because of the tester's 7 lock-parser failures from TASK-001 (the `--only-binary` line) |
| Temp copy with a planted 24-statement `services/planted.py` and one trivial test | exit 1, "Required test coverage of 85% not reached. Total coverage: 0.00%" |
| TestClient on `create_app()`: `GET /docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`, `/api/v1/agent/enroll` | all 404 |
| `OPTIONS /api/v1/x` with `Origin: https://evil.example`, `Access-Control-Request-Method: GET` | 404, no `Access-Control-Allow-*` header |
| `app.routes` / any `APIRoute` / two `create_app()` calls distinct | `[]` / False / True |
| Export twice | byte-identical SHA-256; `openapi` = `3.1.0`; `paths` = `{}`; `file` reports no CRLF |
| `bitscan-manager --help`, `-h` | exit 0 |
| `bitscan-manager serve`, `db migrate`, no args | exit 2, message on stderr |
| No `BITSCAN_*` variables set during the above | 0 set |
| Fresh `python -m venv`, pip install of the dev lock, then `pip install --no-deps --no-build-isolation -e manager`, `bitscan-manager --help` | all exit 0 |

## For the tester

- `fastapi.testclient` emits `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead`. If you run pytest with warnings as errors, filter it or ask me to add `httpx2` to the dev lock.
- To check that `serve` does nothing, call `main(["serve"])`: it returns 2 with no side effects. The console script turns that into exit code 2.
- G6 planted change: in a throwaway worktree, change `title=` in `create_app()` (or add a route) without touching `manager/openapi.json`. Then run the gate (export to `manager/openapi.json`, then `git diff --exit-code -- manager/openapi.json`); it exits non-zero because the export no longer matches the committed file.
