"""REQ-007: deterministic OpenAPI 3.1 export, committed file in sync (G6).

Checks CHK-M0-040 and CHK-M0-041 of tests/m0/test-plan.md.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

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
    canonical = json.dumps(json.loads(text), indent=2, sort_keys=True)
    assert text == canonical + "\n"


def test_document_is_openapi_31_with_no_paths() -> None:
    doc = openapi_document()
    assert str(doc["openapi"]).startswith("3.1.")
    assert doc["paths"] == {}
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
