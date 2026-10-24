# TASK-049 TEST report: body caps by path template, and the after-auth mode

**Verdict: PASS** (2026-10-23, tester). REQ-066, with REQ-037 (5) still holding. Plan checks: CHK-M3-030 to -035 in `tests/m3/test-plan.md`, written before the code was read. Code tested: the `manager/bitscan_manager/app.py` diff described in `work/reports/TASK-049-impl.md`.

## Tests added
- `manager/tests/test_body_caps.py`: 38 tests. Test routes sit at the real agent templates (inventory, results, heartbeat) behind a stand-in token dependency, on concrete random-UUID paths. A raw ASGI `receive` counts the bytes pulled.

## Commands (L, Windows + Git Bash, `manager/.venv`)
- `PY -m pytest tests/test_body_caps.py`: 38 passed.
- `ruff check manager`, `ruff format --check manager`, `mypy --strict --config-file manager/pyproject.toml manager`: clean (127 files).
- Full `PY -m pytest`: 1136 passed, 451 skipped. The skips are the PostgreSQL and Linux-only tests (Docker unavailable on L). TASK-049 has no PostgreSQL part, so no W run was needed.
- OpenAPI export: byte-identical; `tests/test_openapi.py` 6 passed.
- Mutation plants, each in a throwaway copy (`$TEMP/m3-mut-049`, imports checked to come from the copy). The control copy was green (91 passed). Each of the 8 plants turned the suite red:
  - CHK-M3-360: exact-path lookup instead of the template;
  - CHK-M3-361: after-auth branch disabled;
  - `CappedReceive` never refuses;
  - `CappedReceive` refuses one byte late;
  - duplicate template accepted;
  - limit allowed above the class maximum;
  - unanchored match;
  - declared `Content-Length` not passed to the route.

## Acceptance criteria
- TASK-049 acceptance:
  - "a body one byte over the template's cap on a concrete path gets 413 in normal mode": CHK-M3-030.
  - "or in after-auth mode reaches the route through a reader that refuses past cap + 1 bytes (with `Content-Length` and chunked)": CHK-M3-031, CHK-M3-032.
  - "other paths keep 1 MiB": CHK-M3-030 (heartbeat), CHK-M3-034, CHK-M3-035.
  - "a duplicate template or a cap over its class raises at app creation": CHK-M3-033.
- REQ-066 (1), (2), (5), (6) at the middleware level: PASS.
- REQ-066 (3), (4): the real token check, the audit entry and decompression are TASK-063, TASK-073 and TASK-074. They are re-checked there (CHK-M3-168, -250, -258, -261).

## Notes for later tasks (not defects)
- Agreed with the impl report: a path ending in a newline (`%0A`) is matched by the Starlette router but not by the RE2 cap pattern, so it gets the 1 MiB default and no `BodyCap`. CHK-M3-035 shows that nothing over 1 MiB is read. TASK-063's `read_capped` must fail closed when `BodyCap` is missing; I will test that in TASK-063 TEST (CHK-M3-168).
- Caps are matched per path, not per method. That is fine while each template carries one method.
