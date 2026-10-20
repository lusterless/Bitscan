"""REQ-008 (narrowed in M1), REQ-020 (4), (6), (7): bitscan-manager console script.

Checks CHK-M0-042 to CHK-M0-044 and CHK-M1-055/-056. From TASK-013 ``db migrate``
is a real command; every other invocation keeps the M0 refusal: non-zero exit,
no ``BITSCAN_*`` read, no socket and no database module.
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

STILL_STUBS = [
    [],
    ["serve"],
    ["users", "create-admin", "x"],
    ["bits", "rebuild"],
    ["db"],
    ["db", "downgrade"],
    ["db", "downgrade", "base"],
    ["db", "stamp", "head"],
    ["db", "migrate", "extra"],
    ["db", "maintain", "extra"],
    ["bogus"],
]
# db migrate without its variable is also refused (exit 2, message on stderr).
REFUSED = [*STILL_STUBS, ["db", "migrate"], ["db", "maintain"]]
DB_MODULES = ("psycopg", "sqlalchemy", "alembic", "testcontainers", "asyncpg")
MIGRATE = "BITSCAN_MIGRATE_DSN_FILE"


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


def _guarded_run(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> tuple[int, list[str], list[str]]:
    recorder = EnvRecorder(os.environ)
    imported: list[str] = []
    real_import = builtins.__import__

    def recording_import(name: str, *args: Any, **kwargs: Any) -> Any:
        imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.delenv(MIGRATE, raising=False)
    monkeypatch.setattr(os, "environ", recorder)
    monkeypatch.setattr(socket.socket, "__init__", _no_socket)
    monkeypatch.setattr(builtins, "__import__", recording_import)
    code = _run(argv)
    monkeypatch.undo()
    db = [m for m in imported if m.split(".")[0] in DB_MODULES]
    db += [m for m in imported if m.startswith("bitscan_manager.db")]
    return code, db, [k for k in recorder.read if k.startswith("BITSCAN_")]


@pytest.mark.parametrize("argv", STILL_STUBS, ids=lambda a: " ".join(a) or "none")
def test_refused_commands_touch_no_env_socket_or_db(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    code, db, read = _guarded_run(monkeypatch, argv)
    assert code != 0
    assert db == []
    assert read == []


@pytest.mark.parametrize("command", ["migrate", "maintain"])
def test_db_command_without_its_variable_reads_only_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    code, db, read = _guarded_run(monkeypatch, ["db", command])
    assert code == 2
    assert db == []
    assert set(read) == {MIGRATE}
    captured = capsys.readouterr()
    assert MIGRATE in captured.err
    assert captured.out == ""


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
