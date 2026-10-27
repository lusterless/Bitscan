"""Grouping of shell tokens into simple commands for the BIT102 lexer
(TASK-145 plan §3 steps 7 and 8): reserved words, for, case, functions,
subshells and groups, assignments and redirections, with a balance stack
so that a structural mismatch raises instead of mis-grouping. The scanner
(shlex_posix._Lexer) supplies the tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal, NamedTuple

from bitscan_manager.services.importer.shlex_model import (
    Command,
    Redirect,
    Script,
    ShellSyntaxError,
    Word,
)

REDIRS: Final = frozenset(
    {"<", ">", ">>", ">|", "<>", "<&", ">&", "&>", "&>>", "<<", "<<-", "<<<"}
)
# Reserved word -> the construct it opens (a state on the parse stack).
_OPENERS: Final = {
    "if": "if",
    "while": "while",
    "until": "while",
    "{": "{",
    "for": "for:name",
    "select": "for:name",
    "case": "case:word",
    "function": "fn",
}
_CLOSERS: Final = {"fi": "if", "done": "loop", "}": "{", "esac": "case:body"}
_RESERVED: Final = (
    frozenset(_OPENERS)
    | frozenset(_CLOSERS)
    | frozenset({"then", "else", "elif", "do", "!", "time", "coproc"})
)


class Tok(NamedTuple):
    kind: Literal["op", "word", "io", "nl", "eof"]
    line: int
    text: str = ""
    word: Word | None = None


@dataclass
class _Cmd:
    line: int
    assignments: list[Word] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    redirects: list[tuple[int | None, str, Word | None, list[Script]]] = field(
        default_factory=list
    )

    def build(self) -> Command:
        redirects = tuple(Redirect(f, o, t, tuple(h)) for f, o, t, h in self.redirects)
        return Command(tuple(self.assignments), tuple(self.words), redirects, self.line)


class Grammar:
    """Mixin: the scanner provides token(), fail(), pending and peeked."""

    pending: list[tuple[str, bool, bool, list[Script], int]]
    peeked: Tok | None
    depth: int

    def token(self) -> Tok:
        raise NotImplementedError

    def fail(self, reason: str) -> ShellSyntaxError:
        raise NotImplementedError

    def parse(self, end: str | None) -> Script:
        """Commands up to the end of the source (end None) or, for $( and
        <(, up to the ) that closes it. stack holds the open constructs."""
        cmds: list[_Cmd] = []
        data: list[Word] = []
        stack: list[str] = []
        cur: _Cmd | None = None
        prev = "start"  # start | sep | pipe | word: what the last token was
        while True:
            tok = self.token()
            top = stack[-1] if stack else ""
            if tok.kind == "eof":
                if self.pending:
                    raise self.fail("unterminated here-document")
                if stack or end is not None or prev == "pipe":
                    raise ShellSyntaxError("unexpected end of script", tok.line)
                return Script(tuple(c.build() for c in cmds), tuple(data))
            if top == "fn" or (
                top.startswith(("for:", "case:")) and top != "case:body"
            ):
                prev = self.header(tok, stack, data)
            elif tok.kind == "word" and tok.word is not None:
                lead = self.time(tok.word) if cur is None else None
                if lead == []:
                    prev = "start"
                    continue
                if cur is None and lead is None and tok.word.plain() == "coproc":
                    cur = self.coproc(cmds, data)
                    prev = "start" if cur is None else "word"
                    continue
                if cur is None and lead is None and tok.word.plain() in _RESERVED:
                    prev = self.reserved(str(tok.word.plain()), stack, tok.line)
                    continue
                if cur is None:
                    cur = _Cmd(tok.line)
                    cmds.append(cur)
                if lead:
                    cur.words += lead
                elif not cur.words and tok.word.is_assignment():
                    cur.assignments.append(tok.word)
                else:
                    cur.words.append(tok.word)
                prev = "word"
            elif tok.kind == "io" or tok.text in REDIRS:
                op = self.token() if tok.kind == "io" else tok
                if op.kind != "op" or op.text not in REDIRS:
                    raise ShellSyntaxError("expected a redirection", tok.line)
                if cur is None:
                    cur = _Cmd(tok.line)
                    cmds.append(cur)
                self.redirect(cur, op, int(tok.text) if tok.kind == "io" else None)
                prev = "word"
            elif tok.kind == "nl":
                cur, prev = None, "pipe" if prev == "pipe" else "sep"
            elif tok.text == ")":
                # a here-document queued in this $( ) must start before its )
                unread = any(p[4] >= self.depth for p in self.pending)
                if prev == "pipe" or unread and not stack:
                    raise ShellSyntaxError("unexpected )", tok.line)
                cur, prev = None, "word"
                if top == "(":
                    stack.pop()
                elif not stack and end == ")":
                    return Script(tuple(c.build() for c in cmds), tuple(data))
                else:
                    raise ShellSyntaxError("unexpected )", tok.line)
            elif tok.text == "(":
                if cur is not None and len(cur.words) == 1 and not cur.assignments:
                    if cur.redirects:  # never drop a redirection already seen
                        raise ShellSyntaxError("unexpected (", tok.line)
                    if self.token().text != ")":  # NAME ( ) is a function definition
                        raise ShellSyntaxError("unexpected (", tok.line)
                    data.append(cur.words[0])
                    cmds.remove(cur)
                elif cur is not None:
                    raise ShellSyntaxError("unexpected (", tok.line)
                else:
                    stack.append("(")
                cur, prev = None, "start"
            elif tok.text in (";;", ";&", ";;&"):
                if top != "case:body":
                    raise ShellSyntaxError("unexpected " + tok.text, tok.line)
                stack[-1], cur, prev = "case:pat", None, "start"
            else:  # ; & | |& && ||
                if prev != "word":
                    raise ShellSyntaxError("unexpected " + tok.text, tok.line)
                cur, prev = None, "sep" if tok.text in (";", "&") else "pipe"

    def reserved(self, word: str, stack: list[str], line: int) -> str:
        top = stack[-1] if stack else ""
        if word in _OPENERS:
            stack.append(_OPENERS[word])
        elif word in ("then", "else", "elif") and top == "if":
            pass
        elif word == "do" and top == "while":
            stack[-1] = "loop"
        elif word in _CLOSERS and top == _CLOSERS[word]:
            stack.pop()
            return "word"
        elif word != "!":
            raise ShellSyntaxError("unexpected " + word, line)
        return "start"

    def coproc(self, cmds: list[_Cmd], data: list[Word]) -> _Cmd | None:
        """bash `coproc [NAME] command`: NAME (a data word) only before a
        compound command; otherwise the next word starts a simple command."""
        name = self.token()
        if name.word is None or name.word.plain() in _RESERVED:
            self.peeked = name
            return None
        nxt = self.peeked = self.token()
        if (
            nxt.kind == "op"
            and nxt.text == "("
            or (nxt.word is not None and nxt.word.plain() in _OPENERS)
        ):
            data.append(name.word)
            return None
        cur = _Cmd(name.line)
        cmds.append(cur)
        (cur.assignments if name.word.is_assignment() else cur.words).append(name.word)
        return cur

    def time(self, word: Word) -> list[Word] | None:
        """None unless word is the reserved word `time`. bash reads `time
        [-p]` as a keyword, but /bin/sh is dash, which runs the external
        time (TS §3.5): if another option follows, return the words so far
        as an ordinary command, for BIT102 to read time's options; else []
        (the keyword and its -p are skipped)."""
        if word.plain() != "time":
            return None
        lead, nxt = [word], self.token()
        if nxt.word is not None and nxt.word.plain() == "-p":
            lead.append(nxt.word)
            nxt = self.token()
        self.peeked = nxt
        opt = nxt.word.literal() if nxt.word is not None else None
        return lead if opt is not None and opt.startswith("-") else []

    def header(self, tok: Tok, stack: list[str], data: list[Word]) -> str:
        """The parts of for, case and function that are not commands."""
        top, word = stack[-1], tok.word
        plain = word.plain() if word is not None else None
        if tok.kind == "nl" or (tok.text == ";" and top in ("for:after", "for:list")):
            if top == "for:list":
                stack[-1] = "for:after"
            return "start"
        if top == "case:pat" and tok.kind == "op" and tok.text in ("(", "|", ")"):
            if tok.text == ")":
                stack[-1] = "case:body"
            return "start"
        if word is None:
            raise ShellSyntaxError("unexpected " + tok.text, tok.line)
        if top == "fn":
            data.append(word)
            stack.pop()
            nxt = self.token()
            if nxt.text == "(" and self.token().text != ")":
                raise ShellSyntaxError("unexpected (", tok.line)
            if nxt.text != "(":
                self.peeked = nxt
        elif top in ("for:name", "case:word"):
            data.append(word)
            stack[-1] = "for:after" if top == "for:name" else "case:in"
        elif top == "for:after" and plain in ("in", "do"):
            stack[-1] = "for:list" if plain == "in" else "loop"
        elif top == "case:in" and plain == "in":
            stack[-1] = "case:pat"
        elif top == "case:pat" and plain == "esac":
            stack.pop()
            return "word"
        elif top in ("for:list", "case:pat"):
            data.append(word)
        else:
            raise ShellSyntaxError("unexpected word", tok.line)
        return "start"

    def redirect(self, cur: _Cmd, op: Tok, fd: int | None) -> None:
        target = self.token()
        if target.word is None:
            raise ShellSyntaxError("missing redirection target", op.line)
        if op.text not in ("<<", "<<-"):
            cur.redirects.append((fd, op.text, target.word, []))
            return
        delim = target.word.literal()
        if delim is None:
            raise ShellSyntaxError("here-document delimiter expands", op.line)
        quoted = any(p.kind != "lit" for p in target.word.parts)
        body: list[Script] = []
        self.pending.append((delim, op.text == "<<-", quoted, body, self.depth))
        cur.redirects.append((fd, op.text, None, body))
