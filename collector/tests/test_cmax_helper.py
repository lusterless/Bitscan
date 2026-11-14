"""Tests for cmax-helper and cmax-trigger (TS §3.8, §8.3 "Collector helper").

The fixture is the real report of `cmax audit -vvv -y` (ClusterMAX 0.3.0) on a
cloud VM without a GPU. A fake `cmax` prints it, so no test needs root, a GPU
or ClusterMAX itself.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import cmax_helper as helper_mod
import cmax_trigger

REPORT = HERE / "fixtures" / "report-vm.txt"


def fake_cmax(
    tmp: Path, *, delay: float = 0.0, exit_code: int = 0
) -> tuple[list[str], Path]:
    """A stand-in for `cmax audit -vvv -y` that counts its runs."""
    counter = tmp / "runs"
    script = tmp / "cmax"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        f"open({str(counter)!r}, 'a').write('x')\n"
        f"time.sleep({delay})\n"
        f"sys.stdout.write(open({str(REPORT)!r}).read())\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(0o755)
    return [str(script), "audit", "-vvv", "-y"], counter


def make_helper(tmp: Path, **kw: float) -> tuple[helper_mod.Helper, Path]:
    command, counter = fake_cmax(
        tmp, delay=kw.pop("delay", 0.0), exit_code=int(kw.pop("exit_code", 0))
    )
    work = tmp / "work"
    work.mkdir()
    h = helper_mod.Helper(
        command=command,
        environment=helper_mod.audit_environment(str(work)),
        work_dir=str(work),
        version="0.3.0",
        **kw,
    )
    return h, counter


def wait_done(h: helper_mod.Helper) -> None:
    for _ in range(200):
        if h.get("status") != "running":
            return
        time.sleep(0.05)
    raise AssertionError("audit did not finish")


# -- the fixed command --------------------------------------------------------


def test_the_only_command_is_cmax_audit_vvv_y() -> None:
    assert helper_mod.audit_command() == [
        "/usr/lib/clustermax/bin/cmax",
        "audit",
        "-vvv",
        "-y",
    ]


def test_environment_is_minimal_and_home_is_the_tmpfs_dir() -> None:
    env = helper_mod.audit_environment()
    assert set(env) == {"PATH", "HOME", "LANG"}
    assert env["HOME"] == "/run/cmax-work"


# -- parsing the real report --------------------------------------------------


@pytest.mark.parametrize(
    ("check_id", "expected"),
    [
        ("access.sudoAvailable", "PASS observed=true"),
        ("access.externalIdp.detected", "WARNING observed=false"),
        ("software.nccl.installed", "FAIL observed=false"),
        ("access.slurmCommandsOk", "n/a observed=n/a for standalone machines"),
    ],
)
def test_parse_check_maps_verdicts(check_id: str, expected: str) -> None:
    assert helper_mod.parse_check(REPORT.read_text(), check_id) == expected


def test_every_check_in_the_report_parses() -> None:
    text = REPORT.read_text()
    ids = [
        m.group(2)
        for line in text.splitlines()
        if (m := helper_mod.VERDICT.match(line))
    ]
    assert len(ids) == 81
    for check_id in ids:
        assert helper_mod.parse_check(text, check_id).split()[0] in {
            "PASS",
            "FAIL",
            "WARNING",
            "n/a",
        }


def test_unknown_check_is_missing() -> None:
    assert helper_mod.parse_check(REPORT.read_text(), "no.such.check").startswith(
        "MISSING "
    )


def test_header_is_the_target_block() -> None:
    header = helper_mod.parse_header(REPORT.read_text())
    assert header.startswith(
        "Command: cmax audit; Target: Local virtual machine; Host: vm;"
    )
    assert "Confirmation: accepted with --yes" in header


# -- requests -----------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text",
    [
        "",
        "run",
        "collect now",
        "get",
        "get a b",
        "get ../../etc/shadow",
        "get $(id)",
        "exec cmax",
        "get " + "a" * 129,
    ],
)
def test_unknown_or_bad_requests_are_refused(tmp_path: Path, request_text: str) -> None:
    h, counter = make_helper(tmp_path)
    assert h.handle(request_text) == "REFUSED unknown request"
    assert not counter.exists()


def test_collect_runs_once_and_get_returns_lines(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path, delay=0.3)
    assert h.handle("get status") == "none"
    assert h.handle("collect") == "started"
    assert h.handle("collect") == "running"
    assert h.handle("get access.sudoAvailable") == "PASS observed=true"
    assert h.handle("collect") == "ready"
    assert h.handle("get status").startswith("ok ")
    assert h.handle("get status").endswith(" 0.3.0")
    assert counter.read_text() == "x"


def test_concurrent_collects_share_one_run(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path, delay=0.3)
    answers: list[str] = []
    threads = [
        threading.Thread(target=lambda: answers.append(h.handle("collect")))
        for _ in range(16)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wait_done(h)
    assert answers.count("started") == 1
    assert counter.read_text() == "x"


def test_get_before_collect_is_missing(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path)
    assert h.handle("get access.sudoAvailable").startswith("MISSING ")
    assert not counter.exists()


def test_failed_cmax_is_reported(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path, exit_code=3)
    h.handle("collect")
    wait_done(h)
    assert h.handle("get status") == "failed 3"
    assert h.handle("get access.sudoAvailable") == "ERROR cmax exited 3"
    assert h.handle("collect") == "started"


def test_get_times_out_while_the_audit_runs(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path, delay=2.0, get_wait_s=0.2)
    h.handle("collect")
    assert h.handle("get access.sudoAvailable") == "TIMEOUT the audit is still running"


def test_stale_report_is_collected_again(tmp_path: Path) -> None:
    now = [1000.0]
    h, counter = make_helper(tmp_path, clock=lambda: now[0])
    h.handle("collect")
    wait_done(h)
    now[0] += helper_mod.FRESH_S + 1
    assert h.handle("collect") == "started"
    wait_done(h)
    assert counter.read_text() == "xx"


def test_idle_after_timeout_and_never_while_running(tmp_path: Path) -> None:
    now = [1000.0]
    h, _ = make_helper(tmp_path, clock=lambda: now[0], delay=0.3)
    assert not h.idle()
    h.handle("collect")
    now[0] += helper_mod.IDLE_EXIT_S + 1
    assert not h.idle()
    wait_done(h)
    now[0] += helper_mod.IDLE_EXIT_S + 1
    assert h.idle()


def test_helper_writes_nothing_to_disk(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path)
    before = {p for p in tmp_path.rglob("*")}
    h.handle("collect")
    wait_done(h)
    h.handle("get header")
    after = {p for p in tmp_path.rglob("*")}
    # Only the fake cmax's own run counter is new; the helper adds nothing.
    assert after - before == {counter}


# -- socket, peer check and the client ---------------------------------------


class Server:
    def __init__(self, h: helper_mod.Helper, allowed_uid: int) -> None:
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "collect.sock")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.path)
        self.sock.listen()
        self.thread = threading.Thread(
            target=helper_mod.serve, args=(h, self.sock, allowed_uid), daemon=True
        )
        self.thread.start()

    def ask(self, words: list[str]) -> str:
        out = io.StringIO()
        old = os.environ.get("CMAX_TRIGGER_SOCKET")
        os.environ["CMAX_TRIGGER_SOCKET"] = self.path
        try:
            with redirect_stdout(out):
                assert cmax_trigger.main(words) == 0
        finally:
            if old is None:
                del os.environ["CMAX_TRIGGER_SOCKET"]
            else:
                os.environ["CMAX_TRIGGER_SOCKET"] = old
        return out.getvalue().strip()


def test_trigger_round_trip(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path)
    server = Server(h, os.getuid())
    assert server.ask(["collect"]) == "started"
    assert server.ask(["get", "software.perf.installed"]) == "FAIL observed=false"
    assert server.ask(["get", "header"]).startswith("Command: cmax audit;")


def test_other_uid_is_refused(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path)
    server = Server(h, os.getuid() + 12345)
    assert server.ask(["collect"]) == "REFUSED peer is not allowed"
    assert not counter.exists()


def test_oversized_request_is_refused(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path)
    server = Server(h, os.getuid())
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(server.path)
        conn.sendall(b"collect" + b" " * 400 + b"\n")
        assert conn.recv(100).strip() == b"REFUSED bad request"
    assert not counter.exists()


def test_trigger_without_helper_prints_nohelper(tmp_path: Path) -> None:
    out = subprocess.run(
        [sys.executable, "-I", str(HERE.parent / "src" / "cmax_trigger.py"), "collect"],
        env={"CMAX_TRIGGER_SOCKET": str(tmp_path / "absent.sock")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0
    assert out.stdout.startswith("NOHELPER ")


def test_trigger_usage() -> None:
    assert cmax_trigger.main([]) == 2
    assert cmax_trigger.main(["run", "x"]) == 2


def test_helper_refuses_to_start_outside_systemd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LISTEN_PID", raising=False)
    with pytest.raises(SystemExit):
        helper_mod.systemd_listener()
