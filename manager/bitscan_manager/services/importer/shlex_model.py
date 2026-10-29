"""Output model of the POSIX sh lexer for BIT102 (TASK-145 plan §2;
shlex_posix lexes, shlex_grammar groups tokens into commands). Pure data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

MAX_DEPTH: Final = 8
type PartKind = Literal[
    "lit",
    "sq",
    "dq",
    "param",
    "cmdsub",
    "backtick",
    "arith",
    "procsub_in",
    "procsub_out",
]


class ShellSyntaxError(Exception):
    """Input the lexer cannot handle; BIT102 reports it (fail closed)."""

    def __init__(self, reason: str, line: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.line = line


@dataclass(frozen=True)
class Part:
    kind: PartKind
    text: str  # the literal text (lit, sq, dq pieces); the raw source otherwise
    script: Script | None = (
        None  # what a substitution, or a param or arith holding one, runs
    )


@dataclass(frozen=True)
class Word:
    parts: tuple[Part, ...]
    line: int
    raw: str  # the source text of the word, for messages

    def literal(self) -> str | None:
        """The value after quote removal, or None if any part expands."""
        if all(p.kind in ("lit", "sq", "dq") for p in self.parts):
            return "".join(p.text for p in self.parts)
        return None

    def plain(self) -> str | None:
        """The text of a word with no quoting and no expansion."""
        one = self.parts[0] if len(self.parts) == 1 else None
        return one.text if one is not None and one.kind == "lit" else None

    def scripts(self) -> tuple[Script, ...]:
        return tuple(p.script for p in self.parts if p.script is not None)

    def is_assignment(self) -> bool:
        head = self.parts[0] if self.parts else None
        if head is None or head.kind != "lit" or "=" not in head.text:
            return False
        name = head.text.split("=", 1)[0]
        return name.isascii() and name.isidentifier()


@dataclass(frozen=True)
class Redirect:
    fd: int | None  # the leading IO number, if any
    op: str
    target: Word | None  # None for << and <<- (the body is not a target)
    heredoc_scripts: tuple[Script, ...] = ()  # substitutions in an unquoted body


@dataclass(frozen=True)
class Command:
    """One simple command; words[0] is the command word, if any."""

    assignments: tuple[Word, ...]
    words: tuple[Word, ...]
    redirects: tuple[Redirect, ...]
    line: int


@dataclass(frozen=True)
class Script:
    """Commands at one nesting level, in source order. data_words are words
    that are not commands (for lists, case words and patterns, function
    names); BIT102 checks only the scripts nested in them."""

    commands: tuple[Command, ...]
    data_words: tuple[Word, ...] = ()


def join_scripts(scripts: list[Script]) -> Script | None:
    if not scripts:
        return None
    commands = tuple(c for s in scripts for c in s.commands)
    return Script(commands, tuple(w for s in scripts for w in s.data_words))
