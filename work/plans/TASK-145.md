# TASK-145 plan: POSIX `sh` lexer for BIT102

Planner: planner-m7, 2026-10-27, from design note D2 (`work/tasks.md`, M7). Risk: high (importer; two approvals). File: `manager/bitscan_manager/services/importer/shlex_posix.py` only. Depends on TASK-140 (the package). Consumer: TASK-146 (`bit102.py`). Answers applied: #108 (c), (e), (h), (i), (j).

## 1. Spec

- SR §4.2 (SR L277): "`Execute` is split into tokens with a POSIX `sh` lexer (not a substring search)".
- SR §4.2 (SR L285): command substitution `$(…)`, backticks and process substitution `<(…)` inside `sh -c` scripts are rejected. SR L287: BIT102 is a safety net; the sandbox is the real control.
- #108 (j): input the lexer cannot handle is rejected (fail closed).

This module only splits text. It never runs, expands, globs or resolves anything, and decides nothing about BIT102. Python's `shlex` is not used: it handles neither `$( )`, backticks, here-documents nor `${ }`.

## 2. Output model

```python
class ShellSyntaxError(Exception):         # fail closed; TASK-146 reports BIT102
    def __init__(self, reason: str, line: int) -> None: ...

PartKind = Literal["lit", "sq", "dq", "param", "cmdsub", "backtick", "arith", "procsub_in", "procsub_out"]

@dataclass(frozen=True)
class Part:
    kind: PartKind
    text: str                      # the literal text (lit, sq, dq literal pieces); the raw source otherwise
    script: "Script | None" = None # nested script for cmdsub, backtick, procsub_*; also for param and arith when they hold substitutions

@dataclass(frozen=True)
class Word:
    parts: tuple[Part, ...]
    line: int
    def literal(self) -> str | None: ...   # the unquoted value if every part is lit, sq or a dq piece with no expansion; else None
    def scripts(self) -> tuple["Script", ...]: ...  # every nested script, at any part

@dataclass(frozen=True)
class Redirect:
    fd: int | None                 # the leading IO number, if any
    op: str                        # one of: < > >> >| <> <& >& &> &>> << <<- <<<
    target: Word | None            # None for here-documents
    heredoc_scripts: tuple["Script", ...] = ()  # substitutions found in an unquoted here-doc body

@dataclass(frozen=True)
class Command:                     # a simple command
    assignments: tuple[Word, ...]  # leading NAME=value words
    words: tuple[Word, ...]        # words[0] is the command word, if any
    redirects: tuple[Redirect, ...]
    line: int

@dataclass(frozen=True)
class Script:
    commands: tuple[Command, ...]  # in source order, at this nesting level only

MAX_DEPTH: Final = 8
def lex(source: str, *, depth: int = 0) -> Script: ...   # raises ShellSyntaxError
```

TASK-146 walks `Script.commands`, then recurses into every `Word.scripts()`, every redirect target's scripts and `heredoc_scripts`, and, for `sh`/`bash`/`dash -c`, into `lex(<script word literal>, depth=d+1)`.

## 3. Algorithm

The scanner follows POSIX XCU §2.3 token recognition, with the bash extensions an `Execute` can meet on Ubuntu.

1. **Characters.** Track `line` (starting at 1, plus 1 per `\n`, including newlines inside quotes and here-documents). Remove `\` followed by a newline outside single quotes (line continuation).
2. **Operators.** `&&`, `||`, `;;`, `;`, `&`, `|`, `|&`, `(`, `)` and newline end a word. Treat `;;&` and `;&` (bash case terminators) like `;;`. Redirection operators are `<`, `>`, `>>`, `>|`, `<>`, `<&`, `>&`, `&>`, `&>>`, `<<`, `<<-` and `<<<`. A run of digits directly before a redirection operator is its `fd`. `<(` and `>(` start a process substitution part, not a redirection.
3. **Quoting.**
   - `'…'`: literal (`sq`); an unterminated quote raises.
   - `"…"`: inside, `\` escapes only `$`, `` ` ``, `"`, `\` and newline. `$(`, `` ` ``, `${` and `$((` start nested parts, as outside quotes. Everything else is literal text. Unterminated raises.
   - `\x` outside quotes: the literal `x`. So `\rm` and `r''m` give the word with literal value `rm`.
4. **Expansions.**
   - `$(`: scan to the matching `)`, respecting quotes, nested `$(`, `(` … `)` pairs, `case` patterns and comments inside. Then `lex(inner, depth+1)` → `cmdsub`.
   - `` ` ``: scan to the next unescaped backtick; inside, `\`` , `\\` and `\$` lose the backslash. Then `lex(inner, depth+1)` → `backtick`.
   - `$((`: scan to the matching `))`. If the inner text holds `$(` or a backtick, lex those parts → `arith` with a `script`.
   - `${`: scan to the matching `}`. If the inner text holds `$(`, a backtick or `${`, lex them → `param` with a `script`.
   - `$name`, `$1`, `$?` and the like: a `param` part with no script.
   - `<(` and `>(`: like `$(` → `procsub_in` and `procsub_out`.
   - Depth: `lex` called with `depth > MAX_DEPTH` raises "nested too deeply".
5. **Comments.** `#` at the start of a word (outside quotes) runs to the end of the line.
6. **Here-documents.** After `<<` or `<<-`, the next word is the delimiter. It is quoted if any part of it was quoted; its literal value is the delimiter. At the next newline that ends the command line, read body lines until a line equal to the delimiter (`<<-`: leading tabs stripped from body lines and the delimiter line). With an unquoted delimiter, scan the body for `$(`, backticks, `${` and `$((` exactly as inside double quotes, and keep the scripts in `heredoc_scripts`. With a quoted delimiter the body is data. A body not terminated before the end of the source raises (fail closed, #108 (h)).
7. **Grouping into commands.** Walk the tokens with a small state machine:
   - *Command position* is the start of the script, and after `;`, `&`, `|`, `|&`, `&&`, `||`, `(`, `)`, `;;`, a newline, and the reserved words listed here.
   - In command position the reserved words `if`, `then`, `else`, `elif`, `fi`, `do`, `done`, `while`, `until`, `{`, `}` and `!` are dropped; the next word keeps command position. A reserved word counts only when it is unquoted, a whole word, and in command position.
   - `for NAME [in WORD…]`: NAME and the `in` list are not commands; `do` returns to command position.
   - `case WORD in`: then pattern mode. Words up to `)` (an optional leading `(` allowed) are patterns, not commands. After `)`, command position until `;;` (back to pattern mode) or `esac`.
   - `NAME ( )`, a word in command position followed by `(` `)`, is a function definition. The name is not a command, and the body follows in command position.
   - In command position, words of the form `NAME=…` (NAME matches `[A-Za-z_][A-Za-z0-9_]*`, the `=` unquoted) are assignments until the first other word.
   - Redirections attach to the current command, which may have no words (for example `> /tmp/x` alone).
   - `select`, `function NAME { … }`, `[[ … ]]` and `(( … ))`: `function` is dropped like a reserved word (its NAME is not a command); `[[` … `]]` and `(( … ))` become one command whose words are not command words (`words` empty, and their nested scripts are kept in an assignment-free `Command` with one `Word` holding the parts). `select` is treated like `for`.
8. **Anything not covered** raises `ShellSyntaxError`: an unmatched `)`, `}`, `fi`, `done` or `esac`; a missing `do`; an operator at the start of a script (`; rm`); a stray `)` in a case pattern list; a NUL character. This is the fail-closed path. TASK-146 turns it into BIT102 with the reason.

Validate the grouping with a small balance stack (`if`/`fi`, `do`/`done`, `case`/`esac`, `{`/`}`, `(`/`)`), so a structural mismatch raises instead of mis-grouping.

## 4. Limits and performance

- Input is at most 16,384 characters (BIT008 runs before it). The scanner is a single pass per nesting level, so the cost is linear in the size times the depth. Each call must finish within 100 ms on the CI runner, at most 8 levels.
- No regular expressions at all (the identifier check uses `str` methods). If one becomes necessary, it must use `re2` (G1 bans `re`).

## 5. Tests (TP-M7-07; tester file `manager/tests/test_bit102_lexer.py`)

1. A table of at least 60 sources with the expected command words and nested scripts, including:
   - `echo "rm -rf /"`: one command `echo` with a `dq` word; no nested script.
   - `r''m x` and `\rm x`: command word literal `rm`.
   - `a;rm x`, `a && rm x`, `a || rm x`, `a | rm x`, `a & rm x`, `(rm x)`, `{ rm x; }`: `rm` is a command.
   - `x=$(rm y)`: an assignment whose word holds a `cmdsub` script with command `rm`.
   - `` echo `rm y` `` and `echo "$(rm y)"`: nested `rm`.
   - `diff <(cat a) <(cat b)`: two `procsub_in` scripts.
   - `echo ${x:-$(rm y)}`: a `param` part with a nested script.
   - `echo $((1 + $(rm y)))`: an `arith` part with a nested script.
   - `if grep -q x f; then rm y; fi`: commands `grep` and `rm`.
   - `for f in rm mv; do echo "$f"; done`: only `echo` is a command.
   - `case "$x" in rm) echo rm;; esac`: only `echo` is a command.
   - `f() { rm y; }; f`: commands `rm` and `f`.
   - `FOO=1 BAR=2 rm y`: two assignments, command `rm`.
   - `cat <<'EOF'` with `$(rm y)` in the body: no `heredoc_scripts`.
   - `cat <<EOF` with `$(rm y)` in the body: one `heredoc_script` with `rm`.
   - `cat <<-EOF` with a tab-indented delimiter.
   - `# rm y` alone: no command.
   - `echo x # rm y`: one command, `echo`.
   - `2>/dev/null`, `>&2`, `2>&1`, `&>/tmp/x`, `>|/tmp/x`, `<<<"rm"`: the right `fd`, `op` and target.
   - `dpkg-query -W -f='${Status}' apparmor 2>/dev/null` (the SR §1.1 command): command `dpkg-query`, the `'${Status}'` argument a literal, one redirect.
   - A line continuation `ls \` newline `-l`: one command `ls -l`.
   - CRLF source built in code: `\r` stays a literal character (the XML parser already normalised CRLF).
2. Fail closed (each raises `ShellSyntaxError` with a line): an unterminated `'`, `"`, `$(`, backtick, `${` or here-document; `)` alone; `fi` alone; `if x; then y`; `; rm`; a NUL; 9 nested `$(`.
3. Property test: Hypothesis text up to 16,384 characters, drawn from shell-significant characters and words. `lex` returns a `Script` or raises `ShellSyntaxError`, never anything else, within 100 ms each.
4. Source check: no `subprocess`, `os.system`, `os.exec*`, `eval(`, `exec(` or `re` import in the module.

Plants: CHK-M7-332 (a lexer error swallowed and an empty `Script` returned) must turn TASK-146's corpus red; a plant that drops `$(` recursion must turn row 1 red.

## 6. Budget

About 200 lines was planned. **As built** (user ruling 2026-10-27, `work/decisions.md`): about 514 lines, accepted as one task id in three files under `services/importer/`, with imports one way (model → grammar → posix):
- `shlex_model.py`: `Part`, `Word` (adds `.raw`), `Redirect`, `Command`, `Script` (adds `data_words`), `ShellSyntaxError`, `MAX_DEPTH`.
- `shlex_grammar.py`: the grouping into commands (§3 step 7).
- `shlex_posix.py`: `lex(source, *, depth=0, line=1)`, which re-exports the model.

The planned `shlex_heredoc.py` split is not used. Its over-detection (`[[ ]]`, `(( ))`, `$((`, `time`) errs toward rejecting.

**BIT102 consequence (user ruling, same row):** a command word that is not a literal (`"$c" x`, `${x} y`, `$(echo rm) x`, `$'\x72m' x`, `sh -c "$s"`) is allowed. Only its nested scripts are checked. That is TASK-146's rule, and this lexer only has to expose the nested scripts. Accepted residual: `c=rm; "$c" -rf /` passes BIT102; the sandbox (M10) is the control.
