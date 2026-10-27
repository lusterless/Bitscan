# TASK-146 TEST (revision 1): PASS

Tester: tester-m7c, 2026-10-27 (re-run in the cloud container; the first tester's report and plants were lost). REQ-157, REQ-177, REQ-180; #108 (a)–(k). Spec: SR §4.2 (SR L277–L287), §4.1 BIT102, §1.1; TS §3.7, §8.1. Rulings tested as written:
- User, 2026-10-27: a non-literal command word passes, and only its nested scripts are checked.
- Lead, 2026-10-27: apt, apt-get and systemctl verbs are refused anywhere among the literal arguments; `<>` is an output redirection; `env -S` is lexed.
- The `stdbuf -io L` dispute is closed (`work/status.md`: the builder was right). The test uses `stdbuf -i0 -oL rm x`.

Checks CHK-M7-115 to -121; mutation rows CHK-M7-327 to -332. Test file: `manager/tests/test_bit102.py`. Corpora: `bits/tests/bit102/must_reject.json` (149) and `must_pass.json` (96). Implementation: `manager/bitscan_manager/services/importer/bit102.py` (impl report `work/reports/TASK-146-impl.md`, revision 1).

C is as in `work/reports/TASK-144-test.md`. Unit-only; no PostgreSQL needed. Plants are in the same scratch copy.

## Runs

| Run | Where | Command | Count |
| --- | --- | --- | --- |
| r0 (as found) | C | `pytest -q -p no:cacheprovider tests/test_bit102.py` | 1160/1160 passed, 0 failed, 0 errors, 0 skipped (matches the lost run) |
| r1 (final, with added tests) | C | same | 1177/1177 passed, 0 failed, 0 errors, 0 skipped |
| dependents | C | `pytest -q tests/test_bit_validate.py` (runs `check_execute` on every fixture); `tests/test_bit_fixtures.py tests/test_bit_fuzz.py` | 689/689; 231/231 passed |
| load | C | full suite `pytest -n 8`, 3 times | 8143/8143, 8145/8145, 8147/8147 passed |
| static | C | ruff, ruff format, `mypy --strict --config-file manager/pyproject.toml manager` | clean; 276 files |

## Tests added (tester-owned; 17 cases, nothing weakened)

- `test_wrapper_long_option_values_do_not_hide_the_command` (13). #108 (d) says "skipping its options". A long option with its value as the next word must not hide the command: `sudo --user root rm x`, `sudo --group adm`, `env --unset HOME`, `env --chdir /`, `nice --adjustment 5`, `ionice --class 3`, `stdbuf --output L`, `timeout --signal KILL 5`, `timeout --kill-after 1 5`, `chroot --userspec a:b /`, and `env --split-string 'rm x'`, `env -iS 'rm x'`, `env -iS'rm x'`.
  - Plant `B-long-opt-value` (a long option's separate value not skipped) **survived** the 1160 tests as found. That is a #108 (d) bypass (`root` would be taken as the command, hiding `rm`).
  - Now red (10 failed). The `-iS` rows also make the new plant `B-envS-cluster` red.
- `test_sed_in_place_abbreviations` (4): `sed --in`, `--in-pl`, `--in-pl=.bak`, `-n --i`. SR §4.2 refuses `--in-place`, and GNU getopt accepts any unique prefix of it. Plant `B-sed-long-abbrev` (only the full `--in-place` matched) **survived**; it is now red (4 failed).

The code already handled every added case (the impl report's r1 probes list them). The gap was in the tests only. No product bug.

## Acceptance criteria (tasks.md TASK-146)

| Criterion | Check | Result |
| --- | --- | --- |
| Every must-reject case gets BIT102 with the offending token in its message | CHK-M7-115 | PASS: 149/149, each finding BIT102, Reject, at the caller's line and element, and the corpus token in a message |
| Every simple command anywhere (pipelines, lists, subshells, substitutions, `-c` scripts) | CHK-M7-116 | PASS: 24 corpus cases × 27 contexts = 646 rows: `|`, `;`, `&&`, `||`, `&`, `( )`, `{ ; }`, `if`, `while`, `until`, `for`, `case`, function, `$( )`, backticks, `<( )`, `>( )`, `!`, assignment, `"$( )"`, `${x:-$( )}`, here-document, `bash -c`, `sh -c`, `dash -c`, `sudo`, `env`. Plus 10 substitutions in data words and input-redirection targets |
| #108 matching (paths, `mkfs.*`, wrappers, assignments) | CHK-M7-117 | PASS: 66 forms (`/bin/rm`, `../../bin/rm`, `mkfs.ext4`, 13 wrappers with options, `FOO=1 rm`, `sed` clusters and `--in-place`, apt and systemctl verbs after option values, `dpkg --purge=x`); 11 short-cluster rows (r1 fix, incl. `stdbuf -i0 -oL rm x`); 13 + 4 added rows |
| Redirections | CHK-M7-118 | PASS: 25 refused (incl. `/tmp/../etc/x`, `"$F"`, `$HOME/x`, `/tmpx`, `/tmp`, `&>`, `>&`, `<>`, `/dev/sda`, `/tmp/$(id -u)`); 18 pass (`/dev/null`, `/dev/stdout`, `/dev/stderr`, `/tmp/…`, `2>&1`, `>&2`, `>&-`, input forms, `<>/tmp/x`) |
| Code-running forms | CHK-M7-119 | PASS: 36 rows: `.`, `source`, `eval`, `exec`, `xargs`, the 4 `find` actions, shells without `-c` (file, `-s`, stdin, `<`), `-c` with `$( )`, backticks, `<( )`, `${…$( )}`, here-document substitution, `-c` scripts checked (also through `-o pipefail`, `-ec`, `--`, nested `sh -c`), `env -S` forms, `sudo sh -c`, `busybox sh -c` |
| No case of the must-pass corpus (the SR §1.1 `Execute` included) gets BIT102 | CHK-M7-120 | PASS: 96/96 corpus (first entry = the SR §1.1 `Execute`, extracted from the spec); all 32 `Execute`s in `bits/samples/` read through the real parser; 47 ruled and read-only forms (the lead's false-positive guards, the user's 6 non-literal forms, `command -v`/`-V`, here-document with a quoted delimiter, `sed -ei`, `sed -- -i`) |
| Unlexable `Execute` is BIT102 (fail closed) | CHK-M7-121 | PASS: 13 unlexable inputs give exactly one "cannot be checked" BIT102; 10 nested `sh -c` levels fail closed |
| Messages | — | PASS: the token as written (`r''m`, `"rm" (via "sudo")`); a 16,000-char target never whole, under 300 chars; `\x01` escaped; one finding per distinct offence, in order; 3,000-example fuzz never raises, each under 1 s CPU |

Accepted residual risk (user decision 2026-10-27, `work/decisions.md`): `c=rm; "$c" -rf /` passes BIT102 and is tested as must-pass. The runner sandbox (TS §3.7, M10) is the control. This report notes it, as the decision asks.

## Plants (scratch copy; tests run: `tests/test_bit102.py tests/test_bit_validate.py`, 1866 tests, `-n 4`)

Security rows (tasks.md mutation table):

| Plant | Change | Result |
| --- | --- | --- |
| CHK-M7-327 | substring search over `Execute` for the listed words instead of the lexer | red, 473 failed (incl. `test_not_a_substring_search`: `echo "rm"` rejected, `r''m` accepted) |
| CHK-M7-328 | path-qualified names not reduced (`name = value`) | red, 14 |
| CHK-M7-329 (a) | nested scripts (`$( )`, backticks, `<( )`, here-documents) not walked (`_nested` empty) | red, 188 |
| CHK-M7-329 (b) | `-c` scripts not checked | red, 88 |
| CHK-M7-329 (c) | data words (`for` lists, `case` words) not walked | red, 5 |
| CHK-M7-329 (d) | redirect-target substitutions not walked | red, 5 |
| CHK-M7-330 (a) | `WRAPPERS` empty | red, 127 |
| CHK-M7-330 (b) | `busybox` dropped from `WRAPPERS` | red, 3 |
| CHK-M7-331 (a) | any redirect target accepted | red, 69 |
| CHK-M7-331 (b) | `..` component allowed under `/tmp/` | red, 3 |
| CHK-M7-331 (c) | non-literal target (`"$F"`) accepted | red, 7 |
| CHK-M7-331 (d) | `/tmp` prefix without the slash | red, 4 |
| CHK-M7-332 (a) | `check_execute` returns `[]` on `ShellSyntaxError` (fail open) | red, 13 |
| CHK-M7-332 (b) | an unlexable `-c` script passes | red, 2 |

Revision 1 and further rule plants:

| Plant | Change | Result |
| --- | --- | --- |
| B-r1-cluster | the r1 bug back: a short cluster whose letter takes a value (`-iu root`) skipped as one word | red, 8 |
| B-r1-next-word | a value-taking short option never takes the next word | red, 17 |
| B-long-opt-value | a long option's separate value not skipped | red, 10 (after the added test) |
| B-envS-cluster | `env -S` found only as the first letter of a cluster | red, 2 (added test) |
| B-envS-unchecked | `env -S` strings not checked | red, 6 |
| B-sed-cluster | `sed -i` only as the whole word | red, 5 |
| B-sed-long-abbrev | `--in-place` only in full | red, 4 (after the added test) |
| B-verb-first-only | apt/systemctl/dpkg/find only the first argument checked | red, 44 |
| B-dpkg-eq | `dpkg --opt=value` forms not matched | red, 5 |
| B-mkfs-dot | `mkfs.*` not matched | red, 6 |
| B-find-okdir | `-okdir` dropped | red, 2 |
| B-write-word-tee | `tee` dropped | red, 27 |
| B-code-xargs | `xargs` dropped | red, 30 |
| B-apt-autoremove | `autoremove` dropped | red, 2 |
| B-systemctl-setprop | `set-property` dropped | red, 1 |
| B-sh-c-subst | `-c` word holding a substitution allowed | red, 3 |
| B-sh-c-literal-subst | a literal `-c` script holding a substitution allowed | red, 7 |
| B-sh-no-c | a shell without `-c` allowed | red, 43 |
| B-ltgt-input | `<>` treated as input | red, 1 |
| B-nonliteral-reject | a non-literal command word rejected (against the user's ruling) | red, 9 |
| B-command-v-runs | `command -v`/`-V` treated as running the command | red, 1 |
| B-assignments-unchecked | substitutions in assignments not walked | red, 25 |
| B-msg-unquoted | token not quoted in messages | red, 2 |
| B-sed-skip-value | `-e`/`-f`/`-l` no longer take the next word | **survived** (see below) |

**38/39 red; all 14 security rows red.** The survivor, `B-sed-skip-value`, errs toward rejecting. Without the skip, an `-e`/`-f`/`-l` value that starts with `-` and holds an `i` (for example `sed -f -i.sed f`, where GNU sed reads `-i.sed` as a script file) would be refused as in-place. No realistic CIS command has such a value, and the change can only add rejections, never hide one. So it is not a security row, and I added no contrived must-pass case. Reviewer: please confirm, or ask for a must-pass row.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-115 | CODE | C | `pytest -q tests/test_bit102.py -k "must_reject and not context or corpora"` | PASS | 149/149 with token | 2026-10-27 |
| CHK-M7-116 | CODE | C | `pytest -q tests/test_bit102.py -k "every_context or context_count or data_words"` | PASS | 646 + 10 rows | 2026-10-27 |
| CHK-M7-117 | CODE | C | `pytest -q tests/test_bit102.py -k "108_matching or wrapper or abbreviations"` | PASS | 66 + 11 + 13 + 4 rows | 2026-10-27 |
| CHK-M7-118 | CODE | C | `pytest -q tests/test_bit102.py -k "redirections"` | PASS | 25 refused, 18 pass | 2026-10-27 |
| CHK-M7-119 | CODE | C | `pytest -q tests/test_bit102.py -k code_running` | PASS | 36 rows | 2026-10-27 |
| CHK-M7-120 | CODE | C | `pytest -q tests/test_bit102.py -k "must_pass or sample or sr_example or ruled or substring"` | PASS | 96 + 32 + 1 + 47 rows | 2026-10-27 |
| CHK-M7-121 | CODE | C | `pytest -q tests/test_bit102.py -k "unlexable or depth_8"` | PASS | 13 + 1 rows, one "cannot be checked" finding | 2026-10-27 |
| CHK-M7-327 | CODE | C | plant: substring search | PASS (red) | 473 failed | 2026-10-27 |
| CHK-M7-328 | CODE | C | plant: `/bin/rm` not reduced | PASS (red) | 14 failed | 2026-10-27 |
| CHK-M7-329 | CODE | C | plants (a)–(d): nested, `-c`, data words, redirect targets not walked | PASS (red) | 188, 88, 5, 5 failed | 2026-10-27 |
| CHK-M7-330 | CODE | C | plants: `WRAPPERS` empty; `busybox` dropped | PASS (red) | 127, 3 failed | 2026-10-27 |
| CHK-M7-331 | CODE | C | plants (a)–(d): any target, `..`, `"$F"`, `/tmp` without slash | PASS (red) | 69, 3, 7, 4 failed | 2026-10-27 |
| CHK-M7-332 | CODE | C | plants: fail open in `check_execute` and in `-c` scripts (lexer half in TASK-145) | PASS (red) | 13, 2 failed | 2026-10-27 |
| CHK-M7-146-extra | CODE | C | 24 rule plants (table above) | PASS (23 red, 1 survivor that errs toward rejecting) | see table | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 276 files | 2026-10-27 |

Verdict: **PASS**. 1177/1177 passed, 0 failed, 0 errors, 0 skipped. Plants: 38/39 red, with every security row red.
