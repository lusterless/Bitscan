# TASK-262 TEST: PASS (manager version 0.2.0)

Tester: tester-rel2, 2026-11-11, round 1. **Recorded by the lead from tester-rel2's reply.** A rule refused the subagent's report write, and the user approved the lead recording it (decisions 2026-11-11).

The rows are CHK-R020-001 to -013, -016, -017 and plants -080 to -086, in [tests/release/report.md](../../tests/release/report.md).

- Version `0.2.0` in `manager/pyproject.toml`, `__init__.py` and `openapi.json`. The openapi diff against `d26c472` is only `info.version`, and two exports are byte-identical (`bd2b2b59…`).
- `test_openapi.py` 6/6 and `test_project_config.py` 10/10 after the PD-51 re-pins (L75, L42). `test_manager_wheel.sh` (re-pinned L32) OK 60/60.
- The `release.yml` versions step passes for 0.2.0 / v0.2.0 and refuses 0.2.1, `~pre3`, v0.2.1, v0.2.0-rc1 and an injection. All plants are red.
- Note: the versions step doesn't read `__init__.py`. That pairing is covered only by `test_openapi` (plant -084).
- BIT102 is r1 (`279291cf…`), with no r2 files.
