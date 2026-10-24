# TASK-084 REVIEW: services.inventory import-cycle fix

Verdict: APPROVED

Reviewer: reviewer (fresh instance), 2026-10-24. One round (normal review; not a two-approval task: no agent-route behaviour changes).

Scope reviewed: `manager/bitscan_manager/api/agent/__init__.py` (the file in `work/reports/TASK-084-impl.md`; already in commit `8587388`, not in the working-tree diff), with `manager/tests/test_module_imports.py` (tester). TEST PASS: `work/reports/TASK-084-test.md`, CHK-M3-319 and CHK-M3-319-mut in `tests/m3/report.md`.

## Checks
1. Spec and ruling: matches the lead ruling of 2026-10-23 (decisions.md, "Import cycle fixed in M3"). The cycle is broken at its smallest point: the two threshold constants are imported inside `build_agent_windows()`, which only `create_app()` calls (`app.py:296`). The contract models stay in `api/agent/schemas.py`. Threshold values are unchanged: `FLOOD_PER_10_MIN` and `NEW_PACKAGES_PER_DAY`, read from the same modules. The remaining module-level imports (`runtime`, `services.audit.thresholds`) do not import back into `api.agent`.
2. Security invariants: nothing touched. No route, token, logging or SQL change. `openapi.json` is byte-identical (tester, test_openapi green).
3. Scope: 1 source file, about 5 lines. No refactor. The comment at the deferred import gives the reason, not a restatement.
4. Tests: `test_module_imports.py` imports every module first in a fresh `python -I` with the tree under test put first, and checks that `sys.modules[name].__file__` comes from that tree, so an installed copy cannot mask a failure. The walk asserts at least 90 modules and names the four modules from the cycle. The plant (the module-level import restored) turns exactly those 4 red. So the test can fail.
5. Re-run by the reviewer (Windows; lint evidence only, per speed rule 2):
   - `ruff check`: clean.
   - `ruff format --check`: 215 files formatted.
   - `mypy --strict`: no issues in 215 files.
   - `test_module_imports.py` on Windows, not evidence: 96/97. `services.audit.shipper` failed in the serial run. On its own it imports in 1.5 s (`python -I`), so the failure looks like the 120 s subprocess timeout hit on a loaded Windows box (the whole run took 9.6 min). The Linux evidence run is 97/97.

## Findings
1. nit, `manager/tests/test_module_imports.py:55`. The per-module `timeout=120` can trip on a slow or loaded Windows machine (seen once above), and the failure message then shows a `TimeoutExpired` instead of an import error. Optional (tester's area): catch `subprocess.TimeoutExpired` and fail with a message that names the timeout. Does not block: the evidence run is Linux.
