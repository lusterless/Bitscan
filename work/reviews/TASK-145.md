# TASK-145 REVIEW: POSIX sh lexer for BIT102

Verdict: CHANGES_REQUESTED

Reviewer: reviewer-m7, 2026-10-27. REQ-156; #108 (c), (h), (j). High risk (importer; two approvals, PD-35).

Scope reviewed: frozen worktree at `e2d569c`, per `work/reports/TASK-145-impl.md`:
- `shlex_model.py` (102 lines);
- `shlex_grammar.py` (220 lines);
- `shlex_posix.py` (350 lines).

All three are under `manager/bitscan_manager/services/importer/`. The size and the three-file split are the user's ruling of 2026-10-27, so they are not findings.

TEST: PASS (`work/reports/TASK-145-test.md`; 175/175, 17/17 plants red). My re-run is as in TASK-144.md (2268 passed; ruff, format and mypy clean).

Spec read: SR §4.2 (L277, L285, L287), TS §3.3 L249 (`/bin/sh -c`, which is dash on every supported host), POSIX XCU §2.3, §2.6.3, §2.7.4. Every bypass below was run in this container under `dash` and `bash`, with `echo` in place of `rm`.

## Checks
- **Quoting, operators, expansions.** `$( )`, backticks, `${ }`, `$(( ))`, `<( )`, `>( )` and `$'…'` all lex, and their nested scripts are kept. So do `case` patterns inside `$( )`, a `)` inside a comment in `$( )`, and line continuations inside operators and words.
- **Command position.** Reserved words count only unquoted and only in command position. `for` lists, `case` words and patterns, and function names are kept as `data_words`.
- **Fail closed (#108 (j)).** Lexer errors raise `ShellSyntaxError`, and so does a `RecursionError`. There is no partial result. Depth is capped at 8 for every nesting form.
- **No regex, no execution.** No `re`, `shlex`, `subprocess` or `eval`, and nothing is expanded or opened.

## Tester's question
- `${…}` and `$((…))` count toward the depth of 8: confirmed. REQ-156 says "nesting deeper than 8" and does not say which forms count. Counting every form errs toward rejecting, gives a bound that no input can get around, and only rejects 9-deep parameter nesting, which no real check uses. The added test `test_param_and_arith_count_toward_depth_8` is the right pin.

## Findings
1. **blocking**, `shlex_posix.py:121-124` with `:258-263`, and `shlex_grammar.py:190`/`:223` (#108 (c), (h), (j); SR §4.2 L277; CHK-M7-329).
   - **The bug.** Pending here-documents are shared by every nesting level. So the first newline *inside* a `$( )`, `"$( )"`, `<( )`, `${x:-$( )}` or `$(( $( ) ))` reads the outer command's here-document body there.
   - **What the shells do.** `dash` and `bash` read that body only after the outer line ends, and they run the lines inside the substitution as commands.
   - **Result: these pass BIT102 with no finding, and dash runs the `rm`:**
     ```
     cat <<'E' $(
     rm -rf /x
     E
     )
     ```
     The same holds with `<<E` (unquoted), `"$(…)"`, `cat <<'E'; echo $(…)`, `${x:-$(…)}`, `$(($(…)))` and `<(…)` (the last runs under bash).
   - **Why it is in scope.** This is a literal `rm` in command position, not the user's accepted non-literal residual. The lexer misgroups it, so BIT102 fails open.
   - **Fix.** Record the nesting level with each pending here-document. A newline at a deeper level while one is pending raises `ShellSyntaxError` (fail closed, like the existing `)` rule at `shlex_grammar.py:223`). Alternatively, read the body only at a newline of the level that queued it.
   - **Tests.** Add the forms above to the must-reject corpus.
2. **should-fix**, `shlex_grammar.py:138-142` (`_RESERVED`) (#108 (c): "every simple command anywhere").
   - **The gap.** bash's `coproc` keyword is not handled. `bash -c 'coproc rm x'` passes, and bash runs `rm x` (checked).
   - **Why it belongs here.** The lexer already follows bash for `time` and `!` so that `bash -c` scripts are checked; `coproc` is the same kind of keyword.
   - **Fix.** Treat `coproc` as reserved. With a simple command, the next word is the command word. With `coproc NAME {…}` or `coproc NAME (…)`, NAME is a data word. If unsure, fail closed. Add must-reject rows.
   - It is not on the r2 list; main may fold it into r2.
3. nit, `shlex_grammar.py:233-237`: for `NAME ( )`, `cmds.remove(cur)` also drops any redirections already attached to `cur`, as in `>/etc/x f() { :; }`. That form is a syntax error in dash and bash, so nothing runs today. Raising when `cur.redirects` is non-empty would keep the "never drop what was seen" rule.

## Revision 1 and 1b re-review (2026-10-27)

Verdict: APPROVED

Frozen worktree at `64315ca`: the `0529083` product code plus the tester's reports. Files: `shlex_grammar.py` and `shlex_posix.py` (r1 and r1b hunks; the `Grammar.time()` and `@P`/`@E` hunks belong to TASK-146 r2). TEST: PASS (`TASK-145-test.md`, revision section: 230/230, 7/7 plants red).

Re-run by me: the six importer test files gave 2981 passed. `ruff check` and `ruff format --check` (278 files) are clean, and so is `mypy --strict` on `services/importer`.

Round-1 findings:
1. **Blocking, here-document across a substitution: fixed.**
   - Each pending entry now carries the depth that queued it (`shlex_grammar.py` `redirect()`).
   - A newline at a deeper depth while an outer one is pending raises (`shlex_posix.py:125-128`). So does any newline in a backtick child whose parent has one pending (`outer`, L290).
   - Substitutions inside `${…}` and `$((…))` go through `subst()` and so through `token()`, which means the depth rule covers them too.
   - The `)` rule (`shlex_grammar.py:133`) now looks only at here-documents queued at or below the current depth. That removes the old false positive on `cat <<E $(date)`.
   - The tester's must-reject rows cover all my forms plus `>( )` and a nested form. The two plants (depth ignored, `outer` dropped) are red.
2. **Should-fix, `coproc`: fixed.** `Grammar.coproc()` makes NAME a data word only before `(` or a compound opener. Otherwise the next word starts a simple command. Rows and the plant are red.
3. **Nit, function-definition redirections: fixed.** It now raises instead of dropping them.

r1b: the function-definition branch pops by identity in O(1), fail closed if `cur` is not the last command. The tester's 774 ms input now runs in about 48 ms, within REQ-156 (4).

No new findings.
