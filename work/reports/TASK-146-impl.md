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
- **Closed 2026-10-28** by the lead's ruling (c): the builder's reading stands, and the test uses `stdbuf -i0 -oL rm x`.

## Revision 2 (2026-10-28): BIT102 gaps closed

Defined by the `work/decisions.md` rows "BIT102 gaps closed" (user 2026-10-27, lead 2026-10-28), "TASK-146 r2 shape rulings" and "TASK-146 r2 rulings" (lead 2026-10-28). Spec: SR §4.2 (L277–L287), TS §3.7 (L505), §8.1 (L1244, L1255). BIT102 stays a safety net; the runner sandbox is the control.

### Files

| File | Change | Lines (non-blank) |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/bit102.py` | rules, walk, su/runuser/flock | 316 |
| `manager/bitscan_manager/services/importer/bit102_wrappers.py` | **new**: wrapper table, getopt reader, su/flock argument readers (moved out of `bit102.py`, as allowed) | 225 |
| `manager/bitscan_manager/services/importer/bit102_braces.py` | **new**: bash brace expansion (`brace_words`, `TooMany`, `BRACE_LIMIT`, `BRACE_STEPS`), split out by ruling (9) | 143 |

Three files under one task id (ruling (9)). No other file was changed. The lexer files (`shlex_*.py`) are untouched.

**Interface:** unchanged, `check_execute(execute, *, line, element) -> list[Finding]`. Messages that already existed keep their wording.

### New rules

1. **Wrappers looked through (decision (1))**, in `WRAPPERS`:
   - `time`: GNU time `+af:o:pqvV`; `-f`/`--format` and `-o`/`--output` take a value.
   - `nsenter`: util-linux 2.39.3. `-t`/`--target`, `-S`/`--setuid`, `-G`/`--setgid` and `-W`/`--wdns` take a value (`-W` per ruling (5)). `-m -u -i -n -p -C -U -T -r -w` (and their long forms) are getopt `::` options: their value counts only when attached.
   - `unshare`: `-R -w -S -G` and the long-only `--map-user(s)`, `--map-group(s)`, `--propagation`, `--setgroups`, `--monotonic`, `--boottime` and `--load-interp` take a value. The namespace options take a value only with `=`.
   - `setpriv`: its value-taking long options.
   - `taskset`: one positional (the mask, or the list after `-c`).
   - `chrt`: `-T -P -D` take a value, plus one positional (the priority).
   - Modes that run nothing pass: `taskset -p`/`--pid`, `chrt -p`/`--pid` and `chrt -m`/`--max` (table field `norun`, like `command -v`).
2. **`su`, `runuser` and `flock` command strings (decision (2)):**
   - `-c CMD`, `-cCMD`, `--command CMD` and `--command=CMD` (and su/runuser's `--session-command`) are checked like an `sh -c` script, with the SR §4.2 refusal of `$( )`, backticks, `<( )` and `>( )`.
   - su/runuser permute their options (util-linux getopt has no `+`), so `su root -c 'x'` counts.
   - flock's options stop at the lock path. `-c`/`--command` are read before the path as well, and attached after it. Both are a superset of what real flock accepts.
3. **`trap` is in `CODE_WORDS`** (decision (3)), so it is refused wherever it is the command word.
4. **Brace expansion in bash scripts (decision (4)).** The walk carries a `bash` flag. It is set for the script of `bash -c`, and of `su`/`runuser`/`flock -c`, then inherited by its substitutions and here-documents. It is cleared for `sh`/`dash -c`, `env -S` and the top-level Execute (run by `/bin/sh`).
   - In a bash script, every word of a simple command is brace-expanded as bash does. The expanded command is checked, and then each result of the command word is checked as the command word followed by the words after it: `{echo,rm} x` and `{sudo,x} rm y` are both refused.
   - Empty unquoted results vanish (`{,} rm x` runs `rm`).
   - Refused as "cannot be checked":
     - an expansion of more than `BRACE_LIMIT` = 256 words per simple command;
     - more than 100,000 scan steps per word;
     - nesting too deep;
     - a pair with a top-level `..` that is neither a comma list nor a valid sequence (see below).
   - Refused as "not literal": a command word whose expansion holds a non-literal part (`{r,$x}m`).
5. **Shape rulings:**
   - (a) The file named by `time -o`/`--output` (also `-o/x`, `--output=x` and abbreviations) and flock's lock path follow the #108 (i) output-target rule. A lone numeric flock argument (`flock 9`, `flock -n 9`) is a descriptor and passes.
   - (b) `su`/`runuser` with neither `-c` nor a command are refused like `sh` with no `-c`.
   - (c) `stdbuf -i0 -oL rm x` is refused. `stdbuf -io L rm x` stays unflagged, and so does `nsenter -mt 1 rm x` by the same getopt reasoning (`-m` is `m::`, so `t` is its value and nsenter runs `1`).

### Rulings applied ("TASK-146 r2 rulings", lead, 2026-10-28)

My proposals Q1–Q6 went to main. The lead accepted (1)–(4), (6), (7) and (8) as built, corrected (5), and settled the size in (9):
- **(1)** su, and runuser without `-u`, run the user's shell with `[-c CMD] ARGS`. ARGS without `-c` go to the #108 (f) shell rule, so `su root ls` is refused as a shell given a file. `runuser -u USER cmd…` runs cmd directly and is looked through; `runuser -u USER` alone is refused.
- **(2)** The TASK-145 lexer drops a leading `time` as bash's keyword, but `/bin/sh` (dash) runs GNU time. So a simple command whose first word is a literal starting with `-` is read as `time` plus its words. This makes `time -o /etc/x ls` and `time -f %e rm x` refused, with no lexer change.
- **(3)** Brace expansion covers every word of the command, so `apt-get {install,x} y`, `sed -{i,n}`, `systemctl {stop,x} ssh` and `find / -{exec,x}` are refused. Only the command word gets the "not literal" refusal.
- **(4)** getopt_long abbreviations: a long option that is not an exact name takes the next word when it is a prefix of one of the wrapper's value-taking long options. An exact `::` name such as `--wd` wins. So `env --u X rm y`, `sudo --us root rm x` and `nsenter --tar 1 rm x` are refused.
- **(5) Corrected:** nsenter `-W`/`--wdns` takes a required value (the lead checked util-linux 2.39.3 on Ubuntu 24.04). I had proposed `W::`. It has moved from `attached` to `takes`, so `nsenter -W /etc rm x` is rejected naming `rm`. Only `-r`/`-w` (and `--root`/`--wd`) stay attached-only.
- **(6)** su, runuser and flock `-c` scripts are bash scripts.
- **(7)** `flock N` with an all-digit operand and no command is a descriptor lock and passes.
- **(8)** `env -a`/`--argv0` and `doas -a` take a value.
- **(9)** The brace expander moved to `bit102_braces.py`. Behaviour is unchanged.

### Brace expansion vs bash (evidence)

The expander was compared with GNU bash 5.3.15 (Git Bash) on 80,000 random words, built from braces, commas, `..`, digits, letters, quotes, backslash escapes and `${y}`. There were 0 differences, apart from words the expander refuses: about 0.15 %, all over the bound or the `..` shape. Two bash behaviours shaped the code:
- **Pairing is not stack matching.** A top-level `}` closes a pair only after a top-level comma, or around a valid sequence; otherwise the scan goes on. `{{1..3}},00+1}` gives `1}`, `2}`, `3}` and `00+1`, while `{a{b,c}d}` gives `{abd}` and `{acd}`.
- **A pair with a top-level `..`, no comma and no valid sequence is unpredictable.** `{0{a,b}..2}` stays whole, but `{z{a,b}..2}` and `{a..{a,b}}` expand inside. The expander refuses such a word rather than guess.

Other details, all matching bash:
- A `{}` at the start of a word, or of a post-amble, is not an opener.
- Sequences take int64 integers, zero-padded when an end has a leading `0` (not `-0`), or single ASCII letters. A step of 0 counts as 1, and the step's sign is ignored.

### Probes run (scratch harness outside the tree)

- **Corpus replay:** 1,149 checks, 0 failures. These are every must-reject case with its token (149), every case in every context (646), must-pass (96), every sample `Execute` (32), and every parametrised list in `test_bit102.py`. That includes the five non-literal forms and `stdbuf -i0 -oL rm x`.
- **r2 probes:** 195, 0 failures. A selection:

  | Input | Result |
  | --- | --- |
  | `/usr/bin/time -f %e rm x`, `command time rm x`, `time -f %e rm x` | rejected, `rm` |
  | `/usr/bin/time -o /etc/x ls`, `--output=/etc/x`, `-o/etc/x`, `--out /etc/x`, `time -o /etc/x ls` | rejected, `/etc/x` |
  | `/usr/bin/time -o /tmp/t ls`, `-o /dev/null`, `time -p ls` | pass |
  | `nsenter -t 1 -m rm x`, `nsenter -m/proc/1/ns/mnt rm x`, `nsenter --wd rm x`, `nsenter --tar 1 rm x` | rejected, `rm` |
  | `nsenter -W /etc rm x`, `nsenter --wdns /etc rm x`, `nsenter -W/etc rm x`, `nsenter --wdns=/etc rm x`, `nsenter --wdn /etc rm x`, `nsenter -FW /etc rm x` | rejected, `rm` (ruling (5)) |
  | `unshare -r rm x`, `unshare --map-user 0 rm x`, `unshare --mount=/x rm x` | rejected, `rm` |
  | `setpriv --reuid 0 rm x`, `taskset -c 0 rm x`, `chrt -f 5 rm x`, `chrt -T 1 -P 2 -D 3 -d 0 rm x` | rejected, `rm` |
  | `taskset -p 1`, `taskset -cp 0 1`, `chrt -p 1`, `chrt -m`, `chrt --max` | pass |
  | `flock /tmp/l rm x`, `flock -w 5 /tmp/l rm x`, `flock /tmp/l sudo rm x` | rejected, `rm` |
  | `flock /etc/x ls`, `flock 9 ls`, `flock "$L" ls`, `flock /etc/x` | rejected (lock path) |
  | `flock -n 9`, `flock /tmp/l cat /etc/x`, `flock /tmp/l -c 'cat /etc/x'` | pass |
  | `su -c 'rm x'`, `su root -c 'rm x'`, `su -lc 'rm x' root`, `su --command='rm x' root`, `su root -- -c 'rm x'` | rejected, `rm` |
  | `runuser -u root rm x`, `runuser -u root -- sudo rm x`, `runuser -c 'rm x' root` | rejected, `rm` |
  | `flock /tmp/l -c 'rm x'`, `--command 'rm x'`, `--command='rm x'`, `-c'rm x'`, `flock -c 'rm x' /tmp/l` | rejected, `rm` |
  | `su -c "$(id)" root`, `su -c '$(id)' root`, ``su -c '`id`' root``, `flock /tmp/l -c '$(id)'` | rejected, `id` |
  | `su`, `su -`, `su root`, `su - root`, `runuser root`, `runuser -u root`, `su root ls`, `echo x \| su root` | rejected, `su`/`runuser` |
  | `su -c id root`, `su - root -c id`, `runuser -u nobody -- id` | pass |
  | `trap 'rm x' EXIT`, `trap`, `builtin trap x EXIT`, `bash -c 'trap x EXIT'` | rejected, `trap` |
  | `bash -c '{rm,x} y'`, `'{echo,rm} x'`, `'r{m,x} y'`, `'{,} rm x'`, `'{q..s}m x'`, `'{sudo,x} rm y'`, `'echo $({rm,x} y)'` | rejected, `rm` |
  | `bash -c 'apt-get {install,x} y'`, `'sed -{i,n} p f'`, `'systemctl {stop,x} ssh'`, `'find / -{exec,x} y'` | rejected |
  | `su -c '{rm,x} y'`, `flock /tmp/l -c '{rm,x} y'` | rejected, `rm` |
  | `bash -c '{r,$x}m y'`, `'$x{a,b}'` | rejected (not literal) |
  | `bash -c '{1..1000} x'`, `'echo {1..300}'`, `'{0{a,b}..2} x'` | rejected (cannot be checked) |
  | `sh -c '{rm,x} y'`, `dash -c '{rm,x} y'`, `{rm,x} y`, `env -S '{rm,x} y'` | pass (no brace expansion there) |
  | `bash -c 'echo {rm,x}'`, `'echo {1..200}'`, `'{ echo a; }'`, `'ls {a,b}'`, `'"{rm,x}" y'`, `'\{rm,x} y'`, `'{rm} x'` | pass |
  | `stdbuf -i0 -oL rm x` / `stdbuf -io L rm x`, `nsenter -mt 1 rm x` | rejected / pass, pass |

- **Fuzz:** 20,000 random inputs (pieces include braces, the new wrappers, `-o`, `-p`, `--com`). None raised; the worst took 0.6 ms. Adversarial inputs, each under 62 ms:
  - 16,000 unmatched `{`;
  - 5,000-deep nesting;
  - 3,000 `{a,b}` groups;
  - 5,000 `{a}`;
  - `{1..9223372036854775807}`;
  - 2,500 brace words;
  - 3,000 `-c` options to su;
  - 3,000 `-w` options to flock.
- **Gates** (re-run after the `-W` fix and the split): `ruff check manager` and `ruff format --check manager` (280 files) are clean, and so is `mypy --strict --config-file manager/pyproject.toml manager` (281 files). On one earlier run, mypy reported errors in `services/importer/pipeline.py`. That file belongs to TASK-154 (in progress, impl-manager-m7), not to this task, and the next full run was clean.
- **Scratch re-run after the changes:** corpus replay 1,149/1,149, r2 probes 195/195, fuzz 20,000 inputs (worst 0.6 ms), brace differential 15,000 more words with 0 differences, and the plant sample all caught, including the new `-W` plant.

### For the tester: plants, one per new rule

| Rule | Plant | Expected catch |
| --- | --- | --- |
| (1) wrapper | delete the `"time"` (or `"nsenter"`, `"unshare"`, `"setpriv"`, `"taskset"`, `"chrt"`) entry in `WRAPPERS` | `/usr/bin/time rm x` (etc.) passes |
| (1) value-taking options | drop `-t --target` from nsenter's `takes` | `nsenter -t 1 rm x` passes |
| (1) `::` options | move nsenter's `-m` from `attached` to `takes` | `nsenter -m rm x` passes |
| (1) nsenter `-W` (ruling (5)) | move `-W --wdns` from nsenter's `takes` to `attached` | `nsenter -W /etc rm x` passes |
| (1) positional | set taskset's or chrt's `positional` to 0 | `taskset 1 rm x` passes |
| (1) no-run modes | empty `norun` for taskset/chrt | `taskset -p 1 rm x`, `chrt -p 0 rm x` (must pass: nothing runs) get BIT102 |
| (1) abbreviations | remove the prefix branch in `read_option` | `env --u X rm y` passes |
| (1) leading `time` | remove the leading-dash block in `_script` | `time -f %e rm x` passes |
| (2) command strings | skip the `parsed.strings` loop in `_su` or `_flock` | `su -c 'rm x'`, `flock /tmp/l -c 'rm x'` pass |
| (2) substitution refusal | call `_shell_script(..., subs=True)` in `_c_script` | `su -c '$(id)' root` passes |
| (2) runuser -u | skip the `_command` call in `_su` | `runuser -u root rm x` passes |
| (3) trap | remove `"trap"` from `CODE_WORDS` | `trap 'rm x' EXIT` passes |
| (4) brace expansion | pass `expand=False` in `_script` | `bash -c '{rm,x} y'` passes |
| (4) each result as command word | drop the `group` loop in `_command` | `bash -c '{echo,rm} x'`, `'{sudo,x} rm y'` pass |
| (4) dialect | set `bash=True` in `check_execute` (`bit102.py`) | `{rm,x} y` gets BIT102 (must pass) |
| (4) bound | raise `bit102_braces.BRACE_LIMIT` to 10**6 | `bash -c '{1..1000} x'` passes |
| (4) not literal | drop the not-literal refusal in `_command` | `bash -c '{r,$x}m y'` passes |
| (4) empty results | keep empty results in `bit102_braces.brace_words` | `bash -c '{,} rm x'` passes |
| (5a) `time -o` file | drop the `files` loop in `_simple` | `/usr/bin/time -o /etc/x ls` passes |
| (5a) flock lock path | drop the lock-path check in `_flock` | `flock /etc/x ls` passes |
| (5b) su without -c | drop the `_shell` call in `_su` | `su root` passes |

### Things to know

- Messages for new cases (each quotes the token through `model.quote`):
  - `Execute writes "<file>" with "time -o".`
  - `Execute writes "<lock>" with "flock".`
  - `Execute has a brace expansion that cannot be checked: "<word>".`
  - `Execute has a brace expansion that is not literal: "<word>".`
- su, runuser and flock scripts reuse the `sh -c` messages, for example `Execute passes a substitution to "su" -c: "$(id)".`
- The other modified files in this worktree (`api/user/*`, `openapi.json`, `pipeline.py`) belong to other tasks, not to TASK-146.

## Revision 2 deferred (2026-10-29)

The user deferred revision 2 to a later milestone (decisions row "TASK-146 r2 deferred", 2026-10-29). This was a file restore only; no rule changed. The Revision 2 sections above describe the saved code, not the code in the tree.

- **Where r2 is saved:** `C:\Users\kaiquan.koh\Documents\m7-deferred\task146-r2\`. It holds the three r2 modules and the scratch harness folder `bit102_r2\` (corpus, probes, braces differential, fuzz, plants). Each copy's SHA-256 was checked against its source before the restore.

  | File | SHA-256 |
  | --- | --- |
  | `bit102.py` | `fee8ac5e396ad920ecc326e348eea03a6d118610a062181130c384139e85a0b0` |
  | `bit102_wrappers.py` | `af1ece3968360b9fbae8296c67b891d0ccf82ae66d12f8d905747433d32d48d8` |
  | `bit102_braces.py` | `a6326ef92b16ae3932e2ffbff4467cc1f23e50d2d271744677a12f1fc4eea24c` |
  | `bit102_r2/braces.py` | `3ac0d496c675615495ff6de71fb3cca9e1d7fe3073598e8467c365829bf4f715` |
  | `bit102_r2/corpus.py` | `e399db0bf84f95a3060cf1841ba06ab68bd32dcd1849f6bfe372ac0827607910` |
  | `bit102_r2/fuzz.py` | `e8bf0d1e3a10ee5730d8a87171d7c392350ed1ed84ae00fb48a8a664e979a256` |
  | `bit102_r2/plants.py` | `2f8a2502c134ab9f70d0143de75873b1af41010a341b1d9366b3892fef8e4ade` |
  | `bit102_r2/probes.py` | `03dc39c222ff41602a01a82e6b72d904c88bee5a9f5494f82bce8ea2783922dd` |

- **r1 is restored:** `git checkout c6b7e13 -- manager/bitscan_manager/services/importer/bit102.py`. The file is now the committed r1 version, 337 lines, SHA-256 `279291cff382653ffcc59a2382e32f57c0586bbe84011acdcf466de5d8a991fd`, and `git status` shows it unmodified.
- **The r2 modules are deleted:** `services/importer/bit102_wrappers.py` and `bit102_braces.py`. A grep of `manager/` (tests included, `.venv` excluded) finds no other import of either.
- **Gates on the whole tree after the restore:** `ruff check manager` passes, `ruff format --check manager` reports 310 files already formatted, and `mypy --strict --config-file manager/pyproject.toml manager` finds no issues in 310 source files.
