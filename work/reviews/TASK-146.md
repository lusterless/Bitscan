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
