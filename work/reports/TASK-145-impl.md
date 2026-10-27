# TASK-145 IMPL: POSIX sh lexer for BIT102

Owner: impl-manager-m7b. REQ-156; #108 (c), (e), (h), (i), (j). Spec: SR §4.2 (SR L277, L285, L287). Design: note D2 and `work/plans/TASK-145.md`. Risk: high (importer; two approvals).

## What changed

| File | Change | Non-blank lines |
| --- | --- | --- |
| `manager/bitscan_manager/services/importer/shlex_model.py` | new: `Part`, `Word`, `Redirect`, `Command`, `Script`, `ShellSyntaxError`, `MAX_DEPTH`, `PartKind`, `join_scripts` | 78 |
| `manager/bitscan_manager/services/importer/shlex_grammar.py` | new: grouping of tokens into commands (plan §3 steps 7 and 8) | 202 |
| `manager/bitscan_manager/services/importer/shlex_posix.py` | new: `lex()`, the scanner (tokens, quoting, expansions, here-documents); re-exports the model | 322 |

No other file was changed. The split was a user ruling (2026-10-27): one task id, three files, imports one way only (`shlex_model` ← `shlex_grammar` ← `shlex_posix`), so there is no cycle. The plan budgeted about 200 lines. The plan's fallback (moving out the here-documents) would have saved only about 25, because the grouping state machine alone is about 200.

## Interface (consumers import from `shlex_posix`)

`lex(source, *, depth=0, line=1) -> Script`. It raises `ShellSyntaxError(reason, line)` and never returns a partial script. The model is the plan's §2, with these differences:
- `Word.raw`: the source text of the word. BIT102 messages quote tokens as written; the corpus expects `r''m`, for example.
- `Word.plain()`: text with no quoting and no expansion, used for reserved words and IO numbers. `Word.is_assignment()`: `NAME=…`, with an unquoted ASCII identifier before the `=`.
- `Script.data_words`: words that are not commands, namely `for` names and lists, `case` subjects and patterns, and function names. BIT102 checks only the scripts nested in them. Without this, `for f in $(rm x)` and `case "$(rm x)" in` would hide their substitutions.
- `lex` takes `line=` too, so a nested `-c` script can keep its line base.
- An escaped character (`\x`) is an `sq` part, so `\rm` gives the literal `rm` but `\if` is not a keyword.

## Behaviour notes for the reviewer

These are deliberate. Every one errs toward BIT102 seeing more, never less (accepted by the lead, 2026-10-27):
- `$((` is always arithmetic. An unbalanced one raises; there is no fallback to `$( (…) )`, because a fallback re-parse can blow up exponentially under nesting. Writing `$( (x) )` with a space still works.
- `[[ ]]` and `(( ))` get no special handling and are lexed as ordinary tokens. So `[[ $a > b ]]` reads as an output redirection to `b`, and BIT102 would reject it.
- `time` (with `-p`) is a reserved word, as in bash, so `time rm x` exposes `rm`. `!` works the same way.
- Where the grammar is lenient (a word after `)` or `fi`), the word becomes a command word, so it gets checked.
- `${…}` and `$((…))` count toward `MAX_DEPTH` as well as `$( )`, backticks and `<( )`/`>( )`, so no input can recurse without a bound. `RecursionError` is still caught and turned into `ShellSyntaxError` as a fail-closed net.
- A `<<` here-document inside `$( )` whose body has not started by that `)` raises (fail closed).
- `$'…'` (ANSI-C) is a `param` part, never a literal.
- A `\r` in the source stays a literal character, as the plan says.

## Checks run here (scratch harness outside the tree; the tests are tester-m7b's)

- All 91 must-pass cases and every `Execute` of both samples lex without an error.
- All 149 must-reject cases give the command structure TASK-146 needs.
- Every plan §5 row 1 shape gives the expected commands, redirects (`fd`, `op`, target) and nested scripts, including the SR §1.1 command.
- Every plan §5 row 2 fail-closed input raises with a line: unterminated `'`, `"`, `$(`, backtick, `${` or here-document; `)` alone; `fi` alone; `if x; then y`; `; rm`; NUL; 9 nested `$(`. Also `while x; done`, `{ rm x }`, `a |` and `$((1)`.
- 8 nested `$(` lex; 9 raise.
- 23,000 random inputs built from shell-significant pieces raised nothing but `ShellSyntaxError`, worst 7.6 ms.
- Pathological 16,384-character inputs (8,192 separators, 8-deep nesting, long words): about 52 ms worst on this Windows box. Under load from the other agents, wall time rose to 90–150 ms, but process CPU time stayed at 31–62 ms. The plan's bound is 100 ms on the CI runner.
- Source: no `subprocess`, `os.system`, `eval(`, `exec(` or `re`, and no regular expressions at all.
- `ruff check manager`, `ruff format --check manager` and `mypy --strict --config-file manager/pyproject.toml` on these files are clean.

## For the tester (TP-M7-07, `test_bit102_lexer.py`)

- Import from `bitscan_manager.services.importer.shlex_posix`, which re-exports the model.
- Line continuation: when building `\` + newline in a test, use `chr(92) + chr(10)` or a Python file. A Git Bash heredoc mangled it in my harness, though the lexer handles it.
- The plant "drop the `$(` recursion" is in `shlex_posix._Lexer.subst`.
