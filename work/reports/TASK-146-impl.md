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
