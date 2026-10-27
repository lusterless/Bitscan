"""BIT102 option tables of the wrappers: the #108 (d) ones (WRAPPERS) and
those added by TASK-146 r2 (SPECS; decision 2026-10-27, amending #108
(d)): external `time`, `nsenter`, `unshare`, `flock`, `setpriv`,
`taskset`, `chrt`, `su` and `runuser`.

Each wrapper's options are read as its getopt does (coreutils 9.4,
util-linux 2.37 to 2.39, sudo 1.9.15, GNU time). An option that is not in
the table, a long-option abbreviation included (getopt_long would accept
`env --un`), cannot be checked and is BIT102 (fail closed, #108 (j)); so
is an argument whose meaning differs between those versions.
"""

from dataclasses import dataclass, field
from typing import Final

from bitscan_manager.services.importer.model import quote
from bitscan_manager.services.importer.shlex_posix import Part, Word


@dataclass(frozen=True)
class _Spec:
    flags: frozenset[str]
    values: frozenset[str] = frozenset()  # take a value (attached or the next word)
    optional: frozenset[str] = frozenset()  # take a value only when attached
    numeric: frozenset[str] = frozenset()  # nsenter -S/-G: optional in 2.39 only
    scripts: frozenset[str] = frozenset()  # the value is a shell script (-c)
    permute: bool = False  # su and runuser: GNU getopt reorders the words
    positional: int = 0  # words before the command: timeout's duration, chroot's dir


def _o(names: str) -> frozenset[str]:
    return frozenset(names.split())


_INFO: Final = "-h --help -V --version "
_SU: Final = _Spec(
    _o(_INFO + "-m -p --preserve-environment -l --login -f --fast -P --pty"),
    _o("-w --whitelist-environment -g --group -G --supp-group -s --shell -u --user"),
    scripts=_o("-c --command --session-command"),
    permute=True,
)
_GNU: Final = "--help --version "
# #108 (d) wrappers; env -S/--split-string is a command line (a "script").
WRAPPERS: Final[dict[str, _Spec]] = {
    "env": _Spec(
        _o(_GNU + "-i --ignore-environment -0 --null -v --debug")
        | _o("--list-signal-handling"),
        _o("-u --unset -C --chdir"),
        _o("--block-signal --default-signal --ignore-signal"),
        scripts=_o("-S --split-string"),
    ),
    "command": _Spec(_o("-p -v -V")),  # -v and -V run nothing
    "builtin": _Spec(frozenset()),
    "nice": _Spec(_o(_GNU), _o("-n --adjustment")),  # and -N, --N, -+N
    "nohup": _Spec(_o(_GNU)),
    "ionice": _Spec(
        _o(_INFO + "-t --ignore"),
        _o("-c --class -n --classdata -p --pid -P --pgid -u --uid"),
    ),
    "setsid": _Spec(_o(_INFO + "-c --ctty -f --fork -w --wait")),
    "stdbuf": _Spec(_o(_GNU), _o("-i --input -o --output -e --error")),
    "timeout": _Spec(
        _o(_GNU + "-v --verbose --preserve-status --foreground"),
        _o("-k --kill-after -s --signal"),
        positional=1,
    ),
    "chroot": _Spec(_o(_GNU + "--skip-chdir"), _o("--userspec --groups"), positional=1),
    "sudo": _Spec(
        _o("-A --askpass -b --background -B --bell -E -e --edit -H --set-home")
        | _o("--help -i --login -K --remove-timestamp -k --reset-timestamp -l")
        | _o("--list -n --non-interactive -N --no-update -P --preserve-groups -S")
        | _o("--stdin -s --shell -V --version -v --validate"),
        _o("-C --close-from -D --chdir -g --group -h --host -p --prompt -R")
        | _o("--chroot -r --role -t --type -T --command-timeout -U --other-user")
        | _o("-u --user"),  # sudo -h WORD takes WORD as the host (1.9.15)
        _o("--preserve-env"),
    ),
    "doas": _Spec(_o("-L -n -s"), _o("-C -u")),
    "busybox": _Spec(frozenset()),
}
_NS: Final = "-m --mount -u --uts -i --ipc -n --net -p --pid -C --cgroup -U --user"
SPECS: Final[dict[str, _Spec]] = {
    "time": _Spec(
        _o("--help -V --version -a --append -p --portability -q --quiet -v"),
        _o("-f --format -o --output"),
    ),
    "nsenter": _Spec(
        _o(_INFO + "-a --all -e --env -F --no-fork -Z --follow-context")
        | _o("--preserve-credentials"),
        _o("-t --target -W --wdns"),
        _o(_NS + " -T --time -r --root -w --wd"),
        _o("-S --setuid -G --setgid"),
    ),
    "unshare": _Spec(
        _o(_INFO + "-f --fork -r --map-root-user -c --map-current-user")
        | _o("--map-auto --keep-caps"),
        _o("-R --root -w --wd -S --setuid -G --setgid --propagation --setgroups")
        | _o("--monotonic --boottime --map-user --map-group --map-users")
        | _o("--map-groups"),
        _o(_NS + " -T --time --kill-child --mount-proc"),
    ),
    "flock": _Spec(
        _o(_INFO + "-s --shared -x -e --exclusive -u --unlock -n --nb --nonblock")
        | _o("--nonblocking -o --close -F --no-fork --verbose"),
        _o("-w --wait --timeout -E --conflict-exit-code"),
        scripts=_o("-c --command"),
    ),
    "setpriv": _Spec(
        _o(_INFO + "-d --dump --nnp --no-new-privs --clear-groups --keep-groups")
        | _o("--init-groups --reset-env"),
        _o("--ambient-caps --inh-caps --bounding-set --ruid --euid --rgid --egid")
        | _o("--reuid --regid --groups --securebits --pdeathsig --selinux-label")
        | _o("--apparmor-profile --landlock-access --landlock-rule"),
    ),
    "taskset": _Spec(_o(_INFO + "-a --all-tasks -p --pid -c --cpu-list")),
    "chrt": _Spec(
        _o(_INFO + "-b --batch -d --deadline -f --fifo -i --idle -o --other -r")
        | _o("--rr -R --reset-on-fork -a --all-tasks -m --max -p --pid -v")
        | _o("--verbose"),
        _o("-T --sched-runtime -P --sched-period -D --sched-deadline"),
    ),
    "su": _SU,
    "runuser": _SU,
}


@dataclass
class Step:
    """What a wrapper runs: the command words (none: nothing runs), -c
    scripts, and a finding when it cannot be checked or starts a shell
    without -c."""

    words: tuple[Word, ...] = ()
    scripts: list[Word] = field(default_factory=list)
    problem: str | None = None


def text_word(text: str, origin: Word) -> Word:
    """A literal word for an option value that was attached in `origin`."""
    return Word((Part("sq", text),), origin.line, origin.raw)


def look_through(name: str, shown: str, args: tuple[Word, ...]) -> Step:
    spec, step = SPECS[name], Step()
    operands, seen = list[Word](), set[str]()
    i = 0
    while i < len(args):
        word, opt = args[i], args[i].literal()
        if opt == "--":
            operands += args[i + 1 :]
            break
        if opt is None or not opt.startswith("-") or opt == "-":
            if not spec.permute:
                operands += args[i:]
                break
            operands.append(word)
            i += 1
            continue
        taken = read_option(spec, args, i, seen, step.scripts)
        if taken is None:
            step.problem = (
                f"Execute cannot be checked: option {quote(word.raw)} of {shown}."
            )
            return step
        i += taken
    _operands(name, shown, operands, seen, step)
    return step


def read_option(
    spec: _Spec, args: tuple[Word, ...], i: int, seen: set[str], scripts: list[Word]
) -> int | None:
    """Words taken by the option at i, as getopt reads it; None if unknown."""
    word, opt = args[i], str(args[i].literal())
    nxt = args[i + 1 : i + 2]
    if opt.startswith("--"):
        key, eq, value = opt.partition("=")
        names, attached = [key], value if eq else None
    else:  # a short cluster: the first letter that takes a value ends it
        names, attached = [], None
        for k, letter in enumerate(opt[1:], start=2):
            names.append(f"-{letter}")
            if f"-{letter}" not in spec.flags:
                attached = opt[k:] or None
                break
    seen.update(names)
    key = names[-1]
    if key in spec.flags:
        return None if attached is not None else 1  # --flag=x: getopt error
    if key in spec.optional or (key in spec.numeric and attached is not None):
        return 1
    if key in spec.numeric:  # a uid or gid; otherwise the 2.39 reading runs it
        return 2 if nxt and _digits(nxt[0]) else 1
    if key not in spec.values | spec.scripts:
        return None
    if key in spec.scripts:
        scripts += [text_word(attached, word)] if attached is not None else nxt
    return 1 if attached is not None else 2


def _operands(
    name: str, shown: str, ops: list[Word], seen: set[str], step: Step
) -> None:
    if name in ("taskset", "chrt", "flock") and ops:
        first, ops = ops[0], ops[1:]  # the mask, priority or lock file
        if name == "chrt" and not _digits(first):
            # util-linux 2.41 lets SCHED_OTHER/BATCH/IDLE omit the priority
            step.problem = (
                f"Execute cannot be checked: {quote(first.raw)} after {shown}."
            )
            return
        if name == "flock" and ops and ops[0].literal() in ("-c", "--command"):
            step.scripts += ops[1:2]  # `flock FILE -c CMD`, run by $SHELL -c
            return
    if name not in ("su", "runuser") or seen & {"-u", "--user"}:
        step.words = tuple(ops)  # runuser -u USER runs the command itself
        if not ops and not step.scripts and name == "runuser":
            step.problem = f"Execute runs a shell without -c: {shown}."
        return
    if ops and ops[0].literal() == "-":  # `su - USER`
        ops = ops[1:]
    if not step.scripts:
        step.problem = f"Execute runs a shell without -c: {shown}."
    elif ops[1:]:  # words after USER go to the user's shell as its arguments
        step.problem = f"Execute cannot be checked: {quote(ops[1].raw)} after {shown}."


def _digits(word: Word) -> bool:
    lit = word.literal()
    return lit is not None and lit.isascii() and lit.isdigit()
