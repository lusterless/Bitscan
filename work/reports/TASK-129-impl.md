# TASK-129 IMPL: manager wheel bundles the built UI

REQ-137, REQ-140 (wheel half); #6 (install half), PD-28 (b); TS §8.7, §6.3, §2.1. impl-manager, 2026-10-26.

## What changed

`manager/pyproject.toml` only (+9 lines). New `[tool.hatch.build.targets.wheel]` section:

- `packages = ["bitscan_manager"]`: the wheel holds only the package. `manager/tests/` sits outside it, so no test file is packed. Migrations are `.py` files inside the package (`bitscan_manager/db/migrations/{env.py,__init__.py,versions/*.py}`), so every one is packed. There is no `alembic.ini` or `script.py.mako`: `db/__init__.py` builds the Alembic config in code.
- `artifacts = ["/bitscan_manager/webui/**"]`: Vite writes the UI into `bitscan_manager/webui/` (`web/vite.config.ts` `outDir`). Git ignores that folder (`.gitignore` L18) and hatchling skips VCS-ignored files by default, so it has to be listed as an artifact.
- `version = "0.1.0"` was already set. Nothing changed there.

No source, lock, OpenAPI or web change.

## Local checks (Windows, M3 venv; `hatchling build -t wheel` into a temp dir)

- Before the change (no UI build): 114 entries. All 7 migration files are there, no `tests/` path, no `webui/` path. Hatchling's default already skips the git-ignored UI.
- After the change, with a temporary dummy UI (`webui/index.html`, `webui/favicon.svg`, `webui/assets/index-abc.{js,css}`, deleted afterwards): `bitscan_manager-0.1.0-py3-none-any.whl`, 118 entries, all four UI files under `bitscan_manager/webui/`, migrations present, no `tests/` path.
- After the change, with no UI build: the wheel still builds (114 entries, no webui). This is the REQ-137 (5) development case.
- `ruff check manager`, `ruff format --check manager`: clean. `mypy --strict --config-file manager/pyproject.toml manager`: the only errors are the TASK-131 test-file errors listed in `TASK-131-impl.md`. None come from this task.

I did not run a real `npm run build`, a pip install into a fresh venv, `db migrate` or `serve`. Those are TP-M6-02 checks for the tester.

## For the tester (TP-M6-02, G47)

- Build: `npm ci --ignore-scripts && npm run build` in `web/`, then `pip wheel --no-deps --no-build-isolation -w <out> manager/`. The build environment needs `hatchling` and `editables` from `requirements-dev.txt`.
- The CHK-M6-320 plant removes the `artifacts` line: the wheel then has no `webui/` and `/` answers 404. For the CHK-M6-322 plant, change `packages` to include `tests` or drop the section (with the section dropped, the default still excludes `tests/`, which this run showed).
- Files changed outside the task list: none.
