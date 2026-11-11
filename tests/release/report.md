# Release 0.2.0: test report (TASK-262, TASK-263)

**Recorded by the lead from tester-rel2's reply, 2026-11-11.** A rule refused tester-rel2's write of this file ("Subagents should return findings as text, not write report files"). tester-rel2 stopped and did not retry. The user approved the lead writing the returned rows here (decisions 2026-11-11). The rows and evidence are tester-rel2's, unchanged in substance. Plan: [test-plan.md](test-plan.md).

`W` = tester-rel2's WSL copy `~/rel2/tree`. It is byte-identical to the worktree for every batch file, re-checked after round 2, and uses its own hashed venv `~/rel2/venv`, `CI=true`, xdist and the Zscaler CA. Scripts are in `C:\Users\kaiquan.koh\rel2-scripts\`, outside the tree.

## Verdicts

- **TASK-262: PASS** (round 1).
- **TASK-263: PASS** (round 2). Round 1 had 2 FAILs, CHK-R020-034 and -036, which impl-deploy-rel fixed. CHK-R020-046 is NOT RUN (see below).

## Test-side changes (PD-51, old → new)

| File | Old → new | Check id |
| --- | --- | --- |
| `manager/tests/test_openapi.py` L75 | `0.1.0` → `0.2.0` | CHK-M0-040 → CHK-R020-006 |
| `manager/tests/test_project_config.py` L42 | `0.1.0` → `0.2.0` | CHK-M0-011 → CHK-R020-007 |
| `deploy/tests/test_manager_wheel.sh` L32 | `VERSION=0.1.0` → `0.2.0` | CHK-M6-020/-022 → CHK-R020-009 |
| `deploy/tests/check_runbook_bootstrap.py` | `SPEC_START, SPEC_END` `1018, 1033` → `1023, 1038`. Red on `main` since `86f33a6` (2026-11-03); no workflow runs it | CHK-M6-040 → CHK-R020-045 |
| `e2e/m6/manager_walk.py` | the §6 release file names take the `--rel` wheel's version (`rel_version`, `rel_files`); on failure the walk writes a FAIL row and stops | CHK-M6-048 / CHK-M11-295 → CHK-R020-044 |
| `e2e/m6/check_walk_rel_version.py` | new | CHK-R020-044 |

Left alone on purpose:
- `e2e/m6/release_checks.sh`: its `0.1.0` values are scratch inputs;
- the agent-version fixtures, `compat.py` and the `~pre` build inputs;
- `ops_upgrade.py` (CHK-R020-012).

## TASK-262

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-R020-001, -002, -003 | PASS | pyproject `0.2.0`; `__version__` `0.2.0` imported from the copy; openapi `info.version` `0.2.0` |
| CHK-R020-004 | PASS | `git diff d26c472 -- manager/openapi.json`: 1 line, `"version": "0.1.0"` → `"0.2.0"` under `info` |
| CHK-R020-005 (G6) | PASS | two exports and the committed file all sha256 `bd2b2b59…f043146` |
| CHK-R020-008 | PASS | before the re-pin: 2 failed of 16 (exactly `test_document_is_openapi_31` and `test_version_and_console_script`, `'0.2.0' == '0.1.0'`), 14 passed |
| CHK-R020-006 | PASS | `test_openapi.py` 6/6 passed, 0 failed, 0 errors, 0 skipped |
| CHK-R020-007 | PASS | `test_project_config.py` 10/10 passed, 0 failed, 0 errors, 0 skipped |
| CHK-R020-009 | PASS | `pip wheel` of the copy gives `bitscan_manager-0.2.0-py3-none-any.whl` (METADATA Version 0.2.0, `py3-none-any`). The re-pinned `test_manager_wheel.sh` in a fresh ubuntu:24.04 container: OK 60/60 (installed 0.2.0, head `m0006`, UI served byte-identical). Run 1 stopped in the harness (a read-only CA mount over the system path broke `ca-certificates`); the mount was fixed, not the test |
| CHK-R020-010 | PASS | the versions step, extracted from `release.yml` as written and run with `bash -e`: dispatch `0.2.0` and push `v0.2.0` both pass, outputs `version=0.2.0`, `deb_version=0.2.0-1` |
| CHK-R020-011 | PASS | pyproject, `__init__` and the changelog upstream are all `0.2.0`; the changelog is `0.2.0-1` |
| CHK-R020-012 | PASS | grep finds no other tree-version pin (classified above) |
| CHK-R020-013 / -023 | PASS | `check_release_workflow` 17/17 |
| CHK-R020-016, -017 | PASS | `bit102.py` sha256 `279291cff382653ffcc59a2382e32f57c0586bbe84011acdcf466de5d8a991fd`; no `bit102_*` files tracked or untracked; importer diff against `d26c472` empty (checked by hash and file list only) |
| Plants CHK-R020-080 to -083c | all red | 0.2.1 given; `~pre3` changelog; pyproject 0.2.1; tag v0.2.1; v0.2.0-rc1; a `$(touch)` injection (refused, no command ran). Versions script 10/10 |
| Plant CHK-R020-084 (`__init__` 0.1.0) | red | `test_openapi` 3 failed. The versions step still passes: it reads only pyproject and the changelog, so the `__init__` pairing is covered only by tests |
| Plant CHK-R020-085 (openapi 0.1.0) | red | 2 export-comparison tests failed |
| Plant CHK-R020-086 (pyproject 0.1.0) | red | `test_project_config` 1 failed |

## TASK-263 (round 2)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-R020-020 | PASS | `check_debian_meta` 83/83 |
| CHK-R020-021 | PASS | `check_runbook_text` on README and the 3 runbooks: only the 2 known findings (`agent-install.md` L79, L123, the `bse_REPLACE…` placeholders, as in the TASK-259 record); 0 in manager-install |
| CHK-R020-022 | PASS | `check_md_links` OK, 42 links |
| CHK-R020-024 | PASS | Version `0.2.0-1`, Source `bitscan-agent`, `unstable`/`medium`, stderr empty |
| CHK-R020-025 | PASS | Wed 11 Nov 2026 is after Sun 08 Nov (`0.2.0~pre2-1`) and not in the future |
| CHK-R020-026 | PASS | `bash deploy/debian/build-deb.sh` in the m4b-build-u24 container (Go 1.27.2) gives `bitscan-agent_0.2.0-1_amd64.deb`, sha256 `e208f069…cde3b`, Version 0.2.0-1; the binaries carry `0.2.0-1` |
| CHK-R020-027 (G37) | PASS | lintian 2.117 `--pedantic --fail-on error,warning` (as `package.yml`): rc 0, only I/O/N tags, no unused or mismatched override |
| CHK-R020-028 | PASS | `control` has no `(pre-release)`, `idle` or `0.x` |
| CHK-R020-029 | PASS | 7 `~pre` hits outside the changelog history: 5 are the "unsupported" rule; changelog L27 and agent-install L178 are the rule's remedy (lead ruling Q2) |
| CHK-R020-030 | PASS | no pre-release note for 0.2.0 |
| CHK-R020-031, -032 | PASS | both Compatibility pairs at manager-operations L43, agent-install L170 and README L55 |
| CHK-R020-033 | PASS | matches the `compat.py` header rows (a: `runner_unavailable`, score null / n/a; b: no compliance job; upgrade) |
| CHK-R020-034 | PASS (round 2; FAIL round 1) | the changelog has a `bits/samples` bullet (not in this package or the manager release; CIS control numbers not yet confirmed); README L355 has it too |
| CHK-R020-035 | PASS | no `bits/samples` file, by name or hash, in the `.deb` (12 files) or the wheel |
| CHK-R020-036 | PASS (round 2; FAIL round 1) | changelog and README L395 name every gap in the ruling: `-c` strings of su/runuser/flock, `trap`, braces, the extra wrappers, abbreviated long options, the `time -o`/`--output` and `flock` output files, and the non-literal command word (lead ruling Q1). The sandbox is named as the real control; the r2 rules are not claimed. Checked against the ruling's text only |
| CHK-R020-037 | PASS | every claim maps to built work (scans, schedules, CSV, re-evaluation, retention, spool, redaction, capread off, `bits rebuild` CLI, upgrade paths: G38 at M11, CHK-M11-307; maintainer scripts unchanged since `d26c472`); no out-of-scope claim |
| CHK-R020-038, -039 | PASS | 0 process ids in added lines; the only `bs*_` strings are placeholders and prefix mentions |
| CHK-R020-040 | PASS | round 1 4/4 (184 s); round 2, on the round-2 README: `test_readme_walk_linux`, `_m5_`, `_m7_`, `_m9_` 4/4 passed, 0 failed, 0 skipped, 181.8 s (W, `CI=true`, `-n 4`; `rel2-scripts\readme2.log`) |
| CHK-R020-041, -042 | PASS | changelog entry style consistent; §7 and §1 unchanged and consistent |
| CHK-R020-043 | PASS | manager-install L163, L165–166, L411–412, L420 read `0.2.0`; no `0.1.0`; the names equal what `release.yml` writes |
| CHK-R020-044 | PASS | `check_walk_rel_version.py` 17/17 |
| CHK-R020-045 | PASS | bootstrap OK (TS L1023–L1038); a planted `;` → `:` goes red |
| CHK-R020-046 (`check_manager_sboms`) | NOT RUN | tester-rel2 stopped (the refused write) before the local release run (`e2e/m6/release_local.sh`). Covered by the `release` workflow run on the release PR (runbook §7 step 4) |

## Hosted runs (lead steps)

| Check | Result | Evidence |
| --- | --- | --- |
| CHK-R020-060 to -067 | NOT RUN (yet) | the release PR's CI, `e2e.yml` and `release.yml` (0.2.0) on `release-0.2.0`; the lead records them |
