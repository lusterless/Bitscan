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

---

# TASK-146 TEST (revision 2 final): PASS

Tester: tester-m7d, 2026-10-27. Code under test: `0529083`. The r2 final code is `8173527`; it includes the three fixes in (6) for this tester's findings, and TASK-145 r1b is on top. Impl report: `work/reports/TASK-146-impl.md` "Revision 2", items (1) to (6). Review being answered: `work/reviews/TASK-146.md` findings 1 and 2 (blocking) and 3 (should-fix, tester-owned).

Rulings tested as written (`work/decisions.md`):
- the r2 order: the wrappers time, nsenter, unshare, flock, setpriv, taskset, chrt, `su -c` and runuser, plus brace expansion in bash mode;
- trap is refused whenever it sets an action;
- alias with a definition, `hash -p`, let, and `${…@P}` / `${…@E}` are refused;
- the readings the lead accepted (`trap SIG` passes; `sudo VAR=value cmd`);
- "three more fail-open forms" (the env `--` and nsenter `-S`/`-G` fixes, and `sudo -s`/`-i` and `doas -s` with no command are BIT102);
- the `sudo -e` residual, which has no test.

Spec: SR §4.2 L277–L287, §4.1 BIT102, §1.1; TS §3.3 L249.

Environment C and the scratch copy are as in `TASK-145-test.md` "revision 1 and 1b". GNU `time` 1.9 was installed in the container for the real-shell checks. `doas` is not installed, so its rows follow the ruling without a shell run.

## Runs

| Run | Command (from `manager/`) | Count |
| --- | --- | --- |
| as found (r2 snapshot, before my rows) | six files, `-n 4` | 2548/2548 passed |
| r2 + my rows, before (6) | `pytest -q tests/test_bit102.py` (scratch probe) | the 4 `env --` rows and the 4 `nsenter -S +0` rows not refused (bugs 1 and 2 below) |
| r2 final (`8173527`) + all rows | `pytest -q -p no:cacheprovider -n 4` on the six files | 2977/2977 passed |
| final (`0529083`) | `pytest -q -p no:cacheprovider -n 4 tests/test_bit102.py` | 1555/1555 passed, 0 failed, 0 errors, 0 skipped |
| final, six files, 3 runs | `pytest -q -p no:cacheprovider -n 4 tests/test_bit102.py tests/test_bit102_lexer.py tests/test_bit_fixtures.py tests/test_bit_fuzz.py tests/test_bit_parse.py tests/test_bit_validate.py` | 2981/2981 passed, 3 times |
| static (repo root) | `ruff check manager`; `ruff format --check manager`; `mypy --strict --config-file manager/pyproject.toml manager` | clean; 278 files |

The existing corpus still passes:
- the 96 old must-pass rows;
- the SR §1.1 `Execute` (`test_sr_example_execute_passes`);
- every `Execute` in `bits/samples/*.bit`, read through the real parser (`test_every_sample_execute_passes`);
- the 149 old must-reject rows and their 646 context rows.

## Findings (product; all three fixed in r2 (6), real-shell checked)

1. **env reads `-` and `NAME=value` after `--`** (#108 (d)). `env -- FOO=1 rm x`, `env -- - rm x`, `env -i -- FOO=1 rm x` and `env -u HOME -- FOO=1 rm x` all passed BIT102. Under dash, coreutils 9.4 runs the command in each (`dash -c 'env -- FOO=1 echo RAN'` prints RAN). sudo is not affected (`sudo -- FOO=1 echo RAN`: command not found). The implementer widened the fix to any operand holding `=` (`env a-b=1`, `env 1=2`, `env "$x"=1`, `sudo a-b=1`); all four run under dash, checked here.
2. **nsenter `-S`/`-G`/`--setuid`/`--setgid` take the next word as a required argument in util-linux 2.39.3**, even though `--help` prints `[=<uid>]`. `nsenter -S echo RAN` gives "failed to parse uid: 'echo'". `+0` and `' 0'` parse as uid 0, so `nsenter -S +0 rm x`, `-S ' 0'`, `--setuid +0` and `-G +0` passed BIT102 while nsenter runs the command. Now a non-decimal value is "cannot be checked".
3. **`sudo -s` / `sudo -i` / `doas -s` with no command start a root shell that reads stdin.** `echo 'echo RAN' | sudo -s` prints RAN, and the same holds for `-i`. The lead ruled them BIT102. With a command, the words are checked as a script. sudo really escapes the words (`sudo -s 'echo RAN; echo TWO'` runs one command named `echo RAN; echo TWO`), so refusing `sudo -s 'ls; rm x'` is stricter than sudo. The ruling allows that.

## Tests added (tester-owned; nothing weakened, corpus size guards raised to 386 / 190)

- `bits/tests/bit102/must_reject.json` gets 199 TASK-146 rows (`rule` starting `146`), each with the token its message must hold:
  - 39 wrappers naming `rm`, plus 14 wrapper rows that fail closed;
  - 20 brace expansions, plus 4 brace rows that fail closed (unmatched, nested, 257 words, 65 levels), plus 1 brace inside a trap action;
  - 19 trap/alias/hash/let rows and 7 `@P`/`@E` rows;
  - 12 shell-option rows, plus 6 that fail closed;
  - 20 old-wrapper abbreviation and unknown-option rows (`option "--un"` …), plus 10 rows that still name `rm`;
  - 4 `env --` rows and 7 sed attached-value rows (review finding 3: `sed -es/a/b/ -i f`, `sed -l5 -i f`, `sed -nfx -i f`, `-l5 -i p f`, `-fx -i f`, `--line-length=5 -i p f`, `--expression=p -i f`);
  - 36 rows for (6).
- `must_pass.json` gets 94 rows in all, including the TASK-145 ones:
  - every must-pass list in the impl report, and the (6) list;
  - `trap -p 'rm x' EXIT` and `trap -l 'rm x' EXIT`: neither shell sets an action (dash: "Illegal option -p"; bash: invalid signal spec);
  - `sudo -l`, `sudo -v`, `sudo -k`;
  - `sed -es/a/b/ f`, `sed -l5 p f`, `sed -nfx f`.
- `manager/tests/test_bit102.py`:
  - `test_sed_attached_value_does_not_take_the_next_word` (7), and `test_sed_separate_value_is_taken` (2; `sed -e -i f`, `sed -l 5 p f`). The second is the opposite pin that the r1 survivor `B-sed-skip-value` lacked;
  - `test_brace_expansion_word_limit_256` (256 words pass, 257 refused), `test_brace_nesting_limit_64` (64 pass, 65 refused) and `test_brace_expansion_only_in_bash_mode`;
  - `test_shell_option_values_are_not_the_script` (7; the script is found, not "without -c") and `test_shell_option_values_with_read_only_script_pass` (3);
  - `test_code_defining_builtins_use_the_eval_message` (8), `test_listing_and_reset_forms_pass` (16) and `test_at_p_message_is_the_fail_closed_one`.

## Real-shell confirmation (scratch `sh146/shellprobe.py` with `shellprobe.json`; `rm` replaced by `echo RAN`; sed rows edit a scratch file `f`)

- **The hidden command really runs: 150 rows.** Each is the Execute run by `dash -c` (bash for the `<(`/`>(`, `@P` and `let` rows); the `echo RAN` stand-in prints RAN, or sed edits `f` in place:
  - every wrapper row except the 5 below;
  - every brace row (bash expands `{echo,RAN}`, `ech{o..o}`, `"e"{cho,}`, `{sh,-c,'echo RAN'}` …);
  - every shell-option row (`-co`, `-oc`, `-Oc`, `+oc`, `-c -`, `-c -o`, `--rcfile`, `+c`);
  - the abbreviations that real getopt accepts (`env --un`/`--ch`/`--sp`, `nice --adj`, `timeout --sig`/`--pres`, `stdbuf --out`, `sudo --us`/`--gr`, `chroot --sk`, `setsid --fo`, `nsenter --targ`, `setpriv --reu`);
  - `echo 'rm x' | su root` and `su root -- -c 'rm x'`;
  - the trap, alias, hash, let and `@P` rows;
  - the `env --` and `nsenter -S +0` rows;
  - 6 of the 7 sed rows.

  The (6) rows were run by hand: `env a-b=1`, `env 1=2`, `sudo a-b=1`, `env "$x"=1`, `env -- - FOO=1 a-b=2`, `nsenter -S0`, `nsenter -S 0 -t $$`, `sudo -iu root CMD`, `sudo -s FOO=1 CMD`, `sudo --shell CMD`, `sudo --login` (stdin), `sudo -s -- CMD` and `sudo -sk CMD` each print their RAN.
- **The shell itself refuses or runs nothing: 52 rows.** These are fail-closed or ruling rows, where refusing is the safe side:
  - unknown options, `--flag=x`, `chrt -o`, `bash --rcf`, `sh -q`;
  - the brace fail-closed rows (bash's reading differs, or the expansion is too large);
  - `trap ''`, `trap "$a"`, `trap 0 'ls' EXIT`, `hash -p` under dash (bash only), `let x=1`, `${x@E}` (expands escapes only);
  - `x=$(cat <<'E' $(⏎…)⏎)` (syntax error in both shells);
  - `nsenter -S rm x` (uid parse error);
  - `flock -c 'rm x' /tmp/l`: flock 2.39 says "invalid option -- 'c'", because `-c` is only valid after the file;
  - `chrt -T 1 -P 2 -D 3 -d 0` (EINVAL here);
  - `runuser -l nobody -c` (nologin; with root it runs);
  - `sudo -h host` (sudo refuses a remote host);
  - `sed -l5 -i f`, which has no script (the `-l5 -i p f` variant edits `f`).
- **Skipped: 5 rows.**
  - `bash -c 'systemctl {stop,status} ssh'`, which would stop ssh;
  - `su root /tmp/script` (no script);
  - `alias r=rm`, `alias -p r=rm` and `builtin alias r=rm`, which define an alias and run nothing (the `alias r=echo⏎r RAN` row runs).

## Plants (scratch copy; `tests/test_bit102.py tests/test_bit102_lexer.py`, `-n 4`; `scratchpad/plants_r2.json`, runner `plant2.py`)

| Plant | Change | Red |
| --- | --- | --- |
| W-SPECS-empty | no r2 wrappers | 67 |
| W-WRAPPERS-empty | no #108 (d) wrappers | 196 |
| W-unknown-option-taken-1 | an unknown option (incl. abbreviations) takes 1 word | 23 |
| W-flag-eq-accepted | `--flag=x` accepted | 3 |
| W-optional-as-value | optional letters take the next word | 4 |
| W-numeric-else-1 | nsenter `-S` non-decimal value read as the command (the bug-2 code) | 8 |
| W-time-dropped | external `time` not a wrapper | 9 |
| W-chrt-priority-unchecked | chrt non-decimal priority not refused | 3 |
| W-flock-file-c-unchecked | `flock FILE -c CMD` not checked | 4 |
| W-su-no-permute | su/runuser do not permute | 6 |
| W-su-without-c-allowed | su without `-c` allowed | 7 |
| W-su-script-unchecked | su/runuser/flock `-c` scripts not checked | 18 |
| W-env-after-dashdash | env stops at `--` (the bug-1 code) | 5 |
| W-sets-var-is-assignment | `_sets_var` back to `is_assignment` | 6 |
| W-sudo-assignment-skip-dropped | `sudo FOO=1` not skipped | 5 |
| W-sudo-shell-no-command-allowed | `sudo -s` with no command allowed | 12 |
| W-sudo-shell-command-unchecked | `sudo -s CMD` not checked | 10 |
| W-sudo-shell-rule-dropped | the sudo/doas shell rule removed | 14 |
| S-oO-take-no-word | `o`/`O` take no word (r1 blocking 1) | 16 |
| S-O-not-value | only `o` takes a word | 7 |
| S-lone-dash-not-consumed | a lone `-` not consumed | 6 |
| S-unknown-letter-accepted | an unknown shell letter accepted | 1 |
| S-long-prefix-accepted | any shell long option accepted | 4 |
| S-rcfile-takes-no-word | `--rcfile` takes no word | 1 |
| B-bash-false | no brace expansion | 29 |
| B-dash-is-bash | brace expansion for sh/dash too | 3 |
| B-su-script-dash-mode | su `-c` scripts not in bash mode | 3 |
| B-cap-unbounded | the 256-word cap removed | 3 |
| B-depth-unbounded | the 64-level cap removed | 3 |
| B-no-sequences | `{x..y}` not expanded | 3 |
| B-empty-word-kept | a word that expands to nothing kept | 1 |
| R-defines-code-false | trap/alias/hash/let never refused | 28 |
| R-let-dropped | let allowed | 5 |
| R-alias-dropped | alias definitions allowed | 8 |
| R-hash-dropped | `hash -p` allowed | 5 |
| R-trap-dropped | trap actions allowed | 12 |
| R-trap-reset-refused | `trap - SIG` refused (false positive) | 5 |
| R-trap-listing-ignored | `trap -p/-l …` refused (false positive) | 4 |
| R-trap-one-operand-refused | `trap SIG` refused (false positive) | 2 |
| R-atP-atE-dropped | `${…@P}`/`${…@E}` not refused | 17 |
| R-atE-dropped | only `@P` refused | 3 |
| T-time-always-keyword | `Grammar.time()` always `[]` | 6 |
| D-sed-attached-skips-next | an attached `-e`/`-f`/`-l` value also skips the next word (review finding 3) | 11 |
| D-sed-long-eq-skips-next | `--expression=…` also skips the next word | 5 |
| D-sed-skip-value (r1 survivor) | `-e`/`-f`/`-l` never take the next word | 1 (`sed -e -i f`) |

**45/45 red**, the r1 survivor included.
- Every security row (W-*, S-*, B-bash-false, B-cap/B-depth, R-*-dropped, R-defines-code-false, R-atP-atE-dropped, D-sed-*) is red.
- The `shlex_grammar.py` plant (T-time) was re-run on `0529083`.
- Red counts leave out the extra `test_long_inputs` failure explained in the TASK-145 section (a stored quadratic example). Each plant above has a red test of its own.

## For the reviewer

- **Stricter than the shell, which is the safe side:**
  - `flock -c CMD FILE`, because flock 2.39 rejects `-c` before the file;
  - `sudo -s 'a; b'`, because sudo escapes it;
  - `coproc` at the top level under dash.
- **Brace sequences.** `bit102_brace._sequence` accepts any single character, while bash expands only letters (`{....}` stays literal). The impl over-expands, which is the safe direction: a literal bash word is never hidden.
- **Possibly in the open "arithmetic subscript" class (decisions 2026-10-27, open for the user).** bash `${!x}` indirection with `x='a[$(cmd)]'` runs `cmd` (checked: `a=(1); x="a[\$(echo RAN >&2)0]"; echo ${!x}` prints RAN). It is not in the rulings, so I added no test; main may add it to the open item.
- **Hypothesis database.** Once a slow example was stored, `test_long_inputs_up_to_16384_chars` failed on every run in that checkout, but a fresh database would not find it again. The deterministic `fndefs` rows now pin the case.

## Report rows (tests/m7/report.md format; main folds them in)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-115 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k must_reject` | PASS | 386/386 rows with token (199 new for TASK-146 r2); 150 real-shell RUNS | 2026-10-27 |
| CHK-M7-117 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "must_reject or sed_attached or sed_separate"` | PASS | 39 + 14 wrapper rows, 30 old-wrapper rows, 36 (6) rows, 7 + 2 sed rows | 2026-10-27 |
| CHK-M7-119 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "shell_option or code_defining or listing_and_reset or at_p"` | PASS | 7 + 3 + 8 + 16 + 1 | 2026-10-27 |
| CHK-M7-120 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "must_pass or sample or sr_example or ruled"` | PASS | 190 corpus (SR §1.1 first) + every `bits/samples` Execute | 2026-10-27 |
| CHK-M7-121 (r2) | CODE | C | `pytest -q tests/test_bit102.py -k "brace_expansion or brace_nesting"` and the fail-closed corpus rows | PASS | 256/257 and 64/65 bounds; 24 fail-closed corpus rows | 2026-10-27 |
| CHK-M7-330 (r2) | CODE | C | plants W-* (18) | PASS (red) | 18/18 | 2026-10-27 |
| CHK-M7-146-r2-plants | CODE | C | `python plant2.py plants_r2.json` | PASS (red) | 45/45 | 2026-10-27 |
| static | CODE | C | ruff, ruff format, mypy (CI form) | PASS | clean, 278 files | 2026-10-27 |

Verdict: **PASS** (r2 final). 1555/1555 passed in `test_bit102.py`; 2981/2981 passed across the six files, 3 times; 0 failed, 0 errors, 0 skipped. Plants: 45/45 red. Three fail-open forms were found by this round and fixed in r2 (6) before the verdict.
