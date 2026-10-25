"""CHK-M4-275 (REQ-110 (1)): walk through deploy/runbooks/agent-install.md on
clean Ubuntu 24.04 systemd containers against the real M3 manager (`serve`
from this tree, real PostgreSQL 16, HTTPS with a private CA; fake OpenBao and
audit sink from manager/tests). Every runbook command is run as written,
except: commands run as root through `docker exec` (so `sudo` is dropped), and
`sudoedit` is replaced by writing the shown content into the file it created.
Each step and its result is one row; the run fails if any row differs from
what the runbook says.

Run (WSL, root, Docker, the manager venv):
  PYTHONPATH=<copy>/manager PATH=<venv>/bin:$PATH \
    python <copy>/e2e/runbook_walk.py --deb DIR --out FILE.jsonl
DIR holds bitscan-agent_<v>_amd64.deb and its .sha256 (build-deb.sh output).
Containers are named m4b-walk-*; images m4b-sysd-u24 (systemd, no policy-rc.d).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bitscan_manager.auth.totp import code_at, step_at
from tests.certs import make_pki
from tests.conftest import own_migrated_server
from tests.fake_sink import https_sink, server_context
from tests.fake_vault import fake_vault
from tests.test_cli_users_pg import run as run_users
from tests.test_serve_linux import CANARY_VAULT, env_for, free_port, https_get, start, wait_ready

V1 = "/api/v1"
IMAGE = "m4b-sysd-u24"


@dataclass
class Row:
    section: str
    step: str
    command: str
    expected: str
    actual: str
    ok: bool


ROWS: list[Row] = []
SECRETS: dict[str, str] = {}


def hide(text: str) -> str:
    for value, name in SECRETS.items():
        text = text.replace(value, name)
    return text


def row(section: str, step: str, command: str, expected: str, actual: str, ok: bool) -> bool:
    r = Row(section, step, hide(command), expected, hide(actual)[:600], ok)
    ROWS.append(r)
    print(("PASS " if ok else "FAIL ") + f"[{section}] {step}: {r.actual[:200]}", flush=True)
    return ok


def spki_der(pem: str) -> bytes:
    """The leaf certificate's SubjectPublicKeyInfo, by a minimal DER walk
    (independent of openssl): Certificate -> tbsCertificate -> [version],
    serial, signature, issuer, validity, subject, subjectPublicKeyInfo."""
    first = pem.split("-----BEGIN CERTIFICATE-----", 1)[1].split("-----END CERTIFICATE-----", 1)[0]
    der = base64.b64decode("".join(first.split()))

    def tlv(buf: bytes, i: int) -> tuple[int, int, int]:  # tag, start of value, end
        tag, n = buf[i], buf[i + 1]
        i += 2
        if n & 0x80:
            k = n & 0x7F
            n = int.from_bytes(buf[i:i + k], "big")
            i += k
        return tag, i, i + n

    _, cs, _ = tlv(der, 0)            # Certificate SEQUENCE
    _, ts, _ = tlv(der, cs)           # tbsCertificate SEQUENCE
    i = ts
    tag, _, end = tlv(der, i)
    if tag == 0xA0:                   # [0] version
        i = end
    for _ in range(5):                # serial, signature, issuer, validity, subject
        _, _, i = tlv(der, i)
    _, _, end = tlv(der, i)
    return der[i:end]


def wait(pred: Callable[[], Any], timeout: float, every: float = 2.0) -> Any:
    end = time.time() + timeout
    while True:
        v = pred()
        if v or time.time() > end:
            return v
        time.sleep(every)


# ---------------------------------------------------------------- hosts


class Host:
    """A clean host. Unless keep_id is set, it gets its own /etc/machine-id
    and the stock Ubuntu layout /var/lib/dbus/machine-id -> /etc/machine-id
    before it boots (the m4b-sysd images bake one id, and a separate D-Bus
    copy, into every container). dbus_copy makes /var/lib/dbus/machine-id a
    separate regular file holding the same id (an image built that way)."""

    def __init__(self, name: str, image: str = IMAGE, keep_id: bool = False, dbus_copy: bool = False) -> None:
        self.name = f"m4b-walk-{name}"
        self.hostname = f"walk-{name}"
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        subprocess.run(
            ["docker", "create", "--name", self.name, "--hostname", self.hostname,
             "--privileged", "--cgroupns=private", "--tmpfs", "/run", "--tmpfs", "/run/lock",
             "--add-host", "mgr.example:host-gateway", image],
            check=True, capture_output=True,
        )
        if not keep_id:
            d = Path(tempfile.mkdtemp(prefix="m4b-mid."))
            mid = secrets.token_hex(16)
            (d / "machine-id").write_text(mid + "\n")
            if dbus_copy:
                (d / "dbus").mkdir()
                (d / "dbus" / "machine-id").write_text(mid + "\n")
            else:
                (d / "dbus").mkdir()
                os.symlink("/etc/machine-id", d / "dbus" / "machine-id")
            subprocess.run(["docker", "cp", str(d / "machine-id"), f"{self.name}:/etc/machine-id"], check=True, capture_output=True)
            subprocess.run(["docker", "cp", str(d / "dbus" / "machine-id"), f"{self.name}:/var/lib/dbus/machine-id"], check=True, capture_output=True)
            shutil.rmtree(d, ignore_errors=True)
        subprocess.run(["docker", "start", self.name], check=True, capture_output=True)
        wait(lambda: self.sh("systemctl is-system-running")[1].strip() in ("running", "degraded"), 60, 1)

    def sh(self, cmd: str, stdin: str | None = None, timeout: int = 600) -> tuple[int, str]:
        p = subprocess.run(
            ["docker", "exec", "-i", self.name, "bash", "-c", cmd],
            input=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout,
        )
        return p.returncode, p.stdout.replace("\r", "")

    def put(self, src: Path, dst: str) -> None:
        subprocess.run(["docker", "cp", str(src), f"{self.name}:{dst}"], check=True, capture_output=True)

    def journal(self) -> str:
        return self.sh("journalctl -u bitscan-agent --no-pager -o cat")[1]

    def stat(self, path: str) -> str:
        return self.sh(f"stat -c '%U:%G %a' {path} 2>/dev/null || echo absent")[1].strip()

    def remove(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)


# ---------------------------------------------------------------- manager


class Manager:
    def __init__(self, port: int, ca: Path) -> None:
        self.port, self.ca = port, ca
        self.session = ""
        self.used = -1
        self.seed = b""

    def call(self, method: str, path: str, body: Any = None, token: str | None = None) -> tuple[int, Any]:
        h = {} if token == "" else {"Authorization": f"Bearer {token or self.session}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        status, _, out = https_get(self.port, self.ca, path, h, data, method)
        try:
            return status, json.loads(out) if out else None
        except ValueError:
            return status, out.decode(errors="replace")

    def code(self) -> str:
        while True:
            now = step_at(datetime.now(UTC))
            for step in (now, now + 1):
                if step > self.used:
                    self.used = step
                    return code_at(self.seed, step)
            time.sleep(0.5)

    def enrol_token(self, **kw: Any) -> str:
        status, out = self.call("POST", f"{V1}/enrollment-tokens", {"max_uses": 1, "expires_in_hours": 24} | kw)
        assert status == 201, (status, out)
        tok = out["token"]
        SECRETS[tok] = f"<bse_{len(SECRETS)}>"
        return tok

    def requests(self, state: str = "pending") -> list[dict[str, Any]]:
        status, out = self.call("GET", f"{V1}/enrollment-requests?state={state}&limit=500")
        return out.get("items", []) if status == 200 and isinstance(out, dict) else []

    def request_for(self, hostname: str, timeout: float = 180) -> dict[str, Any] | None:
        return wait(lambda: next((r for r in self.requests() if r["hostname"] == hostname), None), timeout)

    def agent(self, agent_id: str) -> dict[str, Any]:
        status, out = self.call("GET", f"{V1}/agents/{agent_id}")
        return out if status == 200 else {}


# ---------------------------------------------------------------- the walk


def walk(deb_dir: Path, work: Path) -> None:  # noqa: PLR0915
    deb = next(deb_dir.glob("bitscan-agent_*_amd64.deb"))
    version = deb.name.split("_")[1]
    pki = make_pki(work / "pki")
    sink_leaf, vault_leaf = pki.leaf("sink"), pki.leaf("vault")
    mgr_leaf = pki.leaf("mgr", sans="DNS:mgr.example,DNS:localhost,IP:127.0.0.1")
    creds = work / "pgcreds"
    creds.mkdir()
    with (
        own_migrated_server(creds) as pg,
        https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
        fake_vault(server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT) as vault,
    ):
        port = free_port()
        env = env_for(pg, work, pki, mgr_leaf, f"https://localhost:{sink.port}/audit", port,
                      BITSCAN_VAULT_ADDR=f"https://127.0.0.1:{vault.port}", BITSCAN_LISTEN=f"0.0.0.0:{port}")
        serve = start(env, work, port, pki, mgr_leaf)
        try:
            wait_ready(serve)
            run_walk(Manager(port, pki.ca), pki, mgr_leaf.cert, deb, version, port, work)
        finally:
            if serve.proc.poll() is None:
                serve.stop()
            log = (work / "serve.log").read_text(errors="replace")
            row("manager", "serve log holds no enrolment or agent token", "grep serve.log",
                "no bse_/bsa_ token", "clean" if not re.search(r"bs[ae]_[A-Za-z0-9_-]{43}", log) else "token found",
                not re.search(r"bs[ae]_[A-Za-z0-9_-]{43}", log))


def admin_session(m: Manager, work: Path) -> None:
    """An admin with TOTP and a TOTP-verified session in m; job_pull_seconds 60."""
    # admin with TOTP (README "Users", "API")
    admin, pw = "walk-admin", "walk pass " + secrets.token_hex(8)
    made = run_users(["create-admin", admin], work / "creds" / "app_dsn", stdin=pw + "\n")
    assert made.returncode == 0, made.stderr
    _, out = m.call("POST", f"{V1}/auth/login", {"username": admin, "password": pw}, token="")
    m.session = out["token"]
    _, out = m.call("POST", f"{V1}/auth/totp/enrol", {})
    secret = out["secret"]
    m.seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    st, _ = m.call("POST", f"{V1}/auth/totp/enrol", {"totp_code": m.code()})
    _, out = m.call("POST", f"{V1}/auth/login", {"username": admin, "password": pw, "totp_code": m.code()}, token="")
    m.session = out["token"]
    st, _ = m.call("PATCH", f"{V1}/settings", {"job_pull_seconds": 60})
    row("setup", "admin TOTP session; job_pull_seconds 60", "PATCH /settings", "200", str(st), st == 200)


def run_walk(m: Manager, pki: Any, leaf_cert: Path, deb: Path, version: str, port: int, work: Path) -> None:  # noqa: PLR0915
    url = f"https://mgr.example:{port}"
    debname = deb.name
    admin_session(m, work)
    row("setup", "runbook under test", str(RUNBOOK), "sha256 recorded", hashlib.sha256(RUNBOOK.read_bytes()).hexdigest(), True)

    sha_file = deb.with_name(deb.name + ".sha256")
    hosts: list[Host] = []

    def host(name: str, image: str = IMAGE, **kw: bool) -> Host:
        h = Host(name, image, **kw)
        hosts.append(h)
        h.put(deb, f"/root/{debname}")
        h.put(sha_file, f"/root/{sha_file.name}")
        h.put(pki.ca, "/root/manager-ca.pem")
        return h

    try:
        if ONLY_CLONES:
            clone_section(m, url, debname, host)
            return
        # ------------------------------------------------ 1. Before you start
        a = host("a")
        rc, out = a.sh("timedatectl")
        row("1", "NTP: timedatectl shows the synchronized line", "timedatectl",
            "a 'System clock synchronized:' line", out.strip().replace("\n", " | ")[:300],
            "System clock synchronized:" in out)
        rc, out = a.sh("cd /root && install -d -m 0755 /etc/bitscan && install -m 0644 manager-ca.pem /etc/bitscan/ca.pem && stat -c '%U:%G %a %n' /etc/bitscan /etc/bitscan/ca.pem")
        row("1", "private CA copied under /etc", "install -d -m 0755 /etc/bitscan; install -m 0644 manager-ca.pem /etc/bitscan/ca.pem",
            "root:root 755 /etc/bitscan, root:root 644 ca.pem", out.strip(), rc == 0 and "root:root 755 /etc/bitscan" in out and "root:root 644 /etc/bitscan/ca.pem" in out)
        tls = work / "tls.crt"
        shutil.copy(leaf_cert, tls)
        p = subprocess.run(f"openssl x509 -in {tls} -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1",
                           shell=True, capture_output=True, text=True)  # noqa: S602 # the runbook's pipeline, fixed text
        pin = p.stdout.strip()
        want_pin = hashlib.sha256(spki_der(leaf_cert.read_text())).hexdigest()
        row("1", "key pin computed on the manager host", "openssl x509 -in tls.crt -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1",
            "64 hex = SHA-256 of the leaf SPKI (independent check)", pin, pin == want_pin and len(pin) == 64)

        # ------------------------------------------------ 2. Check the package
        rc, out = a.sh(f"cd /root && sha256sum -c {sha_file.name}")
        row("2", "sha256sum -c", f"sha256sum -c {sha_file.name}", f"{debname}: OK", out.strip(), rc == 0 and out.strip() == f"{debname}: OK")
        rc, out = a.sh(f"mkdir -p /root/t && cp /root/{debname} /root/{sha_file.name} /root/t/ && printf x >> /root/t/{debname} && cd /root/t && sha256sum -c {sha_file.name}")
        row("2", "a changed package fails the check", "sha256sum -c (one byte appended)", "FAILED, non-zero", out.strip(), rc != 0 and "FAILED" in out)

        # ------------------------------------------------ 3a. Preseed (with CA and pin)
        tok_a = m.enrol_token()
        preseed = (f"bitscan-agent bitscan/manager_url string {url}\n"
                   f"bitscan-agent bitscan/enrol_token password {tok_a}\n"
                   "# Optional, for a private CA and a key pin:\n"
                   "bitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem\n"
                   f"bitscan-agent bitscan/manager_spki_sha256 string {pin}\n")
        rc, out = a.sh("install -m 0600 /dev/null /root/bitscan.preseed && cat > /root/bitscan.preseed && stat -c '%U:%G %a' /root/bitscan.preseed", stdin=preseed)
        row("3a", "preseed file created root-only", "install -m 0600 /dev/null /root/bitscan.preseed; (sudoedit)", "root:root 600", out.strip(), out.strip() == "root:root 600")
        rc, out = a.sh(f"debconf-set-selections /root/bitscan.preseed && cd /root && apt install ./{debname} </dev/null; echo rc=$?")
        row("3a", "preseed loaded and package installed", f"debconf-set-selections /root/bitscan.preseed; apt install ./{debname}", "rc=0, no question asked",
            out.strip().splitlines()[-1], out.strip().endswith("rc=0"))
        rc, out = a.sh("rm -f /root/bitscan.preseed; ls /root/bitscan.preseed 2>&1")
        row("3a", "preseed deleted", "rm -f /root/bitscan.preseed", "No such file", out.strip(), "No such file" in out)
        rc, out = a.sh(
            "getent passwd bitscan bitscan-runner | cut -d: -f1,6,7; stat -c '%U:%G %a %n' /etc/bitscan/agent.yaml;"
            " grep -c bse_ /etc/bitscan/agent.yaml; printf 'GET bitscan/enrol_token\\n' | debconf-communicate bitscan-agent 2>/dev/null")
        # the agent may already have exchanged enroll.token for its bsa_ token
        # (it does at once, even while the enrolment is held): either state
        # shows the token was written as bitscan
        files = a.sh("stat -c '%U:%G %a %n' /var/lib/bitscan-agent/enroll.token /var/lib/bitscan-agent/token /var/lib/bitscan-agent/agent_id 2>/dev/null")[1]
        tok_ok = ("bitscan:bitscan 600 /var/lib/bitscan-agent/enroll.token" in files
                  or ("bitscan:bitscan 600 /var/lib/bitscan-agent/token" in files and "/var/lib/bitscan-agent/agent_id" in files))
        ok = ("bitscan:/nonexistent:/usr/sbin/nologin" in out and "bitscan-runner:/nonexistent:/usr/sbin/nologin" in out
              and "root:bitscan 640 /etc/bitscan/agent.yaml" in out and "\n0\n" in out and out.rstrip().endswith("0") and tok_ok)
        row("3a", "what the install does: users, agent.yaml, enroll.token, debconf cleared", "getent/stat/debconf-communicate",
            "users nologin no home; agent.yaml root:bitscan 640 without token; enroll.token bitscan 600 (or already exchanged); db_get empty",
            (out.strip() + " | " + files.strip()).replace("\n", " | "), ok)
        rc, out = a.sh("grep -rlF " + tok_a + " /var/cache/debconf /etc /var/log 2>/dev/null; true")
        row("3a", "token in no debconf file, /etc or log", "grep -r", "nothing", out.strip() or "nothing", out.strip() == "")

        # ------------------------------------------------ 4. Check the result
        rc, out = a.sh("systemctl is-enabled bitscan-agent.service bitscan-runner.socket; systemctl is-active bitscan-agent.service bitscan-runner.socket;"
                       " systemctl is-enabled bitscan-capread.socket; journalctl -u bitscan-agent -n 20 --no-pager | wc -l")
        lines = out.split()
        row("4", "units enabled and active; capread disabled; journal readable", "systemctl is-enabled/is-active ...; journalctl -u bitscan-agent -n 20",
            "enabled enabled active active disabled", " ".join(lines), lines[:5] == ["enabled", "enabled", "active", "active", "disabled"])
        req = m.request_for(a.hostname)
        rc, out = a.sh("ls /var/lib/bitscan-agent | tr '\\n' ' '")
        row("4", "(observation) state files while the enrolment is still held", "ls /var/lib/bitscan-agent",
            "recorded only", out.strip(), True)
        row("4", "the host appears as a held enrolment", "GET /enrollment-requests", "pending request for walk-a, kind new",
            json.dumps({k: req.get(k) for k in ("kind", "hostname", "agent_version")}) if req else "none", bool(req) and req.get("kind") == "new")
        st, _ = m.call("POST", f"{V1}/enrollment-requests/{req['request_id']}/approve") if req else (0, None)
        row("4", "admin approves", "POST /enrollment-requests/{id}/approve", "200", str(st), st == 200)
        wait(lambda: (lambda ls: "agent_id" in ls and "enroll.token" not in ls)(a.sh("ls /var/lib/bitscan-agent")[1]), 300, 3)
        rc, out = a.sh("ls /var/lib/bitscan-agent | tr '\\n' ' '")
        row("4", "enrolled: agent_id and token present, enroll.token gone", "ls /var/lib/bitscan-agent", "agent_id, token; no enroll.token",
            out.strip(), "agent_id" in out and "token" in out.split() and "enroll.token" not in out)
        a_id = a.sh("cat /var/lib/bitscan-agent/agent_id")[1].strip()
        detail = wait(lambda: (lambda d: d if d.get("os_info") and d.get("last_snapshot") else None)(m.agent(a_id)), 420, 5) or m.agent(a_id)
        snap = detail.get("last_snapshot") or {}
        row("4", "the first inventory follows the first inventory job (CA file and pin in use)", "GET /agents/{id}",
            "os_info and last_snapshot set, status online",
            json.dumps({"status": detail.get("status"), "os_id": (detail.get("os_info") or {}).get("os_id"), "package_count": snap.get("package_count")}),
            bool(detail.get("os_info")) and bool(snap.get("package_count")))
        rc, out = a.sh("dpkg-query -W | wc -l")
        row("4", "snapshot package count equals dpkg-query on the host", "dpkg-query -W | wc -l", str(snap.get("package_count")), out.strip(),
            str(snap.get("package_count")) == out.strip())

        # ------------------------------------------------ 5. If the install stops
        b = host("b")
        tok_b = m.enrol_token()
        b.sh("cd /root && install -d -m 0755 /etc/bitscan && install -m 0644 manager-ca.pem /etc/bitscan/ca.pem")
        rc, out = b.sh(f"printf 'bitscan-agent bitscan/manager_url string http://mgr.example:{port}\\nbitscan-agent bitscan/enrol_token password {tok_b}\\nbitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem\\n' | debconf-set-selections && cd /root && apt install ./{debname} </dev/null; echo rc=$?")
        msgs = [l for l in out.splitlines() if l.startswith("bitscan-agent: ")]
        row("5", "an invalid URL stops the install with one line", f"apt install ./{debname} (http:// URL preseeded)",
            "one 'bitscan-agent: the manager URL must be an https:// URL with a host' line, rc non-zero",
            f"{msgs} {out.strip().splitlines()[-1]}", msgs == ["bitscan-agent: the manager URL must be an https:// URL with a host"] and not out.strip().endswith("rc=0"))
        rc, out = b.sh("dpkg-query -W -f='${Status}' bitscan-agent; echo; systemctl is-active bitscan-agent.service bitscan-runner.socket; systemctl is-enabled bitscan-agent.service")
        row("5", "package unconfigured, no service enabled or started", "dpkg-query; systemctl", "half-configured, inactive inactive, disabled",
            out.strip().replace("\n", " "), "half-configured" in out and "active\n" not in out.replace("inactive", "") and "enabled\n" not in out.replace("disabled", ""))
        rc, out = b.sh(f"echo 'bitscan-agent bitscan/manager_url string {url}' | debconf-set-selections && dpkg --configure bitscan-agent </dev/null; echo rc=$?; dpkg-query -W -f='${{Status}}' bitscan-agent")
        row("5", "fix the cause, then dpkg --configure", "dpkg --configure bitscan-agent", "rc=0, install ok installed", out.strip().replace("\n", " ")[-120:],
            "rc=0" in out and out.strip().endswith("install ok installed"))
        b_req = m.request_for(b.hostname)
        row("5", "the fixed host enrols (held)", "GET /enrollment-requests", "pending walk-b", str(bool(b_req)), bool(b_req))

        # ------------------------------------------------ 3b. Interactive (teletype frontend fed on stdin)
        d = host("d")
        tok_d = m.enrol_token()
        # 3b: with a private CA, preseed the CA question first (as the runbook says)
        d.sh("cd /root && install -d -m 0755 /etc/bitscan && install -m 0644 manager-ca.pem /etc/bitscan/ca.pem"
             " && echo 'bitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem' | debconf-set-selections")
        rc, out = d.sh(f"cd /root && DEBIAN_FRONTEND=teletype apt install ./{debname}; echo rc=$?", stdin=f"{url}\n{tok_d}\n")
        asked = [q for q in ("Bitscan manager URL:", "Bitscan enrolment token:", "CA bundle for the manager", "Pin of the manager public key") if q in out]
        row("3b", "interactive install asks the URL and the token only", f"apt install ./{debname} (answers typed)",
            "asks manager URL and enrolment token; not the CA file or pin; rc=0", f"asked {asked}; {out.strip().splitlines()[-1]}",
            asked == ["Bitscan manager URL:", "Bitscan enrolment token:"] and out.strip().endswith("rc=0"))
        row("3b", "the typed token is not echoed", "apt output", "token absent", "absent" if tok_d not in out else "echoed", tok_d not in out)
        d_req = m.request_for(d.hostname)
        row("3b", "the interactively installed host enrols", "GET /enrollment-requests", "pending walk-d, kind new",
            json.dumps({"kind": d_req.get("kind")}) if d_req else "none", bool(d_req) and d_req.get("kind") == "new")

        # ------------------------------------------------ 3c. install.env
        c = host("c")
        tok_c = m.enrol_token()
        envtext = f"MANAGER_URL={url}\nENROL_TOKEN={tok_c}\nCA_FILE=/etc/bitscan/ca.pem\n# MANAGER_SPKI_SHA256=<64 hexadecimal characters>\n"
        rc, out = c.sh("cd /root && install -d -m 0755 /etc/bitscan && install -m 0644 manager-ca.pem /etc/bitscan/ca.pem && install -m 0600 /dev/null /etc/bitscan/install.env && cat > /etc/bitscan/install.env && stat -c '%U:%G %a' /etc/bitscan/install.env", stdin=envtext)
        row("3c", "install.env created root:root 0600", "install -d -m 0755 /etc/bitscan; install -m 0600 /dev/null /etc/bitscan/install.env; (sudoedit)", "root:root 600", out.strip(), out.strip() == "root:root 600")
        rc, out = c.sh(f"cd /root && apt install ./{debname} </dev/null; echo rc=$?; ls /etc/bitscan/install.env 2>&1; grep -c '^ca_file: ./etc/bitscan/ca.pem.$' /etc/bitscan/agent.yaml")
        row("3c", "install from install.env; file deleted; CA taken", f"apt install ./{debname}", "rc=0; install.env gone; ca_file set",
            out.strip().replace("\n", " ")[-200:], "rc=0" in out and "No such file" in out and out.strip().endswith("1"))
        c_req = m.request_for(c.hostname)
        row("3c", "the host enrols", "GET /enrollment-requests", "pending walk-c", str(bool(c_req)), bool(c_req))

        # ------------------------------------------------ 3a warning: string preseed and both clearing routes
        for route in ("rm", "save"):
            e = host(f"e{route}")
            fake = "bse_" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789") for _ in range(43))
            SECRETS[fake] = f"<bse_string_{route}>"
            rc, out = e.sh(f"printf 'bitscan-agent bitscan/manager_url string {url}\\nbitscan-agent bitscan/enrol_token string {fake}\\n' | debconf-set-selections && cd /root && apt install ./{debname} </dev/null >/dev/null 2>&1; echo rc=$?; grep -lF {fake} /var/cache/debconf/* 2>/dev/null")
            row("3a-warning", f"string preseed leaves the token in config.dat-old ({route} route)", "debconf-set-selections (string); apt install",
                "rc=0; only /var/cache/debconf/config.dat-old holds it", out.strip().replace("\n", " "),
                out.strip().replace("\n", " ") == "rc=0 /var/cache/debconf/config.dat-old")
            cmd = ("rm -f /var/cache/debconf/config.dat-old" if route == "rm"
                   else f"echo 'bitscan-agent bitscan/manager_url string {url}' | debconf-set-selections")
            rc, out = e.sh(f"{cmd}; grep -lF {fake} /var/cache/debconf/* 2>/dev/null; echo left=$?")
            row("3a-warning", f"clearing route '{route}' removes it", cmd, "no debconf file holds the token", out.strip(), out.strip() == "left=1")
            e.remove()

        clone_section(m, url, debname, host)

        # ------------------------------------------------ 6. Upgrade (host a)
        new_version = version + "+walk1"
        newdeb = work / f"bitscan-agent_{new_version}_amd64.deb"
        x = work / "repack"
        subprocess.run(["dpkg-deb", "-R", str(deb), str(x)], check=True)
        ctl = x / "DEBIAN" / "control"
        ctl.write_text(re.sub(r"^Version: .*$", f"Version: {new_version}", ctl.read_text(), flags=re.M))
        subprocess.run(["dpkg-deb", "--root-owner-group", "-b", str(x), str(newdeb)], check=True, capture_output=True)
        subprocess.run(f"cd {work} && sha256sum {newdeb.name} > {newdeb.name}.sha256", shell=True, check=True)  # noqa: S602
        a.put(newdeb, f"/root/{newdeb.name}")
        a.put(work / f"{newdeb.name}.sha256", f"/root/{newdeb.name}.sha256")
        before = a.sh("sha256sum /etc/bitscan/agent.yaml /var/lib/bitscan-agent/token /var/lib/bitscan-agent/agent_id | cut -c1-16; systemctl show -p InvocationID --value bitscan-agent")[1]
        rc, out = a.sh(f"cd /root && sha256sum -c {newdeb.name}.sha256 && apt install ./{newdeb.name} </dev/null; echo rc=$?")
        after = a.sh("sha256sum /etc/bitscan/agent.yaml /var/lib/bitscan-agent/token /var/lib/bitscan-agent/agent_id | cut -c1-16; systemctl show -p InvocationID --value bitscan-agent")[1]
        bl, al = before.split(), after.split()
        row("6", "upgrade asks nothing, keeps agent.yaml, token and id, restarts the services", f"sha256sum -c; apt install ./{newdeb.name}",
            "rc=0; three hashes equal; new InvocationID", f"{out.strip().splitlines()[-1]}; kept={bl[:3] == al[:3]}; restarted={bl[3:] != al[3:]}",
            out.strip().endswith("rc=0") and bl[:3] == al[:3] and bl[3:] != al[3:])
        t_before = m.agent(a_id).get("last_heartbeat_at")
        ok = wait(lambda: m.agent(a_id).get("last_heartbeat_at") != t_before, 420, 5)
        row("6", "the upgraded agent keeps reporting", "GET /agents/{id}", "a newer last_heartbeat_at", str(m.agent(a_id).get("last_heartbeat_at")), bool(ok))

        # ------------------------------------------------ 7. Re-enrol (host a): revoke, refused token, route 1, route 2
        old_token = a.sh("cat /var/lib/bitscan-agent/token")[1].strip()
        SECRETS[old_token] = "<old bsa_>"
        st, _ = m.call("POST", f"{V1}/agents/{a_id}/revoke")
        row("7", "admin revokes the agent", "POST /agents/{id}/revoke", "204", str(st), st == 204)
        ok = wait(lambda: "the host must be re-enrolled" in a.journal(), 300, 5)
        row("7", "the agent log says the host must be re-enrolled", "journalctl -u bitscan-agent", "'the host must be re-enrolled'", str(bool(ok)), bool(ok))
        bogus = "bse_" + "B" * 43
        SECRETS[bogus] = "<bse_unknown>"
        rc, out = a.sh(f"echo 'bitscan-agent bitscan/enrol_token password {bogus}' | debconf-set-selections && dpkg-reconfigure -fnoninteractive bitscan-agent </dev/null; echo rc=$?")
        ok = wait(lambda: "enrolment did not complete; the agent stays idle until it is restarted" in a.journal() and "enrolment refused; the host needs a new enrolment token" in a.journal(), 180, 5)
        row("7", "an unknown token: the agent logs the two runbook lines and stays idle", "dpkg-reconfigure (unknown bse_)",
            "'enrolment did not complete; …' with reason 'enrolment refused; …'", str(bool(ok)), bool(ok))
        tok_r1 = m.enrol_token(auto_approve=True)
        inv0 = a.sh("systemctl show -p InvocationID --value bitscan-agent")[1].strip()
        rc, out = a.sh("DEBIAN_FRONTEND=teletype dpkg-reconfigure bitscan-agent; echo rc=$?", stdin=f"{tok_r1}\n")
        asked = [q for q in ("Bitscan manager URL:", "Bitscan enrolment token:", "CA bundle for the manager", "Pin of the manager public key") if q in out]
        row("7", "route 1: dpkg-reconfigure asks only for the new token", "dpkg-reconfigure bitscan-agent (token typed)",
            "asks the enrolment token only; rc=0; token not echoed", f"asked {asked}; {out.strip().splitlines()[-1]}; echoed={tok_r1 in out}",
            asked == ["Bitscan enrolment token:"] and out.strip().endswith("rc=0") and tok_r1 not in out)
        dc = a.sh("printf 'GET bitscan/enrol_token\\n' | debconf-communicate bitscan-agent 2>/dev/null")[1].strip()
        inv1 = a.sh("systemctl show -p InvocationID --value bitscan-agent")[1].strip()
        yaml1 = a.sh("sha256sum /etc/bitscan/agent.yaml | cut -c1-16")[1].strip()
        row("7", "route 1: debconf cleared, agent restarted, agent.yaml unchanged", "debconf-communicate; systemctl show; sha256sum",
            "'0'; new InvocationID; same agent.yaml", f"db_get={dc!r}; restarted={inv1 != inv0}; yaml_same={yaml1 == bl[0]}",
            dc == "0" and inv1 != inv0 and yaml1 == bl[0])
        rr = m.request_for(a.hostname)
        row("7", "route 1: a re-enrolment onto the same machine id is held, even with auto_approve", "GET /enrollment-requests",
            "pending, kind not new", json.dumps({"kind": rr.get("kind"), "agent_id": (rr.get("agent_id") or "")[:8]}) if rr else "none",
            bool(rr) and rr.get("kind") != "new")
        st, _ = m.call("POST", f"{V1}/enrollment-requests/{rr['request_id']}/approve") if rr else (0, None)
        ok = wait(lambda: "enroll.token" not in a.sh("ls /var/lib/bitscan-agent")[1] and a.sh("cat /var/lib/bitscan-agent/token")[1].strip() != old_token, 300, 3)
        new_id = a.sh("cat /var/lib/bitscan-agent/agent_id")[1].strip()
        hist = m.agent(a_id)
        row("7", "route 1: on approval the host keeps its history", "approve; GET /agents/{id}", "same agent_id, os_info and snapshot kept",
            json.dumps({"approve": st, "same_id": new_id == a_id, "snapshot": bool(hist.get("last_snapshot"))}), st == 200 and bool(ok) and new_id == a_id and bool(hist.get("last_snapshot")))
        st_old, out_old = m.call("POST", f"{V1}/agent/{a_id}/heartbeat", {}, token=old_token)
        row("7", "route 1: the old token is revoked", "a call with the old bsa_ token", "401", f"{st_old} {out_old.get('type') if isinstance(out_old, dict) else ''}", st_old == 401)
        # route 2: install.env with only ENROL_TOKEN
        m.call("POST", f"{V1}/agents/{a_id}/revoke")
        wait(lambda: a.journal().count("the host must be re-enrolled") >= 2, 300, 5)
        tok_r2 = m.enrol_token()
        rc, out = a.sh("install -m 0600 /dev/null /etc/bitscan/install.env && cat > /etc/bitscan/install.env && dpkg-reconfigure bitscan-agent </dev/null; echo rc=$?; ls /etc/bitscan/install.env 2>&1", stdin=f"ENROL_TOKEN={tok_r2}\n")
        row("7", "route 2: install.env with only ENROL_TOKEN, then dpkg-reconfigure", "install -m 0600 …; dpkg-reconfigure bitscan-agent",
            "rc=0; no question; install.env deleted", out.strip().replace("\n", " ")[-160:], "rc=0" in out and "No such file" in out and "Bitscan enrolment token:" not in out)
        rr2 = m.request_for(a.hostname)
        st, _ = m.call("POST", f"{V1}/enrollment-requests/{rr2['request_id']}/approve") if rr2 else (0, None)
        ok = wait(lambda: "enroll.token" not in a.sh("ls /var/lib/bitscan-agent")[1], 300, 3)
        row("7", "route 2: held, approved, enrolled again", "GET /enrollment-requests; approve", "kind not new; 200; enroll.token gone",
            json.dumps({"kind": rr2.get("kind") if rr2 else None, "approve": st, "enrolled": bool(ok)}), bool(rr2) and rr2.get("kind") != "new" and st == 200 and bool(ok))
        rc, out = a.sh("printf 'ENROL_TOKEN=x\\nCA_FILE=\\n' > /etc/bitscan/install.env && chmod 600 /etc/bitscan/install.env && dpkg-reconfigure bitscan-agent </dev/null 2>&1; echo rc=$?; rm -f /etc/bitscan/install.env")
        row("7", "route 2: any other key is refused on an installed host", "install.env with CA_FILE; dpkg-reconfigure",
            "'…may hold only ENROL_TOKEN once agent.yaml exists', rc non-zero", out.strip().replace("\n", " ")[-200:],
            "may hold only ENROL_TOKEN once agent.yaml exists" in out and "rc=0" not in out)
        a.sh("dpkg --configure -a </dev/null >/dev/null 2>&1; true")
        # CA file / pin change by editing agent.yaml
        hb0 = m.agent(a_id).get("last_heartbeat_at")
        wrong = "0" * 64
        rc, out = a.sh(f"sed 's/^manager_spki_sha256: .*/manager_spki_sha256: \\x27{wrong}\\x27/' /etc/bitscan/agent.yaml > /tmp/y && cat /tmp/y > /etc/bitscan/agent.yaml && stat -c '%U:%G %a' /etc/bitscan/agent.yaml && systemctl restart bitscan-agent")
        ok = wait(lambda: "failed verification" in a.journal(), 120, 3)
        row("7", "changing the pin in agent.yaml (as root, owner kept) takes effect after a restart", "edit agent.yaml; systemctl restart bitscan-agent",
            "root:bitscan 640; a wrong pin is refused ('…failed verification…')", f"{out.strip()}; refused={bool(ok)}", out.strip() == "root:bitscan 640" and bool(ok))
        rc, out = a.sh(f"sed 's/^manager_spki_sha256: .*/manager_spki_sha256: \\x27{pin}\\x27/' /etc/bitscan/agent.yaml > /tmp/y && cat /tmp/y > /etc/bitscan/agent.yaml && systemctl restart bitscan-agent")
        ok = wait(lambda: m.agent(a_id).get("last_heartbeat_at") != hb0, 420, 5)
        row("7", "the right pin restored: the agent reports again", "edit agent.yaml; systemctl restart bitscan-agent", "a newer heartbeat", str(m.agent(a_id).get("last_heartbeat_at")), bool(ok))

        # ------------------------------------------------ 8. Remove and purge (host a)
        rc, out = a.sh("apt remove -y bitscan-agent </dev/null >/dev/null 2>&1; echo rc=$?; systemctl is-active bitscan-agent.service bitscan-runner.socket; systemctl is-enabled bitscan-agent.service bitscan-runner.socket 2>&1; ls /etc/bitscan /var/lib/bitscan-agent | tr '\\n' ' '")
        row("8", "remove: units stopped and disabled, configuration and state kept", "apt remove bitscan-agent",
            "rc=0; inactive; not enabled; agent.yaml, ca.pem, agent_id, token kept", out.strip().replace("\n", " "),
            "rc=0" in out and out.count("inactive") == 2 and "agent.yaml" in out and "agent_id" in out and "\nenabled" not in out)
        rc, out = a.sh("apt purge -y bitscan-agent </dev/null >/dev/null 2>&1; echo rc=$?; ls -A /etc/bitscan 2>&1 | tr '\\n' ' '; ls /var/lib/bitscan-agent 2>&1; getent passwd bitscan bitscan-runner | cut -d: -f1 | tr '\\n' ' '; printf 'GET bitscan/manager_url\\n' | debconf-communicate bitscan-agent 2>/dev/null")
        row("8", "purge: state and agent.yaml gone; ca.pem and /etc/bitscan kept; users kept; debconf answers gone", "apt purge bitscan-agent",
            "rc=0; /etc/bitscan holds only ca.pem; no /var/lib/bitscan-agent; users kept; debconf 10 (unknown)", out.strip().replace("\n", " "),
            "rc=0" in out and "ca.pem" in out and "agent.yaml" not in out and "No such file" in out and "bitscan bitscan-runner" in out and not out.strip().endswith("0 " + url))
        st, out = m.call("GET", f"{V1}/agents/{a_id}")
        row("8", "removing the package does not deregister the host", "GET /agents/{id}", "200, host still listed (goes offline after 30 min)",
            f"{st} {out.get('status') if isinstance(out, dict) else ''}", st == 200)

        # tokens never in a journal
        leaks = [hh.hostname for hh in hosts if hh.name in subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
                 and any(t in hh.journal() for t in SECRETS)]
        row("all", "no enrolment or agent token in any agent journal", "journalctl -u bitscan-agent", "none", str(leaks), not leaks)
    finally:
        for hh in hosts:
            hh.remove()
        subprocess.run(["docker", "rmi", "-f", "m4b-walk-tmpl:latest", "m4b-walk-tmpld:latest"], capture_output=True)


def clone_section(m: Manager, url: str, debname: str, host: Callable[..., Host]) -> None:  # noqa: PLR0915
    """Runbook section 1, "Cloned hosts": the commands are read from the runbook."""
    regen = runbook_clone_commands()
    row("1", "cloned-host commands read from the runbook", "-", "a non-empty sh block", regen, bool(regen))
    # ------------------------------------------------ 1. Cloned hosts
    # template images: "tmpl" with the stock Ubuntu layout (/var/lib/dbus/
    # machine-id a link to /etc/machine-id), "tmpld" with a separate D-Bus
    # copy of the id (as an image built with dbus installed offline has)
    for tname, kw in (("tmpl", {}), ("tmpld", {"dbus_copy": True})):
        t = Host(tname, **kw)
        subprocess.run(["docker", "commit", t.name, f"m4b-walk-{tname}:latest"], check=True, capture_output=True)
        t.remove()
    clones = []
    for n in ("g1", "g2", "g3"):
        g = host(n, "m4b-walk-tmpl:latest", keep_id=True)
        clones.append(g)
    mid = [g.sh("cat /etc/machine-id")[1].strip() for g in clones]
    layout = clones[0].sh("ls -l /var/lib/dbus/machine-id | sed 's/.* \\/var/\\/var/'")[1].strip()
    row("1", "clones share /etc/machine-id", "cat /etc/machine-id", "g1 == g2 == g3", " ".join(x[:8] for x in mid) + f"; {layout}", len(set(mid)) == 1)
    g1, g2, g3 = clones
    def regenerate(g: Host, label: str, old: str) -> str:
        rc, out = g.sh("set -e\n" + regen)
        lines = out.strip().splitlines()
        new = lines[-1] if lines else ""
        link = g.sh("readlink /var/lib/dbus/machine-id; stat -c %F /var/lib/dbus/machine-id")[1].split()
        row("1", f"regenerate the machine id on a clone ({label})", regen.replace("\n", "; "),
            "the runbook's first cat shows the old id; a new 32-hex id; /var/lib/dbus/machine-id a link to /etc/machine-id",
            f"rc={rc}; printed {[x[:8] for x in lines if re.fullmatch(r'[0-9a-f]{32}', x)]}; {' | '.join(x for x in lines if not re.fullmatch(r'[0-9a-f]{32}', x))}; was {old[:8]}…; dbus: {' '.join(link)}",
            rc == 0 and bool(lines) and lines[0] == old and re.fullmatch(r"[0-9a-f]{32}", new) is not None and new != old
            and link[:1] == ["/etc/machine-id"] and "symbolic" in " ".join(link))
        return new

    regenerate(g3, "stock layout", mid[0])
    g4 = host("g4", "m4b-walk-tmpld:latest", keep_id=True)
    old4 = g4.sh("cat /etc/machine-id")[1].strip()
    regenerate(g4, "image with a separate /var/lib/dbus/machine-id copy", old4)
    g4.remove()
    for g in clones:
        t = m.enrol_token()
        g.sh(f"printf 'bitscan-agent bitscan/manager_url string {url}\\nbitscan-agent bitscan/enrol_token password {t}\\nbitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem\\n' | debconf-set-selections && cd /root && install -d -m 0755 /etc/bitscan && install -m 0644 manager-ca.pem /etc/bitscan/ca.pem && apt install ./{debname} </dev/null >/dev/null 2>&1")
        if g is g1:
            r1 = m.request_for(g1.hostname)
            if r1:
                m.call("POST", f"{V1}/enrollment-requests/{r1['request_id']}/approve")
            wait(lambda: "agent_id" in g1.sh("ls /var/lib/bitscan-agent")[1], 300, 3)
    g1_id = g1.sh("cat /var/lib/bitscan-agent/agent_id")[1].strip()
    r2 = m.request_for(g2.hostname)
    r3 = m.request_for(g3.hostname)
    row("1", "a clone without a new machine id appears as a re-enrolment of the first", "GET /enrollment-requests",
        f"walk-g2 kind reenrol..., matching {g1_id[:8]}",
        json.dumps({"kind": r2.get("kind"), "agent_id": (r2.get("agent_id") or "")[:8], "matches": [x.get("hostname") if isinstance(x, dict) else x for x in r2.get("matches", [])]}) if r2 else "none",
        bool(r2) and r2.get("kind") != "new" and (r2.get("agent_id") == g1_id or any(g1_id in json.dumps(x) for x in r2.get("matches", []))))
    row("1", "a clone with a regenerated machine id is a new host", "GET /enrollment-requests", "walk-g3 kind new, no match",
        json.dumps({"kind": r3.get("kind"), "matches": r3.get("matches")}) if r3 else "none",
        bool(r3) and r3.get("kind") == "new" and not any(mid[0] in json.dumps(x) for x in r3.get("matches", [])))
    for g in clones:
        g.remove()



RUNBOOK = Path(__file__).resolve().parents[1] / "deploy" / "runbooks" / "agent-install.md"
ONLY_CLONES = False


def runbook_clone_commands() -> str:
    """The first ```sh block after "**Cloned hosts:**", as a script: one
    command per line (inline comments kept), every `sudo ` dropped (the walk
    runs as root)."""
    text = RUNBOOK.read_text(encoding="utf-8")
    after = text.split("**Cloned hosts:**", 1)[1]
    block = after.split("```sh", 1)[1].split("```", 1)[0]
    cmds = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return "\n".join(re.sub(r"\bsudo\s+", "", c) for c in cmds)


def main() -> int:
    global RUNBOOK, ONLY_CLONES  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--deb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--runbook", type=Path, default=RUNBOOK)
    ap.add_argument("--only-clones", action="store_true", help="re-run only runbook section 1, Cloned hosts")
    args = ap.parse_args()
    RUNBOOK, ONLY_CLONES = args.runbook.resolve(), args.only_clones
    work = Path(tempfile.mkdtemp(prefix="m4b-walk."))
    try:
        walk(args.deb, work)
    except Exception as exc:  # recorded, then the run fails
        row("harness", "walk aborted", "-", "no exception", f"{type(exc).__name__}: {exc}", False)
    finally:
        args.out.write_text("".join(json.dumps(asdict(r)) + "\n" for r in ROWS))
        shutil.rmtree(work, ignore_errors=True)
    bad = [r for r in ROWS if not r.ok]
    print(f"{'OK' if not bad else 'FAIL'} {len(ROWS) - len(bad)}/{len(ROWS)} steps as written", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
