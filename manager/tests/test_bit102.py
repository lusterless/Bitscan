"""TP-M7-08: BIT102 rules over the lexer output (TASK-146; REQ-157, REQ-177,
REQ-180).

Expected verdicts come from SR §4.2 (the lists, the read-only uses, "the
canonical example ... and a corpus of common CIS commands are must-pass"),
SR §1.1, the approved answer #108 (a)-(k), the lead's rulings of 2026-10-27
(apt/apt-get/systemctl verbs anywhere among the literal arguments; `<>` is an
output redirection; `env -S` lexed) and the user's ruling of 2026-10-27
(a non-literal command word passes; only its nested scripts are checked).
Corpora: bits/tests/bit102 (tester-m7). CHK-M7-115 to -121; plants
CHK-M7-327 to -332. Owner: tester-m7b.
"""

from __future__ import annotations

import json
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bitscan_manager.services.importer.bit102 import check_execute
from bitscan_manager.services.importer.model import Code, Finding
from bitscan_manager.services.importer.parse import parse_bit
from bitscan_manager.services.importer.structure import check
from bitscan_manager.services.importer.values import trim_xml
from tests.bit_unit import BT, SAMPLES
from tests.test_bit_fixtures import sr_example

BS, NL = chr(92), chr(10)
ELEMENT = "Policy/PluginsGroups/Plugin[1]/Execute"
REJECT: list[dict[str, object]] = json.loads(
    (BT / "bit102" / "must_reject.json").read_text(encoding="utf-8")
)["cases"]
PASS: list[str] = json.loads(
    (BT / "bit102" / "must_pass.json").read_text(encoding="utf-8")
)["cases"]


def bit102(cmd: str, line: int = 14) -> list[Finding]:
    return check_execute(cmd, line=line, element=ELEMENT)


def assert_rejected(cmd: str, token: str | None = None) -> list[Finding]:
    found = bit102(cmd)
    assert found, f"not rejected: {cmd!r}"
    for f in found:
        assert (f.code, f.line, f.element) == (Code.BIT102, 14, ELEMENT)
        assert f.rejects
    if token is not None:
        assert any(token in f.message for f in found), (cmd, token, found)
    return found


def assert_passes(cmd: str) -> None:
    assert bit102(cmd) == [], cmd


def sample_executes() -> list[tuple[str, str]]:
    """(id, trimmed Execute) of every plugin in bits/samples, read through
    the real parser and structure check (REQ-157 (2))."""
    out: list[tuple[str, str]] = []
    for path in sorted(SAMPLES.glob("*.bit")):
        result = parse_bit(path.read_bytes())
        assert result.root is not None, path.name
        parsed = check(result.root, result.pi_lines).parsed
        assert parsed is not None, path.name
        for p in parsed.plugins:
            out.append((f"{path.stem}#{p.index}", trim_xml(p.execute.text)))
    return out


SAMPLE_EXECUTES = sample_executes()


# CHK-M7-115: every must-reject case, with its token -------------------------


def test_corpora_sizes() -> None:
    # Guards on the oracle (tester-m7's corpora): CHK-M7-004 sizes.
    assert len(REJECT) >= 386  # 149 at r1; +237 for TASK-145 r1 / TASK-146 r2
    assert len(PASS) >= 190  # 96 at r1; +94
    assert len(SAMPLE_EXECUTES) >= 30


@pytest.mark.parametrize("case", REJECT, ids=lambda c: str(c["cmd"])[:60])
def test_must_reject(case: dict[str, object]) -> None:
    assert_rejected(str(case["cmd"]), str(case["token"]))


# CHK-M7-116: every must-reject command in every context --------------------

CONTEXTS = [
    "true | {}",
    "true; {}",
    "true && {}",
    "false || {}",
    "true & {}",
    "( {} )",
    "{{ {}; }}",
    "if true; then {}; fi",
    "while false; do {}; done",
    "until true; do {}; done",
    "for i in 1; do {}; done",
    "case x in x) {};; esac",
    "f() {{ {}; }}",
    "echo $({})",
    "echo `{}`",
    "cat <({})",
    "echo x > >({})",
    "! {}",
    "x=$({})",
    'echo "$({})"',
    "echo ${{x:-$({})}}",
    "cat <<EOF\n$({})\nEOF",
    "bash -c '{}'",
    'sh -c "{}"',
    "dash -c '{}'",
    "sudo {}",
    "env {}",
]
CONTEXT_CASES = [
    (ctx, case)
    for case in REJECT
    if case.get("contexts")
    for ctx in CONTEXTS
    if not ("'" in str(case["cmd"]) and "'{}'" in ctx)
    and not ('"' in str(case["cmd"]) and '"{}"' in ctx)
]


@pytest.mark.parametrize(
    ("ctx", "case"),
    CONTEXT_CASES,
    ids=[f"{c[0][:14]}|{str(c[1]['cmd'])[:30]}" for c in CONTEXT_CASES],
)
def test_must_reject_in_every_context(ctx: str, case: dict[str, object]) -> None:
    cmd = ctx.format(case["cmd"])
    assert_rejected(cmd, str(case["token"]))


def test_context_count() -> None:
    assert sum(1 for c in REJECT if c.get("contexts")) >= 24
    assert len(CONTEXT_CASES) >= 24 * 20


# CHK-M7-117: #108 (a)-(e) matching forms -----------------------------------


@pytest.mark.parametrize(
    ("cmd", "token"),
    [
        ("/bin/rm x", "rm"), ("/usr/bin/rm x", "rm"), ("./rm x", "rm"),
        ("../../bin/rm x", "rm"), ("/usr/sbin/mkfs.ext4 /dev/sdb", "mkfs"),
        ("mkfs.ext4 /dev/sdb", "mkfs"), ("mkfs.xfs x", "mkfs"), ("mkfs x", "mkfs"),
        ("env rm x", "rm"), ("env -i FOO=1 rm x", "rm"), ("env - rm x", "rm"),
        ("env -u HOME rm x", "rm"), ("env --unset=HOME rm x", "rm"),
        ("env -- rm x", "rm"), ("busybox rm x", "rm"), ("sudo rm x", "rm"),
        ("sudo -u root rm x", "rm"), ("sudo -uroot rm x", "rm"),
        ("sudo --user=root rm x", "rm"), ("sudo -- rm x", "rm"),
        ("doas rm x", "rm"), ("doas -u root rm x", "rm"), ("command rm x", "rm"),
        ("command -p rm x", "rm"), ("builtin eval x", "eval"), ("nice rm x", "rm"),
        ("nice -n 5 rm x", "rm"), ("nice -5 rm x", "rm"), ("nohup rm x", "rm"),
        ("setsid rm x", "rm"), ("ionice -c3 rm x", "rm"), ("ionice -c 3 rm x", "rm"),
        ("stdbuf -oL rm x", "rm"), ("stdbuf -o L rm x", "rm"),
        ("timeout 5 rm x", "rm"), ("timeout -s KILL 5 rm x", "rm"),
        ("timeout -k 1 5 rm x", "rm"), ("timeout --preserve-status 5 rm x", "rm"),
        ("chroot / rm x", "rm"), ("chroot --userspec=a:b / rm x", "rm"),
        ("sudo env nice timeout 5 rm x", "rm"), ("FOO=1 rm x", "rm"),
        ("FOO=1 BAR=$(id) rm x", "rm"), ("sudo /bin/rm x", "rm"),
        ("sed -i s/a/b/ f", "-i"), ("sed -ni p f", "-ni"),
        ("sed -i.bak s/a/b/ f", "-i.bak"),
        ("sed --in-place=.b s/a/b/ f", "--in-place"),
        ("sed --in-place s/a/b/ f", "--in-place"),
        ("sed -e p -i f", "-i"), ("sed -n -i p f", "-i"), ("sed -Ei s/a/b/ f", "-Ei"),
        ("/bin/sed -i s/a/b/ f", "-i"), ("sudo sed -i s/a/b/ f", "-i"),
        ("apt-get -y install x", "install"), ("apt-get -s upgrade", "upgrade"),
        ("apt -y full-upgrade", "full-upgrade"),
        ("apt-get -o a=b install x", "install"),
        ("dpkg --purge=x", "--purge"), ("dpkg --remove=x", "--remove"),
        ("dpkg --install=x.deb", "--install"), ("dpkg --configure -a", "--configure"),
        ("systemctl --now enable x", "enable"), ("systemctl -p x stop ssh", "stop"),
        ("systemctl --no-block restart ssh", "restart"),
        ("/bin/systemctl mask x", "mask"),
    ],
)  # fmt: skip
def test_108_matching_forms(cmd: str, token: str) -> None:
    assert_rejected(cmd, token)


@pytest.mark.parametrize(
    "cmd",
    [
        # #108 (d) "skipping its options": a short-option cluster whose last
        # letter takes the next word (getopt) must not hide the command.
        "sudo -iu root rm -f /etc/x",
        "sudo -nu root rm x",
        "sudo -Hu root rm x",
        "env -iu FOO rm -f /etc/x",
        "timeout -vk 5 10 rm x",
        "timeout -vs KILL 10 rm x",
        "ionice -tc 3 rm x",
        "doas -nu root rm x",
        "nice -n5 rm x",
        "stdbuf -i0 -oL rm x",
        "stdbuf -eL -o L rm x",
    ],
)
def test_wrapper_option_clusters_do_not_hide_the_command(cmd: str) -> None:
    assert_rejected(cmd, "rm")


@pytest.mark.parametrize(
    "cmd",
    [
        # #108 (d): a long option given its value as the next word (getopt)
        # must not hide the command either.
        "sudo --user root rm x",
        "sudo --group adm rm x",
        "env --unset HOME rm x",
        "env --chdir / rm x",
        "nice --adjustment 5 rm x",
        "ionice --class 3 rm x",
        "stdbuf --output L rm x",
        "timeout --signal KILL 5 rm x",
        "timeout --kill-after 1 5 rm x",
        "chroot --userspec a:b / rm x",
        # env -S as a separate word and inside a short cluster.
        "env --split-string 'rm x'",
        "env -iS 'rm x'",
        "env -iS'rm x'",
    ],
)
def test_wrapper_long_option_values_do_not_hide_the_command(cmd: str) -> None:
    assert_rejected(cmd, "rm")


@pytest.mark.parametrize(
    ("cmd", "token"),
    [
        # SR §4.2 `--in-place`: GNU getopt accepts any unique prefix of it.
        ("sed --in s/a/b/ f", "--in"),
        ("sed --in-pl s/a/b/ f", "--in-pl"),
        ("sed --in-pl=.bak s/a/b/ f", "--in-pl=.bak"),
        ("sed -n --i p f", "--i"),
    ],
)
def test_sed_in_place_abbreviations(cmd: str, token: str) -> None:
    assert_rejected(cmd, token)


@pytest.mark.parametrize(
    "cmd",
    [
        # Review finding 3 (TASK-146 r1): a value attached to -e, -f or -l
        # (or given with =) does not use up the next word, so the -i after
        # it is still the in-place flag (GNU sed 4.9 edits f in each case).
        "sed -es/a/b/ -i f",
        "sed -l5 -i f",
        "sed -nfx -i f",
        "sed -l5 -i p f",
        "sed -fx -i f",
        "sed --line-length=5 -i p f",
        "sed --expression=p -i f",
    ],
)
def test_sed_attached_value_does_not_take_the_next_word(cmd: str) -> None:
    assert_rejected(cmd, '"-i"')


@pytest.mark.parametrize(
    "cmd",
    [
        # Without an attached value, -e/-f/-l take the next word (the
        # opposite pin): these are not in-place edits.
        "sed -e -i f",
        "sed -l 5 p f",
    ],
)
def test_sed_separate_value_is_taken(cmd: str) -> None:
    assert_passes(cmd)


# CHK-M7-118: redirections (#108 (i)) ----------------------------------------

REDIRECT_REJECT = [
    "echo x > /etc/x", "echo x >/tmp/../etc/x", "echo x > /tmp/a/../../etc/x",
    'echo x > "$F"', "echo x > $HOME/x", "echo x > /tmpx", "echo x > /tmp",
    "echo x > tmp/x", "echo x > ~/x", "echo x &> /var/x", "echo x >& /var/x",
    "echo x >> /etc/x", "echo x >| /etc/x", "echo x 2> /etc/x", "echo x 1>/etc/x",
    "echo x &>> /var/x", "cat <>/etc/x", "echo x >/dev/sda", "echo x >/dev/fd/1",
    "echo x > /tmp/$(id -u)", "echo x > /tmp/`id`", "echo x > /dev/null/../x",
    "> /etc/x", "echo x >/proc/sys/kernel/x", "echo x >\"/etc/x\"",
]  # fmt: skip
REDIRECT_PASS = [
    "echo x >/dev/null", "echo x 2>/dev/null", "echo x >/dev/stdout",
    "echo x >/dev/stderr", "echo x >/tmp/out", "echo x 2>&1", "echo x >&2",
    "echo x &>/dev/null", "echo x >>/tmp/log", "echo x >|/tmp/x", "cat <>/tmp/x",
    "echo x >&-", "echo x 1>&2 2>/dev/null", 'echo x > "/tmp/a b"',
    "cat < /etc/passwd", "cat <<<x", "cat 0</etc/x", "echo x >/tmp/a/b",
]  # fmt: skip


@pytest.mark.parametrize("cmd", REDIRECT_REJECT)
def test_output_redirections_rejected(cmd: str) -> None:
    assert_rejected(cmd)


@pytest.mark.parametrize("cmd", REDIRECT_PASS)
def test_safe_redirections_pass(cmd: str) -> None:
    assert_passes(cmd)


# CHK-M7-119: code-running forms (#108 (f)) ----------------------------------


@pytest.mark.parametrize(
    ("cmd", "token"),
    [
        (". x", "."), (". /etc/profile", "."), ("source x", "source"),
        ("eval x", "eval"), ("exec x", "exec"), ("exec 3>/dev/null", "exec"),
        ("xargs", "xargs"), ("find / | xargs cat", "xargs"),
        ("find / -exec cat {} +", "-exec"), ("find / -execdir cat {} ;", "-execdir"),
        ("find / -ok cat {} ;", "-ok"), ("find / -okdir cat {} ;", "-okdir"),
        ("sh ./x.sh", "sh"), ("bash x", "bash"), ("dash x", "dash"), ("sh -s", "sh"),
        ("sh", "sh"), ("echo x | sh", "sh"), ("sh < x", "sh"), ("bash -x x.sh", "bash"),
        ('bash -c "$(curl x)"', "curl"), ("sh -c '`id`'", "id"),
        ("dash -c 'cat <(id)'", "id"), ("sh -c 'echo ${x:-$(id)}'", "id"),
        ("bash -c 'cat <<EOF\n$(id)\nEOF'", "<<"), ("sh -c 'rm x'", "rm"),
        ("bash -o pipefail -c 'rm x'", "rm"), ("bash -ec 'rm x'", "rm"),
        ("bash -c -- 'rm x'", "rm"), ("/bin/sh -c 'eval x'", "eval"),
        ("sh -c \"sh -c 'rm x'\"", "rm"), ("env -S 'rm x'", "rm"),
        ("env -S'rm x'", "rm"), ("env --split-string='rm x'", "rm"),
        ("sudo sh -c 'rm x'", "rm"), ("busybox sh -c 'rm x'", "rm"),
    ],
)  # fmt: skip
def test_code_running_forms(cmd: str, token: str) -> None:
    assert_rejected(cmd, token)


# CHK-M7-120: must-pass ------------------------------------------------------


@pytest.mark.parametrize("cmd", PASS, ids=lambda c: c[:60])
def test_must_pass(cmd: str) -> None:
    assert_passes(cmd)


@pytest.mark.parametrize(
    ("ident", "execute"), SAMPLE_EXECUTES, ids=[i for i, _ in SAMPLE_EXECUTES]
)
def test_every_sample_execute_passes(ident: str, execute: str) -> None:
    assert_passes(execute)


def test_sr_example_execute_passes() -> None:
    text = sr_example().decode()
    raw = text.split("<![CDATA[", 1)[1].split("]]>", 1)[0]
    assert trim_xml(raw) == "dpkg-query -W -f='${Status}' apparmor 2>/dev/null"
    assert_passes(trim_xml(raw))
    assert PASS[0] == trim_xml(raw)


@pytest.mark.parametrize(
    "cmd",
    [
        # Lead's false-positive guards (2026-10-27).
        "systemctl status ssh", "systemctl is-enabled cron",
        "systemctl show -p ActiveState ssh", "systemctl status restart-helper.service",
        "apt list --installed", "apt-cache policy openssh-server",
        "dpkg -l | grep install",
        # User's ruling (2026-10-27): a non-literal command word passes.
        '"$c" x', "${x} y", "$(echo rm) x", "$'" + BS + "x72m' x", 'sh -c "$s"',
        "sudo \"$c\" x",
        # SR §4.2 read-only uses and quoting.
        "apt-cache policy apparmor", "apt list --installed 2>/dev/null",
        "find / -xdev -perm -4000 -print 2>/dev/null", "systemctl is-enabled ssh",
        "command -v apparmor_parser", "command -V rm", 'echo "rm"', "echo rm -rf /",
        "printf '%s\\n' mount", "grep -c install /var/log/dpkg.log", "echo eval",
        "findmnt --task 1 -no OPTIONS /tmp", "cat <<'EOF'\n$(rm x)\nEOF",
        "systemctl list-unit-files --state=enabled", "systemctl is-active ssh",
        "dpkg -s apparmor", "dpkg-query -W -f='${Version}' openssh-server",
        "stat -c %a /etc/shadow", "sed -n 's/^x//p' /etc/x", "sed -e 's/a/b/' f",
        "sed -ei f", "sed -- -i f", "find / -name '*.rm' -print",
        "bash -c 'echo ok'", "sh -c 'grep -q x /etc/y && echo yes'",
        "env FOO=1", "env", "nice", "timeout 5 cat /etc/x", "sudo -l",
        "for f in rm mv; do echo $f; done", "case $x in rm) echo;; esac",
        "awk '{print $1}' /etc/passwd | sort -u", "echo x 2>&1 | tee_like",
    ],
)  # fmt: skip
def test_read_only_and_ruled_forms_pass(cmd: str) -> None:
    assert_passes(cmd)


def test_forbidden_word_inside_a_non_literal_word_still_rejected() -> None:
    # The ruling allows the outer word; the nested script is still checked.
    assert_rejected("$(rm -rf /) x", "rm")
    assert_rejected('"$(rm x)" y', "rm")
    assert_rejected("${x:-$(rm y)} z", "rm")


@pytest.mark.parametrize(
    "cmd",
    [
        # #108 (c): substitutions in words that are not commands still run.
        "for f in $(rm x); do :; done",
        "for f in a `rm x`; do :; done",
        'case "$(rm x)" in a) :;; esac',
        "case x in $(rm y)) :;; esac",
        "select f in $(rm x); do :; done",
        # ... and in the targets of input redirections and here-strings.
        "cat < <(rm x)",
        "cat <<<$(rm x)",
        'cat < "$(rm x)"',
        "cat 0<`rm x`",
        "cat <&$(rm x)",
    ],
)
def test_substitutions_in_data_words_and_input_targets(cmd: str) -> None:
    assert_rejected(cmd, "rm")


# CHK-M7-121: fail closed ----------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    ["echo 'abc", 'echo "abc', "echo $(abc", "echo `abc", "echo ${abc",
     "cat <<EOF\nabc", ")", "fi", "if x; then y", "; rm", "a\x00b",
     "echo " + "$(" * 9 + "x" + ")" * 9, "sh -c 'echo \"unterminated'"],
)  # fmt: skip
def test_unlexable_execute_is_bit102(cmd: str) -> None:
    (f,) = assert_rejected(cmd)
    assert "cannot be checked" in f.message


def test_nested_shell_scripts_past_depth_8_fail_closed() -> None:
    cmd = "rm x"
    for _ in range(10):
        cmd = "sh -c " + "'" + cmd.replace("'", "'" + BS + "''") + "'"
    assert_rejected(cmd)


# Messages (#105 (g)): token quoted, at most 64 characters of input ---------


def test_message_quotes_the_token_as_written() -> None:
    (f,) = bit102("r''m -f /etc/x")
    assert "r''m" in f.message
    (f,) = bit102("sudo rm x")
    assert '"rm"' in f.message and "sudo" in f.message


def test_message_bounded_and_escaped() -> None:
    long_target = "/etc/" + "x" * 16_000
    (f,) = bit102("echo y >" + long_target)
    assert long_target not in f.message and len(f.message) < 300
    (f,) = bit102("echo y >'/etc/a\x01b'")
    assert "\x01" not in f.message and BS + "x01" in f.message


def test_one_finding_per_distinct_offence_in_order() -> None:
    found = bit102("rm a; cp b c; rm a")
    assert [f.code for f in found] == [Code.BIT102, Code.BIT102]
    assert '"rm"' in found[0].message and '"cp"' in found[1].message


def test_execute_line_and_element_are_the_callers() -> None:
    (f,) = check_execute(
        "rm x", line=77, element="Policy/PluginsGroups/Plugin[9]/Execute"
    )
    assert (f.line, f.element) == (77, "Policy/PluginsGroups/Plugin[9]/Execute")


# Substring search would be wrong in both directions (CHK-M7-327) -----------


def test_not_a_substring_search() -> None:
    assert_passes('echo "rm"')
    assert_passes("echo firmware")
    assert_passes("grep -r mount /etc/fstab")
    assert_rejected("r''m x", "r''m")
    assert_rejected(BS + "rm x")


# Fuzz: check_execute never raises ------------------------------------------

PIECES = [
    " ", NL, ";", "|", "&&", "(", ")", "{", "}", ">", "<", ">>", "2>", "&>", "<(",
    "$(", "`", "${", "'", '"', BS, "#", "rm", "sudo", "env", "-i", "-u", "sh",
    "-c", "sed", "dpkg", "apt", "install", "/" + "tmp/", "/dev/null", "..", "x", "=",
]  # fmt: skip


@settings(
    max_examples=3_000, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
@given(st.lists(st.sampled_from(PIECES), max_size=200).map("".join))
def test_check_execute_never_raises(src: str) -> None:
    start = time.thread_time()
    found = bit102(src)
    assert time.thread_time() - start < 1.0
    for f in found:
        assert f.code is Code.BIT102 and f.rejects


# TASK-146 r2: brace expansion bounds in bash mode (impl report r2 (3)) ------


def test_brace_expansion_word_limit_256() -> None:
    # 2**8 = 256 words pass (none is a listed command); echo + 256 = 257
    # words for one command are refused as "cannot be checked".
    assert_passes("bash -c '" + "{a,b}" * 8 + "'")
    (f,) = assert_rejected("bash -c 'echo " + "{a,b}" * 8 + "'")
    assert "too many words" in f.message


def test_brace_nesting_limit_64() -> None:
    assert_passes("bash -c 'echo " + "{a," * 64 + "b" + "}" * 64 + "'")
    (f,) = assert_rejected("bash -c 'echo " + "{a," * 65 + "b" + "}" * 65 + "'")
    assert "too many braces" in f.message


def test_brace_expansion_only_in_bash_mode() -> None:
    # dash has no brace expansion: the Execute and sh/dash -c stay literal.
    for cmd in ("{rm,x}", "sh -c '{rm,x}'", "dash -c '{rm,x}'", "echo {rm,-rf,/x}"):
        assert_passes(cmd)
    for cmd in ("bash -c '{rm,x}'", "su -c '{rm,x}'", "sh -c \"bash -c '{rm,x}'\""):
        assert_rejected(cmd, '"rm"')


# TASK-146 r2: the shells' own option parsing (r1 blocking 1) ----------------


@pytest.mark.parametrize(
    ("cmd", "script_word"),
    [
        # The script the shell really runs is checked, not the o/O value.
        ("bash -co pipefail 'rm x'", "rm"),
        ("bash -oc pipefail 'rm x'", "rm"),
        ("bash -Oc extglob 'rm x'", "rm"),
        ("sh -co errexit 'rm x'", "rm"),
        ("sh -c - 'rm x'", "rm"),
        ("bash -c - 'rm x'", "rm"),
        ("bash -oO pipefail extglob -c 'rm x'", "rm"),
    ],
)
def test_shell_option_values_are_not_the_script(cmd: str, script_word: str) -> None:
    found = assert_rejected(cmd, f'"{script_word}"')
    assert all("without -c" not in f.message for f in found)


@pytest.mark.parametrize(
    "cmd", ["bash -co pipefail 'ls'", "sh -c - 'ls'", "bash -O extglob -c 'ls'"]
)
def test_shell_option_values_with_read_only_script_pass(cmd: str) -> None:
    assert_passes(cmd)


# TASK-146 r2: rulings (trap, alias, hash, let, @P/@E) -----------------------


@pytest.mark.parametrize(
    "cmd",
    ["trap 'echo done' EXIT", "trap '' INT", 'trap "$a" EXIT', "alias r=rm",
     "hash -p /bin/rm ls", "let x=1", "command trap 'ls' INT", "builtin alias r=rm"],
)  # fmt: skip
def test_code_defining_builtins_use_the_eval_message(cmd: str) -> None:
    (f,) = assert_rejected(cmd)
    assert "runs other code with" in f.message


@pytest.mark.parametrize(
    "cmd",
    ["trap", "trap -p", "trap -l", "trap -p EXIT", "trap - EXIT", "trap -- - INT TERM",
     "trap INT", "trap -p 'rm x' EXIT", "alias", "alias ll", "alias -p", "hash",
     "hash -r", "hash -t ls", "hash ls", "hash -- -p"],
)  # fmt: skip
def test_listing_and_reset_forms_pass(cmd: str) -> None:
    assert_passes(cmd)


def test_at_p_message_is_the_fail_closed_one() -> None:
    (f,) = assert_rejected('echo "${x@P}"')
    assert "cannot be checked" in f.message and "runs text as code" in f.message
    assert_passes("echo '${x@P}'")
    assert_passes("echo ${x@Q} ${x@A} ${x@K}")
