# TASK-022 TEST report: CI migration gate

Tester: tester. REQ-033. Date 2026-10-20. Impl report: `work/reports/TASK-022-impl.md` (revision 2). TP-M1-16. User merge decision: M1 lands as five stacked PRs, one migration each.

## Verdict: PASS (local). The live GitHub check is NOT RUN, because it needs pushed PRs.

## Commands and counts

- An independent scratch clone (`%TEMP%\tester2_t022\stack_test.sh`, gate extracted byte for byte from manager.yml): 25/25.
- 4 planted gate mutations, each caught.
- impl-deploy's tools, re-run: run.sh 29/29, stack.sh 10/10. Their extracted gate is identical to the tester's.
- actionlint v1.7.12 via `go run`, sumdb verified, from a scratch dir: no findings.
- Static greps: no `continue-on-error`, `|| true`, `if:` or `-m "not pg"`.

## Acceptance criteria → [tests/m1/report.md](../../tests/m1/report.md)

| REQ-033 | Check | Result |
| --- | --- | --- |
| (1) modify, delete or rename an existing migration fails | CHK-M1-251 | PASS |
| (2) two added fails; zero or one passes; each stacked PR passes | CHK-M1-251, CHK-M1-254 | PASS |
| (3) the pg job runs with CI=true and runs the M1 suites | CHK-M1-252 | PASS |
| (4) no continue-on-error, `\|\| true` or skip | CHK-M1-250, CHK-M1-255 | PASS |
| PR base and push behaviour | CHK-M1-253 | PASS |
| live on GitHub | CHK-M1-256 | NOT RUN (needs pushes) |

## Note

With squash merges, each next stacked PR must be rebased onto the new main before it is reviewed. Without the rebase the gate fails with 3 added, which is the correct behaviour.
