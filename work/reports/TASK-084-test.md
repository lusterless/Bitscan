# TASK-084 TEST: services.inventory import-cycle fix

**Verdict: PASS** (2026-10-24, tester-h). TP-M3-38, CHK-M3-319; REQ-062, REQ-074. Code under test: `bm/api/agent/__init__.py` (`work/reports/TASK-084-impl.md`).
- **Commands (W, `CI=true`, `-n auto`):** 21 targeted files, 1564/1565 passed. The 1 failure was my harness test; fixed and 4/4 on re-run. test_module_imports.py 97/97.
- **Plant:** module-level `ingest` import restored. RED, 93/97 passed, 4 failed: exactly `services.inventory`, `.decode`, `.ingest` and `.upload`.
- **L:** ruff, format and mypy clean.
- **Acceptance:**
  - every module imports on its own in a fresh `python -I`: CHK-M3-319 PASS;
  - behaviour unchanged: the agent, inventory and contract suites are green;
  - `openapi.json` byte-identical: test_openapi green in h084.
