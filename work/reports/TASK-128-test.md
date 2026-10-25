# TASK-128 TEST: README user guide for M5

Verdict: **PASS**. Test: manager/tests/test_readme_m5_walk_linux.py, new. It walks the README's "Web UI", "Package search", "API" (trailing slash) and "Enrolling agents" statements against a real serve that serves the real `npm run build` output, with expected answers taken from README.md. Command (W, CI=true): `pytest -q tests/test_readme_m5_walk_linux.py`. Results: 1/1 passed, 103 rows, 0 deviations (after one test-bug fix). Four plants are red: three README misstatements and one product change. The browser steps themselves (forms and buttons) are covered by the Vitest suites and by the user's walk-through, CHK-M5-305.

Observation for the lead (not a TASK-128 finding; this line is unchanged since M3, and the M4 README has the same text): README line 3 still says "Debian 12 (amd64 and arm64, cgroup v2)". The user's decisions of 2026-10-24 dropped arm64 and Debian 12 from v1.

## Revision 1: PASS
Only README L3 changed (Ubuntu 22.04 and 24.04, amd64). README walk 1/1 (103 rows, 0 deviations). This resolves the observation from round 1.
