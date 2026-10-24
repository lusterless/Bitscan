# TASK-058 REVIEW: dev-only test libraries for the contract and fuzz suites

Reviewer: reviewer. Date: 2026-10-23. REQ-061, REQ-074. Decision: PD-21 (a) (`jsonschema` and `hypothesis` in the dev lock only; user, 2026-10-23). Lock command: decisions 2026-10-20 (TASK-001 revision 2), recorded in the lock header. Inputs:
- `work/reports/TASK-058-impl.md`;
- tester's TEST PASS (message 2026-10-23; CHK-M3-001 to -005, rows to be written to `tests/m3/report.md` by `main`).

Files reviewed:
- `manager/pyproject.toml` (4 lines in the `dev` extra);
- `manager/requirements-dev.txt` (regenerated; 237 lines added, none removed).

Verdict: APPROVED

Not on the TS §8.2 two-approval list.

## What was checked

- **Decision conformance.** Both packages are in the `dev` extra only, as PD-21 (a) says.
  - `manager/requirements.txt` is byte-identical to HEAD (`git diff` is empty), so the runtime lock gains nothing (CHK-M3-003).
  - The dev-lock diff only adds lines: seven new pins (`attrs`, `hypothesis`, `jsonschema`, `jsonschema-specifications`, `referencing`, `rpds-py`, `sortedcontainers`), each with hashes.
  - The header still records the exact `uv pip compile` command with the unchanged `--exclude-newer 2026-10-19T16:56:37Z` cutoff, so no reviewed dependency update was needed.
- **Security invariants.** Hash-pinned (`--generate-hashes`) and wheels only (`--only-binary :all:`), as for the M0 locks. No runtime code or configuration changed.
- **Scope.** Two files, as the task row lists.
- **Tests.** The tester's evidence covers:
  - a fresh install on Linux and Windows with `--require-hashes`;
  - an altered `hypothesis` hash refused (the G4 plant);
  - byte-for-byte reproduction of the lock from its header command;
  - wheel hashes for cp312 manylinux x86_64 and aarch64.

  I did not regenerate the lock myself, since that writes a file. `tests/test_lock_files.py` passes in my run (Windows).

## Findings

None.
