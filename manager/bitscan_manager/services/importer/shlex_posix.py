"""POSIX sh lexer for BIT102 (SR §4.2; #108; design note D2, TASK-145 plan).

Splits an `Execute` into simple commands (assignments, words, redirections)
and the scripts nested in substitutions and here-documents, after POSIX XCU
§2.3 and §2.6.3 plus the bash forms an Ubuntu host runs. It never runs,
expands or globs anything and decides nothing about BIT102. Input it cannot
lex raises ShellSyntaxError, which BIT102 rejects (fail closed, #108 (j));
so do bash's ${…@P} and ${…@E}, wherever they appear.
Python's shlex is not used: it knows neither $( ), backticks nor
here-documents. No regular expressions.

Where shell grammar is ambiguous the lexer leans to treating a word as a
command word, so that BIT102 checks more, never less. `$((` is always
arithmetic (unbalanced is an error, not a `$( (…) )`); `[[ ]]` and `(( ))`
are lexed as ordinary tokens.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Final

from bitscan_manager.services.importer.shlex_grammar import Grammar, Tok
from bitscan_manager.services.importer.shlex_model import (
    MAX_DEPTH,
    Command,
    Part,
    PartKind,
    Redirect,
    Script,
    ShellSyntaxError,
    Word,
    join_scripts,
)

__all__ = [
    "MAX_DEPTH",
    "Command",
    "Part",
    "PartKind",
    "Redirect",
    "Script",
    "ShellSyntaxError",
    "Word",
    "lex",
]

_META: Final = frozenset(" \t\n;&|<>()")
_STOP: Final = _META | frozenset("'\"\\$`")  # what ends a run of plain characters
_OPS: Final = (
    ";;&", "&>>", "<<-", "<<<", "&&", "&>", "||", "|&", ";;", ";&", "<<", "<>",
    "<&", ">>", ">|", ">&", ";", "&", "|", "<", ">", "(", ")",
)  # fmt: skip
# Operators by first character, longest first.
_OPS_AT: Final = {c: tuple(op for op in _OPS if op[0] == c) for c in "&|;<>()"}
_SPECIAL: Final = frozenset("@*#?-$!0123456789")


def lex(source: str, *, depth: int = 0, line: int = 1) -> Script:
    """Raises ShellSyntaxError; never returns a partial script."""
    if "\x00" in source:
        raise ShellSyntaxError(
            "NUL character", line + source.count("\n", 0, source.index("\x00"))
        )
    try:
        return _Lexer(source, depth, line, outer=False).run()
    except RecursionError:  # bounded by MAX_DEPTH; kept as a fail-closed net
        raise ShellSyntaxError("nested too deeply", line) from None


class _Lexer(Grammar):
    def __init__(self, src: str, depth: int, line: int, *, outer: bool) -> None:
        self.src, self.n, self.pos, self.depth, self.base = (
            src,
            len(src),
            0,
            depth,
            line,
        )
        self.newlines = [i for i, c in enumerate(src) if c == "\n"]
        # Here-documents waiting for the next newline: delimiter, strip tabs,
        # quoted, the list their body's scripts go into, and the depth that
        # queued them. outer: one is pending in the enclosing lexer (backticks).
        self.pending: list[tuple[str, bool, bool, list[Script], int]] = []
        self.outer = outer
        self.peeked: Tok | None = None

    def line(self) -> int:
        return self.base + bisect_left(self.newlines, self.pos)

    def fail(self, reason: str) -> ShellSyntaxError:
        return ShellSyntaxError(reason, self.line())

    def deeper(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.fail("nested too deeply")

    def run(self) -> Script:
        if self.depth > MAX_DEPTH:
            raise self.fail("nested too deeply")
        return self.parse(end=None)

    # ----- tokens -----

    def token(self) -> Tok:
        if self.peeked is not None:
            tok, self.peeked = self.peeked, None
            return tok
        src = self.src
        while self.pos < self.n:
            if src[self.pos] in " \t":
                self.pos += 1
            elif src.startswith("\\\n", self.pos):
                self.pos += 2
            elif src[self.pos] == "#":  # a comment runs to the end of the line
                end = src.find("\n", self.pos)
                self.pos = self.n if end < 0 else end
            else:
                break
        line = self.line()
        if self.pos >= self.n:
            return Tok("eof", line)
        if src[self.pos] == "\n":
            # dash and bash read a here-document's body only after the line
            # that queued it ends; the lines inside a substitution run first.
            if self.outer or any(p[4] < self.depth for p in self.pending):
                raise self.fail("newline in a substitution before a here-document")
            self.pos += 1
            self.heredocs()
            return Tok("nl", line)
        if not self.at_procsub():
            for op in _OPS_AT.get(src[self.pos], ()):
                if src.startswith(op, self.pos):
                    self.pos += len(op)
                    return Tok("op", line, op)
        word = self.word()
        digits = word.plain()
        if (
            digits is not None
            and digits.isascii()
            and digits.isdigit()
            and len(digits) <= 9
            and self.pos < self.n
            and src[self.pos] in "<>"
            and not self.at_procsub()
        ):
            return Tok("io", line, digits)
        return Tok("word", line, word=word)

    def at_procsub(self) -> bool:
        return self.src[self.pos] in "<>" and self.src.startswith("(", self.pos + 1)

    def word(self) -> Word:
        src, line, first = self.src, self.line(), self.pos
        parts: list[Part] = []
        buf: list[str] = []
        while self.pos < self.n:
            c = src[self.pos]
            if c not in _STOP:
                end = self.pos + 1
                while end < self.n and src[end] not in _STOP:
                    end += 1
                buf.append(src[self.pos : end])
                self.pos = end
            elif c in "<>" and src.startswith("(", self.pos + 1):
                _flush(parts, buf, "lit")
                start = self.pos
                self.pos += 2
                parts.append(
                    self.subst("procsub_in" if c == "<" else "procsub_out", start)
                )
            elif c in _META:
                break
            elif c == "'":
                _flush(parts, buf, "lit")
                end = src.find("'", self.pos + 1)
                if end < 0:
                    raise self.fail("unterminated single quote")
                parts.append(Part("sq", src[self.pos + 1 : end]))
                self.pos = end + 1
            elif c == '"':
                _flush(parts, buf, "lit")
                self.pos += 1
                parts.extend(self.dq('"'))
            elif c == "\\" and src.startswith("\n", self.pos + 1):
                self.pos += 2  # line continuation
            elif c == "\\":  # an escaped character is quoted, so `\if` is no keyword
                _flush(parts, buf, "lit")
                parts.append(Part("sq", src[self.pos + 1 : self.pos + 2] or "\\"))
                self.pos = min(self.pos + 2, self.n)
            else:  # $ or `
                _flush(parts, buf, "lit")
                parts.append(self.expansion(in_dq=False))
        _flush(parts, buf, "lit")
        return Word(tuple(parts), line, src[first : self.pos])

    def dq(self, term: str | None) -> list[Part]:
        """Double-quoted text up to term (None: to the end, for a body)."""
        src, parts, buf = self.src, list[Part](), list[str]()
        while True:
            if self.pos >= self.n:
                if term is None:
                    break
                raise self.fail("unterminated double quote")
            c = src[self.pos]
            if c == term:
                self.pos += 1
                break
            if c == "\\" and src[self.pos + 1 : self.pos + 2] in (
                "$",
                "`",
                '"',
                "\\",
                "\n",
            ):
                buf.append(src[self.pos + 1].replace("\n", ""))
                self.pos += 2
            elif c in "$`":
                _flush(parts, buf, "dq")
                parts.append(self.expansion(in_dq=True))
            else:
                buf.append(c)
                self.pos += 1
        if buf or not parts:
            parts.append(Part("dq", "".join(buf)))
        return parts

    # ----- expansions -----

    def expansion(self, in_dq: bool) -> Part:
        src, start = self.src, self.pos
        if src[start] == "`":
            return self.backtick(in_dq)
        nxt = src[start + 1 : start + 2]
        if src.startswith("$((", start):
            return self.scan(start, 3, "arith", in_dq)
        if nxt == "(":
            self.pos += 2
            return self.subst("cmdsub", start)
        if nxt == "{":
            return self.scan(start, 2, "param", in_dq)
        if nxt == "'" and not in_dq:  # $'…' (ANSI-C quoting): never a plain literal
            i = start + 2
            while i < self.n and src[i] != "'":
                i += 2 if src[i] == "\\" else 1
            if i >= self.n:
                raise self.fail("unterminated $'")
            self.pos = i + 1
            return Part("param", src[start : self.pos])
        if nxt and nxt in _SPECIAL:
            self.pos += 2
            return Part("param", src[start : self.pos])
        if nxt.isascii() and (nxt.isalpha() or nxt == "_"):
            i = start + 1
            while (
                i < self.n and src[i].isascii() and (src[i].isalnum() or src[i] == "_")
            ):
                i += 1
            self.pos = i
            return Part("param", src[start:i])
        self.pos += 1
        return Part("dq" if in_dq else "lit", "$")

    def subst(self, kind: PartKind, start: int) -> Part:
        """$( or <( or >( already consumed: the nested script up to its )."""
        self.deeper()
        script = self.parse(end=")")
        self.depth -= 1
        return Part(kind, self.src[start : self.pos], script)

    def backtick(self, in_dq: bool) -> Part:
        src, start, line = self.src, self.pos, self.line()
        i, buf = start + 1, list[str]()
        while True:
            if i >= self.n:
                raise self.fail("unterminated backtick")
            c = src[i]
            if c == "`":
                break
            if c == "\\" and src[i + 1 : i + 2] in (
                ("`", "$", "\\", '"') if in_dq else ("`", "$", "\\")
            ):
                buf.append(src[i + 1])
                i += 2
            else:
                buf.append(c)
                i += 1
        self.pos = i + 1
        outer = self.outer or bool(self.pending)
        script = _Lexer("".join(buf), self.depth + 1, line, outer=outer).run()
        return Part("backtick", src[start : self.pos], script)

    def scan(self, start: int, skip: int, kind: PartKind, in_dq: bool) -> Part:
        """${…} (kind param) or $((…)) (kind arith): to the matching close,
        keeping the scripts of substitutions inside."""
        self.deeper()
        src, scripts, level = self.src, list[Script](), 0
        self.pos = start + skip
        opener, close = ("{", "}") if kind == "param" else ("(", ")")
        while True:
            if self.pos >= self.n:
                raise self.fail(
                    "unterminated ${" if kind == "param" else "unterminated $(("
                )
            c = src[self.pos]
            if c in "$`":
                part = self.expansion(in_dq)
                scripts += [part.script] if part.script is not None else []
                continue
            if c == '"' and kind == "param":
                self.pos += 1
                scripts += [p.script for p in self.dq('"') if p.script is not None]
                continue
            if c == "'" and kind == "param" and not in_dq:
                end = src.find("'", self.pos + 1)
                if end < 0:
                    raise self.fail("unterminated single quote")
                self.pos = end + 1
                continue
            if c == "\\":
                self.pos += 2
                continue
            if c == close and level == 0:
                if kind == "arith" and not src.startswith("))", self.pos):
                    raise self.fail("unbalanced $((")
                self.pos += 1 if kind == "param" else 2
                break
            level += 1 if c == opener else -1 if c == close else 0
            self.pos += 1
        self.depth -= 1
        if kind == "param" and src.endswith(("@P}", "@E}"), start, self.pos):
            # bash turns the value into code: refused like eval (user, 2026-10-27)
            raise self.fail("${…@P} or ${…@E} runs text as code")
        return Part(kind, src[start : self.pos], join_scripts(scripts))

    def heredocs(self) -> None:
        """Read the bodies of the here-documents of the line just ended."""
        src = self.src
        for delim, strip, quoted, holder, _ in self.pending:
            line, lines = self.line(), list[str]()
            while True:
                if self.pos >= self.n:
                    raise self.fail("unterminated here-document")
                end = src.find("\n", self.pos)
                text = src[self.pos : self.n if end < 0 else end]
                self.pos = self.n if end < 0 else end + 1
                text = text.lstrip("\t") if strip else text
                if text == delim:
                    break
                lines.append(text)
            if not quoted and lines:  # a quoted delimiter makes the body data
                body = _Lexer("\n".join(lines) + "\n", self.depth, line, outer=False)
                holder += [p.script for p in body.dq(None) if p.script is not None]
        self.pending.clear()


def _flush(parts: list[Part], buf: list[str], kind: PartKind) -> None:
    if buf:
        parts.append(Part(kind, "".join(buf)))
        buf.clear()
