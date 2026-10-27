"""BIT102: write-like or state-changing commands in `Execute` (SR §4.2; #108).

Works on the shlex_posix lexer's output, never on substrings. Every simple
command is checked wherever it appears: pipelines, lists, subshells, groups,
compound commands, function bodies, $( ), backticks, <( ), >( ), unquoted
here-documents, and the script of `sh`/`bash`/`dash -c` and of `su`/
`runuser`/`flock -c` (each lexed again). Input the lexer cannot handle is
BIT102 (fail closed, #108 (j)). In a bash script, words are checked after
brace expansion (bit102_brace). `trap` setting an action, `alias` with a
definition, `hash -p` and `let` are refused like eval (decisions 2026-10-27).

A command word that is not literal (`"$c" x`, `$(echo rm) x`) is allowed and
only its nested scripts are checked (user decision 2026-10-27); the runner
sandbox (TS §3.7) is the control for it. BIT102 is a safety net (SR L287):
nothing is added to the SR §4.2 lists (#108 (k)).
"""

from collections.abc import Iterable, Iterator
from typing import Final

from bitscan_manager.services.importer.bit102_brace import BraceError, expand_words
from bitscan_manager.services.importer.bit102_wrap import (
    SPECS,
    WRAPPERS,
    look_through,
    read_option,
)
from bitscan_manager.services.importer.model import Code, Finding, quote
from bitscan_manager.services.importer.shlex_posix import (
    Redirect,
    Script,
    ShellSyntaxError,
    Word,
    lex,
)

WRITE_WORDS: Final = frozenset(
    {"rm", "mv", "cp", "tee", "dd", "chmod", "chown", "chgrp", "truncate", "ln"}
    | {"install", "mkfs", "mount", "umount"}
)
CODE_WORDS: Final = frozenset({".", "source", "eval", "exec", "xargs"})
SHELLS: Final = frozenset({"sh", "bash", "dash"})
APT_VERBS: Final = frozenset(
    {"install", "remove", "purge", "upgrade", "full-upgrade", "dist-upgrade"}
    | {"autoremove"}
)
DPKG_OPTIONS: Final = frozenset(
    {"-i", "-r", "-P", "--install", "--remove", "--purge", "--configure"}
)
SYSTEMCTL_VERBS: Final = frozenset(
    {"start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask"}
    | {"kill", "isolate", "set-property"}
)
FIND_ACTIONS: Final = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
SAFE_TARGETS: Final = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr"})
# A path compared in policy text (SR §4.2); this module never opens it.
TMP_PREFIX: Final = "/tmp/"  # noqa: S108
INPUT_OPS: Final = frozenset({"<", "<&", "<<", "<<-", "<<<"})


def check_execute(execute: str, *, line: int, element: str) -> list[Finding]:
    """BIT102 findings for one trimmed `Execute`: one per distinct offence,
    in source order, each quoting the offending token (#105 (g))."""
    try:
        script = lex(execute)
    except ShellSyntaxError as exc:  # exc.reason is fixed text, never input
        return [_finding(line, element, f"Execute cannot be checked: {exc.reason}.")]
    messages = dict.fromkeys(_script(script, 0, bash=False))  # /bin/sh is dash
    return [_finding(line, element, m) for m in messages]


def _finding(line: int, element: str, message: str) -> Finding:
    return Finding(line, element, Code.BIT102, message)


def _script(script: Script, depth: int, *, bash: bool) -> Iterator[str]:
    """bash: the script runs under bash, so its words brace-expand."""
    for cmd in script.commands:
        for redirect in cmd.redirects:
            yield from _redirect(redirect)
            scripts = redirect.target.scripts() if redirect.target else ()
            yield from _nested(scripts + redirect.heredoc_scripts, depth, bash)
        for word in cmd.assignments + cmd.words:
            yield from _nested(word.scripts(), depth, bash)
        yield from _command(cmd.words, depth, bash)
    for word in script.data_words:
        yield from _nested(word.scripts(), depth, bash)


def _nested(scripts: Iterable[Script], depth: int, bash: bool) -> Iterator[str]:
    for nested in scripts:
        yield from _script(nested, depth + 1, bash=bash)


def _redirect(r: Redirect) -> Iterator[str]:
    """#108 (i): output only to the safe devices or under /tmp/ with no ..
    component and no expansion; 2>&1 and >&2 pass. <> opens for writing too."""
    if r.op in INPUT_OPS or r.target is None:
        return
    target = r.target.literal()
    if r.op == ">&" and target is not None and (target == "-" or _digits(target)):
        return
    if target is not None and (
        target in SAFE_TARGETS
        or (
            target.startswith(TMP_PREFIX)
            and target != TMP_PREFIX
            and ".." not in target.split("/")
        )
    ):
        return
    yield f"Execute redirects output with {quote(r.op)} to {quote(r.target.raw)}."


def _digits(text: str) -> bool:
    return text.isascii() and text.isdigit()


def _resolve(
    words: tuple[Word, ...],
) -> tuple[int, list[str], list[Word], str | None] | None:
    """#108 (a), (d), (e): the index of the command word after any wrappers,
    the wrappers' text, `env -S` strings (command lines themselves) and a
    finding for an option not in the wrapper's table (fail closed). None
    when nothing runs (`command -v x`); an index past the end when only
    wrappers are given (a bare `env`, or `env -S '…'`)."""
    i, via, split = 0, list[str](), list[Word]()
    while i < len(words):
        value = words[i].literal()
        name = None if value is None else value.rsplit("/", 1)[-1]
        if name is None or name not in WRAPPERS:
            return i, via, split, None
        spec, seen = WRAPPERS[name], set[str]()
        via.append(words[i].raw)
        i += 1
        while i < len(words):
            opt = words[i].literal()
            if opt is None or opt == "--":
                i += opt == "--"
                break
            if (name == "env" and opt == "-") or (
                name in ("env", "sudo") and words[i].is_assignment()
            ):
                i += 1
                continue
            if not opt.startswith("-") or opt == "-":
                break
            num = opt[2:] if opt[1:2] in ("-", "+") else opt[1:]  # nice -5, --5
            nice = name == "nice" and num.isascii() and num.isdigit()
            taken = 1 if nice else read_option(spec, words, i, seen, split)
            if taken is None:
                shown = quote(words[i].raw)
                problem = f"Execute cannot be checked: option {shown} of {quote(name)}."
                return len(words), via, split, problem
            i += taken
        if name == "command" and seen & {"-v", "-V"}:
            return None
        i += spec.positional
    return len(words), via, split, None  # only wrappers: no command word, but env -S


def _command(words: tuple[Word, ...], depth: int, bash: bool) -> Iterator[str]:
    if bash:
        try:
            words = expand_words(words)
        except BraceError as exc:
            yield f"Execute cannot be checked: {exc.reason} in a bash script."
            return
    via: list[str] = []
    while True:  # each pass looks through one wrapper; words get shorter
        resolved = _resolve(words)
        if resolved is None:
            return
        index, wrappers, split, problem = resolved
        via += wrappers
        for text in split:  # env -S splits a command line; it expands nothing
            yield from _shell_script(text, "env -S", depth, bash, subst=True)
        if problem is not None:
            yield problem
        if index >= len(words):
            return
        word, args = words[index], words[index + 1 :]
        value = word.literal()
        if value is None:  # not literal: allowed, nested scripts already checked
            return
        name = value.rsplit("/", 1)[-1]
        shown = quote(word.raw) + (f" (via {quote(' '.join(via))})" if via else "")
        if name not in SPECS:
            break
        step = look_through(name, shown, args)
        for script in step.scripts:  # run by the user's shell: may be bash
            yield from _shell_script(script, f"{name} -c", depth, True, subst=True)
        if step.problem is not None:
            yield step.problem
        via.append(word.raw)
        words = step.words
    literals = [a.literal() for a in args]
    if name in WRITE_WORDS or name.startswith("mkfs."):
        yield f"Execute runs the write-like command {shown}."
    elif name in CODE_WORDS or _defines_code(name, literals):
        yield f"Execute runs other code with {shown}."
    elif name == "sed":
        flag = _sed_in_place(args)
        if flag is not None:
            yield f"Execute runs {shown} with {quote(flag)}."
    elif name in ("apt", "apt-get", "dpkg", "systemctl", "find"):
        for arg, lit in zip(args, literals, strict=True):
            if lit is not None and _bad_argument(name, lit):
                yield f"Execute runs {shown} with {quote(arg.raw)}."
                break
    elif name in SHELLS:
        yield from _shell(word, args, shown, depth)


def _defines_code(name: str, lits: list[str | None]) -> bool:
    """Text the shell later runs as code, refused like eval (user rulings
    2026-10-27): `let`, `hash -p`, `alias` defining one, `trap` setting an
    action. `alias`, `alias name`, `trap`, `trap -p`, `trap -l`, `trap -
    SIG` and `trap SIG` (one operand: a reset in dash and bash) pass. A word
    that is not literal could be anything, so it counts (fail closed)."""
    if name == "let":
        return True
    if name == "alias":
        return any(lit is None or "=" in lit for lit in lits)
    if name not in ("hash", "trap"):
        return False
    i, letters = 0, ""
    while i < len(lits):
        lit = lits[i]
        if lit is None:
            return True
        i += 1
        if lit == "--":
            break
        if not lit.startswith("-") or lit == "-":
            i -= 1
            break
        letters += lit[1:]
    if name == "hash":
        return "p" in letters
    operands = lits[i:]
    listing = any(c in letters for c in "lpP")
    return not listing and len(operands) > 1 and operands[0] != "-"


def _bad_argument(name: str, arg: str) -> bool:
    """#108 (g). A forbidden apt or systemctl verb is refused wherever it
    appears among the arguments, so an option's value cannot hide the verb."""
    if name in ("apt", "apt-get"):
        return arg in APT_VERBS
    if name == "systemctl":
        return arg in SYSTEMCTL_VERBS
    if name == "dpkg":
        return arg in DPKG_OPTIONS or arg.split("=", 1)[0] in DPKG_OPTIONS - {
            "-i",
            "-r",
            "-P",
        }
    return arg in FIND_ACTIONS


def _sed_in_place(args: tuple[Word, ...]) -> str | None:
    """`-i` in any short cluster (`-ni`, `-i.bak`), `--in-place[=…]` and its
    getopt abbreviations (`--in`); -e, -f and -l take the next word."""
    skip = False
    for arg in args:
        opt = arg.literal()
        if skip or opt is None or not opt.startswith("-") or opt == "-":
            skip = False
            continue
        if opt == "--":
            return None
        if opt.startswith("--"):
            if opt.startswith("--i"):
                return arg.raw
            skip = opt in ("--expression", "--file", "--line-length")
            continue
        for k, ch in enumerate(opt[1:]):
            if ch == "i":
                return arg.raw
            if ch in "efl":
                skip = k == len(opt) - 2  # no value attached: it is the next word
                break
    return None


# Long options bash takes (exact names only: `--rcf` is an error); dash
# takes none. Letters of `set` and of the bash and dash command lines.
SHELL_LONG: Final = frozenset(
    {"--debug", "--debugger", "--dump-po-strings", "--dump-strings", "--help"}
    | {"--login", "--noediting", "--noprofile", "--norc", "--posix"}
    | {"--pretty-print", "--restricted", "--verbose", "--version"}
)
SHELL_LETTERS: Final = frozenset("abcefhiklmnoprstuvxBCDEHIOPTV")


def _shell(word: Word, args: tuple[Word, ...], shown: str, depth: int) -> Iterator[str]:
    """#108 (f): sh, bash and dash pass only as `-c <script>`; the script
    may hold no substitution (SR §4.2) and is checked like the Execute.
    Options are read as the shells do: each o or O in a cluster takes the
    next word in turn (`-co pipefail`), and a lone - or -- ends them."""
    i, has_c = 0, False
    while i < len(args):
        opt, raw = args[i].literal(), args[i].raw
        if opt is None or opt[:1] not in ("-", "+") or opt in ("-", "--"):
            i += opt in ("-", "--")
            break
        i += 1
        if opt in ("--rcfile", "--init-file"):
            i += 1
        elif opt in SHELL_LONG:
            pass
        elif opt.startswith("--") or not set(opt[1:]) <= SHELL_LETTERS:
            yield f"Execute cannot be checked: option {quote(raw)} of {shown}."
            return
        else:
            i += sum(c in "oO" for c in opt[1:])
            has_c = has_c or "c" in opt
    if not has_c or i >= len(args):
        yield f"Execute runs a shell without -c: {shown}."
        return
    script = args[i]
    inner = next((p.text for p in script.parts if p.script is not None), None)
    if inner is not None:
        yield f"Execute passes a substitution to {shown} -c: {quote(inner)}."
    else:  # not literal and no substitution: allowed (user decision 2026-10-27)
        bash = str(word.literal()).rsplit("/", 1)[-1] == "bash"
        yield from _shell_script(script, word.raw + " -c", depth, bash, subst=False)


def _shell_script(
    script: Word, shown: str, depth: int, bash: bool, *, subst: bool
) -> Iterator[str]:
    """Lex a command-line argument and check it like the Execute; with
    subst False, any $( ), backtick or <( ) in it is refused too."""
    text = script.literal()
    if text is None:
        return
    try:
        lexed = lex(text, depth=depth + 1)
    except ShellSyntaxError as exc:
        yield f"Execute cannot be checked: {exc.reason} in a {quote(shown)} script."
        return
    found = None if subst else _substitution(lexed)
    if found is not None:
        yield f"Execute passes a substitution to {quote(shown)}: {quote(found)}."
    yield from _script(lexed, depth + 1, bash=bash)


def _substitution(script: Script) -> str | None:
    """The first substitution anywhere in a -c script (SR §4.2), as written."""
    for cmd in script.commands:
        words = cmd.assignments + cmd.words
        words += tuple(r.target for r in cmd.redirects if r.target is not None)
        for word in words:
            for part in word.parts:
                if part.script is not None:
                    return part.text
        if any(r.heredoc_scripts for r in cmd.redirects):
            return "<<"
    for word in script.data_words:
        for part in word.parts:
            if part.script is not None:
                return part.text
    return None
