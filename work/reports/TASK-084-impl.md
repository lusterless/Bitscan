# TASK-084 IMPL: break the services.inventory import cycle

This task follows the lead's ruling of 2026-10-23 in `work/decisions.md` (found by tester-g). There is no behaviour change and no `openapi.json` change.

## The defect

`python -I -c "import bitscan_manager.services.inventory"` raised `ImportError: cannot import name 'DecodedInventory' from partially initialized module ...decode`. The same failure hit `services.inventory.decode`, `.ingest` and `.upload` when each was the first import.

The cycle:
1. `services/inventory/decode.py` imports `api.agent.schemas`.
2. That runs `api/agent/__init__.py` first, which imported `services.inventory.ingest.NEW_PACKAGES_PER_DAY` and `services.jobs.pull.FLOOD_PER_10_MIN` at module level.
3. `ingest.py` imports `decode.DecodedInventory` while `decode` is still half-initialised.

The app and the test suite never hit it, because `api.agent` was always imported first.

## The fix (smallest point)

`api/agent/__init__.py` no longer imports any service module at package import time. The two threshold constants are now imported inside `build_agent_windows()`. That function runs only in `create_app()`, after every module has loaded. Everything else stays where it was:
- the constants are unchanged and live in the same modules;
- the contract models stay in `api/agent/schemas.py`;
- `AgentWindows` and its thresholds are unchanged.

A comment at the import says why it is deferred.

I chose this over moving the constants to a new module. It changes one file, keeps the existing imports working (`services.jobs.FLOOD_PER_10_MIN`, and the tests importing `ingest.NEW_PACKAGES_PER_DAY`), and adds no new module. No other module-level import in `api/agent/__init__.py` reaches a service that imports back into `api.agent`: `services.audit.thresholds` imports only `runtime`.

## Files

- `manager/bitscan_manager/api/agent/__init__.py`. This is a shared module: every agent route imports this package. List it as shared.

## How to check

```sh
# every bitscan_manager module (96, excluding Alembic env/versions), each in a fresh interpreter
cd manager && for m in $(.venv/Scripts/python -c "import pkgutil,bitscan_manager as b;print(' '.join(x.name for x in pkgutil.walk_packages(b.__path__,'bitscan_manager.') if '.db.migrations.versions.' not in x.name and not x.name.endswith('.env')))"); do .venv/Scripts/python -I -c "import $m" || echo "FAIL $m"; done
```

- **Before the fix:** 4 of 96 modules failed (`services.inventory`, `.decode`, `.ingest`, `.upload`).
- **After the fix:** 0 of 96 fail.
- I excluded `db/migrations/env.py` and `versions/*` from the walk: Alembic runs them only inside its own context.
- **Gates (Windows):** ruff, format and `mypy --strict` are green. `openapi.json` was re-exported and is byte-identical.
- **Full pytest:** 2321 passed, 0 failed, 1494 skipped (no Docker on Windows, so the PostgreSQL tests skip).

## Notes for the tester

- The fresh-interpreter test for every module should use `-I` (as above), so the current directory and user site do not affect the result.
- The window thresholds are unchanged: 20 per 10 minutes for result-409 floods, and 1,000 new packages per day.
