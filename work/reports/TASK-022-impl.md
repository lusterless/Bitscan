# TASK-022 IMPL report (impl-deploy)

Task: CI gate, migrations forward-only and one per PR (REQ-033; testing.md "Static gates"; TS §5.3).
Status: IMPL done, ready for TEST (TP-M1-16). Nothing committed or pushed.

## What changed

One file: `.github/workflows/manager.yml` (+71 lines, none removed). The existing `gates` job is unchanged.

- **Revision 2 (stacked PRs, decisions.md 2026-10-20):** the `pull_request` trigger now lists `types: [opened, synchronize, reopened, edited]`.
  - **Why:** the default types do not include `edited`, which is the event GitHub sends when a PR's base branch changes. Without it, a stacked child PR retargeted after its parent merges would keep its old green check, computed against the old base, on the same head SHA. If the parent was squash-merged, that stale check would allow a merge that now adds two migrations.
  - **Review:** the reviewer's pre-review raised the same should-fix independently.
  - **Side effect:** the whole workflow, `gates` included, also re-runs on title or body edits. This costs CI time and nothing else. Re-running on base changes only would need an `if:`, which REQ-033 (4) forbids.

New job `migrations` (runs first in the file, independent of `gates`):

- `actions/checkout` pinned at the same full SHA as M0 (`3d3c42e5…` v7.0.1), `persist-credentials: false`, `fetch-depth: 0` (full history, so the PR base, the PR head and the push `before` commit are all present).
- One step, "Migrations are forward-only, at most one added". No job or step `if:`, no `continue-on-error`, no `|| true`. Workflow permissions stay `contents: read`.
- GitHub context values reach the script only through `env:` (`EVENT_NAME`, `PR_BASE_SHA`, `PR_HEAD_SHA`, `PUSH_BEFORE`, `PUSH_AFTER`). The `run:` text contains no `${{ }}`.

Script logic:

1. Picks the range by event. `pull_request` uses `base.sha...head.sha` (three dots, so the diff starts at the merge base and later commits on the base branch are not counted). `github.event.pull_request.base.sha` is the tip of **that PR's own base branch**, whatever it is. In the M1 stack, PR 1 is diffed against the M0 PR #1 branch, PR 2 against PR 1's branch, and so on, never against `main` unless `main` is the PR's base. `fetch-depth: 0` fetches every branch, so a stacked base branch's commit is present. `push` (to main) uses `before...after`, and fails unless `before` is an ancestor of `after` (a history rewrite on main fails). Any other event fails.
2. Each SHA must be 40 lowercase hex characters, not all zeros, and a fetched commit. Otherwise the step fails with "cannot diff".
3. Runs `git diff --name-status -z --find-renames "$base...$head" -- manager/bitscan_manager/db/migrations/versions/` into a file under `$RUNNER_TEMP`. Writing to a file instead of process substitution means a failing `git diff` fails the step under `set -e`.
4. Reads NUL-separated records with `read -r -d ''`, so names are never word-split or globbed. Names are printed with `printf %q`, so a name with a newline or `::` cannot start a GitHub workflow-command line.
   - `A` of `versions/__init__.py`: allowed. This is the one-time creation, and an `A` can only happen while the file is absent on the base.
   - `A` of any other path: counted as an added migration file. Every added file except `__init__.py` counts, not only `m*.py`, which is the stricter reading.
   - `R*` or `C*` (both names read): fails as rename or copy.
   - Anything else (`M`, `D`, `T`, …), including a modified `__init__.py`: fails as a changed existing migration.
5. Fails if more than one migration file was added. Otherwise it prints `migrations ok: N added, none changed`.

Because the diff is limited to the path first, a rename from outside into `versions/` shows as `A` and counts as one added migration. A rename out of `versions/` shows as `D` and fails.

Requirement (3): the existing `gates` job still runs `pytest --cov=bitscan_manager/services --cov-fail-under=85` from `manager/` with `CI: "true"`. `testpaths = ["tests"]` with no marker deselection means every M1 suite in `manager/tests/` (the `pg` ones included) is collected. A missing Docker makes the run exit non-zero through the conftest hook. No change was needed there.

## Design choice for the lead

- **Push events:** the task says "pull-request gate", and REQ-033 (4) forbids a skip condition. A PR-only job would need `if: github.event_name == 'pull_request'`, which is a skip. So the same rule also runs on push to main, against `before...after`, with an ancestry check.
- **Effect:** each merge to main must also add at most one migration and change none, and a force-push to main fails.
- **If you prefer PR-only:** the alternative is a job-level `if:` for PRs only. That needs your ruling against REQ-033 (4).

## Verification (local, Git Bash on Windows)

- **actionlint:** NOT RUN, because it is not installed. I did not download it without approval. If the lead approves, run `go run github.com/rhysd/actionlint/cmd/actionlint@<pinned version>` from the repo root, or let CI or the tester run it.
- **YAML parse:** the YAML was parsed with the repo's own `web/node_modules/js-yaml`:
  - jobs are `migrations,gates`;
  - the `migrations` job and its steps have no `if` and no `continue-on-error`;
  - the `run` text has no `${{` and no `|| true`;
  - `gates` pytest `env.CI` is `true`.
- **Forbidden constructs:** `grep -nE "continue-on-error|\|\| *true|^\s+if:" .github/workflows/manager.yml` finds nothing.
- **Script syntax:** the script was taken byte for byte from the YAML block (dedented) by `extract.py`, and `bash -n` passes.

### Planted cases

Planted cases ran in a throwaway clone, never in the working repo. `git clone --no-local` was made into `%TEMP%\t022\repo` with clone-local `core.protectNTFS false` so hostile names can be committed through the index.

Base for the PR cases is `m1-db-audit-core` (`ae6a6b4`), which has `__init__.py`, `m0001` and `m0002`. Result: **29/29 as expected**, and the `$(touch …PWNED)` marker was never created.

| Case | Expected | Result |
| --- | --- | --- |
| zero migrations (README edit) | pass | 0 added |
| one added | pass | 1 added |
| two added, one commit; two added, two commits | fail | "more than one migration added (2)" |
| modify `m0001`; modify `m0001` plus add one | fail | `(M)` |
| delete `m0001` | fail | `(D)` |
| rename `m0001` (R100), rename plus edit (R099) | fail | "renamed or copied" |
| rename `m0001` out of `versions/` | fail | `(D)` |
| rename a non-migration file into `versions/` | pass | 1 added |
| modify `__init__.py` | fail | `(M)` |
| modify then revert `m0001` (net no change) | pass | 0 added |
| type change `m0001` to a symlink | fail | `(T)` |
| one added with a name containing a newline, `::error::`, `$(…)`, backticks, `*` | pass | names never executed |
| two added, hostile names (incl. a leading `-n`) | fail | names printed `%q`-escaped on one line |
| rename `m0002` to a hostile name with a newline | fail | escaped |
| stale PR: base later added `m0003`, PR adds `m0004` | pass | 1 added (three-dot) |
| first PR to `main`: creates `__init__.py` plus `m0001` | pass | 1 added |
| current committed M1 branch vs `main` | fail | 2 added (`m0001`, `m0002`) |
| push: one added; two added; modify | pass; fail; fail | as expected |
| push: `before` not an ancestor (force-push) | fail | "rewrote history" |
| push: `before` all zeros; unknown SHA; non-hex text; empty base | fail | "cannot diff" |
| event `workflow_dispatch` | fail | "unexpected event" |

### Stacked-PR cases (revision 2)

These ran in the same clone, with `s0` standing in for the M0 PR #1 head (no `versions/`) and `s1` to `s5` each adding one migration in two commits on top of the previous one. PR 1 also creates `__init__.py`. Result: **10/10 as expected**.

| Case | Expected | Result |
| --- | --- | --- |
| PR k (`s1` to `s5`), each diffed against its own base (`s0`, `s1`, …, `s4`) | pass, all 5 | 1 added each |
| `s3` diffed against `s0` (wrong base) | fail | 3 added |
| `s5` diffed against `s0` (the whole stack as one PR) | fail | 5 added |
| PR 2 retargeted to a `main` that merged PR 1 with a merge commit | pass | 1 added |
| PR 2 retargeted to a `main` that squash-merged PR 1, not rebased | fail | 2 added (the `edited` trigger makes this run) |
| PR 2 rebased onto the squashed `main` | pass | 1 added |

Notes for the lead on the stack:

- With merge commits, a retargeted child still passes without a rebase.
- With squash merges, each child must be rebased onto the new `main` before it can pass.
- Branch protection "require branches to be up to date before merging" would force the same rebase and re-run. That is a repository setting, outside this task.
- **Live check:** that GitHub sends `edited` for its automatic retarget, when the parent branch is deleted on merge, is documented GitHub behaviour but was not observed live. The tester or lead should confirm it on the first real retarget, or retarget by hand.

How to rerun:

```bash
bash /tmp/t022/tools/plant.sh   # recreates the clone and branches
cd /tmp/t022/tools && python extract.py /c/Users/kaiquan.koh/Documents/Bitscan/.github/workflows/manager.yml > gate.sh
bash /tmp/t022/tools/run.sh     # prints OK/MISMATCH per case (29)
bash /tmp/t022/tools/stack.sh   # stacked-PR cases (10)
```

The scripts are scratch files under `%TEMP%\t022\tools`, outside the tree. The tester may reuse them or write their own for TP-M1-16.

## Notes for the tester

- **Pass and fail cases:** the gate must pass for zero or one added file and fail for the REQ-033 (1) and (2) cases. The TASK-022 row's acceptance criterion names `m0001_catalog.py`; the planted cases use it.
- **Live check:** the real GitHub check can only be shown by a PR on GitHub. Local evidence covers the shell logic and the YAML. Whether a live check runs is the lead's call, because nobody pushes.
- **Not checked:** `git diff` also reports changes inside a submodule as `M`. There are no submodules, so this was not planted.

## Coordination issue: resolved by the user (decisions.md 2026-10-20)

The user chose option A. M1 lands as five stacked PRs, one migration each, in chain order, stacked on the unmerged M0 PR #1. The gate stays exactly as REQ-033 says, with no exception.

- **Per-PR base:** the gate diffs each PR against its own base branch (see "Script logic" step 1), and the stacked-PR cases above verify this.
- **Retargeting:** revision 2 adds the `edited` trigger, so a retargeted PR is re-checked.
- **Push check on `main`:** each merge adds one migration, so it stays green. That holds only if the stack is merged one PR at a time into `main`, not collapsed into one branch first.

The analysis as originally raised is kept below for the record.

PD-18 and REQ-033 mean one migration per PR. Today:

- `main` has no `versions/` directory at all;
- commit `ae6a6b4` on `m1-db-audit-core` (local only, the branch is not on `origin`) adds `__init__.py`, `m0001` and `m0002` together;
- the working tree adds `m0003`, `m0004` and `m0005` (untracked).

A single M1 PR from `m1-db-audit-core` to `main` would add five migration files, and this gate fails it, as the planted case shows with the two already committed. The push check would fail the same merge.

Options for the user:

- **A, recommended, matches PD-18 as written:** one PR per migration, in chain order, each merged before the next is opened.
  - PR 1: TASK-011 to TASK-014, with `__init__.py` and `m0001`.
  - PR 2: `m0002` (TASK-015, plus TASK-022 if wanted).
  - PR 3: `m0003`.
  - PR 4: `m0004`.
  - PR 5: `m0005` with TASK-019 to TASK-021.

  This needs `ae6a6b4` split so `m0001` and `m0002` land in different commits. That is a local history edit of an unpushed branch, done by the lead. With squash merges, each next branch must be rebased onto the new `main` before its PR. Otherwise the three-dot diff still shows the earlier migration as added and the gate fails. Stacked PRs work only if each is retargeted and rebased after its parent merges.
- **B:** keep one M1 PR and have a repository admin merge it past the failed required check once (branch-protection bypass). The workflow keeps no skip condition, but the gate is knowingly overridden once and the push check on `main` also goes red for that merge. This is an owner decision, and it weakens the record that the gate always held.
- **C:** fold `m0001` to `m0005` into one migration. This contradicts the user's PD-18 answer ("several forward-only Alembic migrations, one per PR"), so it would need the user to reverse that.

I made no change for any option.
