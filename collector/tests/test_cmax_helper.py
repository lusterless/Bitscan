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
from typing import Any

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


def rid(n: int) -> str:
    """The n-th run id the test helper hands out (32 lowercase hex)."""
    return f"{n:032x}"


def make_helper(tmp: Path, **kw: Any) -> tuple[helper_mod.Helper, Path]:
    command, counter = fake_cmax(
        tmp, delay=kw.pop("delay", 0.0), exit_code=int(kw.pop("exit_code", 0))
    )
    work = tmp / "work"
    work.mkdir()
    ids = iter(range(1, 1000))
    h = helper_mod.Helper(
        command=command,
        environment=helper_mod.audit_environment(str(work)),
        work_dir=str(work),
        version="0.3.0",
        new_id=lambda: rid(next(ids)),
        **kw,
    )
    return h, counter


def wait_done(h: helper_mod.Helper, run_id: str = rid(1)) -> None:
    for _ in range(200):
        if h.get(run_id, "status") != "running":
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
        "get status",
        "get access.sudoAvailable",
        "get a b",
        "get " + rid(1),
        "get " + rid(0xABC).upper() + " status",
        "get " + rid(1)[:31] + " status",
        "get " + rid(1) + " ../../etc/shadow",
        "get " + rid(1) + " $(id)",
        "get " + rid(1) + " status extra",
        "exec cmax",
        "get " + rid(1) + " " + "a" * 129,
    ],
)
def test_unknown_or_bad_requests_are_refused(tmp_path: Path, request_text: str) -> None:
    h, counter = make_helper(tmp_path)
    assert h.handle(request_text) == "REFUSED unknown request"
    assert not counter.exists()


def test_collect_starts_a_run_and_get_returns_its_lines(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path, delay=0.3)
    assert h.handle(f"get {rid(1)} status").startswith("MISSING ")
    assert h.handle("collect") == f"started {rid(1)}"
    assert h.handle("collect") == f"running {rid(1)}"
    assert h.handle(f"get {rid(1)} status") == "running"
    assert h.handle(f"get {rid(1)} access.sudoAvailable") == "PASS observed=true"
    assert h.handle(f"get {rid(1)} status").startswith("ok ")
    assert h.handle(f"get {rid(1)} status").endswith(" 0.3.0")
    assert counter.read_text() == "x"


def test_every_collect_after_a_run_starts_a_new_audit(tmp_path: Path) -> None:
    """TS §3.8 (owner decision 2026-11-14): a finished report is never
    reused, however fresh; the earlier run stays readable by its id."""
    h, counter = make_helper(tmp_path)
    assert h.handle("collect") == f"started {rid(1)}"
    wait_done(h, rid(1))
    assert h.handle("collect") == f"started {rid(2)}"
    wait_done(h, rid(2))
    assert counter.read_text() == "xx"
    assert h.handle(f"get {rid(1)} software.perf.installed") == "FAIL observed=false"
    assert h.handle(f"get {rid(2)} software.perf.installed") == "FAIL observed=false"


def test_only_the_last_four_runs_are_kept(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path)
    for n in range(1, 6):
        assert h.handle("collect") == f"started {rid(n)}"
        wait_done(h, rid(n))
    assert h.handle(f"get {rid(1)} header").startswith("MISSING ")
    assert h.handle(f"get {rid(1)} status").startswith("MISSING ")
    for n in range(2, 6):
        assert h.handle(f"get {rid(n)} status").startswith("ok "), n


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
    assert answers.count(f"started {rid(1)}") == 1
    assert answers.count(f"running {rid(1)}") == 15
    assert counter.read_text() == "x"


def test_get_of_an_unknown_run_is_missing(tmp_path: Path) -> None:
    h, counter = make_helper(tmp_path)
    assert h.handle(f"get {rid(9)} access.sudoAvailable").startswith("MISSING ")
    assert not counter.exists()


def test_failed_cmax_is_reported(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path, exit_code=3)
    h.handle("collect")
    wait_done(h)
    assert h.handle(f"get {rid(1)} status") == "failed 3"
    assert h.handle(f"get {rid(1)} access.sudoAvailable") == "ERROR cmax exited 3"
    assert h.handle("collect") == f"started {rid(2)}"


def test_get_times_out_while_the_audit_runs(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path, delay=2.0, get_wait_s=0.2)
    h.handle("collect")
    assert (
        h.handle(f"get {rid(1)} access.sudoAvailable")
        == "TIMEOUT the audit is still running"
    )


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
    h.handle(f"get {rid(1)} header")
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
    """Outside a runner job directory every call collects on its own."""
    h, _ = make_helper(tmp_path)
    server = Server(h, os.getuid())
    assert server.ask(["collect"]) == f"started {rid(1)}"
    wait_done(h, rid(1))
    assert server.ask(["get", "software.perf.installed"]) == "FAIL observed=false"
    assert server.ask(["get", "header"]).startswith("Command: cmax audit;")


def plugin_dir(base: Path, job: str, plugin: str) -> Path:
    d = base / ("bitscan-j-" + job) / ("p-" + plugin)
    d.mkdir(parents=True)
    return d


def test_one_audit_per_job_and_a_new_audit_per_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TS §3.8 (owner decision 2026-11-14): the plugins of one job share one
    run, whichever starts first; the next job (a new scan) starts a new one."""
    h, counter = make_helper(tmp_path)
    server = Server(h, os.getuid())
    jobs = tmp_path / "tmp"
    monkeypatch.chdir(plugin_dir(jobs, "aaa", "1"))
    assert server.ask(["get", "software.perf.installed"]) == "FAIL observed=false"
    monkeypatch.chdir(plugin_dir(jobs, "aaa", "2"))
    assert server.ask(["collect"]) == f"started {rid(1)}"  # the saved answer
    assert server.ask(["get", "status"]).startswith("ok ")
    assert (jobs / "bitscan-j-aaa" / "cmax-run").read_text() == f"started {rid(1)}\n"
    assert counter.read_text() == "x"
    monkeypatch.chdir(plugin_dir(jobs, "bbb", "1"))
    assert server.ask(["collect"]) == f"started {rid(2)}"
    wait_done(h, rid(2))
    assert counter.read_text() == "xx"


def test_parallel_plugins_of_one_job_start_one_audit(tmp_path: Path) -> None:
    """Plugins run in parallel (max_parallel_plugins): the lock lets exactly
    one of them send collect."""
    h, counter = make_helper(tmp_path, delay=0.3)
    server = Server(h, os.getuid())
    dirs = [plugin_dir(tmp_path / "tmp", "ccc", str(n)) for n in range(8)]
    script = str(HERE.parent / "src" / "cmax_trigger.py")
    procs = [
        subprocess.Popen(
            [sys.executable, "-I", script, "get", "software.perf.installed"],
            cwd=d,
            env={"CMAX_TRIGGER_SOCKET": server.path},
            stdout=subprocess.PIPE,
            text=True,
        )
        for d in dirs
    ]
    outs = [p.communicate(timeout=30)[0].strip() for p in procs]
    assert outs == ["FAIL observed=false"] * 8
    assert counter.read_text() == "x"


def test_a_failed_collect_is_not_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No helper: NOHELPER is printed and nothing is saved, so a later
    plugin of the job tries again."""
    monkeypatch.chdir(plugin_dir(tmp_path / "tmp", "ddd", "1"))
    monkeypatch.setenv("CMAX_TRIGGER_SOCKET", str(tmp_path / "absent.sock"))
    out = io.StringIO()
    with redirect_stdout(out):
        assert cmax_trigger.main(["get", "header"]) == 0
    assert out.getvalue().startswith("NOHELPER ")
    assert not (tmp_path / "tmp" / "bitscan-j-ddd" / "cmax-run").exists()


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
