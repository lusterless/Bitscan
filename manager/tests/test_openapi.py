"""REQ-007: deterministic OpenAPI 3.1 export, committed file in sync (G6).

Checks CHK-M0-040 and CHK-M0-041 of tests/m0/test-plan.md.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import bitscan_manager
from bitscan_manager.app import openapi_document, write_openapi

COMMITTED = Path(__file__).resolve().parents[1] / "openapi.json"


def _export(path: Path) -> bytes:
    write_openapi(path)
    return path.read_bytes()


def test_export_twice_is_byte_identical(tmp_path: Path) -> None:
    first = _export(tmp_path / "a.json")
    second = _export(tmp_path / "b.json")
    assert first == second


def test_export_bytes_are_utf8_lf_sorted_with_one_trailing_newline(
    tmp_path: Path,
) -> None:
    data = _export(tmp_path / "o.json")
    text = data.decode("utf-8")
    assert b"\r" not in data
    assert text.endswith("}\n") and not text.endswith("\n\n")
    # write_openapi keeps non-ASCII text as UTF-8 (ensure_ascii=False)
    canonical = json.dumps(
        json.loads(text), indent=2, sort_keys=True, ensure_ascii=False
    )
    assert text == canonical + "\n"


def test_export_keeps_non_ascii_text_as_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-ASCII text in the document (a section sign in a docstring, say) is
    written as UTF-8 rather than as \\u escapes, and stays canonical."""
    import bitscan_manager.app as app_module

    real = app_module.openapi_document

    def with_text() -> dict[str, object]:
        doc = real()
        doc["info"]["description"] = "TS §6.2 café"
        return doc

    monkeypatch.setattr(app_module, "openapi_document", with_text)
    data = _export(tmp_path / "u.json")
    assert "TS §6.2 café".encode() in data
    assert b"\\u00a7" not in data
    text = data.decode("utf-8")
    canonical = json.dumps(
        json.loads(text), indent=2, sort_keys=True, ensure_ascii=False
    )
    assert text == canonical + "\n"


def test_document_is_openapi_31() -> None:
    """REQ-007 (3) (paths == {}) is superseded from TASK-038/-044 on."""
    doc = openapi_document()
    assert str(doc["openapi"]).startswith("3.1.")
    assert {"/healthz", "/readyz"} <= set(doc["paths"])
    assert doc["info"]["version"] == bitscan_manager.__version__ == "0.1.0"


def test_committed_file_matches_a_fresh_export(tmp_path: Path) -> None:
    assert COMMITTED.read_bytes() == _export(tmp_path / "fresh.json")


def test_module_command_writes_the_same_bytes(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    outputs = []
    for name in ("one.json", "two.json"):
        target = tmp_path / name
        subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
            [sys.executable, "-m", "bitscan_manager.app", str(target)],
            check=True,
            cwd=tmp_path,
            env=env,
            timeout=60,
        )
        outputs.append(target.read_bytes())
    assert outputs[0] == outputs[1] == COMMITTED.read_bytes()
