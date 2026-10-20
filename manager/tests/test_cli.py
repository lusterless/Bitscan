"""REQ-008: bitscan-manager console script; only --help succeeds in M0.

Checks CHK-M0-042 to CHK-M0-044 of tests/m0/test-plan.md.
"""

import builtins
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

import pytest

from bitscan_manager import cli

from .test_app import EnvRecorder

REFUSED = [[], ["serve"], ["db", "migrate"], ["db", "maintain"], ["bogus"]]
DB_MODULES = ("psycopg", "sqlalchemy", "testcontainers", "asyncpg")


def _run(argv: Sequence[str]) -> int:
    try:
        return cli.main(list(argv))
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)


def _script() -> str:
    found = shutil.which("bitscan-manager", path=str(Path(sys.executable).parent))
    assert found, "console script bitscan-manager is not installed in this venv"
    return found


def _no_socket(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("socket created")


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_exits_zero_and_names_the_program(
    capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    assert _run([flag]) == 0
    out = capsys.readouterr().out
    assert "usage: bitscan-manager" in out


@pytest.mark.parametrize("argv", REFUSED, ids=lambda a: " ".join(a) or "none")
def test_everything_else_is_refused_on_stderr(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert _run(argv) != 0
    captured = capsys.readouterr()
    assert captured.err.strip()
    assert captured.out == ""


@pytest.mark.parametrize("argv", [["serve"], ["db", "migrate"]])
def test_refused_commands_touch_no_env_socket_or_db(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    recorder = EnvRecorder(os.environ)
    imported: list[str] = []
    real_import = builtins.__import__

    def recording_import(name: str, *args: Any, **kwargs: Any) -> Any:
        imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(os, "environ", recorder)
    monkeypatch.setattr(socket.socket, "__init__", _no_socket)
    monkeypatch.setattr(builtins, "__import__", recording_import)

    assert _run(argv) != 0

    monkeypatch.undo()
    assert [m for m in imported if m.split(".")[0] in DB_MODULES] == []
    assert [k for k in recorder.read if k.startswith("BITSCAN_")] == []


def test_console_script_help() -> None:
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [_script(), "--help"], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0
    assert "usage: bitscan-manager" in proc.stdout


@pytest.mark.parametrize("argv", REFUSED, ids=lambda a: " ".join(a) or "none")
def test_console_script_refuses(argv: list[str]) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    proc = subprocess.run(  # noqa: S603  # fixed argv, no untrusted input
        [_script(), *argv], capture_output=True, text=True, env=env, timeout=60
    )
    assert proc.returncode != 0
    assert proc.stderr.strip()
    assert proc.stdout == ""
