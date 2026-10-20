# M1 PR split: five stacked branches, one migration each (plan, impl-split)

Status: PLAN ONLY, awaiting the lead's approval. Nothing below has been run. Implements the decisions
"M1 lands on main as five stacked PRs" and "M1 PR split, user choices" (work/decisions.md, 2026-10-20).

## 0. Facts the plan rests on (checked read-only)

- `origin/m0-scaffolding` = `e9d099d`. `b77eeb6`, `b166ced` and `6716ed2` sit directly on it and contain only
  PR 1 content (docs, TASK-011 deps, config loader first cut, test plan, conftest hook test). They are reused
  unchanged (same SHAs). Only `ae6a6b4` (TASK-012 to TASK-015 together) has to be split.
- `ae6a6b4` deletes nothing. Since `ae6a6b4`, no tracked file was deleted and `m0001`, `m0002`, `config/*`,
  `pyproject.toml`, the locks, `tests/postgres/Dockerfile`, `schema_diff.py`, `test_schema_catalog.py` and
  `test_schema_fleet.py` are unchanged in the working tree.
- Every PR head's revision handling is file-driven: `test_db_migrate.expected_head()` derives the head from the
  migration files; schema tests use `Scope.of(...)` (named tables, `acls=False`); only `test_schema_diff.py` and
  `test_grants.py` expect the full schema and ACLs (PR 5 only). `migrate_to(server, "m0004")` is used only by
  `test_schema_system.py` (PR 4) and `test_seeds_partitions.py` (PR 5).
- Coverage: `source = bitscan_manager/services`, `fail_under = 85`. PR 1 to PR 4 contain only the empty
  `services/__init__.py` (0 statements), exactly as M0; coverage reports 100 % and the gate passes. M0 proved
  this live: PR #1 CI green (58 passed, coverage gate passed). Not a risk; confirm on the PR 1 Windows run.

## 1. Content of each PR head

"HEAD" = the file as committed in `ae6a6b4`; "FINAL" = the file in the reference snapshot (section 2, step 1).

| File (shared or notable) | PR 1 | PR 2 | PR 3 | PR 4 | PR 5 |
| --- | --- | --- | --- | --- | --- |
| `bm/cli/__init__.py` | HEAD (`db maintain` is a stub) | HEAD | HEAD | HEAD | FINAL (`_db`, `_maintain`) |
| `bm/db/__init__.py` | HEAD (`_scrub`) | HEAD | HEAD | HEAD | FINAL (`dsn_secrets`, `scrub`, needed by `maintain.py`) |
| `tests/conftest.py` | FINAL (see note a) | FINAL | FINAL | FINAL | FINAL |
| `tests/test_pg_harness.py` | FINAL (note a) | FINAL | FINAL | FINAL | FINAL |
| `tests/spec_sql.py` | HEAD | HEAD | HEAD | HEAD | FINAL (`redaction_patterns`, used only by `test_seeds_partitions.py`) |
| `tests/test_cli.py` | HEAD (`["db","maintain"]` in STILL_STUBS) | HEAD | HEAD | HEAD | FINAL |
| `tests/test_db_migrate.py` | HEAD | HEAD | HEAD | HEAD | FINAL (`BOUND_DATA` exempts m0005's constants; note b) |
| `tests/test_debversion.py` | absent | HEAD | HEAD | HEAD | FINAL (adds the `bitscan_app` test that needs the m0005 SELECT grant) |
| `tests/schema_diff.py` | HEAD = FINAL | same | same | same | same |
| `README.md` | `b77eeb6` version | same | same | same | FINAL (usage docs; note c) |
| `tests/m1/*.md`, `tests/report.md`, `tests/test-plan.md`, `work/status.md`, `work/decisions.md`, `work/open-questions.md` | HEAD | HEAD | HEAD | HEAD | FINAL (note d) |

Notes:
- a) The final `conftest.py` is revision-agnostic (adds `context_tag`, `SERVER_ARGS`, `redact_passwords`, the
  `bootstrapped_server(extra_args, log)` hook and `migrate_to`; imports only `MIGRATIONS_DIR`, present since
  TASK-013). PR 4 needs `migrate_to`, so using FINAL from PR 1 avoids an intermediate conftest that was never
  tested. The final `test_pg_harness.py` follow-ups (TP-M1-02 review) touch only the Bootstrap, the Dockerfile
  CMD and the image tag, and the Dockerfile is the same in every PR, so they hold at PR 1.
- b) HEAD `test_db_migrate.py` scans every migration literal for bind traps. Its scanner is the same as FINAL
  for files other than m0005, so it passes at PR 3 and PR 4 (m0003, m0004 pass FINAL). It would fail on m0005,
  which is why FINAL lands with m0005.
- c) README FINAL documents `db migrate` and `db maintain`; per the user, it lands in PR 5. PR 1 to PR 4 keep
  the `b77eeb6` README (no usage section for `db migrate`). Question Q4.
- d) The shared records are kept whole at their `ae6a6b4` content through PR 4 (so PR 1's records already
  mention TASK-015) and take FINAL in PR 5. No record is rewritten or synthesized. Per-task records travel with
  their task (table below).

Files added per PR (bm = `manager/bitscan_manager`, mt = `manager/tests`, all content from HEAD or FINAL as above):

- **PR 1** (`m1-pr1`, base `origin/m0-scaffolding`): commits `b77eeb6`, `b166ced`, `6716ed2` reused; then
  commit 1A = everything `ae6a6b4` adds or changes EXCEPT the seven TASK-015 paths (`versions/m0002_fleet_inventory.py`,
  `mt/test_schema_fleet.py`, `mt/test_debversion.py`, `mt/fixtures/debversion_pairs.tsv`,
  `work/reports/TASK-015-{impl,test}.md`, `work/reviews/TASK-015.md`). That is: `bm/config/startup.py`,
  `bm/cli/__init__.py`, `bm/db/__init__.py`, `bm/db/migrations/{__init__,env}.py`, `versions/__init__.py`,
  `versions/m0001_catalog.py`, `mt/{conftest,spec_sql,schema_diff,test_cli,test_config,test_db_migrate,test_pg_harness,test_schema_catalog}.py`,
  `mt/postgres/Dockerfile`, `tests/m1/{report,test-plan}.md`, `work/decisions.md`, and the TASK-012/013/014 and
  TP-M1-02 reports and reviews. Commit 1B = FINAL `mt/conftest.py`, FINAL `mt/test_pg_harness.py`,
  `work/reviews/TP-M1-02.md`.
- **PR 2** (`m1-pr2`, base `m1-pr1`): the seven TASK-015 paths at HEAD content.
- **PR 3** (`m1-pr3`): `versions/m0003_scanning.py`, `mt/test_schema_scanning.py`, `work/reports/TASK-016-{impl,test}.md`, `work/reviews/TASK-016.md`.
- **PR 4** (`m1-pr4`): `versions/m0004_system.py`, `mt/test_schema_system.py`, TASK-017 reports and review.
- **PR 5** (`m1-pr5`): everything else, FINAL. Commits, in order (only the PR head is verified; question Q3):
  - 5A TASK-018: `versions/m0005_privileges_seeds.py`, `mt/{test_grants,test_seeds_partitions,test_schema_diff}.py`, FINAL `mt/{spec_sql,test_db_migrate,test_debversion}.py`, TASK-018 records.
  - 5B TASK-019: `bm/db/maintain.py`, FINAL `bm/db/__init__.py`, FINAL `bm/cli/__init__.py`, FINAL `mt/test_cli.py`, `mt/test_db_maintain.py`, TASK-019 records.
  - 5C TASK-020/021: `bm/services/audit/`, `bm/repositories/`, `mt/test_audit_{chain,append_pg,verify}.py`, TASK-020/021 records.
  - 5D TASK-022: `.github/workflows/manager.yml`, TASK-022 records.
  - 5E docs/chore: `README.md`, `.claude/agents/{implementer,planner,reviewer,tester}.md`, `.claude/settings.json`, FINAL shared records (incl. this plan).

No test needs narrowing: every test file at every head is either FINAL or the HEAD version that was tested at
`ae6a6b4`. The caveat is risk R2 (PR 3 and PR 4 never ran as the head).

## 2. Mechanics (main checkout never touched)

All commands from Git Bash; `R=/c/Users/kaiquan.koh/Documents/Bitscan`, `WT=$R/.claude/worktrees/m1-split`
(gitignored). Only `.git/` metadata (objects, refs, worktree entry) changes for the main repo.

1. Freeze the reference (no working-tree or index change; a temporary index file is used):
   `GIT_INDEX_FILE=$TEMP/m1ref.index git -C $R read-tree HEAD && GIT_INDEX_FILE=$TEMP/m1ref.index git -C $R add -A`
   then `T=$(GIT_INDEX_FILE=... git -C $R write-tree)`, `REF=$(git -C $R commit-tree $T -p HEAD -m "M1 reference snapshot, local only")`,
   `git -C $R update-ref refs/m1-split/reference $REF`. Check `git -C $R diff --stat HEAD $REF` lists exactly the
   paths of the current `git status` (no stray or ignored files). Every FINAL file is taken from `$REF`, so edits
   other agents make later cannot leak in. Ask all agents to pause edits in the main checkout for this step.
2. `git -C $R worktree add -b m1-pr1 $WT 6716ed2` (PR 1 starts with the three reused commits).
3. 1A: `git -C $WT checkout ae6a6b4 -- . && git -C $WT rm -q --cached <the 7 TASK-015 paths> && rm <same>`;
   1B: `git -C $WT checkout $REF -- manager/tests/conftest.py manager/tests/test_pg_harness.py work/reviews/TP-M1-02.md`.
4. PR 2 to PR 4: `git -C $WT switch -c m1-prN` then `git -C $WT checkout <ae6a6b4|$REF> -- <paths>` per section 1.
5. PR 5: `git -C $WT switch -c m1-pr5`, then per commit `git -C $WT checkout $REF -- <paths>`; 5E ends with
   `git -C $WT checkout $REF -- .` so nothing is missed.
6. Before each commit: `git -C $WT status --porcelain` shows only the intended paths. Author is the repo's git
   user (`lusterless`); no `--no-verify`, no signing flags.

Commit messages (body names TS/SR sections and TASK/REQ ids; every message ends with a blank line and
`Co-Authored-By: Claude Code <noreply@anthropic.com>`):

- 1A `feat(manager): config loader, db migrate and migration m0001 (TS §5.2 L638-L707, §5.3, §8.7; TASK-012, TASK-013, TASK-014)`
- 1B `test(manager): harness follow-ups and migrate_to helper (TS §5.2 Bootstrap; TP-M1-02)`
- 2 `feat(manager): migration m0002 fleet and inventory, Debian version compare (TS §5.2 L709-L825, §7.2; TASK-015)`
- 3 `feat(manager): migration m0003 scanning tables and job_created_at trigger (TS §5.2 L842-L938; TASK-016)`
- 4 `feat(manager): migration m0004 system tables (TS §5.2 L827-L840, L941-L990; TASK-017)`
- 5A `feat(manager): migration m0005 privileges, v_plugin, seeds, initial partitions (TS §5.2 L992-L1013, L1037-L1042, L832-L833, §5.3, §8.6; TASK-018)`
- 5B `feat(manager): db maintain for scan_result partitions (TS §5.3; TASK-019)`
- 5C `feat(manager): audit hash chain append and verifier (TS §5.3, §8.1; TASK-020, TASK-021)`
- 5D `ci(manager): forward-only, one-migration-per-PR gate (TS §5.3; TASK-022)`
- 5E `docs: M1 README usage, agent model setting, WSL allow rules, M1 records`

## 3. Per-PR verification (all in `$WT`, for N = 1..5 after `git -C $WT switch m1-prN`)

- Venv: create `$WT/manager/.venv` once (`py -3.12 -m venv`, `pip install --require-hashes -r requirements-dev.txt`,
  `pip install --no-deps --no-build-isolation -e manager`). Do NOT use `$R/manager/.venv`: its editable install
  and `bitscan-manager` console script point at the main checkout, and `run_cli()` would test the wrong code.
  The locks are identical in all five PRs, so one venv serves all heads.
- Static: `ruff check manager && ruff format --check manager && mypy --strict --config-file manager/pyproject.toml manager`.
- Windows: `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` (pg tests skip with
  "not run: Docker unavailable"); record passed/skipped counts and 0 failed. PR 1 to PR 4: coverage line shows
  only `services/__init__.py`, 100 %.
- Migration gate (TASK-022), run locally even for PR 1 to PR 4 (whose workflow does not have it yet): extract the
  `run:` block from `$REF:.github/workflows/manager.yml` with the tester's extractor in
  `%TEMP%\tester2_t022\stack_test.sh` (same Python snippet) into `%TEMP%\m1split\gate.sh`, then with cwd `$WT`:
  `EVENT_NAME=pull_request PR_BASE_SHA=$(git rev-parse <base>) PR_HEAD_SHA=$(git rev-parse m1-prN) RUNNER_TEMP=%TEMP%\m1split\tmp bash gate.sh`
  with base `origin/m0-scaffolding` for PR 1 and `m1-pr(N-1)` otherwise. Expect `migrations ok: 1 added, none changed`
  for each. Negative controls: PR 2 against `origin/m0-scaffolding` and PR 5 against `origin/m0-scaffolding` must fail.
  Also `git diff --name-status <base> m1-prN -- manager/bitscan_manager/db/migrations/versions/` shows one `A`
  (plus `versions/__init__.py` in PR 1).
- Structure: `git diff --stat ae6a6b4 m1-pr2` lists exactly `mt/conftest.py`, `mt/test_pg_harness.py`,
  `work/reviews/TP-M1-02.md` (proves PR 1 + PR 2 = the committed `ae6a6b4` apart from note a).
- WSL (tester, one head at a time, after the Windows runs pass): `git -C $R archive m1-prN` unpacked into a fresh
  `/root/bitscan-tester/m1-prN`, fresh venv, `CI=true` full pytest with the coverage gate, Docker and `dpkg`
  present, 0 skipped, 0 leftover containers. The tester needs a new `%TEMP%\tester2_*.sh` script for this (the
  approved allow rule covers that path); no repo change.

## 4. Final equality check

`git -C $R diff --stat $REF m1-pr5` must print nothing (tree equality in repository terms; `.gitattributes`
`text=auto eol=lf` applies to both). Then, at the end, re-snapshot the live working tree the same way (temporary
index) as `NOW` and run `git diff --stat NOW m1-pr5`: anything listed must be under `work/` or `tests/*.md`
(bookkeeping edited after the freeze, for example the lead's status line about the split); any other path is a
blocker. Ignored paths (`.venv`, caches, `.claude/worktrees/`, `settings.local.json`) never enter either tree.

## 5. Risks and open questions for the lead (ranked)

1. **Q1, gate placement versus the required check (blocker for the user's choice 3).** TASK-022 lands in PR 5, so
   PR 1 to PR 4 run M0's `manager.yml` on GitHub and never report a `migrations` check. If `migrations` is made
   required on main before PR 5 merges, PR 1 to PR 4 wait forever on "Expected"; and until PR 5 merges, the stack
   itself is not gated on GitHub. Options: (a) move `.github/workflows/manager.yml` (TASK-022, depends only on
   TASK-014) into PR 1 as its own commit, so every later PR is gated live; the local gate runs show each PR passes
   it; (b) keep it in PR 5 and make the check required only after PR 5 merges. Needs a user decision; I recommend (a).
2. **R2, PR 3 and PR 4 heads were never run as the head.** TASK-016/017 were tested with later migrations on disk
   (TASK-017 report: `migrate_to` "reaches the m0004-only state that the CLI never stops at"). `migrated_db` at
   PR 3/PR 4 is a new state. Section 1 found nothing head-dependent, but only the WSL runs prove it. A failure there
   is a real finding: narrowing or fixing a test goes to the tester, code to impl-manager, and the reference
   snapshot is re-frozen.
3. **R3, wrong venv.** Using the main checkout's venv silently tests the main checkout (section 3). Mitigated by
   the worktree venv; a cheap check is `python -c "import bitscan_manager; print(bitscan_manager.__file__)"`
   showing a path under `$WT`.
4. **R4, reference drift.** Agents still writing in the main checkout. Mitigated by freezing `$REF` first and the
   bookkeeping-only diff at the end; ask agents to pause edits for step 1.
5. **Q2, harness follow-ups in PR 1.** I put the FINAL `conftest.py`, `test_pg_harness.py` and the TP-M1-02 review in
   PR 1 (commit 1B) instead of PR 5: PR 4 needs `migrate_to`, and the alternative is a hand-made intermediate
   conftest never tested anywhere. Confirm this deviation from "PR 5 holds the rest".
6. **Q3, PR 5 commits.** Five commits (5A to 5E) for review; only the PR head is verified, intermediate commits may
   not be green (for example 5A's FINAL test files before 5B). Alternative: one PR 5 commit. Lead's choice.
7. **Q4, README timing.** The docs-ownership decision says README changes with the behaviour, but the user put
   README in PR 5, so PR 1 ships `db migrate` without usage docs. Keep as decided unless the lead wants the
   `db migrate` sections in PR 1 (would need impl-manager to split the README).
8. **R5, records.** PR 1's shared records (`tests/m1/*.md`, `work/decisions.md`) already mention TASK-015 results,
   as committed in `ae6a6b4`; cosmetic, not rewritten.
9. **R6, base movement.** If M0 PR #1 gains commits before merge, rebase the whole stack onto the new
   `origin/m0-scaffolding` and repeat sections 3 and 4. With merge commits (user choice 2), child PRs keep a valid
   base after each parent merges.
10. Cleanup after the user's go-ahead and push: `git worktree remove $WT`; keep `refs/m1-split/reference` and
    `m1-db-audit-core` until all five PRs are merged.

## 6. Results (build done 2026-10-20, impl-split; local branches only, nothing pushed)

As approved, with the user's Q1 change: `.github/workflows/manager.yml` and the TASK-022 reports and review
are commit 1C in PR 1, and 5D is dropped. Reference snapshot `refs/m1-split/reference` = `022e0ff` (tree `3c2e1a4`).
Worktree `.claude/worktrees/m1-split` with its own venv; the main checkout was never changed (still
`m1-db-audit-core` at `ae6a6b4`, same 60 status entries).

| Branch | Head | Commits on its base | ruff / format / mypy (files) | Windows pytest (pg skipped: Docker unavailable) | services/ coverage |
| --- | --- | --- | --- | --- | --- |
| `m1-pr1` | `24bf548` | `b77eeb6`, `b166ced`, `6716ed2` (reused), `bc7d13a` 1A, `a6ea766` 1B, `24bf548` 1C | pass / pass / pass (25) | 274 passed, 34 skipped, 0 failed | 0 statements, 100 % (no data, as M0) |
| `m1-pr2` | `089eae0` | `089eae0` | pass / pass / pass (28) | 277 passed, 54 skipped | 100 % (no data) |
| `m1-pr3` | `7a40d67` | `7a40d67` | pass / pass / pass (30) | 277 passed, 64 skipped | 100 % (no data) |
| `m1-pr4` | `17fe725` | `17fe725` | pass / pass / pass (32) | 277 passed, 94 skipped | 100 % (no data) |
| `m1-pr5` | `0b1a216` | `7539591` 5A, `b93a45a` 5B, `cdc22a8` 5C, `0b1a216` 5E | pass / pass / pass (46) | 366 passed, 181 skipped (547 total, as the WSL run) | 98.15 % on Windows (2 lines covered only by pg tests) |

Every skip reason is "not run: Docker unavailable". The pg tests have NOT been run at any head yet: that is the
tester's WSL step (R2).

Migration gate, extracted from `m1-pr1`'s `manager.yml` (identical at `m1-pr5`), run locally: OK=12, MISMATCH=0.
Each PR against its own base gives `migrations ok: 1 added, none changed` (PR 1 adds `versions/__init__.py` (exempt) and
`m0001`). Push simulations m0 to PR 1 and PR 4 to PR 5 pass. The negative controls fail as they should: PR 2, PR 5 and
`m1-db-audit-core` against `origin/m0-scaffolding`, PR 5 against PR 3, and a rewritten push (PR 5 to PR 4).
The `migrations` job is present from PR 1 on, so every PR reports the check live.

Equality: `git diff refs/m1-split/reference m1-pr5` is empty, and a fresh temporary-index snapshot of the live
working tree, taken after all runs, has the same tree `3c2e1a4`. After this results section was written, the
working tree differs from `m1-pr5` only in this file (bookkeeping, not amended into PR 5).
Scripts: `%TEMP%\m1split\{gates.sh,head.sh,extract.py}`, logs `%TEMP%\m1split\pytest-m1-prN.log`.
