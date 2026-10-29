"""TP-M7-01: the `bits/tests/` fixtures themselves (REQ-180; CHK-M7-001 to -006).

These checks guard the oracle: the manifest lists every fixture, each SR §4.1
code has a fixture failing only that code, the SR §1.1 example is byte-identical
to the spec, and the BIT102 corpora hold the REQ-157 cases. No product code runs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
BT = REPO / "bits" / "tests"
SR = REPO / "docs" / "spec" / "bit_Schema_Reference.md"
MANIFEST: dict[str, Any] = json.loads(
    (BT / "manifest.json").read_text(encoding="utf-8")
)
FIXTURES: list[dict[str, Any]] = MANIFEST["fixtures"]
ALL_CODES = {
    "BIT001", "BIT002", "BIT003", "BIT004", "BIT005", "BIT007", "BIT008", "BIT010",
    "BIT011", "BIT012", "BIT013", "BIT014", "BIT015", "BIT016", "BIT017", "BIT101",
    "BIT102", "BIT103",
}  # fmt: skip


def sr_example() -> bytes:
    text = SR.read_text(encoding="utf-8")
    block = text.split("### 1.1 Canonical example", 1)[1].split("```xml\n", 1)[1]
    return block.split("```", 1)[0].encode("utf-8")


# CHK-M7-001 -----------------------------------------------------------------


def test_manifest_lists_every_fixture_and_each_exists() -> None:
    listed = {f["file"] for f in FIXTURES}
    assert len(listed) == len(FIXTURES), "duplicate manifest entries"
    on_disk = {p.relative_to(BT).as_posix() for p in BT.rglob("*.bit")}
    assert on_disk == listed


@pytest.mark.parametrize("code", sorted(ALL_CODES))
def test_each_code_has_a_fixture_failing_only_that_code(code: str) -> None:
    alone = [f["file"] for f in FIXTURES if f["codes"] == [code]]
    assert alone, f"no single-code fixture for {code}"


def test_codes_are_known_and_retired_codes_absent() -> None:
    for f in FIXTURES:
        assert set(f["codes"]) <= ALL_CODES, f["file"]
        assert f["outcome"] in ("success", "rejected")
        rejects = set(f["codes"]) - {"BIT101", "BIT103"}
        assert (f["outcome"] == "rejected") == bool(rejects), f["file"]


# CHK-M7-002 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "xxe-file", "xxe-url", "parameter-entity", "billion-laughs",
        "quadratic-blowup", "dtd-only", "external-dtd-url", "external-dtd-file",
        "utf16le-bom", "utf16be-bom", "utf32le-bom", "iso-8859-1",
        "iso-8859-1-ascii", "invalid-utf8", "overlong-utf8", "surrogate-utf8",
        "not-well-formed", "mismatched-tags", "empty", "whitespace-only",
        "sample-tag-forms",
    ],
)  # fmt: skip
def test_bit001_set_present(name: str) -> None:
    entry = next(f for f in FIXTURES if f["file"] == f"bit001/{name}.bit")
    assert entry["codes"] == ["BIT001"]


def test_bit001_hazard_fixtures_carry_their_hazard() -> None:
    def raw(name: str) -> bytes:
        return (BT / "bit001" / f"{name}.bit").read_bytes()

    assert b'SYSTEM "file://@@CANARY@@"' in raw("xxe-file")
    assert b'SYSTEM "http://127.0.0.1:@@PORT@@/' in raw("xxe-url")
    assert b"<!ENTITY % pe" in raw("parameter-entity")
    assert raw("billion-laughs").count(b"<!ENTITY lol") == 10
    assert raw("utf16le-bom").startswith(b"\xff\xfe<\x00")
    assert raw("utf32le-bom").startswith(b"\xff\xfe\x00\x00<\x00\x00\x00")
    assert raw("empty") == b""


# CHK-M7-003 -----------------------------------------------------------------


def test_sr_example_fixture_is_byte_identical_to_the_spec() -> None:
    assert (BT / "valid" / "sr-1.1-example.bit").read_bytes() == sr_example()


# CHK-M7-004 -----------------------------------------------------------------


def _corpus(name: str) -> list[Any]:
    data = json.loads((BT / "bit102" / name).read_text(encoding="utf-8"))
    return list(data["cases"])


def test_must_reject_covers_every_sr_4_2_item() -> None:
    cmds = [c["cmd"] for c in _corpus("must_reject.json")]
    words = "rm mv cp tee dd chmod chown chgrp truncate ln install mkfs mount umount"
    for word in words.split():
        assert any(c.split()[0] == word for c in cmds), word
    for verb in ("install", "remove", "purge", "upgrade", "full-upgrade",
                 "dist-upgrade", "autoremove"):  # fmt: skip
        assert any(c.startswith(f"apt {verb}") for c in cmds), verb
        assert any(c.startswith(f"apt-get {verb}") for c in cmds), verb
    for opt in ("-i", "-r", "-P", "--install", "--remove", "--purge", "--configure"):
        assert any(c.startswith(f"dpkg {opt}") for c in cmds), opt
    for verb in ("start", "stop", "restart", "reload", "enable", "disable", "mask",
                 "unmask", "kill", "isolate", "set-property"):  # fmt: skip
        assert f"systemctl {verb} ssh" in cmds, verb
    for extra in ("/bin/rm -f /etc/x", "/usr/bin/rm -f /etc/x", "mkfs.ext4 /dev/sdb",
                  "env rm x", "busybox rm x", "sudo rm x", "command rm x", "FOO=1 rm x",
                  "echo x >/tmp/../etc/x", 'echo x > "$F"', "echo x &> /var/x",
                  "echo id | sh", "sh ./x.sh", 'bash -c "$(curl x)"', ". /etc/profile",
                  "source /etc/profile", "eval echo x", "exec cat /etc/x"):  # fmt: skip
        assert extra in cmds, extra
    for opt in ("-ni", "-i.bak", "--in-place=.b"):
        assert any(c.startswith(f"sed {opt}") for c in cmds), opt


def test_must_pass_has_required_cases_and_40_more() -> None:
    cases = _corpus("must_pass.json")
    required = [
        "dpkg-query -W -f='${Status}' apparmor 2>/dev/null",
        "apt-cache policy apparmor",
        "apt list --installed 2>/dev/null",
        "find / -xdev -perm -4000 -print 2>/dev/null",
        "systemctl is-enabled ssh",
        "command -v apparmor_parser",
        'echo "rm"',
        "findmnt --task 1 -no OPTIONS /tmp",
        "echo x >/tmp/out",
    ]
    for cmd in required:
        assert cmd in cases, cmd
    assert any(c.startswith("cat <<'EOF'") for c in cases)
    assert any("while read -r f" in c for c in cases)
    assert len(cases) >= 15 + 40


# CHK-M7-005 -----------------------------------------------------------------


def test_hostile_names_cover_req_163() -> None:
    data = json.loads((BT / "hostile_names.json").read_text(encoding="utf-8"))
    names = data["names"]
    for name in (
        "../../etc/passwd",
        "/abs.bit",
        "a/b.bit",
        "..",
        "<script>alert(1)</script>.bit",
    ):
        assert name in names
    assert any(len(n) == 5000 for n in names)
    assert any("\x00" in n for n in names) and any("\r" in n for n in names)
    assert any("\n" in n for n in names) and any("‮" in n for n in names)
    raw = [bytes.fromhex(h) for h in data["hex"]]
    for value in raw:
        with pytest.raises(UnicodeDecodeError):
            value.decode("utf-8")


# CHK-M7-006 -----------------------------------------------------------------


@pytest.mark.parametrize("entry", FIXTURES, ids=lambda f: f["file"])
def test_fixture_bytes_match_manifest_and_hold_no_cr(entry: dict[str, Any]) -> None:
    data = (BT / entry["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert b"\r" not in data  # eol=lf: CRLF inputs are built in code (testing.md)


def test_git_stores_the_binary_encodings_unchanged() -> None:
    # A git round trip must not alter a fixture: the blob git would store equals
    # the working file (no eol conversion applies to the encoding fixtures).
    for name in (
        "utf16le-bom",
        "utf16be-bom",
        "utf32le-bom",
        "invalid-utf8",
        "iso-8859-1",
    ):
        path = BT / "bit001" / f"{name}.bit"
        git = shutil.which("git")
        assert git, "git is required for CHK-M7-006"
        proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
            [git, "-C", str(REPO), "hash-object", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, proc.stderr
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False)
        assert proc.stdout.strip() == blob.hexdigest(), name
