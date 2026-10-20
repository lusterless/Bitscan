# TASK-007 REVIEW: agent systemd units, verbatim from TS §3.7

Reviewer: reviewer. Date: 2026-10-20. REQ-016. Inputs: `work/reports/TASK-007-impl.md`, `work/reports/TASK-007-test.md`, `tests/m0/report.md` CHK-M0-120, -122 to -125.

Verdict: APPROVED

This is the reviewer approval, the first of the two that TS §8.2 L1268 requires (the change touches the agent and runner). TASK-007 is approved pending the user's second approval, which `main` collects. It is not complete until that second approval is recorded.

## What was checked

1. **Spec conformance.** Re-ran `python -I deploy/tests/check_units_verbatim.py agent` and `all`: exit 0, 5 and 9 units identical. Independent check: an awk pass over the whole TS extracted every ```` ```ini ```` block. The spec has exactly 9, at L289-302, 308-363, 369-408, 437-449, 451-482, 1352-1401, 1405-1435, 1439-1467 and 1469-1480. `cmp` against every unit file gives exactly one match per file, to the expected block. All five files are ASCII, end in a single LF, and have no CR and no trailing whitespace. REQ-016 (1) to (3) are met. (4) and (5) are NOT RUN locally (no systemd) and carried to TASK-010 CI.
2. **Security invariants (packaging-and-units.md).** All five files are byte-identical to the spec, so no directive is added, weakened, reworded or reordered. Spot-checked anyway:
   - runner: `CapabilityBoundingSet`/`AmbientCapabilities=CAP_DAC_READ_SEARCH` only, `ProtectHome=read-only`, `NoExecPaths=/` with `ExecPaths=... -/lib64`, `~@debug`, `IPAddressDeny=any`, `-`-prefixed `InaccessiblePaths`, `MemoryMax=256M`, `TasksMax=64`, `CPUQuota=25%`; no `ProtectControlGroups=` and no `PrivateNetwork=`.
   - capread.service: no `[Install]`, `UMask=` or `SystemCallErrorNumber=`.
   - No file has an end-of-line comment.
   - No listener, push path or host-settings change is added.
3. **Scope.** The task adds exactly the 5 listed files under `deploy/systemd/` (145 lines, all spec text). Nothing else under `deploy/` belongs to impl-deploy. The D-Bus policy is correctly deferred to M6.
4. **Tests.** I planted these cases in a temp copy outside the repo. Each made the script exit 1 with the right message:
   - widened runner capability set;
   - `IPAddressDeny` removed from capread;
   - `[Install]` appended to capread;
   - spec shifted by one line (fence assertion);
   - EOL comment mirrored into both the spec and the unit (`EOL-COMMENT` detector);
   - missing unit.

   The unmodified control exits 0. The tester's own nine plants (CHK-M0-120/122/123) agree.

## Findings

1. nit. `deploy/tests/check_units_verbatim.py:96`. The extra-file check runs only in `all` mode: in my test, `agent` mode with a stray `bitscan-runner.conf` exited 0. The docstring (L4-5) says "the set of files is exact" without that qualifier. Fix: say in the docstring that the exact-set check needs `all`, and run `all` in CI.
2. nit (carry to TASK-010, not this task). `work/plans/TASK-010.md` plans `systemd-analyze verify` but not this script. Without it in CI, a later unit edit could drift from the spec while still passing verify. Fix: have `units.yml` also run `python deploy/tests/check_units_verbatim.py all`. Owner: impl-deploy, with the lead's agreement.
