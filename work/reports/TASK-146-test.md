# TASK-146 TEST: PASS (revision 1)

Tester: tester-m7b, run 2026-10-27, re-confirmed on the merged head 2026-10-28. REQ-157, REQ-177, REQ-180. Spec: SR §4.2 (SR L277–L287), §4.1 BIT102, §1.1; TS §3.7 (L505), §8.1 (L1244, L1255), §8.3; answer #108 (a)–(k); lead rulings 2026-10-27 (apt/apt-get/systemctl verbs anywhere among the literal arguments; `<>` is output; `env -S` lexed); user ruling 2026-10-27 (a non-literal command word passes; only its nested scripts are checked); lead ruling 2026-10-28 (c) on `stdbuf`. Checks CHK-M7-115 to -121; plants CHK-M7-327 to -332 (tests/m7/test-plan.md). Test file: `manager/tests/test_bit102.py`; corpora `bits/tests/bit102/must_reject.json` (149 cases) and `must_pass.json` (96 cases). Implementation: `manager/bitscan_manager/services/importer/bit102.py` (impl report `work/reports/TASK-146-impl.md`).

**This report covers revision 1 and is kept for the record. Its review waits for revision 2** (the BIT102 gaps closed by the user on 2026-10-27, decisions "BIT102 gaps closed" and "TASK-146 r2 shape rulings"), which gets its own section below when it is tested.

## Rounds

| Round | Result | Note |
| --- | --- | --- |
| 1 (2026-10-27) | FAIL | #108 (d) bypass: in a wrapper's short-option cluster whose last letter takes a value, the value hid the command (`sudo -iu root rm x` took `root` as the command). Handed to impl-manager-m7b with the failing parameters of `test_wrapper_option_clusters_do_not_hide_the_command`. |
| r1 (2026-10-27) | PASS | `_option()` reads wrapper options as getopt does (TASK-146-impl.md "Revision 1"). One parameter, `stdbuf -io L rm x`, was disputed; the lead closed it on 2026-10-28 (c): getopt reads `-io` as `-i o` and `rm` never runs, so it isn't expected to be flagged. The test uses `stdbuf -i0 -oL rm x`, which gets BIT102 naming `rm`. |

## Runs (revision 1)

Code under test: `git archive 25d41ec` of `manager`, `bits`, `docs` in `/root/bstest-m7b-head` (no product change in the worktree; the old copy differs only in CR LF).

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| clean | W | `CI=true pytest -q tests/test_bit102.py` | 1160/1160 passed, 0 failed, 0 errors, 0 skipped |
| dependents | W | `test_bit102_lexer.py` (shared lexer), `test_bit_validate.py` (imports `check_execute`), `test_bit_fixtures.py`, `test_bit_model.py`, `test_module_imports.py` | 173/173, 687/687, 227/227, 71/71, 126/126 passed; 0 failed, 0 errors, 0 skipped |
| static | L | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | all checks passed; 276 files already formatted; no issues in 276 source files |

W and L are as in `work/reports/TASK-144-test.md`.

## Acceptance criteria (tasks.md TASK-146)

| Criterion | Check | Result |
| --- | --- | --- |
| Every case of the REQ-157 (1) must-reject corpus gets BIT102 with the offending token in its message | CHK-M7-115 | PASS: 149/149 cases; each finding is BIT102, Reject, at the caller's line and element, and one message holds the corpus token |
| … also in each context | CHK-M7-116 | PASS: 646 rows, each case marked `contexts` (at least 24) inside 27 contexts: pipeline, `;`, `&&`, `\|\|`, `&`, `( )`, `{ …; }`, `if`, `while`, `until`, `for`, `case`, function body, `$( )`, backticks, `<( )`, `>( )`, `!`, assignment, `"$( )"`, `${x:-$( )}`, unquoted here-document, `bash -c '…'`, `sh -c "…"`, `dash -c '…'`, `sudo`, `env` |
| #108 matching forms | CHK-M7-117 | PASS: 66 rows (`/bin/rm`, `./rm`, `../../bin/rm`, `mkfs.ext4`, `mkfs.xfs`, `env`/`env -i`/`env -u`/`env --`, `busybox`, `sudo` with `-u`, `-uroot`, `--user=`, `doas`, `command`, `command -p`, `builtin eval`, `nice`, `nohup`, `setsid`, `ionice`, `stdbuf`, `timeout` with `-s`/`-k`, `chroot`, stacked wrappers, `FOO=1`, the `sed -i` forms, apt/dpkg/systemctl with options) plus 11 r1 option-cluster rows (`sudo -iu root`, `env -iu FOO`, `timeout -vk 5 10`, `ionice -tc 3`, `doas -nu root`, `nice -n5`, `stdbuf -i0 -oL`, `stdbuf -eL -o L`, …), each naming its token |
| Redirections (#108 (i)) | CHK-M7-118 | PASS: 25 rejected (`> /etc/x`, `>/tmp/../etc/x`, `> "$F"`, `> $HOME/x`, `> /tmpx`, `> /tmp`, `&> /var/x`, `>& /var/x`, `>>`, `>\|`, `2>`, `&>>`, `<>/etc/x`, `/dev/sda`, `/dev/fd/1`, `/tmp/$(id -u)`, `` /tmp/`id` ``, `/dev/null/../x`, …); 18 pass (`/dev/null`, `/dev/stdout`, `/dev/stderr`, `/tmp/out`, `2>&1`, `>&2`, `>&-`, `<>/tmp/x`, input redirections, here-strings) |
| Code-running forms (#108 (f)) | CHK-M7-119 | PASS: 36 rows (`.`, `source`, `eval`, `exec`, `xargs`, `find -exec/-execdir/-ok/-okdir`, `sh ./x.sh`, `bash x`, `sh -s`, bare `sh`, `echo x \| sh`, `sh < x`, `bash -x x.sh`, `bash -c "$(curl x)"`, ``sh -c '`id`'``, `dash -c 'cat <(id)'`, a here-document substitution in `bash -c`, nested `-c`, `env -S` in three spellings); 10 rows of substitutions in data words (`for`, `case`, `select`) and input-redirection targets |
| No case of the must-pass corpus (the SR §1.1 `Execute` included) gets BIT102 | CHK-M7-120 | PASS: 96 corpus cases (the first is the SR §1.1 `Execute`, extracted from the spec block); all 32 `Execute`s of `bits/samples/` read through the real parser; 47 more rows: the lead's false-positive guards (`systemctl status`, `is-enabled`, `show -p`, a verb inside a unit name, `apt list --installed`, `apt-cache policy`, `grep install`), the user's non-literal forms, SR §4.2 read-only uses; `echo "rm"`, `echo firmware` pass while `r''m x` and `\rm x` are rejected (not a substring search) |
| Unlexable input fails closed | CHK-M7-121 | PASS: 13 unlexable inputs give exactly one BIT102 "cannot be checked"; 10 nested `sh -c` levels (past depth 8) are rejected |
| Messages | — | PASS: the token is quoted as written (`r''m`, `"rm"` via `sudo`); a 16,000-character target is never quoted whole and the message stays under 300 characters; C0 escaped; one finding per distinct offence in source order; the caller's line and element are used; Hypothesis, 3,000 inputs: `check_execute` never raises, each under 1 s |

**Accepted residual risk (user ruling 2026-10-27, to be carried into the M7 PR):** a non-literal command word passes BIT102, so `c=rm; "$c" -rf /` is not caught. The must-pass rows `"$c" x`, `${x} y`, `$(echo rm) x`, `$'\x72m' x`, `sh -c "$s"` and `sudo "$c" x` pin that ruling, and `$(rm -rf /) x`, `"$(rm x)" y` and `${x:-$(rm y)} z` prove the nested scripts are still checked. BIT102 is the safety net; the runner sandbox (TS §3.7, M10) is the control.

## Plants (throwaway copies `/root/m7b-mut/<id>` from the merged head, copy imported first, asserted; definitions `%TEMP%\m7b-plants\plants_145_146.json`)

Control copy (`CTRL-145-146`, no-op): ruff clean; `test_bit102.py` and `test_bit102_lexer.py` green.

| Plant | Change | Red tests (first) |
| --- | --- | --- |
| CHK-M7-327 | substring search over the forbidden words instead of the lexer | `test_not_a_substring_search` (`echo "rm"`), the `sed -i` must-reject rows |
| CHK-M7-328 | path-qualified names not reduced | `/bin/rm`, `/usr/bin/rm`, `./rm`, `/bin/sh -c 'eval x'` |
| CHK-M7-329 (nested) | substitution scripts not checked | `echo $(rm x)`, `` echo `rm x` ``, `cat <(rm x)`, `cat <&$(rm x)` |
| CHK-M7-329 (shell) | `-c` scripts not checked | `test_nested_shell_scripts_past_depth_8_fail_closed`, `sh -c 'rm x'` rows |
| CHK-M7-330 | `WRAPPERS` empty | `env rm x`, `env -i rm x`, `test_message_quotes_the_token_as_written` |
| CHK-M7-331 (any) | every redirect target allowed | `> /etc/x`, `>> /etc/x`, `>\| /etc/x`, `test_message_bounded_and_escaped` |
| CHK-M7-331 (dotdot) | `..` allowed under `/tmp/` | `>/tmp/../etc/x`, `> /tmp/a/../../etc/x` |
| CHK-M7-331 (expansion) | a non-literal target judged by its raw text | `> /tmp/$(id -u)`, `` > /tmp/`id` `` |
| CHK-M7-332 (bit102) | `ShellSyntaxError` branch returns `[]` | the 13 unlexable rows, 9 nested `$(` |
| P146-cluster-r0 | r1 undone: only the first letter of a cluster read | the r1 option-cluster rows (`sudo -iu root`, `doas -nu root`, …) |
| P146-sed | `sed` cluster scan returns nothing | every `sed -i` form, `sudo sed -i` |
| P146-verb-first-only | find actions only at the first argument | `find / -name x -exec …`, `-execdir`, `-ok`, `-okdir` |
| P146-shell-noc | a shell without `-c` allowed | `sh ./x.sh`, `bash /tmp/x`, `dash x.sh`, `bash -x x.sh` |
| P146-subst-in-c | substitution in a `-c` script word allowed | `bash -c "$(curl x)"` |
| P146-dpkg-eq | `--opt=value` not split | `dpkg --purge=x`, `--remove=x`, `--install=x.deb` |
| P146-find | `-execdir` and `-okdir` not refused | those rows |
| P146-mkfs | `mkfs.*` not matched | `mkfs.ext4`, `mkfs.xfs`, `/sbin/mkfs.ext4` |
| P146-envS | `env -S` not lexed | `env -S 'rm x'`, `-S'rm x'`, `--split-string='rm x'` |
| P146-heredoc-in-c | here-document substitution in a `-c` script allowed | `bash -c 'cat <<EOF $(id) EOF'` |
| P146-datawords | data words not walked | `for f in $(rm x)`, `select`, `case` rows |
| P146-redirect-target-scripts | input-redirect target scripts not walked | `cat < <(rm x)`, `cat <<<$(rm x)`, `cat < "$(rm x)"`, `cat <&$(rm x)` |
| P146-ltgt-input | `<>` treated as input | `cat <>/etc/x` |
| P146-nonliteral-reject | a non-literal command word refused (against the user's ruling) | must-pass `"$c" x`, `${x} y`, `$(echo rm) x`, `sudo "$c" x` |

All 23 plants are red; the control is green.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-115 | CODE | W | `pytest -q tests/test_bit102.py -k "must_reject and not every_context or corpora_sizes"` | PASS | 150/150; 149 cases with token | 2026-10-28 |
| CHK-M7-116 | CODE | W | `pytest -q tests/test_bit102.py -k "every_context or context_count"` | PASS | 647/647; 27 contexts | 2026-10-28 |
| CHK-M7-117 | CODE | W | `pytest -q tests/test_bit102.py -k "108_matching or wrapper_option_clusters"` | PASS | 77/77 | 2026-10-28 |
| CHK-M7-118 | CODE | W | `pytest -q tests/test_bit102.py -k redirections` | PASS | 43/43; 25 rejected, 18 pass | 2026-10-28 |
| CHK-M7-119 | CODE | W | `pytest -q tests/test_bit102.py -k "code_running or data_words"` | PASS | 46/46 | 2026-10-28 |
| CHK-M7-120 | CODE | W | `pytest -q tests/test_bit102.py -k "must_pass or sample_execute or sr_example or read_only or not_a_substring"` | PASS | 177/177; SR §1.1 and 32 sample `Execute`s | 2026-10-28 |
| CHK-M7-121 | CODE | W | `pytest -q tests/test_bit102.py -k "unlexable or past_depth_8"` | PASS | 14/14 | 2026-10-28 |
| CHK-M7-315 (TASK-146 part) | CODE | L | ruff, ruff format, mypy --strict (CI config) | PASS | clean, 276 files | 2026-10-28 |
| CHK-M7-327 | CODE | W | plant: substring search | PASS (red) | `test_not_a_substring_search` failed | 2026-10-28 |
| CHK-M7-328 | CODE | W | plant: `/bin/rm` not reduced | PASS (red) | path rows failed | 2026-10-28 |
| CHK-M7-329 | CODE | W | plants: nested and `-c` scripts not checked | PASS (red) | both plants red | 2026-10-28 |
| CHK-M7-330 | CODE | W | plant: wrappers not unwrapped | PASS (red) | `env rm x` rows failed | 2026-10-28 |
| CHK-M7-331 | CODE | W | plants: any target, `..`, non-literal target allowed | PASS (red) | all three red | 2026-10-28 |
| CHK-M7-332 | CODE | W | plants: lexer errors pass (bit102 and lexer halves) | PASS (red) | unlexable and depth rows failed | 2026-10-28 |

## Revision 2: NOT RUN (stopped by a safety check)

Tester: tester-m7c, 2026-10-28, worktree `Bitscan-m7` (branch `m7-catalog`). This was the single attempt allowed by the decisions row "Overnight pre-authorisation" (1).

**What happened:** while I was still reading context (step 0, before any test was written, run or planted), a safety classifier stopped my response and withheld the rest of it. The last tool call that finished was a read-only search of `work/reports/TASK-144-test.md` for its description of the W/L environments. As instructed, I stopped at once: no retry and no rewording.

**State left behind:** apart from this section, no file was changed. `manager/tests/test_bit102.py`, `bits/tests/bit102/must_reject.json` and `must_pass.json` have no diff, so tester-m7b left no partial r2 edits. `tests/m7/test-plan.md` and `tests/m7/report.md` are unchanged. No WSL copy was made, no tests were run and no plants were made.

**Verdict:** none. TASK-146 r2 TEST stays open, and the item waits for the user (decisions "Overnight pre-authorisation" (1)).

### Attempt 2: NOT RUN (tester-m7d, 2026-10-28, user-requested "Run task-146 r2")

**What happened:** a safety classifier stopped my response while I was still reading context (step 0). Nothing had been written, run or planted. The tool calls that finished were all read-only:
- `.claude/rules/testing.md`, `manager/importer.md` and the BIT102 part of `manager/bit-format.md`;
- the TASK-146 rows in `work/tasks.md`, and the BIT102 rows in `work/decisions.md` ("BIT102 gaps closed", "TASK-146 r2 shape rulings", "TASK-146 r2 rulings", "TASK-146 r2 vs the remote approval");
- TP-M7-08 and the mutation table in `tests/m7/test-plan.md`;
- `work/reports/TASK-146-impl.md`, this report, `manager/tests/test_bit102.py`, the start and end of both corpora;
- the three product files `bit102.py`, `bit102_wrappers.py` and `bit102_braces.py`.

The stop came after those reads, before I drafted any r2 test row. As the brief says, I stopped at once: no retry and no rewording.

**State left behind:** apart from this subsection, no file was changed. `manager/tests/test_bit102.py`, `bits/tests/bit102/must_reject.json`, `must_pass.json`, `tests/m7/test-plan.md` and `tests/m7/report.md` have no r2 edits. No CHK id was assigned, so the next r2 id is still CHK-M7-388. No WSL copy was made, no test or gate was run, and no plant was made.

**Verdict:** none. TASK-146 r2 TEST stays open and goes back to `main` and the user.

## Revision 2 deferred; r1 re-confirmed at the M7 gate (tester-m7, 2026-10-29)

The user deferred TASK-146 r2 (decisions "TASK-146 r2 deferred"). `bit102.py` is back to r1, byte-identical to c6b7e13 (sha256 `279291cf…`). `bit102_wrappers.py` and `bit102_braces.py` are removed, and the r2 copies are saved outside the tree.

On a fresh copy (`/root/bstest-m7-r1`, `CI=true`, `PYTHONPATH` pinned, `-n 2`):
- `test_bit102.py` 1,160/1,160 (as above), `test_bit102_lexer.py` 173/173, `test_bit_validate.py` 687/687, `test_bit_fixtures.py` 227/227;
- the pipeline's CHK-M7-191 rows, now with all six BIT102 fixtures, 150/150;
- G59 50/50.

That is **2,447/2,447 passed**, 0 skipped. Whole-tree ruff, format and `mypy --strict` are clean (310 files), with no import of the removed modules. The r1 verdict above stands: **PASS**.
