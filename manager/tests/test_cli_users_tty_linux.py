"""TASK-046 on Linux: `users create-admin` on a terminal prompts twice with
echo off (CHK-M2-266, #7). Linux only (pty, termios)."""

import os
import sys

import pytest

if sys.platform == "win32":
    pytest.skip("not run: Linux only (pty)", allow_module_level=True)

import pty  # noqa: E402
import select  # noqa: E402
import termios  # noqa: E402
from pathlib import Path  # noqa: E402

from .conftest import PgServer  # noqa: E402
from .test_cli_users_pg import PW, new_name, user_row  # noqa: E402

pytestmark = pytest.mark.pg


@pytest.fixture
def dsn_file(migrated_db: PgServer, tmp_path: Path) -> Path:
    path = tmp_path / "app.dsn"
    path.write_text(migrated_db.dsn("bitscan_app") + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("second", ["same", "different"])
def test_tty_prompts_twice_without_echo(
    migrated_db: PgServer, dsn_file: Path, second: str
) -> None:
    name = new_name("tty")
    code = (
        "import sys, pathlib\nfrom bitscan_manager.cli.users import users_main\n"
        f"sys.exit(users_main(['create-admin', {name!r}],"
        f" dsn_file=pathlib.Path({str(dsn_file)!r})))\n"
    )
    pid, fd = pty.fork()
    if pid == 0:  # child
        os.execv(sys.executable, [sys.executable, "-c", code])  # noqa: S606
    seen = b""
    echo_off_at_prompt: list[bool] = []

    def read_until(marker: bytes, limit: float = 30) -> None:
        nonlocal seen
        import time

        deadline = time.monotonic() + limit
        while marker not in seen and time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                try:
                    seen += os.read(fd, 1024)
                except OSError:
                    return

    read_until(b"password: ")
    echo_off_at_prompt.append(not termios.tcgetattr(fd)[3] & termios.ECHO)
    os.write(fd, (PW + "\n").encode())
    read_until(b"the password: ")
    echo_off_at_prompt.append(not termios.tcgetattr(fd)[3] & termios.ECHO)
    os.write(
        fd, ((PW if second == "same" else "other pass " + "word!") + "\n").encode()
    )
    read_until(b"\n\n", limit=20)
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    assert seen.count(b"assword") >= 2  # asked twice
    assert PW.encode() not in seen  # never echoed
    assert echo_off_at_prompt == [True, True]
    if second == "same":
        assert os.waitstatus_to_exitcode(status) == 0
        assert user_row(migrated_db, name) is not None
    else:
        assert os.waitstatus_to_exitcode(status) == 1
        assert user_row(migrated_db, name) is None
