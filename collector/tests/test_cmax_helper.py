"""Tests for cmax-helper, the ClusterMAX scanner role (TS §3.8, §8.3).

A fake `cmax` prints the real ClusterMAX 0.3.0 report (fixtures/report-vm.txt),
writes audit files under CLUSTERMAX_RUNS_ROOT and records its arguments and
environment, so no test needs root, a GPU or ClusterMAX itself.
"""

from __future__ import annotations

import array
import fcntl
import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import cmax_helper as helper_mod

REPORT = HERE / "fixtures" / "report-vm.txt"
JOB = "0b7c1d2e-3f40-4a5b-8c6d-7e8f90a1b2c3"
KUBECONFIG = b"apiVersion: v1\nkind: Config\n"


def fake_cmax(tmp: Path, *, sleep: float = 0.0, exit_code: int = 0) -> Path:
    """A stand-in for cmax: records argv, env and the kubeconfig it can read."""
    record = tmp / "record.json"
    script = tmp / "cmax"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "kube = os.environ.get('KUBECONFIG', '')\n"
        "text = open(kube).read() if kube.startswith('/proc/') else ''\n"
        f"json.dump({{'argv': sys.argv[1:], 'env': dict(os.environ), 'kube': text}}, open({str(record)!r}, 'w'))\n"
        "run = os.path.join(os.environ['CLUSTERMAX_RUNS_ROOT'], 'run-1')\n"
        "os.makedirs(run, exist_ok=True)\n"
        "open(os.path.join(run, 'audit.out'), 'w').write('audit out')\n"
        "open(os.path.join(run, 'audit.values.json'), 'w').write('{}')\n"
        "sys.stderr.write('\\x1b[1mlog line\\x1b[0m\\n')\n"
        f"time.sleep({sleep})\n"
        f"sys.stdout.write(open({str(REPORT)!r}).read())\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(0o755)
    return record


def make_helper(tmp: Path, **kw: Any) -> tuple[helper_mod.Helper, Path]:
    record = fake_cmax(
        tmp, sleep=kw.pop("sleep", 0.0), exit_code=kw.pop("exit_code", 0)
    )
    work = tmp / "work"
    work.mkdir()
    h = helper_mod.Helper(
        cmax=str(tmp / "cmax"),
        environment=helper_mod.audit_environment(str(work), exists=lambda _p: False),
        work_dir=str(work),
        version="0.3.0",
        **kw,
    )
    return h, record


def request(
    target: str = "auto", variables: dict[str, str] | None = None, **extra: Any
) -> bytes:
    doc: dict[str, Any] = {
        "job_id": JOB,
        "target": target,
        "vars": variables or {},
    } | extra
    return json.dumps(doc).encode() + b"\n"


def sealed_memfd(data: bytes = KUBECONFIG, seal: bool = True) -> int:
    fd = os.memfd_create("kubeconfig", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    os.write(fd, data)
    if seal:
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, helper_mod.SEALS)
    return fd


def ask(
    h: helper_mod.Helper,
    line: bytes,
    fds: list[int] | None = None,
    allowed_uid: int | None = None,
) -> tuple[bytes, bytes]:
    """One connection: (first line, the rest) of the helper's answer."""
    ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    uid = os.getuid() if allowed_uid is None else allowed_uid
    t = threading.Thread(target=helper_mod.serve_connection, args=(h, theirs, uid))
    t.start()
    with ours:
        if fds:
            ours.sendmsg(
                [line], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))]
            )
        else:
            ours.sendall(line)
        data = b""
        while chunk := ours.recv(1 << 16):
            data += chunk
    t.join(10)
    first, _, rest = data.partition(b"\n")
    return first, rest


# -- the fixed command and environment ------------------------------------


@pytest.mark.parametrize(
    ("target", "flag"),
    [
        ("auto", []),
        ("standalone", ["--standalone"]),
        ("slurm", ["--slurm"]),
        ("k8s", ["--k8s"]),
    ],
)
def test_the_only_command_is_cmax_audit_vvv_y(target: str, flag: list[str]) -> None:
    assert helper_mod.audit_command(target) == [
        "/usr/lib/clustermax/bin/cmax",
        "audit",
        "-vvv",
        "-y",
        *flag,
    ]


def test_environment_is_minimal() -> None:
    env = helper_mod.audit_environment(exists=lambda _p: False)
    assert set(env) == {"PATH", "HOME", "LANG", "CLUSTERMAX_RUNS_ROOT", "PYTHONPATH"}
    assert env["HOME"] == "/root"
    assert env["CLUSTERMAX_RUNS_ROOT"] == "/run/cmax-work"
    assert env["PYTHONPATH"] == "/usr/lib/clustermax/site"


def test_audit_environment_finds_cluster_configs() -> None:
    present = {"/etc/rancher/k3s/k3s.yaml", "/opt/slurm/etc/slurm.conf"}
    env = helper_mod.audit_environment("/w", exists=present.__contains__)
    assert env["KUBECONFIG"] == "/etc/rancher/k3s/k3s.yaml"
    assert env["SLURM_CONF"] == "/opt/slurm/etc/slurm.conf"
    assert env["PATH"].split(":")[-4:] == list(helper_mod.EXTRA_PATH)
    root = helper_mod.audit_environment(
        "/w", exists={"/root/.kube/config", "/etc/slurm/slurm.conf"}.__contains__
    )
    assert root["KUBECONFIG"] == "/root/.kube/config"
    assert "SLURM_CONF" not in root


def test_allowed_variables_match_the_manager() -> None:
    sys.path.insert(0, str(HERE.parent.parent / "manager"))
    text = (
        HERE.parent.parent / "manager/bitscan_manager/services/jobs/cmax.py"
    ).read_text()
    for name, pattern in helper_mod.ALLOWED_VARS.items():
        assert f'"{name}"' in text
        assert pattern.pattern in text or pattern.pattern in {
            helper_mod._DNS,
            helper_mod._NAMESPACE,
        }
    assert text.count('"CLUSTERMAX_') == len(helper_mod.ALLOWED_VARS)


# -- request checks -------------------------------------------------------


def test_a_good_request_parses() -> None:
    got = helper_mod.parse_request(
        request(
            "k8s",
            {"CLUSTERMAX_K8S_GPU_DRA": "1", "CLUSTERMAX_AUDIT_K8S_NAMESPACE": "audit"},
        ).strip()
    )
    assert got == helper_mod.Request(
        JOB,
        "k8s",
        {"CLUSTERMAX_K8S_GPU_DRA": "1", "CLUSTERMAX_AUDIT_K8S_NAMESPACE": "audit"},
    )


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        (b"not json", "bad request"),
        (b"[]", "bad request"),
        (request(extra_field=1).strip(), "bad request"),
        (json.dumps({"job_id": JOB, "target": "auto"}).encode(), "bad request"),
        (
            json.dumps({"job_id": "x", "target": "auto", "vars": {}}).encode(),
            "bad job_id",
        ),
        (request("all").strip(), "bad target"),
        (
            json.dumps({"job_id": JOB, "target": "auto", "vars": []}).encode(),
            "bad vars",
        ),
        (
            request(variables={"CLUSTERMAX_IMAGE": "evil"}).strip(),
            "variable not allowed",
        ),
        (request(variables={"PATH": "/tmp"}).strip(), "variable not allowed"),
        (
            request(variables={"CLUSTERMAX_K8S_GPU_DRA": "2"}).strip(),
            "variable not allowed",
        ),
        (
            request(variables={"CLUSTERMAX_AUDIT_K8S_NAMESPACE": "Bad_NS"}).strip(),
            "variable not allowed",
        ),
        (
            request(variables={"CLUSTERMAX_K8S_GPU_DRA_DRIVER": "a;rm -rf /"}).strip(),
            "variable not allowed",
        ),
    ],
)
def test_bad_requests_are_refused(line: bytes, reason: str) -> None:
    with pytest.raises(helper_mod.Refused, match=f"^{reason}$"):
        helper_mod.parse_request(line)


def test_only_a_sealed_memfd_is_accepted(tmp_path: Path) -> None:
    fd = sealed_memfd()
    helper_mod.check_memfd(fd)
    os.close(fd)
    unsealed = sealed_memfd(seal=False)
    with pytest.raises(helper_mod.Refused):
        helper_mod.check_memfd(unsealed)
    os.close(unsealed)
    path = tmp_path / "kubeconfig"
    path.write_bytes(KUBECONFIG)
    regular = os.open(path, os.O_RDONLY)
    with pytest.raises(helper_mod.Refused):
        helper_mod.check_memfd(regular)
    os.close(regular)


# -- one audit ------------------------------------------------------------


def test_a_run_returns_the_header_and_the_files(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    (Path(h.work_dir) / "stale").write_text("old")
    out = h.run(helper_mod.Request(JOB, "slurm", {"CLUSTERMAX_K8S_GPU_DRA": "1"}), None)
    assert out.header["exit_code"] == 0
    assert out.header["cmax_version"] == "0.3.0"
    names = [name for name, _ in out.files]
    assert names == ["report.txt", "run.log", "audit.out", "audit.values.json"]
    files = dict(out.files)
    assert files["report.txt"] == REPORT.read_bytes()
    assert files["run.log"] == b"log line\n"
    assert files["audit.out"] == b"audit out"
    assert out.header["files"] == [
        {"name": n, "size": len(d), "truncated": False} for n, d in out.files
    ]
    seen = json.loads(record.read_text())
    assert seen["argv"] == ["audit", "-vvv", "-y", "--slurm"]
    assert seen["env"]["CLUSTERMAX_K8S_GPU_DRA"] == "1"
    assert seen["env"]["KUBECACHEDIR"] == os.path.join(h.work_dir, "kube-cache")
    assert list(Path(h.work_dir).iterdir()) == []


def test_the_kubeconfig_is_given_as_the_helpers_proc_fd(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    fd = sealed_memfd()
    try:
        h.run(helper_mod.Request(JOB, "k8s", {}), fd)
    finally:
        os.close(fd)
    seen = json.loads(record.read_text())
    assert seen["env"]["KUBECONFIG"] == f"/proc/{os.getpid()}/fd/{fd}"
    assert seen["kube"] == KUBECONFIG.decode()
    assert seen["argv"][-1] == "--k8s"
    assert not any(
        KUBECONFIG in p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file() and p.name != "record.json"
    )


def test_a_failed_audit_reports_its_exit_code(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path, exit_code=3)
    out = h.run(helper_mod.Request(JOB, "auto", {}), None)
    assert out.header["exit_code"] == 3


def test_the_audit_stops_after_the_limit_with_124(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path, sleep=30, limit_s=0.5)
    out = h.run(helper_mod.Request(JOB, "auto", {}), None)
    assert out.header["exit_code"] == helper_mod.TIMEOUT_EXIT == 124
    assert list(Path(h.work_dir).iterdir()) == []


def test_a_missing_cmax_is_127(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path)
    h.cmax = str(tmp_path / "absent")
    out = h.run(helper_mod.Request(JOB, "auto", {}), None)
    assert out.header["exit_code"] == 127


def test_files_are_cut_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(helper_mod, "MAX_FILE", 100)
    h, _ = make_helper(tmp_path)
    out = h.run(helper_mod.Request(JOB, "auto", {}), None)
    report = out.header["files"][0]  # type: ignore[index]
    assert report == {"name": "report.txt", "size": 100, "truncated": True}
    assert len(dict(out.files)["report.txt"]) == 100


# -- the socket protocol --------------------------------------------------


def test_round_trip_over_the_socket_with_a_kubeconfig(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    fd = sealed_memfd()
    first, rest = ask(h, request("k8s"), [fd])
    os.close(fd)
    header = json.loads(first)
    assert header["exit_code"] == 0
    assert len(rest) == sum(f["size"] for f in header["files"])
    assert rest.startswith(REPORT.read_bytes())
    assert json.loads(record.read_text())["kube"] == KUBECONFIG.decode()


def test_other_uid_is_refused(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    assert (
        ask(h, request(), allowed_uid=os.getuid() + 12345)[0]
        == b"REFUSED peer is not allowed"
    )
    assert not record.exists()


def test_a_kubeconfig_needs_target_k8s(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    fd = sealed_memfd()
    assert ask(h, request("auto"), [fd])[0] == b"REFUSED a kubeconfig needs target k8s"
    os.close(fd)
    assert not record.exists()


def test_two_descriptors_are_refused(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    a, b = sealed_memfd(), sealed_memfd()
    assert ask(h, request("k8s"), [a, b])[0] == b"REFUSED more than one descriptor"
    os.close(a)
    os.close(b)
    assert not record.exists()


def test_an_unsealed_descriptor_is_refused(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    fd = sealed_memfd(seal=False)
    assert (
        ask(h, request("k8s"), [fd])[0] == b"REFUSED descriptor is not a sealed memfd"
    )
    os.close(fd)
    assert not record.exists()


def test_oversized_request_is_refused(tmp_path: Path) -> None:
    h, record = make_helper(tmp_path)
    line = request(variables={"CLUSTERMAX_AUDIT_K8S_NAMESPACE": "a"}).replace(
        b"}}", b"}" + b" " * 5000 + b"}"
    )
    assert ask(h, line)[0] == b"REFUSED bad request"
    assert not record.exists()


def test_a_second_request_while_one_runs_is_busy(tmp_path: Path) -> None:
    h, _ = make_helper(tmp_path)
    assert h.lock.acquire(blocking=False)
    try:
        assert ask(h, request())[0] == b"BUSY"
    finally:
        h.lock.release()


def test_idle_only_when_not_running(tmp_path: Path) -> None:
    now = [0.0]
    h, _ = make_helper(tmp_path, clock=lambda: now[0])
    now[0] = helper_mod.IDLE_EXIT_S + 1
    assert h.idle()
    assert h.lock.acquire(blocking=False)
    assert not h.idle()
    h.lock.release()


def test_helper_refuses_to_start_outside_systemd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LISTEN_PID", raising=False)
    with pytest.raises(SystemExit):
        helper_mod.systemd_listener()


def test_main_usage() -> None:
    assert helper_mod.main([]) == 2
    assert helper_mod.main(["collect"]) == 2
