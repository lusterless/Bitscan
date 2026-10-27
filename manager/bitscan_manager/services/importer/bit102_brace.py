"""Brace expansion for BIT102 in a bash script (TASK-146 r2, decision
2026-10-27): bash expands `{rm,-rf,/x}` and `r{m,}` before it runs them,
so the words of a command are checked as bash would expand them. The
Execute itself and sh/dash -c scripts run under dash, which has none.

Only unquoted text expands; quoted text and expansions ($x, $( )) are
kept whole. A form whose bash reading is unclear (an unmatched `{` with
a comma after it, a comma only inside nested braces) or that makes more
than CAP words cannot be checked: BIT102 (fail closed, #108 (j)).
"""

from collections.abc import Callable
from typing import Final

from bitscan_manager.services.importer.shlex_posix import Part, PartKind, Word

CAP: Final = 256
_MAX_BRACES: Final = 64  # brace pairs expanded in one word
# An atom is one unquoted ("u") or quoted ("q") character, or a whole
# expansion part ("o").
type _Atom = tuple[str, str, Part | None]


class BraceError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # fixed text, never input


def expand_words(words: tuple[Word, ...]) -> tuple[Word, ...]:
    """The words after brace expansion; raises BraceError."""
    if not any(p.kind == "lit" and "{" in p.text for w in words for p in w.parts):
        return words
    out: list[Word] = []
    for word in words:
        results: list[list[_Atom]] = []
        _expand(_atoms(word), results)
        # bash drops a word that expands to nothing (`{,}rm` gives rm rm)
        out += [_word(a, word) for a in results if a]
        if len(out) > CAP:
            raise BraceError("brace expansion makes too many words")
    return tuple(out)


def _atoms(word: Word) -> list[_Atom]:
    atoms: list[_Atom] = []
    for part in word.parts:
        if part.kind in ("lit", "sq", "dq"):
            kind = "u" if part.kind == "lit" else "q"
            atoms += [(kind, ch, None) for ch in part.text]
        else:
            atoms.append(("o", "", part))
    return atoms


def _expand(atoms: list[_Atom], out: list[list[_Atom]], depth: int = 0) -> None:
    if depth > _MAX_BRACES:
        raise BraceError("too many braces")
    opened: list[tuple[int, list[int]]] = []  # open brace, its top-level commas
    pairs: list[tuple[int, int, list[int]]] = []
    for i, (kind, ch, _) in enumerate(atoms):
        if kind != "u":
            continue
        if ch == "{":
            opened.append((i, []))
        elif ch == "," and opened:
            opened[-1][1].append(i)
        elif ch == "}" and opened:
            start, commas = opened.pop()
            pairs.append((start, i, commas))
    if opened and any(k == "u" and c == "," for k, c, _ in atoms[opened[0][0] :]):
        raise BraceError("unmatched brace")  # a `{` never closed, a comma after it
    for start, end, commas in sorted(pairs):
        if commas:
            cuts = [start, *commas, end]
            alts = [atoms[a + 1 : b] for a, b in zip(cuts, cuts[1:], strict=False)]
        else:
            seq = _sequence(atoms[start + 1 : end])
            if seq is None:
                if any(c in "{," for k, c, _ in atoms[start + 1 : end] if k == "u"):
                    raise BraceError("nested braces")
                continue  # `{}` or `{x}` stays as it is
            alts = [[("q", ch, None) for ch in text] for text in seq]
        for alt in alts:
            _expand(atoms[:start] + alt + atoms[end + 1 :], out, depth + 1)
            if len(out) > CAP:
                raise BraceError("brace expansion makes too many words")
        return
    out.append(atoms)


def _sequence(amble: list[_Atom]) -> list[str] | None:
    """{x..y} or {x..y..step}: integers, or single characters."""
    if any(k != "u" for k, _, _ in amble):
        return None
    ends = "".join(c for _, c, _ in amble).split("..")
    if len(ends) not in (2, 3) or not all(_int(e) for e in ends[2:]):
        return None
    step = abs(int(ends[2])) or 1 if len(ends) == 3 else 1
    to: Callable[[int], str]
    if _int(ends[0]) and _int(ends[1]):
        a, b, to = int(ends[0]), int(ends[1]), str
    elif len(ends[0]) == len(ends[1]) == 1 and len(ends[1]) == 1:
        a, b, to = ord(ends[0]), ord(ends[1]), chr
    else:
        return None
    if abs(b - a) // step >= CAP:
        raise BraceError("brace expansion makes too many words")
    sign = 1 if b >= a else -1
    return [to(n) for n in range(a, b + sign, step * sign)]


def _int(text: str) -> bool:
    digits = text[1:] if text[:1] in ("-", "+") else text
    return digits.isascii() and digits.isdigit() and len(digits) <= 9


def _word(atoms: list[_Atom], origin: Word) -> Word:
    parts: list[Part] = []
    for kind, ch, part in atoms:
        if part is not None:
            parts.append(part)
            continue
        k: PartKind = "lit" if kind == "u" else "sq"
        if parts and parts[-1].kind == k:
            parts[-1] = Part(k, parts[-1].text + ch)
        else:
            parts.append(Part(k, ch))
    raw = "".join(p.text for p in parts)
    return Word(tuple(parts), origin.line, raw)
