# TASK-145 REVIEW: POSIX sh lexer for BIT102

Verdict: APPROVED

Reviewer: reviewer-m7, 2026-10-28. REQ-156. High risk (importer; TS §8.2 two approvals: this is the first).

Scope reviewed: the new `shlex_model.py` (78 non-blank lines), `shlex_grammar.py` (202) and `shlex_posix.py` (322) in `manager/bitscan_manager/services/importer/`, per `work/reports/TASK-145-impl.md`. One task in three files. The size and the split were accepted by the user (decisions 2026-10-27 L320, L323). Imports go one way only: model, then grammar, then posix.

TEST: PASS (`work/reports/TASK-145-test.md`, 173/173 on WSL, on the merged head `25d41ec`).
- The 1160 BIT102 tests (`test_bit102.py`) are green as a dependent.
- 15 plants red (including CHK-M7-332 for the lexer and -387), control green.

My re-run: included in the 860/860 of my TASK-144 re-run; static gates clean.

Spec read: SR §4.2 (L277, L285, L287); TS §3.3 L249 (`/bin/sh -c`), §8.1, §8.3; #108 (c), (h), (i), (j); design note D2 and `work/plans/TASK-145.md`; user ruling 2026-10-27 L320 (non-literal command words allowed, nested scripts checked).

## Checks
1. **Lexer, not substring (SR L277).**
   - Token recognition follows XCU §2.3: quoting (`'`, `"`, `\`), operators longest-first, line continuation, comments only at a token start, IO numbers, and `<(`/`>(` before redirection operators.
   - An escaped character is an `sq` part, so `\rm` gives the literal `rm`, and quoted reserved words aren't keywords.
   - No regular expressions, `shlex`, `subprocess`, `os` or `eval` are used (CHK-M7-102).
2. **Nested scripts (#108 (c)).** These all yield a nested `Script`: `$( )`, backticks (unescaped as XCU §2.6.3 says, inside and outside double quotes), `<( )`/`>( )`, and substitutions inside `${…}`, `$((…))`, double quotes and unquoted here-document bodies. Quoted here-documents are data (#108 (h)). Words in `for` lists, `case` words and patterns, and function names are kept in `data_words`, so the substitutions in them still reach BIT102.
3. **Fail closed (#108 (j)).** Each of these raises `ShellSyntaxError` with a line and fixed text that never echoes input:
   - unterminated quotes, substitutions, `${`, `$((` and here-documents;
   - operators or closers out of place, checked against a balance stack;
   - NUL;
   - nesting deeper than 8, with `${…}` and `$((…))` counted too.

   `RecursionError` is turned into the same error. No path returns a partial script.
4. **Bounds.** It is a single pass per level, and depth is capped. The property and pathological inputs stay under 100 ms of CPU time at 16,384 characters (CHK-M7-112).
5. **Over-detection.** The `$((` rule, `[[ ]]`, `(( ))` and `time` lean toward rejection, as the user ruled (L320). These aren't flagged.

## Findings
None blocking or should-fix.

1. **Closed (lead ruling, decisions 2026-10-28, row "TASK-154 and TASK-165 rulings", last sentence): left as built.** The nit, at `shlex_posix.py:224-256` (`expansion`): bash's locale-translation quoting (`$` directly before a double-quoted string, outside quotes) is lexed as a literal `$` followed by a `dq` part. That matches dash, which runs the top-level `Execute` (TS §3.3 L249), but not bash inside a `bash -c` script. Under the 2026-10-27 non-literal ruling the BIT102 outcome is the same as for `$'…'`, which is already allowed, and changing it would reopen an approved task. No change.
2. nit, `shlex_grammar.py:135`: `cmds.remove(cur)` removes by dataclass equality, not identity. An earlier `_Cmd` equal to `cur` would be removed instead. The resulting list is the same, so the output doesn't change. `cur` is always `cmds[-1]` here, so `cmds.pop()` states the intent exactly.
