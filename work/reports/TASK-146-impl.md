# TASK-146 IMPL: BIT102 rules

Owner: impl-manager-m7b. REQ-157, REQ-177, REQ-180; #108. Spec: SR §4.2 (SR L277–L287), §4.1 BIT102; TS §3.7 (L505), §8.1 (L1244, L1255). Risk: high (importer; two approvals). Depends on TASK-145.

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/bit102.py` | new | 273 |

No other file was changed. The row estimated 170 lines. The extra is the #108 (d) wrapper option table, the `sed` cluster scan and the `sh -c` handling.

## Interface

`check_execute(execute: str, *, line: int, element: str) -> list[Finding]`. The caller (TASK-154) passes the **trimmed** `Execute`, the line of its start tag and its #105 (g) path (`plugin_path(n, "Execute")`). The result holds one `Finding` (code BIT102) per distinct offence, in source order. Each message is fixed text per rule that quotes the offending token through `model.quote` (at most 64 characters, controls escaped). An empty list means it passes.

## Rules (SR §4.2, #108)

Every simple command is checked wherever it appears. The walk covers `Script.commands`, every word's nested scripts (assignments included), redirect targets, here-document scripts and `Script.data_words`, and recurses into `-c` scripts (lexed again at depth + 1, capped by `MAX_DEPTH`).

- **Command words:** `rm`, `mv`, `cp`, `tee`, `dd`, `chmod`, `chown`, `chgrp`, `truncate`, `ln`, `install`, `mkfs`, `mount`, `umount`, and `mkfs.*`, matched on the last path component (`/bin/rm` and `./rm` count).
- **Other code:** `.`, `source`, `eval`, `exec`, `xargs`.
- **`sed`:** `i` anywhere in a short option cluster (`-i`, `-ni`, `-i.bak`); `-e`, `-f` and `-l` take the next word unless their value is attached. Also `--in-place[=…]` and every getopt abbreviation of it (any long option starting `--i`).
- **`dpkg`:** exactly `-i`, `-r`, `-P`, `--install`, `--remove`, `--purge`, `--configure`, and the `--opt=value` forms of the long ones.
- **`apt`/`apt-get` and `systemctl`:** a listed verb anywhere among the literal arguments. This is **stricter than #108 (g)'s "first non-option word"**, deliberately: options that take a value (`systemctl -p x stop ssh`, `apt-get -o a=b install x`) would otherwise hide the verb. A false positive needs a package or unit literally named after a verb. No must-pass case or sample is affected.
- **`find`:** `-exec`, `-execdir`, `-ok`, `-okdir` anywhere.
- **Wrappers (#108 (d)):** `env`, `command`, `builtin`, `nice`, `nohup`, `ionice`, `setsid`, `stdbuf`, `timeout` (after its duration), `chroot` (after its directory), `sudo`, `doas` and `busybox` are unwrapped. Their options are skipped; the options that take a value skip it too (table `WRAPPERS`); `env` also skips `NAME=value` and `-`.
  - `command -v` and `-V` run nothing.
  - `env -S` (`-S x`, `-Sx`, `--split-string[=]x`) is a command line itself, so it is lexed and checked. Its `$( )` is not refused, because `env` expands nothing.
  - The message shows the wrappers: `"rm" (via "sudo")`.
- **Shells (#108 (f)):** `sh`, `bash` and `dash` pass only with `-c` (also in a cluster such as `-ec`; `-o`/`-O` take a value) and a script.
  - Anything else is refused: a file argument, `-s`, no argument (`… | sh`) or an input redirection.
  - A script word holding `$( )`, backticks, `<( )` or `>( )` is refused (SR §4.2), and so is a literal script that holds one once lexed. A here-document substitution inside the script is refused as well.
  - The script is then checked like an `Execute`.
- **Output redirections (#108 (i)):** `>`, `>>`, `>|`, `&>`, `&>>`, `>&` to a file, and also `<>`, which opens for writing and creates. A target passes only if it is literal and exactly `/dev/null`, `/dev/stdout` or `/dev/stderr`, or starts with `/tmp/` with no `..` component. `>&2`, `2>&1` and `>&-` pass. Input operators, `<<<` and here-documents are not output.
- **Unlexable input** is one BIT102 finding, "Execute cannot be checked: <fixed reason>." (#108 (j)).
- **Non-literal command words are allowed by user decision 2026-10-27; the runner sandbox (TS §3.7, M10) is the control for them.** For `"$c" x`, `${x} y`, `$(echo rm) x`, `$'\x72m' x` and `sh -c "$s"`, only the nested scripts are checked; for example the `echo rm` inside `$(echo rm)` is checked, and passes. The same applies to a wrapper's non-literal target (`sudo "$c"`).
- **Nothing beyond SR §4.2 and #108 is refused (#108 (k))**, apart from the three choices in the next section.

## Stricter than #108 (lead ruling 2026-10-27)

These three choices were accepted by the lead. They are deliberate, so please don't flag them as findings.

1. **apt, apt-get and systemctl verbs are refused anywhere among the literal arguments**, not only as the "first non-option word" of #108 (g). SR §4.2's plain text has no position rule, and this closes a gap: an option's value could otherwise hide the verb (`systemctl -p x stop ssh`, `apt-get -o a=b install x`).
2. **`<>` counts as an output redirection**, with the same `/dev/null`, `/dev/stdout`, `/dev/stderr` and `/tmp/…` exceptions, because it opens the target for writing and creates it.
3. **`env -S` command lines are lexed and checked like an `Execute`.** This covers `-S x`, `-Sx` and `--split-string[=]x`. Their `$( )` is not refused, since `env` expands nothing.

Size: the lead accepted `bit102.py` at 273 lines as one file, because most of it is the rules table.

## Checks run here (scratch harness outside the tree; the tests are tester-m7b's)

- **Must-pass:** 128 inputs, no finding. These are the 91 corpus cases, every `Execute` of both samples, and the five non-literal forms above.
- **Must-reject:** 341 forms, each with BIT102 and its corpus `token` in a message. These are the 149 corpus cases, plus each case marked `contexts` inside `true |`, `true;`, `true &&`, `false ||`, `( )`, `$( )`, backticks and `bash -c '…'`.
- **Extra probes:**

  | Input | Result |
  | --- | --- |
  | `env -S'rm x'`, `env -S 'rm x'`, `env --split-string='rm x'` | rejected |
  | `sudo -u root rm x`, `nice -n 5 rm x` | rejected |
  | `systemctl -p x stop ssh`, `apt-get -o a=b install x` | rejected |
  | `sed --in s/a/b/ f` | rejected |
  | `a <> /etc/x` | rejected |
  | `bash -o pipefail -c 'rm x'` | rejected |
  | `echo x >&-`, `command -v rm`, `bash -ec 'ls'`, `env FOO=1` | pass |

- **Fuzz:** 15,000 random inputs through `check_execute` raised nothing, worst 1.6 ms.
- **Gates:** `ruff check manager`, `ruff format --check manager` (263 files) and `mypy --strict --config-file manager/pyproject.toml` on these files are clean. There is one `noqa: S108` on the `/tmp/` prefix constant: a false positive, because the module compares policy text and never opens the path.

## For the tester (TP-M7-08, `test_bit102.py`)

- Run `check_execute(cmd, line=…, element=…)` on each corpus case and on the samples.
- The five non-literal forms are **must-pass** by the user's ruling. Please add them to the must-pass corpus, which is yours to change.
- **Plants:**
  - CHK-M7-327 (substring search): replace `_command` with a text search.
  - CHK-M7-328: drop the `rsplit("/")` reduction.
  - CHK-M7-329: skip `_nested` or `_shell_script`.
  - CHK-M7-330: empty `WRAPPERS`.
  - CHK-M7-331: accept any target in `_redirect`.
  - CHK-M7-332: return `[]` in the `ShellSyntaxError` branch of `check_execute`, or in `lex`.

## Revision 1 (2026-10-27): wrapper option clusters (tester-m7b FAIL)

tester-m7b found a #108 (d) bypass: in a short-option cluster whose last letter takes a value, the value hid the wrapped command. For `sudo -iu root rm x`, the old code skipped only `-iu` and took `root` as the command.

The fix is a new `_option()` in `bit102.py`, which reads each wrapper option as getopt does:
- In a short cluster, the first letter that takes a value (per `WRAPPERS`) ends the cluster. Its value is the rest of the word or, if nothing is left, the next word.
- A long option takes the next word only when it is in the table and has no `=`.
- `env -S` and `--split-string` are found inside clusters too (`-iS 'rm x'`, `-iS'rm x'`).
- `command -pv` still means nothing runs.

New results:
- These now get BIT102 naming `rm`: `sudo -iu root rm -f /etc/x`, `sudo -nu root rm x`, `sudo -Hu root rm x`, `env -iu FOO rm -f /etc/x`, `timeout -vk 5 10 rm x`, `timeout -vs KILL 10 rm x`, `ionice -tc 3 rm x` and `doas -nu root rm x`.
- So do `sudo -uroot rm x`, `sudo --user root rm x`, `sudo --user=root rm x`, `nice -n5 rm x`, `env -u X -i rm x`, `stdbuf -oL rm x`, `env -iS 'rm x'` and `env --split-string 'rm x'`.
- The scratch corpus run is unchanged: 133 must-pass inputs with no finding, and 341 of 341 must-reject forms.

**`stdbuf -io L rm x` is intentionally not flagged.** GNU stdbuf's `-i` takes a MODE, so getopt reads `-io` as `-i o`, and the command stdbuf runs is `L` (with `rm` and `x` as its arguments). That is the rule the tester itself stated. In practice stdbuf refuses mode `o` and runs nothing. Treating `-io` as two flags would make the parser disagree with the real binary. I have sent this to tester-m7b as evidence that this one parameter should not expect BIT102.

The gates are clean on the file.

## Open at the drain (2026-10-27): `stdbuf -io L rm x`

This one parameter is unresolved. The discussion stopped here at the lead's drain order; the lead has not ruled.

- **tester-m7b's view.** `test_bit102.py::test_wrapper_option_clusters_do_not_hide_the_command` expects BIT102 naming `rm` for `stdbuf -io L rm x`. A wrapper option cluster must not hide the wrapped command, and this case is one of the 9 parameters added for that bypass.
- **impl-manager-m7b's view.** GNU stdbuf documents `-i, --input=MODE`. getopt therefore reads `-io` as `-i` with value `o` (the rule the tester stated: the first value-taking letter ends the cluster, and the rest of the word is its value). stdbuf then runs `L`, with `rm` and `x` as its arguments; in practice it refuses mode `o` and runs nothing. `rm` never runs, so flagging it would make BIT102 disagree with the real binary. `stdbuf -oL rm x` and `stdbuf -i0 -oL rm x` do get BIT102.
- **State.** `bit102.py` revision 1 leaves the case unflagged. The other 8 parameters pass, and the corpus results are unchanged.
- **To resume.** The lead decides. Either tester-m7b drops or changes the parameter, or `_option()` gets a rule that treats this form as hiding a command. The most likely shape: when a value-taking letter has its value attached, also check the next word as a command, which errs toward rejecting.

**Closed** (`work/status.md`, M7 drain item 3): the builder's reading stands, and the test now uses `stdbuf -i0 -oL`.

## Revision 2 (2026-10-27): BIT102 gaps closed (decision 2026-10-27, amends #108 (d) and (k))

impl-manager-m7 built (1) and (3); impl-manager-m7d finished it: the trap ruling, the alias/hash/let/`@P` ruling and the two r1 blockers. The lead's WIP snapshot is `50d3ec9`; the rest is in the working tree and nothing more is committed. There are two new files and two changed files, all in `manager/bitscan_manager/services/importer/`:

| File | Lines (total) | What |
| --- | --- | --- |
| `bit102_wrap.py` (new) | 230 | the option tables: the #108 (d) wrappers (`WRAPPERS` L44, new in this round) and the r2 ones (`SPECS`); `look_through()`; the getopt reader `read_option()` L170, now shared by both tables; operand rules `_operands()`; `text_word()` |
| `bit102_brace.py` (new) | 130 | `expand_words()` L30, `_expand()` L56, sequences `_sequence()` L92 |
| `bit102.py` | 401 (was 337 at r1) | `bash` flag threaded through `_script` / `_nested` / `_shell_script`; `_resolve()` L123 reads the #108 (d) wrappers through `read_option()`; `_command()` L194 brace-expands in bash mode and loops through the r2 wrappers; `_defines_code()` L251 (trap, alias, hash, let); `_shell()` L333 with `SHELL_LONG`/`SHELL_LETTERS` L325 |
| `shlex_grammar.py` | 267 (was 220 at r1) | `time` handling moved from `reserved()` into `Grammar.time()` L200. The rest of its diff is TASK-145 r1 |
| `shlex_posix.py` | 361 | `${…@P}`/`${…@E}` refused in `scan()` L334. The rest of its diff is TASK-145 r1 |

**Size (final, with (6)).** Against the r1 base `150bcd3`, TASK-146 r2 is about 680 changed lines: about 565 added and 120 removed, counting blank lines. The lead accepted the ~640-line version (decisions.md, 2026-10-27); (6) adds about 40 more.
- **Where the rest comes from.** This round added about 240 changed lines (about 140 added, 100 removed) on top of the snapshot:
  - the #108 (d) wrapper tables, moved into `bit102_wrap.py` and completed with every flag (about 45 lines), plus `_resolve()` reworked onto the shared reader, replacing the old `_option()`;
  - `_defines_code()` (30 lines, replacing the 14-line `_trap()`);
  - the shell option tables in `_shell()` (about 15 lines).
- **Tables and docstrings.** About 110 of all the lines are option tables and about 80 are docstrings and comments.
- **Seams, if main wants it split:**
  - r2a: wrappers, `time` and the old-wrapper tables (`bit102_wrap.py`, `_resolve`/`_command`, grammar);
  - r2b: brace expansion (`bit102_brace.py`, the `bash` flag);
  - r2c: the rulings (`_defines_code`, `@P`/`@E` in `shlex_posix.scan`) and the `_shell` option parsing.

### (1) Wrappers (`bit102_wrap.py`)

Each wrapper's options are read the way its getopt reads them. The tables come from util-linux 2.39 `--help` on this container, checked against what 2.37 (Ubuntu 22.04) and 2.38 (Debian 12) accept, plus GNU time. Everything except su/runuser stops at the first non-option, because their optstrings start with `+`. su and runuser permute (no `+`), so options after the user count too. `--` ends options. Option clusters, attached values (`-t1`, `--target=1`) and optional-argument letters work as getopt does: `-m/proc/1/ns/mnt` and `-mU` use up the rest of the word. The wrapped command is checked as a command word, and wrappers nest in any order with the #108 (d) ones (`nice time nsenter … flock /tmp/l rm x` → `"rm" (via "nice time nsenter chrt taskset setpriv unshare flock")`).

| Wrapper | Form → checked command | Example (BIT102) |
| --- | --- | --- |
| `time` (external: `/usr/bin/time`, `\time`, `command time`, `sudo time`) | after `-f`/`-o` values and flags | `/usr/bin/time -f %e rm x` |
| `time` at the start of a command | `time` and `time -p` stay bash's keyword (lexer table unchanged). If any other option follows, the words become an ordinary `time …` command (L171), because `/bin/sh` is dash (TS §3.5 L249), which runs the external time | `time -o /tmp/t rm x`, `time -p -o x rm x`, `time -- rm x` |
| `nsenter` | `-t`/`-W` take a value; namespace letters, `-r` and `-w` take one only when attached | `nsenter -t 1 -m rm x`, `nsenter -m/proc/1/ns/mnt rm x` |
| `unshare` | `-R -w -S -G --propagation --setgroups --map-*…` take a value; namespace letters, `--kill-child` and `--mount-proc` take an attached one only | `unshare -mU rm x`, `unshare -fr --propagation private rm x` |
| `flock` | `FILE CMD…`, `FILE -c CMD`/`--command CMD`, and `-c CMD` before FILE; the `-c` script is lexed and checked | `flock -n /tmp/l -c 'rm x'`, `flock -w 5 /tmp/l rm x` |
| `setpriv` | all value options are long (`--reuid=0`, `--reuid 0`) | `setpriv --reuid 0 --init-groups rm x` |
| `taskset` | `MASK CMD` (`-c` is a flag here, a cpu-list format, not a value) | `taskset -c 0-3 rm x` |
| `chrt` | `[policy] PRIO CMD`; `-T -P -D` take a value | `chrt -f 10 rm x` |
| `su` | every `-c`/`--command`/`--session-command` script is lexed and checked (in bash mode, see (3)); `-`, `-l`, user before or after `-c` | `su - root -c 'rm x'`, `su -lc 'rm x' root`, `su --command='rm x' root` |
| `runuser` | as su; with `-u USER` the operands are the command, run directly | `runuser -u nobody -- rm x`, `runuser -l nobody -c 'rm x'` |

In each of these cases nothing runs, so nothing is checked: `flock 9`, `taskset -p 1`, `chrt -m`, `chrt -p 1`, `setpriv -d`.

**Where I fail closed (#108 (j)): each case gives one BIT102 finding.**
- An option that is not in the table, a long-option abbreviation included: `nsenter --targ 1 rm x` and `setpriv --reu 0 rm x` give `Execute cannot be checked: option "--targ" of "nsenter".` An unlisted option from a newer util-linux (for example 2.40 `nsenter -c`) is refused the same way. A `--flag=value` on a flag is refused too (it is a getopt error).
- A `chrt` priority that is not a literal decimal: `chrt -o rm x` and `chrt -f "$p" ls` give `Execute cannot be checked: "rm" after "chrt".` util-linux 2.41 lets SCHED_OTHER/BATCH/IDLE leave out the priority, and then that word is the command.
- `su`/`runuser` that would start the user's shell without `-c` give `Execute runs a shell without -c: "su".`, by analogy with #108 (f). This covers `su root`, `su - root`, `… | su root`, `su root /tmp/script`, `su root -- -c 'rm x'`, `runuser nobody`, and `runuser -u nobody` with no command.
- Words after the user when there is a `-c` (`su -c id root x`) are passed to the shell as its arguments. They are refused as "cannot be checked".
- **`nsenter -S`/`-G`** (and `--setuid`/`--setgid`) with a separate word take it only when it is a decimal uid or gid; any other word is "cannot be checked" (corrected in (6): the earlier "only attached in 2.39" premise was wrong).

`su`/`runuser`/`flock -c` scripts are lexed with `$( )` allowed (like `env -S`), because SR §4.2's substitution ban names only `sh`/`bash`/`dash -c`. Their substitutions are still walked and checked.

### (3) Brace expansion (`bit102_brace.py`)

- **Where brace expansion is applied.** Only in bash mode: inside a `bash -c` script, an `su`/`runuser`/`flock -c` script (the user's login shell or `$SHELL`, often bash, so I fail closed), and every script nested in one of those (`$( )`, trap actions).
- **Where it is not.** The `Execute` itself and `sh`/`dash -c` scripts are left alone, because dash has no brace expansion. `{rm,x}` and `sh -c '{rm,x}'` still pass.
- **How words are expanded.** Each command's words are expanded the way bash does it, and the resolver and every rule then see the expanded words. Only unquoted text expands. Quoted text and expansions (`$x`, `$( )`) stay whole, and a word that expands to nothing is dropped.
- **Examples that now get BIT102:**
  - `bash -c '{rm,-rf,/x}'`, `bash -c 'r{m,}  -rf /'`, `bash -c '{,}rm x'`, `bash -c '{,} rm x'`
  - `bash -c 'r{m..m} x'` (a sequence), `bash -c 'ls; {ls,x} | {r,}m x'`
  - `bash -c 'sed -{i,n} s/a/b/ f'`, `bash -c 'systemctl {stop,status} ssh'`, `bash -c 'sudo {rm,ls} x'`
  - `bash -c '{rm,"$x"} y'`, `su -c '{rm,x} y'`, `su -c "bash -c '{rm,-rf,/x}'"`
- **Cases I refuse as "cannot be checked"**, where bash's reading is unclear or the expansion is too large:
  - an unmatched `{` with a comma after it (`{{rm,x}`), message `unmatched brace in a bash script`;
  - a brace pair whose only commas are inside nested braces (`{a{rm,x}b}`), message `nested braces …`;
  - more than 256 words for one command, message `brace expansion makes too many words …`;
  - more than 64 brace levels in one word, message `too many braces …`.
- **Known false positive:** `bash -c 'echo {1..1000}'` is refused because it expands to more than 256 words. It is rare in CIS commands.
- **Cases that still pass:** `bash -c 'ls /etc/{passwd,group}'`, `echo {1..5}`, `{}` and `{x}` as literals, quoted awk programs, and `for i in {1..3}` (a `for` list is data words).
- **Timing.** The worst pathological 16 KB input I timed (`{a..a}` × 2000) took 113 ms.

### (2) trap, alias, hash, let, `${…@P}`/`${…@E}`: refused like eval (user rulings 2026-10-27)

`_defines_code()` (`bit102.py` L251) gives `Execute runs other code with "<name>".`, the eval message. It works wherever the command word resolves, through wrappers (`command trap …`) and in `-c` scripts. A word in option or operand position that is not literal counts as setting code, because it could be anything (fail closed).
- **trap.** It is refused when it sets an action: two or more operands after its options, the first of which is not `-`.
  - These pass: `trap`, `trap -p [SIG]`, `trap -l`, `trap -P …` (any `l`, `p` or `P` letter lists), `trap - SIG…` and `trap -- - SIG…`.
  - `trap SIG` (one operand) also passes. Checked here: dash says "bad trap" or resets, and bash prints usage or resets. Neither sets an action, so it is no exception to the ruling.
  - `trap '' INT` is refused, because it sets an (empty) action. `trap "$a" EXIT` is refused too (fail closed).
  - The lexed-and-checked `_trap()` of the snapshot is gone.
- **alias.** Refused when any argument holds `=` or is not literal. `alias`, `alias ll` and `alias -p` pass.
- **hash.** Refused when a letter `p` appears in its options (`hash -p /bin/rm ls`, `hash -rp …`), or when an option-position word is not literal. `hash`, `hash -r`, `hash -t ls` and `hash ls` pass.
- **let.** Always refused.
- **`${…@P}` and `${…@E}`.** These are refused in the lexer (`shlex_posix.py` `scan()` L334), so they are caught wherever a `${…}` is lexed:
  - words, double quotes and nested `${}`;
  - `$(( ))`;
  - unquoted here-document bodies, which keep only their scripts, so the BIT102 walk could not see them;
  - re-lexed `-c` scripts.

  The finding is `Execute cannot be checked: ${…@P} or ${…@E} runs text as code.`. Single-quoted text and quoted here-document bodies are data and pass (`echo '${x@P}'`). `${x@Q}` and other transformations are not refused (not in the ruling).
- **Checked here.** dash runs `alias r=echo` and then `r RAN`. bash runs `hash -p /bin/echo ls; ls RAN`, `let 'a[$(echo RAN)]=1'`, `: ${x@P}` and `${x@P}` in an unquoted here-document, each with `x='$(echo RAN)'` where needed.

### (4) r1 blocking 1: the shell's own option parsing (`_shell`, `bit102.py` L333)
- **How options are read now.** In a short cluster (`-…` or `+…`), each `o` or `O` letter takes one following word, in order. So `-co pipefail`, `-oc pipefail`, `-Oc extglob`, `+oc errexit` and `-oO pipefail extglob` all work, and `c` is noted wherever it is in the cluster. A lone `-` or `--` ends the options and is consumed.
- **Long options.** `--rcfile` and `--init-file` take a word. The bash long options in `SHELL_LONG` are flags.
- **Fail closed.** Any other long option is refused with `Execute cannot be checked: option "…" of "bash".`. That includes abbreviations (`--rcf`, which bash itself rejects) and every long option of dash, which has none. A letter outside `SHELL_LETTERS`, the union of the bash and dash invocation and `set` letters, is refused the same way (`sh -q`).
- **Checked here under dash and bash.** `bash -co pipefail 'echo RAN'`, `-oc`, `-Oc extglob`, `sh -co errexit`, `sh -c - 'echo RAN'` and `bash -c - …` all print RAN. `sh - -c X` runs the file `-c`, and BIT102 reports it as a shell without `-c`.

### (5) r1 blocking 2: long-option abbreviations of the #108 (d) wrappers
- **The fix.** `env`, `command`, `builtin`, `nice`, `nohup`, `ionice`, `setsid`, `stdbuf`, `timeout`, `chroot`, `sudo`, `doas` and `busybox` now have full tables (`WRAPPERS` in `bit102_wrap.py`), read by the same `read_option()` as the r2 wrappers.
- **Where the tables come from.** Every flag, value and optional-value option is taken from `--help` of coreutils 9.4, util-linux 2.39 and sudo 1.9.15 in this container.
- **Fail closed.** An option not in the table, an abbreviation included, gives `Execute cannot be checked: option "--un" of "env".`. So does an unknown short letter (`sudo -X`) and a `--flag=value` on a flag.
- **Special forms kept:**
  - `env -S`/`--split-string` (as `scripts`, lexed as before);
  - `env -` and `env NAME=v`;
  - `command -v`/`-V`, which run nothing;
  - the timeout duration and the chroot directory (`positional`);
  - `nice -N`, `--N` and `-+N` (the coreutils legacy adjustment, checked here).
- **Added: `sudo NAME=value`.** Like env, it is skipped. sudo 1.9.15 runs `sudo FOO=1 echo RAN`, so before this round `sudo FOO=1 rm x` hid `rm`. That is the same #108 (d) "skip its options" class, and it was found while building the table.
- **`sudo -h WORD`.** WORD is the host here (sudo 1.9.15 says "unable to resolve host echo"), so `-h` takes a value, as before.
- **Checked here.** `env --un HOME`, `--ch /` and `--sp '…'`, `nice --adj 5`, `timeout --sig KILL 5`, `stdbuf --out L`, `sudo --us root`, `sudo --gr root`, `chroot --sk /` and `timeout --pres 5` all run the command under the real binaries. All of them are now refused.
- **stdbuf.** `stdbuf -io L rm x` still passes: getopt reads `-io` as `-i o`, so stdbuf runs `L`. The dispute is closed (the builder's reading, `work/status.md`).

### (6) Three more fail-open forms (tester-m7d; decisions.md 2026-10-27, last TASK-146 row)

All three were checked in this container: coreutils 9.4, util-linux 2.39.3, sudo 1.9.15, dash and bash, with `echo` in place of `rm`.
1. **env `-` and `NAME=value` after `--`.** coreutils env.c reads them after getopt, so `--` makes no difference: `env -- FOO=1 echo RAN` and `env -- - echo RAN` both run.
   - While fixing this I found that env and sudo take *any* operand holding `=` as an assignment, not only `NAME=…`: `env a-b=1 echo RAN`, `env 1=2 echo RAN`, `sudo a-b=1 echo RAN` and `env "$x"=1 echo RAN` all run.
   - So `_sets_var()` (`bit102.py` L184) now skips any env or sudo word with `=` in a literal part, unless the word starts with `-`, which makes it an option.
   - After `--`, env also skips one `-` and the assignments (in `_resolve()`).
   - sudo is not widened past `--`: `sudo -- FOO=1 echo RAN` gives "command not found".
2. **nsenter `-S`/`-G`/`--setuid`/`--setgid`.** In 2.39.3 these take the next word as a required uid or gid. `+0` and `' 0'` both parse as uid 0, and `-S echo` gives "failed to parse uid".
   - `read_option` (`bit102_wrap.py` L192) now takes the next word only when it is decimal digits. Any other word is "cannot be checked" (`option "-S" of "nsenter"`). An attached value (`-S0`, `--setuid=0`) is unchanged.
3. **`sudo -s`/`-i`/`--shell`/`--login` and `doas -s`** (lead ruling, #108 (f)). Handled by `_sudo_shell()` (L172):
   - With no command, they start a shell that reads stdin. The finding is `Execute runs a shell without -c: "sudo".`.
   - With a command, the literal words are joined with spaces and checked as a bash-mode script (`"sudo -s"`; `$( )` allowed, as for `su -c`).
   - A word that is not literal gives "cannot be checked".
   - This is stricter than sudo itself, which backslash-escapes the words: `sudo -s 'echo RAN-2; echo RAN-3'` runs one command named `echo RAN-2; echo RAN-3`. Erring toward rejecting is what the ruling asks.
   - Checked here: `echo 'echo RAN' | sudo -s` and `| sudo -i` run their input; `sudo -s echo RAN`, `sudo -i …`, `--shell` and `--login` run the command.
   - doas is not installed in this container, so `doas -s` follows the ruling unprobed.

### Gaps and residuals

- **Accepted residual (lead, review round 1 routing, 2026-10-27; #108 (k) stands).** `time -o FILE` and `flock FILE` can create a file through a program option, not a redirection. BIT102 checks redirections only. The M10 sandbox (read-only file system) is the control. The residual is recorded for the M7 PR.
- **Accepted residual (lead, 2026-10-27):** `sudo -e FILE` (sudoedit) writes FILE through the editor; the M10 sandbox is the control.
- **Not refused (not in the rulings).** `${x@Q}`/`@A`/`@K`, `declare`/`printf -v`/`[[ -v a[$(…)] ]]` arithmetic-subscript forms and `(( a[$(…)] ))` stay unrefused. For main, if wanted.

### Gates and runs (from the repo root, venv `manager/.venv`)

- `ruff check manager`: clean. `ruff format --check manager`: 278 files formatted. `mypy --strict --config-file manager/pyproject.toml manager`: no issues in 278 files.
- Final run, with TASK-145 r1 in the tree, from `manager/`: `pytest -q -p no:cacheprovider tests/test_bit102.py tests/test_bit102_lexer.py tests/test_bit_fixtures.py tests/test_bit_fuzz.py tests/test_bit_parse.py tests/test_bit_validate.py` gave **2548 passed** (then **2877 passed** once tester-m7d's new rows, including the (6) rows, were in the tree). No existing test needed changing: the corpus has no trap, alias, hash or let row. No existing test failed after (6) either; tester-m7d's new rows live in its own tree. The final probe is 85 must-reject and 59 must-pass rows, plus 33 rows for (6), all as expected. A 30,000-input fuzz raised nothing (worst 0.7 ms).
- **Probe caveat.** Outside `manager/`, the venv imports `bitscan_manager` from another worktree (`/root/m4a-g41.lP0csJ/manager`), so scratch probes need `PYTHONPATH=/home/user/Bitscan/manager`. Every probe above was re-run that way.
- The snapshot's own run (before this round): `pytest … tests/test_bit_fuzz.py` gave **1583 passed**. That includes the must-pass corpus, the samples in `bits/samples/` and the lexer table (`time rm x` and `time -p rm x` still lex as `rm`).
- Scratch probe, outside the tree: 88 must-reject inputs, all refused; 39 must-pass inputs, all with no finding. A random fuzz of 20,000 inputs built from wrapper, brace and quote tokens raised nothing.

### Cases I recommend the tester add

- **Must-reject:** each Example in the wrapper table above. Also `\time -o /tmp/y rm x`, `command time rm x`, `sudo time -v rm x`, `nsenter -S rm x`, `nsenter --setuid rm x`, `nsenter -a -t 1 -- rm x`, `unshare --kill-child=KILL -f rm x`, `flock /tmp/l --command 'rm x'`, `flock -c 'rm x' /tmp/l`, `flock -E 3 -xn /tmp/l rm x`, `taskset -ac 1 rm x`, `chrt -T 1 -P 2 -D 3 -d 0 rm x`, `su -c 'rm x'`, `su root -c 'rm x'`, `su --session-command 'rm x'`, `su -s /bin/bash -c 'rm x' root`, `runuser -u nobody rm x` and `sudo nsenter -t 1 -m su -c 'rm x'`.
- **Fail-closed rows:** `nsenter --targ 1 rm x`, `nsenter -X rm x`, `setpriv --reu 0 rm x`, `chrt -o rm x`, `su root`, `su - root`, `echo 'rm x' | su root`, `su root /tmp/script`, `su root -- -c 'rm x'`, `runuser nobody` and `runuser -u nobody`.
- **Brace must-reject:** every Example in (3), plus `bash -c '{{rm,x}'`, `bash -c '{a{rm,x}b} y'`, `bash -c 'x{a,b}{a,b}{a,b}{a,b}{a,b}{a,b}{a,b}{a,b}{a,b}'`, `bash -c 'echo $({rm,x} y)'` and `trap 'bash -c "{rm,x} y"' EXIT`.
- **Must-pass:**
  - wrappers: `time ls`, `time -p ls`, `/usr/bin/time -f %e ls`, `time -o /tmp/t ls`, `nsenter -t 1 -m cat /etc/fstab`, `nsenter --target 1 --mount findmnt`, `nsenter -S 0 -t 1 cat /x`, `unshare -r id`, `flock /tmp/l cat /etc/x`, `flock -n /tmp/l -c 'cat /etc/x'`, `flock 9`, `setpriv --nnp cat /etc/x`, `setpriv -d`, `taskset -c 0 cat /etc/x`, `taskset -p 1`, `chrt -m`, `chrt -p 1`, `chrt -o 0 cat /x`, `su -c 'id' nobody`, `su - nobody -c 'cat /etc/x'`, `runuser -u nobody -- id`, `runuser -l nobody -c 'id'`;
  - braces: `bash -c 'ls /etc/{passwd,group}'`, `bash -c 'echo {1..5}'`, `bash -c "awk '{print \$1,\$2}' f"`, `bash -c 'find / -name {} -print'`, `bash -c 'for i in {1..3}; do echo $i; done'`, `bash -c 'x={a,b}; echo $x'`, `sh -c '{rm,x}'`, `{rm,x}`, `echo {rm,-rf,/x}`, `bash -c 'echo ${x:-{a,b}}'`.
- **Must-reject, rulings:**
  - trap: `trap 'rm x' EXIT`, `trap 'echo done' EXIT`, `trap -- 'echo done' EXIT`, `trap '' INT`, `trap "$a" EXIT`, `trap 0 'ls' EXIT`, `command trap 'ls' INT`, `bash -c "trap 'ls' EXIT"`;
  - alias: `alias r=rm`, `alias r=rm` + newline + `r -rf /x`, `alias -p r=rm`, `alias "$x"`;
  - hash: `bash -c 'hash -p /bin/rm ls; ls -rf /x'`, `hash -rp /bin/rm ls`;
  - let: `let 'a[$(rm x)]=1'`, `bash -c 'let x=1'`;
  - `@P`/`@E`: `x='$(rm x)'; : ${x@P}`, `echo "${x@P}"`, `bash -c ': ${x@E}'`, `echo ${y:-${x@P}}`, `echo $(( ${x@P} ))`, `cat <<E` + newline + `${x@P}` + newline + `E`, `echo ${arr[@]@P}`.
- **Must-pass, rulings:** `trap`, `trap -p`, `trap -l`, `trap -p EXIT`, `trap - EXIT`, `trap -- - INT TERM`, `trap INT`, `alias`, `alias ll`, `alias -p`, `hash`, `hash -r`, `hash -t ls`, `hash ls`, `echo '${x@P}'`, `echo ${x@Q}`.
- **Must-reject, r1 blocking 1** (`rm` found in the script):
  - `bash -co pipefail 'rm x'`, `bash -oc pipefail 'rm x'`, `bash -Oc extglob 'rm x'`, `sh -co errexit 'rm x'`;
  - `sh -c - 'rm x'`, `bash -c - 'rm x'`, `dash -c -- 'rm x'`;
  - `bash -oO pipefail extglob -c 'rm x'`, `bash +oc errexit 'rm x'`, `bash -c -o errexit 'rm x'`, `bash --rcfile /dev/null -c 'rm x'`.
- **Fail-closed rows, r1 blocking 1:** `bash --rcf /dev/null -c 'rm x'`, `bash --foo -c 'ls'` and `sh -q -c 'rm x'`.
- **Must-reject, r1 blocking 2** (each gives `cannot be checked: option …`): `env --un HOME rm x`, `env --ch / rm x`, `env --sp 'rm x'`, `nice --adj 5 rm x`, `timeout --sig KILL 5 rm x`, `stdbuf --out L rm x`, `sudo --us root rm x`, `sudo --gr root rm x`, `chroot --sk / rm x`, `timeout --pres 5 rm x`, `env --bl INT rm x`, `sudo -X rm x`, `env -X rm x`.
- **Must-reject, still naming `rm`:** `nice -5 rm x`, `nice --5 rm x`, `nice -+5 rm x`, `sudo FOO=1 rm x`, `sudo -u root FOO=1 rm x`, `env --block-signal=INT rm x`, `sudo --preserve-env=HOME rm x`, `sudo -h host rm x`.
- **Must-pass, shells and wrappers:**
  - shells: `bash -co pipefail 'ls'`, `sh -c - 'ls'`, `bash --norc -c 'ls'`, `bash -O extglob -c 'ls'`;
  - env: `env --unset HOME ls`, `env --block-signal ls`, `env - ls`;
  - nice, timeout, chroot: `nice -5 ls`, `timeout --signal KILL 5 ls`, `chroot --skip-chdir / ls`;
  - sudo, command, others: `sudo --user=root ls`, `sudo FOO=1 ls`, `command -pv rm`, `ionice -c 3 ls`, `setsid -f ls`, `doas -u root ls`.
- **(6) must-reject:**
  - env: `env -- FOO=1 rm x`, `env -- - rm x`, `env -i -- FOO=1 rm x`, `env -u HOME -- FOO=1 rm x`, `env a-b=1 rm x`, `env 1=2 rm x`, `env "$x"=1 rm x`, `env -- - FOO=1 a-b=2 rm x`;
  - sudo assignment: `sudo a-b=1 rm x`;
  - nsenter (cannot be checked): `nsenter -S +0 rm x`, `nsenter -S ' 0' rm x`, `nsenter --setuid +0 rm x`, `nsenter -G +0 rm x`, `nsenter -S rm x`, `nsenter --setuid rm x`;
  - nsenter naming `rm`: `nsenter -S 0 -t 1 rm x`, `nsenter -S0 rm x`;
  - shell without -c: `sudo -s`, `sudo -i`, `sudo --shell`, `sudo --login`, `sudo -u root -s`, `sudo -iu root`, `echo 'rm x' | sudo -s`, `doas -s`;
  - command checked: `sudo -s rm x`, `sudo -i rm x`, `sudo -s 'ls; rm x'`, `sudo --login rm x`, `doas -s rm x`, `sudo -s FOO=1 rm x`, `sudo -s bash -c '{rm,x}'`;
  - cannot be checked: `sudo -s "$c"`.
- **(6) must-pass:**
  - env and sudo: `env -- FOO=1 ls`, `env a-b=1 ls`, `env --unset=HOME ls`, `sudo FOO=1 ls`;
  - nsenter: `nsenter -S 0 -t 1 cat /x`, `nsenter --setuid=0 -t 1 cat /x`, `nsenter -S0 cat /x`;
  - sudo shells: `sudo -s ls /etc`, `sudo -i id`, `sudo -s cat /etc/x`, `sudo -s 'echo $(id)'`.
- **Existing rows that need a decision:** none failed. `B-sed-skip-value` and the sed attached-value rows (review finding 3) are unchanged by this round.
- **Plants:**
  - empty `SPECS`;
  - `read_option` returning 1 for unknown options (`nsenter --targ`, `env --un`);
  - `_defines_code` returning False (the ruling rows), and dropping the `@P`/`@E` check in `shlex_posix.scan`;
  - `_shell` taking no word for `o`/`O` (`bash -co pipefail 'rm x'`), and not consuming a lone `-` (`sh -c - 'rm x'`);
  - an empty `WRAPPERS` table, or the env/sudo assignment skip dropped (`sudo FOO=1 rm x`);
  - `_sets_var` reverted to `is_assignment` (`env a-b=1 rm x`), the env skip after `--` removed (`env -- FOO=1 rm x`), the nsenter numeric rule back to `else 1` (`nsenter -S +0 rm x`), `_sudo_shell` returning None (`sudo -s`);
  - optional letters treated as value-taking (`nsenter -m/proc/1/ns/mnt rm x`);
  - `bash=False` everywhere (brace rows);
  - bash mode on for dash (`sh -c '{rm,x}'` must still pass);
  - `Grammar.time()` always returning `[]` (`time -o /tmp/t rm x`).
