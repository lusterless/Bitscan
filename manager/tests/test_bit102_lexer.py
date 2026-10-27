"""TP-M7-07: the POSIX sh lexer for BIT102 (TASK-145; REQ-156).

Expected tokens come from POSIX XCU §2.3 (token recognition), §2.6.3
(command substitution), §2.7 (redirection), §2.10 (grammar), SR §4.2 ("split
into tokens with a POSIX sh lexer"), the approved answer #108 (c), (h), (j)
and work/plans/TASK-145.md §5. One task in three files (user ruling
2026-10-27): shlex_model, shlex_grammar, shlex_posix. CHK-M7-100 to -102 and
-112; plants CHK-M7-332 and -387. Owner: tester-m7b.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bitscan_manager.services.importer import shlex_grammar, shlex_model, shlex_posix
from bitscan_manager.services.importer.shlex_posix import (
    MAX_DEPTH,
    Command,
    Script,
    ShellSyntaxError,
    Word,
    lex,
)

BS, NL = chr(92), chr(10)  # backslash and newline, built in code
# A redirection target under /tmp, as shell text only (never opened).
TX = "/" + "tmp/x"


def lit(word: Word) -> str:
    """The literal value, or the raw text for a word that expands."""
    value = word.literal()
    return value if value is not None else "<" + word.raw + ">"


def walk(script: Script, depth: int = 0) -> list[tuple[int, str]]:
    """(depth, command word) for every simple command, at every nesting
    level, in source order within a level. Commands with no word are ''."""
    out: list[tuple[int, str]] = []
    for cmd in script.commands:
        out.append((depth, lit(cmd.words[0]) if cmd.words else ""))
        for word in cmd.assignments + cmd.words:
            for nested in word.scripts():
                out += walk(nested, depth + 1)
        for r in cmd.redirects:
            for nested in (r.target.scripts() if r.target else ()) + r.heredoc_scripts:
                out += walk(nested, depth + 1)
    for word in script.data_words:
        for nested in word.scripts():
            out += walk(nested, depth + 1)
    return out


def words(src: str) -> list[str]:
    """Command words of every command (all levels), '' for word-less ones."""
    return [w for _, w in walk(lex(src))]


def top(src: str) -> list[Command]:
    return list(lex(src).commands)


# CHK-M7-100: the token table (>= 60 inputs) ----------------------------------

TABLE: list[tuple[str, list[str]]] = [
    # quoting (XCU §2.2)
    ('echo "rm -rf /"', ["echo"]),
    ("echo 'rm -rf /'", ["echo"]),
    ("r''m x", ["rm"]),
    (BS + "rm x", ["rm"]),
    ('"r"m x', ["rm"]),
    ('"rm" x', ["rm"]),
    ("r" + BS + "m x", ["rm"]),
    ("echo '$(rm x)'", ["echo"]),
    ('echo "' + BS + '$(rm x)"', ["echo"]),
    ("echo " + BS + "`rm x" + BS + "`", ["echo"]),
    # operators and lists (XCU §2.9)
    ("a;rm x", ["a", "rm"]),
    ("a ; rm x", ["a", "rm"]),
    ("a&&rm x", ["a", "rm"]),
    ("a || rm x", ["a", "rm"]),
    ("a | rm x", ["a", "rm"]),
    ("a |& rm x", ["a", "rm"]),
    ("a & rm x", ["a", "rm"]),
    ("a" + NL + "rm x", ["a", "rm"]),
    ("(rm x)", ["rm"]),
    ("( a; (rm x) )", ["a", "rm"]),
    ("{ rm x; }", ["rm"]),
    ("! rm x", ["rm"]),
    ("time rm x", ["rm"]),
    ("time -p rm x", ["rm"]),
    # compound commands (XCU §2.9.4) and functions (§2.9.5)
    ("if grep -q x f; then rm y; fi", ["grep", "rm"]),
    ("if a; then b; elif c; then d; else e; fi", ["a", "b", "c", "d", "e"]),
    ("while read -r f; do stat " + '"$f"' + "; done", ["read", "stat"]),
    ("until false; do rm x; done", ["false", "rm"]),
    ('for f in rm mv; do echo "$f"; done', ["echo"]),
    ("for f; do rm x; done", ["rm"]),
    ('case "$x" in rm) echo rm;; esac', ["echo"]),
    ("case x in (a) rm y;; b|c) echo;; esac", ["rm", "echo"]),
    ("case x in a) echo a" + NL + "esac", ["echo"]),
    ("f() { rm y; }; f", ["rm", "f"]),
    ("function f { rm y; }", ["rm"]),
    ("echo if then fi", ["echo"]),
    ('"if" x', ["if"]),
    ("[ -f /etc/x ] && cat /etc/x", ["[", "cat"]),
    # assignments (XCU §2.9.1)
    ("FOO=1 BAR=2 rm y", ["rm"]),
    ("a=1", [""]),
    ("a=b c=d", [""]),
    ("x=$(rm y)", ["", "rm"]),
    ('x="$(rm y)"', ["", "rm"]),
    # substitutions (XCU §2.6.3) and process substitution
    ("echo `rm y`", ["echo", "rm"]),
    ('echo "$(rm y)"', ["echo", "rm"]),
    ("echo $(echo $(rm x))", ["echo", "echo", "rm"]),
    ("echo `echo " + BS + "`rm x" + BS + "``", ["echo", "echo", "rm"]),
    ("diff <(cat a) <(cat b)", ["diff", "cat", "cat"]),
    ("tee >(cat)", ["tee", "cat"]),
    ("echo ${x:-$(rm y)}", ["echo", "rm"]),
    ('echo "${x:-$(rm y)}"', ["echo", "rm"]),
    ("echo $((1 + $(rm y)))", ["echo", "rm"]),
    ("echo $((1+2))", ["echo"]),
    ("echo $HOME $1 $? ${#x} $@ $$", ["echo"]),
    ('ls -l "$(dirname "$0")"', ["ls", "dirname"]),
    ("for f in $(rm x); do :; done", [":", "rm"]),
    ('case "$(rm x)" in a) :;; esac', [":", "rm"]),
    # redirections carry scripts too
    ("echo x 2>" + '"$(rm y)"', ["echo", "rm"]),
    ("cat <<<$(rm x)", ["cat", "rm"]),
    ("cat < <(rm x)", ["cat", "rm"]),
    # here-documents (XCU §2.7.4, #108 (h))
    ("cat <<'EOF'" + NL + "$(rm y)" + NL + "EOF", ["cat"]),
    ('cat <<"EOF"' + NL + "`rm y`" + NL + "EOF", ["cat"]),
    ("cat <<" + BS + "EOF" + NL + "$(rm y)" + NL + "EOF", ["cat"]),
    ("cat <<EOF" + NL + "$(rm y)" + NL + "EOF", ["cat", "rm"]),
    ("cat <<EOF" + NL + "`rm y`" + NL + "EOF", ["cat", "rm"]),
    ("cat <<EOF" + NL + "${x:-$(rm y)}" + NL + "EOF", ["cat", "rm"]),
    ("cat <<-EOF" + NL + "\t$(id)" + NL + "\tEOF", ["cat", "id"]),
    ("cat <<A <<B" + NL + "$(id)" + NL + "A" + NL + "`rm x`" + NL + "B",
     ["cat", "id", "rm"]),
    ("cat <<EOF; rm x" + NL + "body" + NL + "EOF", ["cat", "rm"]),
    ("cat <<EOF" + NL + "rm x" + NL + "EOF" + NL + "ls", ["cat", "ls"]),
    # comments (XCU §2.3 rule 9)
    ("# rm y", []),
    ("echo x # rm y", ["echo"]),
    ("echo x;# rm y", ["echo"]),
    ("echo a#b", ["echo"]),
    ("#!/bin/sh" + NL + "ls", ["ls"]),
    # line continuation and the SR §1.1 command
    ("ls " + BS + NL + "-l", ["ls"]),
    ("r" + BS + NL + "m x", ["rm"]),
    ("dpkg-query -W -f='${Status}' apparmor 2>/dev/null", ["dpkg-query"]),
    # common CIS audit forms
    ("find / -xdev -perm -4000 -print 2>/dev/null", ["find"]),
    ("find / -print | while read -r f; do stat -c %a " + '"$f"' + "; done",
     ["find", "read", "stat"]),
    ("awk -F: '($3 == 0) { print $1 }' /etc/passwd", ["awk"]),
    ("grep -E '^" + BS + "s*PermitRootLogin' /etc/ssh/sshd_config", ["grep"]),
    ("sysctl -n kernel.randomize_va_space", ["sysctl"]),
    ("test -f x || exit 1", ["test", "exit"]),
    ("> " + TX, [""]),
]  # fmt: skip


def test_table_has_at_least_60_inputs() -> None:
    assert len(TABLE) >= 60


@pytest.mark.parametrize(("src", "expected"), TABLE)
def test_command_words(src: str, expected: list[str]) -> None:
    assert words(src) == expected


def test_quoted_argument_is_one_word() -> None:
    (cmd,) = top('echo "rm -rf /"')
    assert [lit(w) for w in cmd.words] == ["echo", "rm -rf /"]
    assert [p.kind for p in cmd.words[1].parts] == ["dq"]
    assert cmd.words[1].scripts() == ()


def test_escaped_and_split_quotes_give_literal_rm() -> None:
    for src in ("r''m x", BS + "rm x", '"r"m x', "'rm' x"):
        (cmd,) = top(src)
        assert cmd.words[0].literal() == "rm", src


def test_escapes_inside_double_quotes() -> None:
    (cmd,) = top('echo "a' + BS + '"b" "' + BS + "$x" + '" "' + BS + 'n"')
    assert [lit(w) for w in cmd.words] == ["echo", 'a"b', "$x", BS + "n"]


def test_word_boundaries() -> None:
    (cmd,) = top("echo a" + BS + " b 'c d'\"e\" a#b")
    assert [lit(w) for w in cmd.words] == ["echo", "a b", "c de", "a#b"]


def test_assignments_and_command() -> None:
    (cmd,) = top("FOO=1 BAR=$(id) rm y")
    assert [w.raw for w in cmd.assignments] == ["FOO=1", "BAR=$(id)"]
    assert lit(cmd.words[0]) == "rm"
    (cmd,) = top("echo FOO=1")
    assert cmd.assignments == () and [lit(w) for w in cmd.words] == ["echo", "FOO=1"]
    (cmd,) = top("'FOO'=1 x")  # a quoted name is not an assignment
    assert cmd.assignments == () and lit(cmd.words[0]) == "FOO=1"


@pytest.mark.parametrize(
    ("src", "fd", "op", "target"),
    [
        ("ls 2>/dev/null", 2, ">", "/dev/null"),
        ("echo x >&2", None, ">&", "2"),
        ("cmd 2>&1", 2, ">&", "1"),
        ("cmd &>" + TX, None, "&>", TX),
        ("cmd &>>" + TX, None, "&>>", TX),
        ("cmd >|" + TX, None, ">|", TX),
        ("cmd >>" + TX, None, ">>", TX),
        ("cmd > " + TX, None, ">", TX),
        ('cat <<<"rm"', None, "<<<", "rm"),
        ("cat < /etc/x", None, "<", "/etc/x"),
        ("cat <>/etc/x", None, "<>", "/etc/x"),
        ("cmd 3<&0", 3, "<&", "0"),
        ("cmd 10>" + TX, 10, ">", TX),
        ("cmd 2>'/dev/null'", 2, ">", "/dev/null"),
    ],
)
def test_redirections(src: str, fd: int | None, op: str, target: str) -> None:
    (cmd,) = top(src)
    (r,) = cmd.redirects
    assert (r.fd, r.op) == (fd, op)
    assert r.target is not None and r.target.literal() == target


def test_digits_not_before_an_operator_are_a_word() -> None:
    (cmd,) = top("echo 2 >" + TX)
    assert [lit(w) for w in cmd.words] == ["echo", "2"]
    assert cmd.redirects[0].fd is None


def test_sr_example_command() -> None:
    (cmd,) = top("dpkg-query -W -f='${Status}' apparmor 2>/dev/null")
    assert [lit(w) for w in cmd.words] == [
        "dpkg-query",
        "-W",
        "-f=${Status}",
        "apparmor",
    ]
    assert [(r.fd, r.op) for r in cmd.redirects] == [(2, ">")]
    assert all(w.scripts() == () for w in cmd.words)


def test_heredoc_quoted_body_is_data_unquoted_is_scanned() -> None:
    (cmd,) = top("cat <<'EOF'" + NL + "$(rm y)" + NL + "EOF")
    (r,) = cmd.redirects
    assert (r.op, r.target, r.heredoc_scripts) == ("<<", None, ())
    (cmd,) = top("cat <<EOF" + NL + "a $(id) b" + NL + "EOF")
    (r,) = cmd.redirects
    assert len(r.heredoc_scripts) == 1
    assert [lit(c.words[0]) for c in r.heredoc_scripts[0].commands] == ["id"]


def test_heredoc_body_is_not_commands() -> None:
    script = lex("cat <<EOF" + NL + "rm -rf /" + NL + "EOF")
    assert [lit(c.words[0]) for c in script.commands] == ["cat"]


def test_crlf_carriage_return_stays_literal() -> None:
    # The XML parser already normalised CRLF; a lone \r is a word character.
    script = lex("echo a\r" + NL + "rm x\r")
    assert [[lit(w) for w in c.words] for c in script.commands] == [
        ["echo", "a\r"],
        ["rm", "x\r"],
    ]


def test_lines_are_counted() -> None:
    script = lex("a" + NL + NL + "b 'x" + NL + "y'" + NL + "c")
    assert [c.line for c in script.commands] == [1, 3, 5]
    script = lex("x", line=40)
    assert script.commands[0].line == 40


def test_function_names_and_for_lists_are_data() -> None:
    script = lex("for f in rm mv; do echo; done; g() { :; }")
    assert [lit(w) for w in script.data_words][:3] == ["f", "rm", "mv"]
    assert "g" in [lit(w) for w in script.data_words]
    assert [lit(c.words[0]) for c in script.commands] == ["echo", ":"]


def test_reserved_words_only_in_command_position() -> None:
    assert words("echo do done fi") == ["echo"]
    assert words("x=1 if") == ["if"]  # after an assignment it is a word
    assert words(BS + "if x") == ["if"]


def test_lexer_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import subprocess

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the lexer executed something")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(os, "system", boom)
    lex("$(rm -rf /) `id` <(cat /etc/shadow) ${x:-$(reboot)}")


# CHK-M7-101: fail closed ----------------------------------------------------

FAIL_CLOSED = [
    "echo 'abc",
    'echo "abc',
    "echo $(abc",
    "echo `abc",
    "echo ${abc",
    "echo $((1",
    "echo $((1)",
    "cat <<EOF" + NL + "abc",
    "cat <<EOF",
    "cat <<EOF" + NL,
    ")",
    "fi",
    "done",
    "esac",
    "then",
    "}",
    "if x; then y",
    "while x; do y",
    "while x; done",
    "for f in a; do x",
    "case x in a) y;;",
    "{ rm x",
    "( rm x",
    "; rm",
    "&& rm",
    "| rm",
    "a |",
    "a &&",
    "a ;; b",
    "a\x00b",
    "echo $'abc",
    "x=$(cat <<EOF)",
    "echo > ",
    "f ( x",
]


@pytest.mark.parametrize("src", FAIL_CLOSED)
def test_unlexable_input_raises_the_fail_closed_error(src: str) -> None:
    with pytest.raises(ShellSyntaxError) as info:
        lex(src)
    assert isinstance(info.value.line, int) and info.value.line >= 1
    assert info.value.reason and isinstance(info.value.reason, str)


def test_fail_closed_error_has_the_line() -> None:
    with pytest.raises(ShellSyntaxError) as info:
        lex("echo ok" + NL + "echo ok" + NL + "echo 'oops")
    assert info.value.line == 3


def test_fail_closed_error_quotes_no_input() -> None:
    marker = "SECRET-7b-91"
    for src in (f"echo '{marker}", f"echo $({marker}", f"{marker} )"):
        with pytest.raises(ShellSyntaxError) as info:
            lex(src)
        assert marker not in info.value.reason and marker not in str(info.value)


def _nest(depth: int, opener: str = "$(", closer: str = ")") -> str:
    src = "rm x"
    for _ in range(depth):
        src = f"echo {opener}{src}{closer}"
    return src


def test_max_depth_is_8() -> None:
    assert MAX_DEPTH == 8


@pytest.mark.parametrize(("opener", "closer"), [("$(", ")"), ("<(", ")"), (">(", ")")])
def test_8_nested_substitutions_accepted_9_refused(opener: str, closer: str) -> None:
    script = lex(_nest(8, opener, closer))
    assert max(d for d, _ in walk(script)) == 8
    assert walk(script)[-1] == (8, "rm")
    with pytest.raises(ShellSyntaxError):
        lex(_nest(9, opener, closer))


def _backticks(depth: int) -> str:
    src = "rm x"
    for _ in range(depth):
        inner = src.replace(BS, BS + BS).replace("`", BS + "`")
        src = f"echo `{inner}`"
    return src


def test_8_nested_backticks_accepted_9_refused() -> None:
    assert walk(lex(_backticks(8)))[-1] == (8, "rm")
    with pytest.raises(ShellSyntaxError):
        lex(_backticks(9))


def test_mixed_nesting_over_8_refused() -> None:
    src = "rm x"
    for i in range(9):
        src = f"echo $({src})" if i % 2 else f"cat <({src})"
    with pytest.raises(ShellSyntaxError):
        lex(src)


def test_depth_argument_counts() -> None:
    lex("echo $(x)", depth=7)
    with pytest.raises(ShellSyntaxError):
        lex("echo $(x)", depth=8)
    with pytest.raises(ShellSyntaxError):
        lex("x", depth=9)


# CHK-M7-112: property test -------------------------------------------------

PIECES = [
    " ", "\t", NL, ";", "&", "|", "&&", "||", "(", ")", "{", "}", "<", ">", ">>",
    "<<", "<<-", "<<<", ">&", "2>", "<(", ">(", "$(", "`", "${", "$((", "))", "'",
    '"', BS, "#", "$", "=", "if", "then", "fi", "do", "done", "case", "in", "esac",
    ";;", "for", "while", "!", "rm", "EOF", "x", "-c", "sh", "*", "?", "~", "\r",
]  # fmt: skip


def _lex_once(src: str) -> float:
    start = time.thread_time()
    try:
        result = lex(src)
    except ShellSyntaxError as exc:
        assert isinstance(exc.line, int)
    else:
        assert isinstance(result, Script)
    return time.thread_time() - start


def _bounded(src: str) -> None:
    """Never anything but ShellSyntaxError, and within 100 ms (REQ-156 (4)).
    CPU time of this thread, best of five, so a garbage-collector pause
    caused by the rest of the test process (not by the lexer) or load from
    other jobs cannot fail it; a super-linear lexer still does."""
    if _lex_once(src) < 0.1:
        return
    assert min(_lex_once(src) for _ in range(5)) < 0.1, len(src)


@settings(
    max_examples=3_000, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
@given(st.lists(st.sampled_from(PIECES), max_size=400).map("".join))
def test_random_shell_soup_raises_only_the_fail_closed_error(src: str) -> None:
    _bounded(src)


@settings(
    max_examples=1_000, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
@given(st.text(max_size=2_000))
def test_random_text_raises_only_the_fail_closed_error(src: str) -> None:
    _bounded(src)


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(st.lists(st.sampled_from(PIECES), min_size=1, max_size=40).map("".join))
def test_long_inputs_up_to_16384_chars(unit: str) -> None:
    _bounded((unit * (16_384 // len(unit) + 1))[:16_384])


@pytest.mark.parametrize(
    "src",
    [
        ("a;" * 8_192)[:16_384],
        ("echo " + "a " * 8_190)[:16_384],
        (_nest(8) + ";") * (16_384 // (len(_nest(8)) + 1)),
        "cat <<EOF" + NL + ("$(id)" + NL) * 2_700 + "EOF",
        "echo " + "'" + "x" * 16_370 + "'",
        "echo $((" + "1+" * 8_000 + "1))",
        ("{ " * 2_000) + "x;" + (" }" * 2_000),
        ("( " * 4_000) + "x" + (" )" * 4_000),
        "if x; then " * 1_000 + "y;" + " fi;" * 1_000,
        "x=" + "$x" * 5_400,
    ],
    ids=[
        "seps",
        "args",
        "nest8",
        "heredoc",
        "sq",
        "arith",
        "braces",
        "parens",
        "ifs",
        "params",
    ],  # fmt: skip
)
def test_pathological_inputs_bounded(src: str) -> None:
    assert len(src) <= 16_384 + 64
    _bounded(src)


# CHK-M7-102: the module executes nothing ------------------------------------

MODULES = [Path(str(m.__file__)) for m in (shlex_model, shlex_grammar, shlex_posix)]


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_lexer_modules_import_nothing_that_executes(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned_modules = {
        "subprocess", "os", "shlex", "re", "regex", "pty", "ctypes",
        "multiprocessing", "importlib", "runpy", "code", "socket",
    }  # fmt: skip
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned_modules, a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned_modules, node.module
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec", "compile", "__import__", "open")
        elif isinstance(node, ast.Attribute):
            assert node.attr not in ("system", "popen", "execv", "execve", "spawn")
