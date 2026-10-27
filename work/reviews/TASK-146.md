# TASK-146 REVIEW: BIT102 rules (revision 1)

Verdict: CHANGES_REQUESTED

Reviewer: reviewer-m7, 2026-10-27. REQ-157, REQ-177, REQ-180; #108. High risk (importer; two approvals, PD-35).

Scope reviewed: frozen worktree at `e2d569c`, `manager/bitscan_manager/services/importer/bit102.py` (337 lines), per `work/reports/TASK-146-impl.md` r1. The lead accepted the size.

The r2 items are being built separately and are not counted here: `time`, `nsenter`, `unshare`, `flock`, `setpriv`, `taskset`, `chrt`, `su -c`, `runuser`, `trap`, and brace expansion in `bash -c`.

TEST: PASS (`work/reports/TASK-146-test.md`; 1177/1177, 38/39 plants red, every security row red). My re-run is as in TASK-144.md.

Spec read: SR §4.2 L277–L287, §4.1 BIT102, TS §3.3 L249, §3.7, §8.1. Rulings applied:
- the user's non-literal command word ruling;
- the lead's ruling on verbs anywhere, `<>` as output, and `env -S`.

Each bypass below was run here under `dash` and/or `bash` (and coreutils/sudo 1.9.15), with `echo` in place of `rm`.

## Checks
- **SR §4.2 lists.** The write words, `mkfs.*`, the code words, `sed -i` (clusters, `--in-place`, and its abbreviations), the dpkg options (exact and `=value` forms), the apt and systemctl verbs, the `find` actions, and shells without `-c` all match SR §4.2 and #108 (a), (b), (e), (f), (g).
- **Walk (#108 (c)).**
  - Every command is checked, along with assignments, redirect targets, here-document scripts and data words.
  - `-c` scripts are lexed again under the shared depth cap.
  - A `-c` substitution is refused (SR L285).
- **Redirections (#108 (i)).**
  - A target passes only if it is literal and exactly one of the three devices, or `/tmp/…` with no `..` component.
  - Dups (`>&N`, `>&-`) pass.
  - `&>`, `>&file` and `<>` count as output.
- **Fail closed.** A `ShellSyntaxError` at the top level or in a `-c` or `env -S` string is BIT102. Messages are fixed text plus `quote()`.
- **Invariants.**
  - No `re`, nothing executed, and no ad-hoc command path.
  - Nothing beyond SR §4.2 is added except the three choices the lead ruled on.

## Findings
1. **blocking**, `bit102.py:279-289` (`_shell`), against #108 (f) and SR §4.2 "-c … script checked". The shell's own option parsing is not followed, so the word taken as "the script" is not the one the shell runs. Each of these passes with no finding, and the shell runs `rm x`:
   - **`o`/`O` in a cluster with `c`:** `bash -co pipefail 'rm x'`, `bash -oc pipefail 'rm x'`, `bash -Oc extglob 'rm x'` and `sh -co errexit 'rm x'`. The `o`/`O` in the cluster takes the next word, so `pipefail` is treated as the script.
   - **`-` as the end of options:** `sh -c - 'rm x'` and `bash -c - 'rm x'`. Both shells treat a lone `-` as `--`. Line 283 consumes only `--`, so `-` becomes the script.
   - **Fix.** In a short cluster, each `o`/`O` letter takes one following word, in order. Treat `-` like `--` (consume it).
   - **Tests.** Add these as must-reject rows, with the `-c` script checked.
2. **blocking**, `bit102.py:178-183` (`_option`, long options), against #108 (d) "skipping its options". getopt_long accepts any unique prefix of a long option, and only exact names are in `WRAPPERS`. So an abbreviated option's value is taken as the command. Each of these passes, and the wrapped command runs (checked with GNU coreutils and sudo here):
   - `env --un HOME rm x`, `env --ch / rm x` and `env --sp 'rm x'` (the last also skips the `-S` check);
   - `nice --adj 5 rm x`, `timeout --sig KILL 5 rm x`, `stdbuf --out L rm x`;
   - `sudo --us root rm x`, `sudo --gr root rm x`.

   This is the same class as the r1 cluster FAIL. The tester's added long-option test uses full names only. TASK-146-test.md lists the `sed` abbreviations as handled, but not these.
   - **Fix.** Match a long option without `=` against each wrapper's value-taking long names by prefix, getopt_long style. An ambiguous or unknown prefix should err toward taking the next word, and that word should also be checked as a command.
   - **Tests.** Add must-reject rows for each wrapper's abbreviation.
3. **should-fix (test gap; tester-owned)**, `manager/tests/test_bit102.py:172-177` and `bits/tests/bit102/must_reject.json`.
   - **The gap.** No row pins `_sed_in_place`'s attached-value rule at `bit102.py:271`, where `-e`, `-f` or `-l` with an attached value does *not* take the next word.
   - **The plant it misses.** "Always skip the next word after `e`/`f`/`l`" would hide `sed -es/a/b/ -i f`, `sed -l5 -i f` and `sed -nfx -i f`, which is the unsafe direction. The code handles all three today, so only the tests need to change.
   - **Fix.** Add those rows as must-reject.

## Tester's questions
- **Wrapper long-option values:** confirmed as a correct #108 (d) reading. Finding 2 extends them to abbreviations.
- **`sed --in` abbreviations:** confirmed (GNU getopt accepts unique prefixes; `--i…` is unique to `--in-place`).
- **`B-sed-skip-value` survivor:** confirmed acceptable with no must-pass row. Without the skip, the code only adds rejections (for example `sed -f -i.sed f`), which is the safe direction. Finding 3 asks for the opposite pin instead.
- **Residual `c=rm; "$c" -rf /`:** confirmed as the user's ruling, recorded in:
  - `work/decisions.md` (2026-10-27);
  - the `work/open-questions.md` M7 section;
  - the impl report;
  - the test report, where it is a must-pass row.

  It still has to go in the M7 PR text (lead).

## For main (spec silent; not counted against r1)
These forms are all literal, or are data that the shell runs as code. None is in SR §4.2 or #108, and #108 (k) says nothing is added. Checked here:
- **dash (`/bin/sh`, so every plugin):** `alias r=rm` followed on the next line by `r -rf /x` runs `rm`.
- **bash only (`bash -c`):**
  - `let 'a[$(rm x)]=1'`;
  - `x='$(rm x)'; : ${x@P}`;
  - `hash -p /bin/rm ls; ls -rf /x`.

The user should decide whether these join the `c=rm` accepted residual, or whether `alias` (and perhaps `hash`, `let`) become code words in r2.

## Revision 2 re-review (2026-10-27)

Verdict: APPROVED

Frozen worktree at `64315ca`, product code `0529083`. Files:
- `bit102.py` (401 lines);
- `bit102_wrap.py` (new, 230);
- `bit102_brace.py` (new, 130);
- the r2 hunks of `shlex_grammar.py` (`time()`) and `shlex_posix.py` (`@P`/`@E` in `scan()`).

The size (~680 changed lines) was accepted by the lead (decisions.md, 2026-10-27). I reviewed it in the three seams the lead set.

TEST: PASS (`TASK-146-test.md` revision section: 1555/1555, 45/45 plants red). Every must-reject row was run under real dash or bash by the tester. My re-run is as in TASK-145.md: 2981 passed, gates clean.

Rulings applied (decisions.md from "TASK-146 revision 2 ordered" on):
- the r2 order;
- trap;
- alias, hash, let, `@P` and `@E`;
- the review-round-1 routing;
- the r2 size and the implementer's readings;
- `env --`, `nsenter -S`/`-G` and `sudo -s`/`-i`;
- the `sudo -e` residual.

### Round-1 findings
1. **Blocking, shell option parsing: fixed.**
   - `_shell` (`bit102.py:333-364`) consumes one word per `o`/`O` letter in a cluster, in order. It consumes a lone `-` or `--`. It takes a word for `--rcfile`/`--init-file`, accepts only the exact bash long flags, and fails closed on any other long option or on a letter outside the bash and dash sets.
   - The tester's rows cover `-co`, `-oc`, `-Oc`, `+oc`, `-oO … …`, and `-c -` for sh, bash and dash. Both plants are red.
2. **Blocking, wrapper long-option abbreviations: fixed.**
   - All 13 #108 (d) wrappers now have full option tables (`bit102_wrap.WRAPPERS`), read by the same getopt-style `read_option()` as the r2 wrappers.
   - Any option not in a table fails closed with "cannot be checked". That covers abbreviations, unknown letters and `--flag=value`.
   - My eight forms are rows. The plant (`read_option` returning 1 for an unknown option) is red.
3. **Should-fix, sed attached values: fixed** (tester): 7 must-reject rows and 2 rows in the other direction. `B-sed-skip-value` is now red through `sed -e -i f`.

### r2 seams
- **Wrappers (`bit102_wrap.py`).**
  - Short clusters end at the first letter that takes a value. Values can be attached or the next word, and optional values are taken only when attached.
  - su and runuser permute; everything else stops at the first non-option.
  - `nsenter -S`/`-G` take the next word only when it is decimal, and otherwise fail closed.
  - `chrt` with a non-decimal priority fails closed. `su`/`runuser` with no `-c` count as a shell without `-c`.
  - The `-c` scripts of su, runuser and flock are lexed in bash mode with `$( )` allowed. That follows the `env -S` precedent: SR L285's ban names only sh, bash and dash.
  - `env` and `sudo` skip any operand holding `=`. env also does so after `--`.
- **`time`.** bash's keyword (with or without `-p`) is skipped. Any other option turns the words into an external `time` command, which `SPECS["time"]` reads. That is correct for `/bin/sh` being dash.
- **Brace expansion (`bit102_brace.py`).** It applies in bash mode only: `bash -c`, the su/runuser/flock/`sudo -s` scripts and their nested scripts. The Execute and sh/dash scripts are not expanded. Only unquoted literal text expands. Unclear forms fail closed (unmatched `{` with a comma, commas only inside nested braces, more than 256 words, more than 64 levels). Reviewed by reading it and through the tester's rows and plants (`bash=False`, and bash mode on for dash).
- **Code-defining builtins (`_defines_code`, `scan()`).** These match the user's rulings:
  - `let` is always refused;
  - `alias` is refused with any `=` or any non-literal argument;
  - `hash` is refused with a `p` letter;
  - `trap` is refused when it sets an action;
  - `${…@P}` and `${…@E}` are refused wherever a `${…}` is lexed, including unquoted here-document bodies and re-lexed `-c` scripts.

  Listing forms pass.

### `sudo -s`/`-i` ruling against #108 (f) and (k)
It is consistent with both, so it is not a finding.
- **#108 (f)** refuses a shell with no `-c`, including one that reads stdin (`… | sh`). `sudo -s`, `sudo -i` and `doas -s` with no command start the target user's shell on stdin, so the ruling applies (f) through the #108 (d) look-through. It adds no new word to the SR §4.2 lists, so **(k)** is not touched.
- With a command, sudo runs the words through the target shell. Checking them as a bash-mode script (`_sudo_shell`, `bit102.py:172-181`) is the same treatment as `su -c`.
- The one difference from sudo itself is that `sudo -s 'a; b'` is rejected even though sudo escapes the words. That errs toward rejecting, as the ruling says.

### Tester's points
- **`flock -c CMD FILE` refused even though flock rejects that form:** accepted. Nothing runs, so it only rejects more.
- **`sudo -s 'a; b'` stricter than sudo:** accepted, as above.
- **`_sequence` over-expanding single characters:** accepted. It is the safe direction, and only in bash mode.
- **bash `${!x}` with `x='a[$(cmd)]'`:** this is the open arithmetic-subscript class (`declare`, `printf -v`, `[[ -v ]]`, `(( ))`). main is putting it to the user, so it is not counted against r2.

### Findings
None blocking or should-fix.

1. nit, `shlex_posix.py:332`: the `@P`/`@E` refusal tests the raw source text of the `${…}`. Please add one lexer row confirming that a line continuation (`\` and a newline) between `@` and `P` inside `${…}` is still refused, or that the lexer removes it before this test.
2. nit, `bit102_wrap.py:36-41`: `_SU` lists `-u --user` for both su and runuser, but only runuser has them. With su they make it treat the operands as the command. su itself refuses `-u`, so this only rejects more.
