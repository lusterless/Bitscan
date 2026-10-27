"""TP-M7-15 (TASK-155), the parts with no database: the #99 (d) client-name
form and the ``FileInput`` hash check (carry (b) of "TASK-154 REVIEW
APPROVED", decisions 2026-10-27).

Expected values come from #99 (d), not from the code: the part's
``filename`` decoded as UTF-8 with replacement, U+0000, the other C0 controls
and DEL replaced by U+FFFD, cut to 255 characters; a missing name is the
empty string. C1 controls (U+0080 to U+009F) and format characters such as
U+202E are not in that list, so they are kept. Owner: tester-m7-155.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bitscan_manager.services.importer import uploads
from bitscan_manager.services.importer.pipeline import FileInput
from bitscan_manager.services.importer.store import Target
from bitscan_manager.services.importer.uploads import client_file_name

R = "�"

# REQ-163 (1) names (as the multipart header's bytes) -> the #99 (d) form.
HOSTILE: list[tuple[bytes | None, str]] = [
    (b"../../etc/passwd", "../../etc/passwd"),
    (b"/abs.bit", "/abs.bit"),
    (b"a/b.bit", "a/b.bit"),
    (b"..", ".."),
    (b".", "."),
    (b"a" * 5000, "a" * 255),
    (b"x\x00y.bit", f"x{R}y.bit"),
    (b"x\ry.bit", f"x{R}y.bit"),
    (b"x\ny.bit", f"x{R}y.bit"),
    (b"\t\x01\x1f\x7f.bit", f"{R}{R}{R}{R}.bit"),
    (b"\x1b[31mred.bit", f"{R}[31mred.bit"),
    (b"<script>alert(1)</script>.bit", "<script>alert(1)</script>.bit"),
    ("evil‮gnp.bit".encode(), "evil‮gnp.bit"),
    (b"\xff\xfe.bit", f"{R}{R}.bit"),
    (b"\xc0\xaf..\xc0\xafetc", f"{R}{R}..{R}{R}etc"),
    (b"caf\xc3", f"caf{R}"),  # truncated multi-byte sequence
    ("\x85nel.bit".encode(), "\x85nel.bit"),  # C1: not in #99 (d)
    (b"", ""),
    (None, ""),
    (b"policy-1.bit", "policy-1.bit"),
    (b".tmp-1-" + b"0" * 64, ".tmp-1-" + "0" * 64),
]


@pytest.mark.parametrize(("raw", "expected"), HOSTILE, ids=range(len(HOSTILE)))
def test_client_name_bytes_take_the_99d_form(raw: bytes | None, expected: str) -> None:
    assert client_file_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(r.decode("utf-8"), e) for r, e in HOSTILE if r is not None and r.isascii()]
    + [("evil‮gnp.bit", "evil‮gnp.bit"), ("é" * 300, "é" * 255)],
)
def test_client_name_str_takes_the_same_form(raw: str, expected: str) -> None:
    assert client_file_name(raw) == expected


def test_the_cut_is_255_characters_not_bytes() -> None:
    assert client_file_name("é" * 255) == "é" * 255
    assert client_file_name(("é" * 256).encode()) == "é" * 255
    assert client_file_name(b"a" * 254 + "€".encode() + b"zz") == "a" * 254 + "€"
    assert len(client_file_name(b"\x00" * 1000)) == 255
    # The replacement happens before the cut: a cut never leaves a control.
    assert client_file_name(b"a" * 254 + b"\x00b") == "a" * 254 + R


def test_a_lone_surrogate_never_survives() -> None:
    out = client_file_name("a\udcffb")
    assert out.startswith("a") and out.endswith("b")
    assert all(not 0xD800 <= ord(c) <= 0xDFFF for c in out)
    out.encode("utf-8")  # storable as text (no surrogate)


@pytest.mark.parametrize("raw", [r for r, _ in HOSTILE if r is not None])
def test_no_output_holds_nul_c0_or_del(raw: bytes) -> None:
    out = client_file_name(raw)
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in out)
    assert len(out) <= 255


# Carry (b): FileInput fails closed when its hashes disagree ---------------------


DATA = b"<Policy/>"
GOOD = hashlib.sha256(DATA).hexdigest()
OTHER = hashlib.sha256(b"other").hexdigest()


@pytest.mark.parametrize("kind", ["upload", "server"])
def test_fileinput_accepts_agreeing_hashes(kind: str) -> None:
    path = None if kind == "upload" else "p.bit"
    f = FileInput(DATA, GOOD, "c.bit", Target(kind, path, GOOD))  # type: ignore[arg-type]
    assert f.sha256 == GOOD
    # An oversize folder file has no buffer: only the two hashes must agree.
    g = FileInput(None, OTHER, "big.bit", Target("server", "big.bit", OTHER))
    assert g.data is None


@pytest.mark.parametrize(
    ("data", "digest", "target_digest"),
    [
        (DATA, GOOD, OTHER),  # sha256 != target.file_sha256
        (DATA, OTHER, OTHER),  # both agree, but not with the bytes
        (DATA, GOOD.upper(), GOOD.upper()),  # not the lowercase hex of the bytes
        (b"", GOOD, GOOD),  # empty bytes are hashed too
        (None, GOOD, OTHER),  # no buffer: the two hashes still differ
        (DATA + b"\n", GOOD, GOOD),  # one byte more
    ],
    ids=["target", "data", "upper", "empty", "nodata-target", "extra-byte"],
)
def test_fileinput_raises_on_each_mismatch(
    data: bytes | None, digest: str, target_digest: str
) -> None:
    with pytest.raises(ValueError):
        FileInput(data, digest, "c.bit", Target("upload", None, target_digest))


# The rename guard: a commit that is not this upload's never moves a file -------


def _pending(policy_id: int, source_file: str | None) -> Any:
    store = None if source_file is None else SimpleNamespace(source_file=source_file)
    return SimpleNamespace(policy_id=policy_id, store=store)


@pytest.mark.parametrize(
    ("written_for", "pending_id", "source_file"),
    [
        (5, 5, None),  # no store result
        (5, 5, "srv.bit"),  # the policy is not stored as this upload
        (5, 5, "uploaded/policy-6.bit"),
        (5, 6, "uploaded/policy-6.bit"),  # the temp was written for another id
    ],
)
def test_rename_refuses_a_commit_that_is_not_this_uploads(
    tmp_path: Path, written_for: int, pending_id: int, source_file: str | None
) -> None:
    upl = uploads._Upload(tmp_path, DATA, GOOD)
    upl.write(written_for)
    before = sorted(os.listdir(tmp_path))
    with pytest.raises(RuntimeError):
        upl.rename(_pending(pending_id, source_file))
    assert sorted(os.listdir(tmp_path)) == before == [f".tmp-{written_for}-{GOOD}"]


def test_rename_without_a_temp_file_raises(tmp_path: Path) -> None:
    upl = uploads._Upload(tmp_path, DATA, GOOD)
    with pytest.raises(RuntimeError):
        upl.rename(_pending(5, "uploaded/policy-5.bit"))
    assert os.listdir(tmp_path) == []


def test_discard_logs_only_the_error_type_when_removal_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    upl = uploads._Upload(tmp_path, DATA, GOOD)
    upl.write(5)

    def refuse(path: Any, *a: Any, **kw: Any) -> None:
        raise PermissionError(13, "denied", str(path))

    monkeypatch.setattr(Path, "unlink", refuse)
    monkeypatch.setattr(os, "unlink", refuse)
    monkeypatch.setattr(os, "remove", refuse)
    upl.discard()
    monkeypatch.undo()
    assert os.listdir(tmp_path) == [f".tmp-5-{GOOD}"]
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs == ["upload temp removal failed: PermissionError"]
