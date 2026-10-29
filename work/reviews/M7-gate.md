# M7 closing review (gate)

Verdict: APPROVED. TASK-146 is the user's named gate exception (finding 1). No blocking or should-fix finding is open.

Reviewer: reviewer-m7, 2026-10-28, final 2026-10-29. Gate: `work/tasks.md` "### M7 gate" and the mutation table CHK-M7-320 to -371. Report: `work/reports/M7-gate-test.md` (tester-m7), PASS, including the "r1 re-run" section.

## What I checked
1. **Every gate row against the gate table** (first run). G1–G6, G12–G16, G18, G34 and G54–G61 are each run on the final tree, and each names the plant that turns it red. No gate was lowered:
   - **G5:** 95.34 % clean against 85 %, with `services/importer` included and every importer module at 91 % or more. The G5 plant, a never-called 602-statement function in `folders.py`, takes it to 84.84 % (5,447 statements, 826 missed): coverage failure, exit 1, red. The arithmetic checks out.
   - **G18:** Run 2 (the planted copy, all fixes in) is 8,866 passed, 0 failed, 0 errors, 0 skipped.
   - **G54:** the timing bound stays 100 ms. The timing moved into a clean `python -I` subprocess (lead ruling (b)), and a quadratic-lexer plant is red under it. The change is to how the time is measured, not to the bound.
   - **The three G18 test fixes** are test-only and justified. No product defect was found.
2. **The r1 re-run** (after the exception, on the restored tree). It totals 2,447/2,447 with 0 skipped (150 + 50 + 1,160 + 173 + 687 + 227):
   - CHK-M7-191 with all six BIT102 fixtures, the `R2_PENDING` exclusion dropped: 150/150;
   - G59: 50/50 on r1;
   - `test_bit102.py` 1,160/1,160, `test_bit102_lexer.py` 173/173, `test_bit_validate.py` 687/687, `test_bit_fixtures.py` 227/227;
   - whole-tree gates clean (310 files), and nothing imports the removed modules.
3. **My own runs (Windows).**
   - On the first tree: `ruff check`, `ruff format --check` and `mypy --strict --config-file manager/pyproject.toml` clean, and the OpenAPI export byte-identical (G6).
   - On the restored r1 tree, again: ruff clean, 310 files formatted, mypy clean on 310 source files, and the OpenAPI export byte-identical.
4. **Tree state** (checked without opening the BIT102 files).
   - `services/importer/bit102.py` is byte-identical to `c6b7e13` (r1).
   - `bit102_wrappers.py` and `bit102_braces.py` are gone from the tree.
   - r2 is saved in `C:\Users\kaiquan.koh\Documents\m7-deferred\task146-r2\`.
5. **Mutation table.** Every row from 320 to 371 is red, either in its per-task report or run here (355, 360, 364, 367).
   - 327–331 are red on r1, the rules now in the tree.
   - 367's subfolder half is green by construction: inotify doesn't report entries in subfolders of a non-recursive watch.
6. **New gate files.**
   - `test_catalog_alerts_pg.py` (G60) raises all six M7 alert kinds through their real paths.
   - `test_readme_m7_walk_linux.py` runs CHK-M7-305, the README live walk, against a real `serve`.
7. **Per-task state.** Every M7 task from TASK-139 to TASK-175 has a review in `work/reviews/` with verdict APPROVED and no open blocking or should-fix finding, except TASK-146, the exception.
   - **TASK-174 and TASK-175:** my condition, a G59 re-run on the final BIT102, is met (50/50 on r1).

## Findings

1. **TASK-146, the user's named gate exception** (decisions 2026-10-29, "TASK-146 r2 deferred to a later milestone" and "TASK-146 deferred to a later milestone as a named M7 gate exception").
   - **What ships:** BIT102 r1 (`bit102.py` at `c6b7e13`). It is TEST PASS (1,160/1,160, plants CHK-M7-327 to -332 red), it runs on every import (CHK-M7-191 with all six fixtures, 150/150), and both samples pass it. BIT102 exists, as the security invariants and SR §4.2 require.
   - **What M7 gives up:**
     - **No code review of the BIT102 rule set,** and no TS §8.2 second approval for TASK-146. The rule is checked only by its tests.
     - **The r2 gap closures** of the user's 2026-10-27 "BIT102 gaps closed" decision, which is deferred, not dropped. They are the extra wrappers, the `su`/`runuser`/`flock -c` command strings, `trap`, brace expansion in `bash -c`, getopt abbreviations, and the `time -o` and flock output targets.
   - **Why the risk is acceptable now:** BIT102 is a safety net, and the runner sandbox is the real control (SR §4.2 L287; TS §3.7). No plugin `Execute` runs on any host before M10, so no write-like command that r1 misses can run in the meantime.
   - **Carried, as a condition on M10:** TASK-146 must be reviewed (r1 and r2) and given its second approval, and r2 must be tested (its own rows, CHK-M7-191's r2 fixtures, a G59 re-run), all in a fresh session. This has to be APPROVED before any milestone lets a plugin run on a host.
2. **Closed (should-fix, gate report):** the "G5 plant" section and the G18 Run 2 counts.
3. **Closed (nit, G4 row):** the reason for the dry run.

## NOT RUN rows (accepted as named)
- **TASK-146 review, second approval and r2:** the user's gate exception (finding 1).
- **The TS §8.3 Sandbox half:** no runner until M10.
- **The VM end-to-end import:** M11 nightly.
- **Load tests:** deferred by the user.
- **VM plants CHK-M6-340..345:** waived by the user (decisions 2026-10-28 "Speed-up" (5)).
