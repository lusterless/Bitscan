# TASK-058 TEST report: dev-only test libraries (PD-21)

**Verdict: PASS** (2026-10-23, tester). REQ-061 and REQ-074 (tooling). Plan checks: CHK-M3-001 to -005. Code tested: `manager/pyproject.toml` and `manager/requirements-dev.txt` (`work/reports/TASK-058-impl.md`).

## Tests changed
- `manager/tests/test_lock_files.py`: `jsonschema` and `hypothesis` added to `TOOLS`, so the runtime lock may never contain them and the dev lock must (17 passed).

## Evidence
- Fresh-venv `--require-hashes` install of the dev lock: exit 0 on Windows (3.12.10) and on WSL x86_64 (3.12.3). Both packages import (4.26.0, 6.170.2).
- `manager/requirements.txt`: byte-identical (`b9090727…bbd6`). Only the seven expected dev pins were added.
- Both locks are reproduced byte for byte by their header commands with the unchanged cutoff.
- Linux x86_64 and aarch64 dry-runs: exit 0, 65 packages.
- Plants: hypothesis appended to a runtime lock copy → the lock test is red. All hypothesis hashes altered → the install fails with the hash error.

## Acceptance criteria
- "`pip install --require-hashes -r manager/requirements-dev.txt` exits 0 in fresh Windows and Linux venvs": CHK-M3-001 PASS.
- "both packages import": CHK-M3-001 PASS.
- "`manager/requirements.txt` is byte-identical to before": CHK-M3-003 PASS.
- "the recorded lock command reproduces the dev lock byte for byte": CHK-M3-004 PASS.

## Finding (gate definition, not a code defect)
- The work/tasks.md G4 plant "one altered `hypothesis` hash in the dev lock" stays green. hypothesis has 78 wheels in the lock, and pip falls back to another allowed wheel when the selected one's hash is wrong; this happens even when the altered hash is the one pip would pick. CHK-M3-002 therefore uses "all hypothesis hashes altered", which is red. Rewording the gate plant is for main or the planner.
