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

## Revision 1 (2026-10-27): review round 1 (reviewer-m7 CHANGES_REQUESTED)

impl-manager-m7d. The changes are in the working tree and nothing is committed. The files changed are `shlex_posix.py` (361 lines, 27 changed) and `shlex_grammar.py` (267 lines; about 30 of the changed lines are this revision). Both are in `manager/bitscan_manager/services/importer/`. The rest of the `shlex_grammar.py` diff is TASK-146 r2's `Grammar.time()`.

### Finding 1 (blocking): here-document bodies read inside a substitution
- **Fix.** Each pending here-document now records the depth that queued it (`shlex_grammar.py` `redirect()`, last line). A newline token at a deeper depth while a here-document is pending at an outer one raises `ShellSyntaxError("newline in a substitution before a here-document")` (`shlex_posix.py` L127), giving BIT102, fail closed.
- **Backticks.** A backtick script is lexed by a child `_Lexer`, so the child gets `outer=True` when its parent has a pending here-document (L290). Any newline inside it then raises the same way.
- **Side effect at `)`.** The rule at `)` (`shlex_grammar.py` L133) now raises only for a here-document queued *inside* the closing `$( )`, which is its intent. Before, any pending here-document counted. So `cat <<E $(date)` followed by a newline, `body` and `E` no longer gets the false "unexpected )". dash and bash run that form normally.
- **Checked in this container under dash and bash** (`echo RAN` in place of `rm -rf /x`). The inner line runs in every form: `$( )`, `<<E` (unquoted), `"$( )"`, `cat <<'E'; echo $( )`, `${x:-$( )}`, `$(($( )))`, backticks and `<( )` (bash; dash has no `<(`). Each of them is now BIT102.

### Finding 2 (should-fix): bash `coproc`
- **Fix.** `coproc` is a reserved word in command position (`_RESERVED`), handled by `Grammar.coproc()` (L180):
  - With a word followed by `(` or a compound opener (`{`, `if`, `while`, `until`, `for`, `select`, `case`, `function`), that word is NAME and becomes a data word.
  - Otherwise the next word starts a simple command, as an assignment if it has that form.
  - A reserved word or a redirection right after `coproc` is handled as usual, so `coproc { rm x; }` and `coproc time rm x` work.
- **Checked under bash.** `coproc echo RAN >&2`, `coproc N { … }`, `coproc N ( … )`, `coproc { … }`, `coproc a=1 echo …` and `coproc N while …` all run their command.
- **dash.** `coproc` is not a keyword in dash (dash runs a command named `coproc`). Reading it as one at the Execute level only makes BIT102 see more.

### Finding 3 (nit): function-definition redirections
`NAME ( )` now raises when redirections are already attached (`>/etc/x f() { :; }`), instead of dropping them (L145). dash and bash reject that form as a syntax error.

### Gates and runs (from the repo root, venv `manager/.venv`)
- `ruff check manager`: clean. `ruff format --check manager`: 278 files formatted. `mypy --strict --config-file manager/pyproject.toml manager`: no issues.
- From `manager/`: `pytest -q -p no:cacheprovider tests/test_bit102.py tests/test_bit102_lexer.py tests/test_bit_fixtures.py tests/test_bit_fuzz.py tests/test_bit_parse.py tests/test_bit_validate.py` gave **2548 passed**, the same as before the change. No existing test needed changing.
- A 30,000-input token fuzz raised nothing; the worst input took 0.7 ms.

### Cases for the tester
- **Must-reject** (each also with `rm -rf /x` in place of `rm x`). These come from the review: `cat <<'E' $(⏎rm -rf /x⏎E⏎)`, `cat <<E $(⏎…⏎E⏎)`, `cat <<'E' "$(⏎…⏎E⏎)"`, `cat <<'E'; echo $(⏎…⏎E⏎)`, `cat <<'E' ${x:-$(⏎…⏎E⏎)}`, `cat <<'E' $(($(⏎…⏎E⏎)))`, `` cat <<'E' `⏎…⏎E⏎` ``, `cat <<'E' <(⏎…⏎E⏎)`, `cat <<'E' >(⏎…⏎E⏎)`, and `x=$(cat <<'E' $(⏎…⏎E⏎)⏎)`. The finding is `Execute cannot be checked: newline in a substitution before a here-document.`
- **Must-reject coproc:** `coproc rm x`, `bash -c 'coproc rm x'`, `bash -c 'coproc NAME { rm x; }'`, `bash -c 'coproc NAME ( rm x )'`, `bash -c 'coproc { rm x; }'`, `bash -c 'coproc a=1 rm x'` and `bash -c 'coproc NAME while rm x; do :; done'`.
- **Must-reject nit:** `>/etc/x f() { :; }`.
- **Must-pass:**
  - `cat <<E $(date)⏎body⏎E` (was a false positive);
  - `x=$(cat <<E⏎body⏎E⏎)`, `cat <<E⏎$(⏎date⏎)⏎E`, ``cat <<E⏎`date`⏎E`` and `( cat <<E )⏎body⏎E`;
  - `bash -c 'coproc cat /etc/x'`, `bash -c 'coproc NAME { cat /etc/x; }'` and `f() { cat /x; }; f`.
- **Lexer table** (`test_bit102_lexer.py`): `coproc NAME { cat x; }` gives data word `NAME` and command `cat x`; `coproc a=1 cat x` gives assignment `a=1`, command `cat x`.
- **Plants:**
  - Ignore the depth in the newline check, i.e. delete the `any(p[4] < self.depth …)` test at L127. The first must-reject row must turn green.
  - Drop `outer=` for backticks (L290). The backtick row must turn green.
  - Remove `"coproc"` from `_RESERVED`. The coproc rows must turn green.

### Revision 1b (2026-10-27): quadratic function definitions (tester-m7d, REQ-156 (4))
- **The bug.** In `shlex_grammar.py`, the `NAME ( )` branch dropped the command with `cmds.remove(cur)`. That compares the dataclass with `==` against every earlier command, so a script of many function definitions lexed in quadratic time. The bug predates r1.
- **The fix.** `cur` is always the last command appended, so it is now removed with `cmds.pop()`, after an identity check that raises `ShellSyntaxError` if it fails (fail closed). The branch is now O(1).
- **Timing.** Best-of-3 thread CPU time for `check_execute` on 16,384-character inputs:

  | Repeated unit | Before | After |
  | --- | --- | --- |
  | `x;f(){ :;};` | 774 ms | 48 ms |
  | `a⏎f()⏎:⏎` | 533 ms | 51 ms |
  | `true⏎f() { :; }⏎` | 140 ms | 32 ms |
  | `{{⏎rm()` | 326 ms | 35 ms |

- **Checks.** Gates are clean. The six-file set gives 2981 passed, with tester-m7d's new rows in the tree.
