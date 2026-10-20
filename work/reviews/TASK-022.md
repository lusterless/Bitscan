# TASK-022 REVIEW: CI gate, migrations forward-only and one per PR

Reviewer: reviewer. Date: 2026-10-20. REQ-033. Spec: `.claude/rules/testing.md` "Static gates" ("Migrations are forward-only, one per PR"), TS §5.3 L1046; decisions PD-18 and 2026-10-20 (five stacked PRs, one migration each, no bypass). File: `.github/workflows/manager.yml` (+71 lines, none removed). Inputs: `work/reports/TASK-022-impl.md` (revision 2), `work/reports/TASK-022-test.md` (PASS locally), `tests/m1/report.md` CHK-M1-250 to -256.

Verdict: APPROVED

CHK-M1-256, the live GitHub check, is a known NOT RUN: it needs pushed PRs. It is to be confirmed when the M1 stack is opened, including whether GitHub sends `edited` on its automatic retarget.

## What was checked

- **Shell safety (`manager.yml:31-85`):**
  - GitHub context reaches the script only through `env:`; the `run:` text has no `${{ }}`;
  - every SHA must be 40 lowercase hex, not all zeros, and a fetched commit, before it is used;
  - the event name is printed with `%q`;
  - file names are read NUL-separated (`-z`, `read -r -d ''`) and printed with `%q`, so a name containing a newline, `::error::`, `$(…)` or a leading `-n` is never executed or turned into a workflow command (the injection-marker cases in CHK-M1-253);
  - `set -euo pipefail`, and the diff goes to a file rather than through process substitution, so a failing `git diff` fails the step.
- **Base and diff:**
  - `pull_request` uses `base.sha...head.sha` with three dots, so a moved base does not count its own new migrations;
  - `base.sha` is the PR's own base branch, so each stacked PR is diffed only against its parent (CHK-M1-254: PR1 to PR5 pass; all five in one PR fails; a retarget without a rebase fails);
  - `push` uses `before...after` with an ancestor check (`:52`), so a force-push to main fails;
  - any other event fails;
  - `fetch-depth: 0` makes every base present.
- **Classification (`:58-76`):**
  - `--find-renames`; `R*`/`C*` fail with both names read;
  - every non-`A` status (M, D, T) fails, including a modified `__init__.py`;
  - `A` of `versions/__init__.py` is allowed once; every other added path counts, which is the stricter reading;
  - more than one added fails (`:78`).

  Together these meet REQ-033 (1) and (2).
- **Stacked-PR retarget (my pre-review should-fix, fixed):** `pull_request.types` now includes `edited` (`:7`), so a base change re-runs the gate instead of leaving a green check computed against the old base.
- **No skip paths:** no job or step `if:`, no `continue-on-error`, no `|| true` (REQ-033 (4), CHK-M1-250). Permissions stay `contents: read`, and `persist-credentials: false` is set.
- **Pinning:** `actions/checkout@3d3c42e5…` (v7.0.1), the same full SHA already used in every workflow.
- **REQ-033 (3):** the `gates` job pytest runs with `CI: "true"` (`:122`) and no marker deselection, so the pg suites run and a missing Docker fails the job.
- **Tests:**
  - an independent clone gives 25/25, and the 4 planted gate mutations are each caught;
  - impl-deploy's suites re-run 29/29 and 10/10;
  - actionlint v1.7.12, verified through the Go checksum database, is clean.
- **Scope:** one file, within the 40-line estimate plus comments, and the owner is impl-deploy.

## Findings

1. **nit.** `edited` also re-runs the whole workflow on title or body edits. That accepts some CI cost to avoid an `if:`, which is correct under REQ-033 (4). No change.
2. **process note for `main`, no code change.** The repository must make the `migrations` job a required status check on `main` in branch protection. Otherwise a red gate does not block a merge. With squash merges, rebase each stacked PR onto the new `main` before merging it, or the gate correctly fails.
