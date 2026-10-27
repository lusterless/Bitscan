"""M6 end-to-end on the two Hyper-V VMs (TP-M6-10..13: CHK-M6-200..213, -260..265,
-280..286, -300; REQ-146..149; work/plans/M6-e2e.md sections 3 to 5, with the
environment ruling of decisions 2026-10-26).

Runs in Git Bash on Windows with the Windows Python (`python -I`): Hyper-V and
the VMs are reached only from Windows (e2e/m6/vm.sh: PowerShell, ssh, scp);
the manager host is a container in WSL (`wsl.exe ... docker ...`).

Network path (decisions 2026-10-26): VMs map bitscan-mgr.test -> MGR_IP
(the Default Switch address); the Windows portproxy forwards MGR_IP:8443 to
127.0.0.1:18443; the manager-host container publishes -p 127.0.0.1:18443:8443.
Nothing in WSL binds 8443. Agents use https://bitscan-mgr.test:8443.

The manager host is installed by tester-m6b's runbook walk, unchanged
(e2e/m6/manager_walk.py --keep, image m6b-mgrhost from
e2e/m6/manager-host.Dockerfile). This script then re-creates that container
with the port published (the walk publishes none): `docker commit` of the
walked host, `docker run -p 127.0.0.1:18443:8443` of the commit, so the
installed files are exactly what the walk produced. The walk's PKI leaf only
covers DNS:bitscan-mgr.test, which is the name the agents use; the IP SAN is
needed only for the W0 listener checks.

One VM at a time (user ruling 2026-10-26; plan section 4 as the planner updated
it): three sessions, in this order, each its own invocation. Facts that later
sessions need (agent ids, IPs, times, the VM-side dpkg facts) are kept in
DIR/state.json (no secrets). Before each Start-VM: >= 3000 MB free on Windows
and no other test VM running.

  python -I e2e/m6/e2e_vms.py --work DIR --session u2404-1 [--dry-run]
  python -I e2e/m6/e2e_vms.py --work DIR --session u2204
  python -I e2e/m6/e2e_vms.py --work DIR --session u2404-2

Every check is one row in DIR/rows.jsonl and on stdout (PASS/FAIL/NOT RUN).
Secrets (passwords, tokens, session) stay in 0600 files under DIR/secrets and
inside the manager host; rows mask every bs?_ token.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

TREE = Path(__file__).resolve().parents[2]
VM_SH = TREE / "e2e" / "m6" / "vm.sh"
# --exec, not --: with "--" wsl.exe runs the command line through the distro's default shell first,
# which expands $1, $VAR and $(...) before bash or docker see them (the CHK-M6-201 leaf and the
# CHK-M6-265 viewer-body failures of session 1 attempts 2-5 were that, a harness bug)
WSL = ["wsl.exe", "-d", "Ubuntu-24.04", "-u", "root", "--exec"]
CT = "m6-e2e-mgr"            # the published manager host (commit of the walked m6b-host)
WALKED = "m6b-host"          # the container manager_walk.py --keep leaves
REL_WSL = "/root/m6tb/relout"  # the local release-workflow output (G49), SHA256SUMS included
DEB = "bitscan-agent_0.1.0-1_amd64.deb"
DEB_SHA = "3b5c98a0866bda0330949eaed4007a336b1f27589f9b48c9ae7f4334280033db"
URL_IN_CT = "https://bitscan-mgr.test:8443"
AGENT_URL = "https://bitscan-mgr.test:8443"
# The Hyper-V Default Switch address = the portproxy listen address = the VMs' bitscan-mgr.test = the
# leaf's IP SAN. One setting: Windows moved it from 172.31.0.1 to 172.26.240.1 at the 21:00 reboot
# (main, 2026-10-26; the user moves the portproxy and the firewall rule, an admin step).
MGR_IP = "172.26.240.1"
SWITCH = f"{MGR_IP}/20"
MGR_NET = ipaddress.ip_network(SWITCH, strict=False)  # the VMs' addresses come from this /20
NEED_MB = 2000  # user decision 2026-10-26: one 1 GB VM at a time, >= 2000 MB free before each Start-VM
VM_MEM = "1GB"  # Set-VMMemory -StartupBytes after every restore (the checkpoint brings back 2 GB)
VMS = {
    "u2204": ("bitscan-u2204", "00-15-5D-0B-22-04", "22.04"),
    "u2404": ("bitscan-u2404", "00-15-5D-0B-24-04", "24.04"),
}
TOKEN = re.compile(r"\bbs[uaek]_[A-Za-z0-9_-]{8,}")
# the final release folder (CHK-M6-319-final, tester-m6c): its .deb is the TASK-138 RC (`--rel final`)
REL_FINAL_WSL = "/root/m6tc/relout-final"
DEB_SHA_FINAL = "d98ef8c3978e99e65f27074be8613c04fcaddba6f774efece30a4f7aefe0f3bf"
# bash -c LEAF_SH leaf PKI OUT: a manager leaf with the ruling's SAN, signed by the walk's CA
LEAF_SH = r"""set -e; umask 077; pki=$1; d=$2; mkdir -p "$d"; cd "$d"
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj /CN=bitscan-mgr.test -keyout leaf.key -out leaf.csr 2>/dev/null
printf 'subjectAltName=DNS:bitscan-mgr.test,IP:@MGR_IP@\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth\n' > leaf.ext
openssl x509 -req -in leaf.csr -CA "$pki/ca.pem" -CAkey "$pki/ca.key" -CAcreateserial -days 7 -extfile leaf.ext -out leaf.crt 2>/dev/null
rm -f leaf.csr leaf.ext; chmod 644 leaf.crt; openssl x509 -in leaf.crt -noout -ext subjectAltName | tail -1""".replace("@MGR_IP@", MGR_IP)
# runs in the manager host as root: session token file, viewer password and body (0600 files only)
HELPER = r"""
import json, os, secrets
os.umask(0o077)
s = json.load(open("/root/e2e/session.json"))
open("/root/e2e/session.bsu", "w").write(s["token"] + "\n")
open("/root/e2e/viewer.json", "w").write(json.dumps({"username": "e2e-viewer", "password": secrets.token_urlsafe(24), "role": "viewer"}))
"""


# REQ-148 (6) check, run on the VM as the ssh user. grep reads the token from its own file (-f), so the
# token is on no command line: sudo logs every command line it runs to the journal, and the old form
# `sudo grep -rlF "$(sudo cat …/token)"` put the bsa_ there (W4's CHK-M6-286 FAIL, tokscan-findings.md).
# A missing or empty token file prints files=NOTOKEN, never a silent 0; ctl= counts the files under
# /var/lib/bitscan-agent that hold the token (at least the token file), so a pattern that matches
# nothing shows up as ctl=0.
MODES_SH = ("sudo sh -c \"stat -c '%U:%G %a %n' /etc/bitscan/agent.yaml /var/lib/bitscan-agent/*\" 2>&1; "
            "echo \"debconf=[$(echo 'GET bitscan/enrol_token' | sudo DEBIAN_FRONTEND=noninteractive debconf-communicate bitscan-agent 2>/dev/null)]\"; "
            "if sudo test -s /var/lib/bitscan-agent/token; then "
            "echo \"files=$(sudo grep -rlFf /var/lib/bitscan-agent/token /var/cache/debconf /etc 2>/dev/null | wc -l)\"; "
            "echo \"ctl=$(sudo grep -rlFf /var/lib/bitscan-agent/token /var/lib/bitscan-agent 2>/dev/null | wc -l)\"; "
            "else echo files=NOTOKEN; fi")
MODES_WANT = ("root:bitscan 640 /etc/bitscan/agent.yaml", "bitscan:bitscan 600 /var/lib/bitscan-agent/token",
              "bitscan:bitscan 644 /var/lib/bitscan-agent/agent_id")


def modes_ok(out: str) -> bool:
    # whole lines: as a substring, "... 600 /var/lib/bitscan-agent/token" also matched the token.json line
    lines = {ln.strip() for ln in out.split("\n")}
    return (all(w in lines for w in MODES_WANT) and "enroll.token" not in out
            and re.search(r"^debconf=\[0 ?\]$", out, re.M) is not None
            and re.search(r"^files=0$", out, re.M) is not None and re.search(r"^ctl=[1-9]\d*$", out, re.M) is not None)


def _in_switch_net(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in MGR_NET
    except ValueError:
        return False


def mask(text: str) -> str:
    return TOKEN.sub(lambda m: m.group(0)[:4] + "<masked>", text)


@dataclass
class Run:
    work: Path
    dry: bool
    rows: list[dict] = field(default_factory=list)
    walk_pki: str = "/root/m6t/w4walk/pki"
    ip: dict[str, str] = field(default_factory=dict)
    agent: dict[str, str] = field(default_factory=dict)  # vm -> agent_id
    state: dict = field(default_factory=dict)  # facts carried between sessions (no secrets)
    rel: str = REL_WSL       # WSL folder with the RC .deb and its release SHA256SUMS
    deb_sha: str = DEB_SHA   # the RC's SHA-256

    @property
    def wsl_work(self) -> str:
        """The work folder as WSL sees it (C:\\x\\y -> /mnt/c/x/y); files pass through it to docker cp."""
        p = str(self.work.resolve()).replace("\\", "/")
        m = re.match(r"^([A-Za-z]):/(.*)$", p)
        return f"/mnt/{m.group(1).lower()}/{m.group(2)}" if m else p

    def load(self) -> None:
        f = self.work / "state.json"
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            self.ip, self.agent, self.state = d.get("ip", {}), d.get("agent", {}), d.get("state", {})

    def save(self) -> None:
        if not self.dry:
            (self.work / "state.json").write_text(json.dumps({"ip": self.ip, "agent": self.agent, "state": self.state}, indent=1))

    def row(self, chk: str, vm: str, ok: bool | None, evidence: str) -> bool:
        res = "NOT RUN" if ok is None else ("PASS" if ok else "FAIL")
        r = {"chk": chk, "vm": vm, "result": res, "evidence": mask(evidence)[-1500:], "t": time.strftime("%H:%M:%S")}
        self.rows.append(r)
        with (self.work / "rows.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")
        print(f"{res} {chk} {vm} :: {r['evidence'][-300:]}", flush=True)
        return bool(ok)

    # ---------------------------------------------------------------- transports
    def sh(self, argv: list[str], stdin: str | None = None, timeout: int = 900) -> tuple[int, str]:
        if self.dry:
            print("DRY " + " ".join(shlex.quote(a) for a in argv)[:300])
            return 0, ""
        # bytes, not text mode: on Windows text mode turns "\n" into "\r\n" on the way into wsl.exe
        p = subprocess.run(argv, input=None if stdin is None else stdin.encode("utf-8"), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, env=dict(os.environ, MSYS_NO_PATHCONV="1"))
        return p.returncode, p.stdout.decode("utf-8", errors="replace").replace("\r", "")

    def vm(self, *args: str, timeout: int = 900) -> tuple[int, str]:
        return self.sh(["bash", str(VM_SH), *args], timeout=timeout)

    def on(self, vm: str, cmd: str, timeout: int = 900) -> tuple[int, str]:
        return self.vm("ssh", self.ip.get(vm, "0.0.0.0"), cmd, timeout=timeout)

    def props(self, vm: str, unit: str, *names: str) -> dict[str, str]:
        """`systemctl show -p A -p B UNIT` read as NAME=VALUE lines, so each value is taken by its
        property name: with `--value`, systemd prints the values in its own order (NRestarts before
        ActiveState), which the W4 CHK-M6-209 rows misread as a FAIL."""
        rc, out = self.on(vm, "systemctl show " + " ".join(f"-p {n}" for n in names) + f" {unit}")
        got = dict(ln.split("=", 1) for ln in out.strip().split("\n") if "=" in ln)
        return {n: got.get(n, "?") for n in names}

    def mgr(self, cmd: str, timeout: int = 600) -> tuple[int, str]:
        """A root shell in the manager host."""
        return self.sh(WSL + ["docker", "exec", "-i", CT, "bash", "-o", "pipefail", "-c", cmd], timeout=timeout)

    def api(self, method: str, path: str, body: object = None, token_file: str | None = None,
            machine_id: str | None = None) -> tuple[int, object]:
        """One call from inside the manager host through mgr_api.py (stdlib)."""
        args = ["python3.12", "-I", "/opt/m6b/mgr_api.py", "call", "--url", URL_IN_CT, "--ca", "/home/admin/rel/manager-ca.pem"]
        args += ["--token-file", token_file] if token_file else ["--state", "/home/admin/stage/session.json"]
        if machine_id:
            args += ["--machine-id", machine_id]
        if body is not None:
            args += ["--body", json.dumps(body)]
        args += [method, path]
        rc, out = self.mgr(" ".join(shlex.quote(a) for a in args))
        if self.dry:
            return 200, {}
        m = re.match(r"^(\d{3}) (.*)$", out.strip(), re.S)
        if not m:
            return 0, out
        try:
            return int(m.group(1)), json.loads(m.group(2))
        except ValueError:
            return int(m.group(1)), m.group(2)

    def audit(self, since_id: int = 0) -> list[dict]:
        """Audit entries newer than since_id, newest first (admin session)."""
        st, body = self.api("GET", "/api/v1/audit-log?limit=500")
        if self.dry or not isinstance(body, dict):
            return []
        return [e for e in body.get("items", []) if e["audit_id"] > since_id]

    def alerts(self, kind: str, since_id: int) -> list[dict]:
        return [e for e in self.audit(since_id) if isinstance(e.get("detail"), dict)
                and e["detail"].get("alert") is True and e["detail"].get("alert_kind") == kind]

    def metric(self, text_name: str) -> dict[str, float]:
        # curl with the header from a 0600 file (-H @file), so the token is on no command line
        rc, out = self.mgr("umask 077; printf 'Authorization: Bearer %s\\n' \"$(cat /root/e2e/viewer.bsk)\" > /root/e2e/viewer.hdr; "
                           f"curl -sS --cacert /home/admin/rel/manager-ca.pem -H @/root/e2e/viewer.hdr {URL_IN_CT}/api/v1/metrics")
        vals: dict[str, float] = {}
        for ln in out.split("\n"):
            m = re.match(rf"^{re.escape(text_name)}(\{{[^}}]*\}})?\s+([0-9.eE+-]+)$", ln.strip())
            if m:
                vals[m.group(1) or ""] = float(m.group(2))
        return vals

    def wait(self, what: str, fn, timeout: float, every: float = 10):  # type: ignore[no-untyped-def]
        if self.dry:
            print(f"DRY wait up to {timeout:.0f} s for {what}")
            return None
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = fn()
            if v:
                return v
            time.sleep(every)
        return None


# -------------------------------------------------------------------- preflight


def preflight(r: Run) -> bool:
    ok = True
    ok &= mem_ok(r, "host")
    rc, sw = r.vm("switch")
    ok &= r.row("CHK-M6-200", "host", None if r.dry else sw.strip() == SWITCH, f"Default Switch {sw.strip()} (want {SWITCH})")
    rc, pp = r.sh(["netsh.exe", "interface", "portproxy", "show", "v4tov4"])
    ok &= r.row("CHK-M6-200", "host", None if r.dry else bool(re.search(re.escape(MGR_IP) + r"\s+8443\s+127\.0\.0\.1\s+18443", pp)),
                f"portproxy {MGR_IP}:8443 -> 127.0.0.1:18443 present")
    if not r.state.get("mgr.up"):  # later sessions find the manager host's own 18443 publish
        rc, ss = r.sh(WSL + ["sh", "-c", "ss -ltnH 'sport = :8443' | wc -l; ss -ltnH 'sport = :18443' | wc -l"])
        ok &= r.row("CHK-M6-200", "wsl", None if r.dry else ss.split() == ["0", "0"], f"nothing in WSL on 8443 / 18443 before the start: {ss.split()}")
    else:
        rc, ins = r.sh(WSL + ["sh", "-c", f"docker inspect -f '{{{{.State.Running}}}}' {CT}; ss -ltnH 'sport = :8443' | wc -l"])
        ok &= r.row("CHK-M6-200", "wsl", None if r.dry else ins.split() == ["true", "0"], f"manager host {CT} still running, nothing on 8443: {ins.split()}")
    rc, sums = r.sh(WSL + ["sh", "-c", f"cd {r.rel} && sha256sum -c SHA256SUMS && sha256sum {DEB}"])
    ok &= r.row("CHK-M6-319", "wsl", None if r.dry else (rc == 0 and r.deb_sha in sums),
                f"RC files = the local release-workflow output {r.rel}; sha256sum -c SHA256SUMS rc {rc}; .deb {r.deb_sha[:16]}…")
    return ok or r.dry


# -------------------------------------------------------------------- manager host


def manager_up(r: Run) -> bool:
    """Commit the walked host and run it again with the port published."""
    rc, out = r.sh(WSL + ["sh", "-c", f"docker inspect -f '{{{{.State.Running}}}}' {WALKED}"])
    if not r.dry and out.strip() != "true":
        return r.row("CHK-M6-201", "mgr", False, f"{WALKED} not running; run manager_walk.py --keep first ({out.strip()})")
    cmds = [
        f"docker rm -f {CT} >/dev/null 2>&1; docker commit {WALKED} m6-e2e-mgr:walked >/dev/null",
        f"docker stop {WALKED} >/dev/null",
        f"docker run -d --name {CT} --hostname bitscan-mgr --privileged --cgroupns=private --tmpfs /run --tmpfs /run/lock "
        "--add-host bitscan-mgr.test:127.0.0.1 --add-host openbao.test:127.0.0.1 --add-host audit.test:127.0.0.1 "
        "--memory 1500m -p 127.0.0.1:18443:8443 m6-e2e-mgr:walked >/dev/null",
    ]
    for c in cmds:
        rc, out = r.sh(WSL + ["sh", "-c", c], timeout=600)
        if rc != 0 and not r.dry:
            return r.row("CHK-M6-201", "mgr", False, f"{c[:80]}: {out}")
    # Environment ruling: the served certificate carries DNS:bitscan-mgr.test and IP:MGR_IP.
    # The walk's leaf has the name only, so a new leaf from the walk's CA replaces it the way
    # manager-operations.md section 2 says (cp onto the existing 0600 files, restart).
    wsl_w4 = r.wsl_work
    # wsl.exe drops the positional arguments after `bash -c SCRIPT`, and in a detached run it does not
    # forward piped stdin; so the script goes through a file in the work folder (no secret in it)
    leaf_sh = r.work / "leaf.sh"
    if not r.dry:
        leaf_sh.write_bytes((f"set -- {shlex.quote(r.walk_pki)} {shlex.quote(wsl_w4 + '/secrets')}\n" + LEAF_SH + "\n").encode())
    rc, out = r.sh(WSL + ["bash", wsl_w4 + "/leaf.sh"], timeout=120)
    r.row("CHK-M6-201", "mgr", None if r.dry else (rc == 0 and f"IP Address:{MGR_IP}" in out), f"new leaf from the walk's CA: rc {rc}: {out.strip()[-300:]!r}")
    r.sh(WSL + ["sh", "-c", f"docker cp {wsl_w4}/secrets/leaf.crt {CT}:/root/e2e-leaf.crt && docker cp {wsl_w4}/secrets/leaf.key {CT}:/root/e2e-leaf.key; "
                f"rm -f {wsl_w4}/secrets/leaf.key"])
    r.mgr("cp /root/e2e-leaf.crt /etc/bitscan/secrets/tls.crt && cp /root/e2e-leaf.key /etc/bitscan/secrets/tls.key && "
          "rm -f /root/e2e-leaf.crt /root/e2e-leaf.key && systemctl restart bitscan-manager")
    # files for the VMs: the RC .deb and SHA256SUMS of the local release run, the manager CA, and a second CA (REQ-148 (2))
    r.sh(WSL + ["sh", "-c", f"cp {r.rel}/{DEB} {r.rel}/SHA256SUMS {wsl_w4}/ &&docker cp {CT}:/home/admin/rel/manager-ca.pem {wsl_w4}/manager-ca.pem && "
                "openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 2 -subj '/CN=m6 other CA' "
                f"-keyout /tmp/m6-other.key -out {wsl_w4}/other-ca.pem >/dev/null 2>&1; rm -f /tmp/m6-other.key"])
    # the walk started the doubles as a transient unit, which does not survive the commit: start them again
    # with the walk's own command (manager_walk.py, CHK-M6-050)
    r.mgr("systemctl is-active -q m6b-doubles || systemd-run --unit m6b-doubles -p WorkingDirectory=/opt/m6b /usr/bin/python3.12 -I "
          "/opt/m6b/doubles.py --dir /opt/m6b --cert /opt/m6b/doubles.crt --key /opt/m6b/doubles.key; sleep 2; systemctl is-active m6b-doubles")
    got = r.wait("the published manager /readyz", lambda: (r.mgr(
                 "curl -sS --cacert /home/admin/rel/manager-ca.pem https://bitscan-mgr.test:8443/readyz")[1].strip()
                 .endswith('{"status":"ok"}')), 180, 5)
    rc, win = r.sh(["curl.exe", "-sS", "--ssl-no-revoke", "--noproxy", "*", "--max-time", "10", "--cacert",
                    str(r.work / "manager-ca.pem"), "--resolve", f"bitscan-mgr.test:8443:{MGR_IP}", "https://bitscan-mgr.test:8443/readyz"])
    return r.row("CHK-M6-201", "mgr", None if r.dry else bool(got) and win.strip().endswith('{"status":"ok"}'),
                 f"manager host {CT} -p 127.0.0.1:18443:8443; /readyz inside ok={bool(got)}; from Windows via the portproxy: {win.strip()[:80]}")


def tokens(r: Run) -> None:
    """Admin TOTP session (from the walk), viewer and admin bsk_, one single-use bse_ per VM."""
    r.mgr("install -d -m 0700 /root/e2e && cp /home/admin/stage/session.json /root/e2e/session.json && chmod 600 /root/e2e/session.json")
    st, _ = r.api("GET", "/api/v1/settings")
    r.row("CHK-M6-204", "mgr", None if r.dry else st == 200, f"the walk's admin TOTP session still valid: GET /settings {st}")
    # the helper (no secret in it) goes through a file, not stdin (see manager_up)
    if not r.dry:
        (r.work / "helper.py").write_bytes(HELPER.encode())
    r.sh(WSL + ["sh", "-c", f"docker cp {r.wsl_work}/helper.py {CT}:/root/e2e/helper.py"])
    r.mgr("chmod 600 /root/e2e/helper.py && cd /root/e2e && umask 077 && python3.12 -I /root/e2e/helper.py")
    # the body file is read by the shell inside the container; it never reaches a host command line
    rc, out = r.mgr(f"cd /root/e2e && python3.12 -I /opt/m6b/mgr_api.py call --url {URL_IN_CT} --ca /home/admin/rel/manager-ca.pem "
                    "--state /root/e2e/session.json --body \"$(cat viewer.json)\" POST /api/v1/users; rm -f viewer.json; "
                    "umask 077; bitscan-manager users create-api-token e2e-viewer --name e2e-metrics > viewer.bsk && "
                    "bitscan-manager users create-api-token alice --name e2e-refusals > admin.bsk && echo TOKENS-OK")
    r.row("CHK-M6-265", "mgr", None if r.dry else ("TOKENS-OK" in out and out.startswith("201")),
          f"viewer user (TOTP session) and two bsk_ (server CLI, as root): {out[:120]}")
    for vm in VMS:
        new_bse(r, f"/root/e2e/{vm}.bse")


def new_bse(r: Run, path: str, hours: int = 24) -> None:
    """One single-use bse_ (no CIDRs, no auto-approve), saved 0600 inside the manager host."""
    body = json.dumps({"max_uses": 1, "expires_in_hours": hours})
    r.mgr(f"umask 077; python3.12 -I /opt/m6b/mgr_api.py call --url {URL_IN_CT} --ca /home/admin/rel/manager-ca.pem "
          f"--state /root/e2e/session.json --save-token {path} --body {shlex.quote(body)} POST /api/v1/enrollment-tokens >/dev/null")


# -------------------------------------------------------------------- phase A


def mem_ok(r: Run, vm: str) -> bool:
    """User ruling: >= 3000 MB free for one 2 GB VM, re-checked before each Start-VM."""
    # Free memory dips for a moment right after a container start or commit; read three times 20 s
    # apart (one minute, no action in between) and judge the last reading. No cache drop, no setting.
    reads: list[str] = []
    for i in range(3):
        rc, mem = r.vm("mem")
        reads.append(mem.strip())
        if i < 2 and not r.dry:
            time.sleep(20)
    last = reads[-1]
    return r.row("CHK-M6-200", vm, None if r.dry else (last.isdigit() and int(last) >= NEED_MB),
                 f"before Start-VM: Windows free physical memory {' / '.join(reads)} MB over 40 s, judged on the last "
                 f"(need >= {NEED_MB} for one 1 GB VM)") or r.dry


def vm_start(r: Run, vm: str, restore: bool, allow_running: str | None = None) -> bool:
    name, mac, _ = VMS[vm]
    others = [n for k, (n, _, _) in VMS.items() if k != vm and n != allow_running]
    if others:
        rc, st = r.sh(["powershell.exe", "-NoProfile", "-Command", "(Get-VM " + ",".join(others) + ").State"])
        if not r.dry and "Running" in st:
            return r.row("CHK-M6-200", vm, False, f"another VM is running ({st.strip()}): not allowed here")
    if not mem_ok(r, vm):
        return False
    if restore:
        r.vm("restore", name)
        r.sh(["powershell.exe", "-NoProfile", "-Command", f"Set-VMMemory -VMName {name} -DynamicMemoryEnabled $false -StartupBytes {VM_MEM}"])
    rc, cfg = r.sh(["powershell.exe", "-NoProfile", "-Command",
                    f"$m = Get-VMMemory -VMName {name}; '' + [int]($m.Startup / 1MB) + ' MB dynamic=' + $m.DynamicMemoryEnabled"])
    if not r.row("CHK-M6-200", vm, None if r.dry else cfg.strip().startswith("1024 MB dynamic=False"),
                 f"VM memory before Start-VM: {cfg.strip()} (user decision: 1 GB fixed)") and not r.dry:
        return False
    rc, ip = r.vm("start", name, mac, timeout=420)
    ok = rc == 0 and _in_switch_net(ip.strip())
    if r.dry:
        ip, ok = str(MGR_NET.network_address + 250), True
    r.ip[vm] = ip.strip()
    r.state[f"{vm}.up"] = ok
    r.row("CHK-M6-200", vm, None if r.dry else ok, f"{'restored clean, ' if restore else 'same disk (no restore), '}started, IP {ip.strip()}")
    r.save()
    if ok:
        r.vm("hosts", r.ip[vm], MGR_IP)  # the IP may differ from session 1; the hosts line is rewritten either way
    return ok


def vm_prepare(r: Run, vm: str) -> None:
    name, mac, ver = VMS[vm]
    # NTP needs a moment after boot (the W0 check waited up to 120 s the same way)
    rc, info = r.on(vm, 'cloud-init status --wait >/dev/null 2>&1; cloud-init status | tr "\\n" " "; stat -fc %T /sys/fs/cgroup; '
                    'for i in $(seq 1 24); do s=$(timedatectl show -p NTPSynchronized --value); [ "$s" = yes ] && break; sleep 5; done; echo $s; '
                    '. /etc/os-release; echo "$VERSION"; dpkg-query -W "bitscan*" 2>/dev/null | wc -l')
    r.row("CHK-M6-201", vm, None if r.dry else ("done" in info and "cgroup2fs" in info and "\nyes\n" in info and f"{ver}." in info
          and info.strip().endswith("0")), f"release, cgroup v2, NTP, no Bitscan package: {info!r}")
    r.vm("hosts", r.ip[vm], MGR_IP)
    rc, w0 = r.on(vm, "sudo install -d -m 0755 /etc/bitscan; true")
    for src in (r.work / "manager-ca.pem", r.work / DEB, r.work / "SHA256SUMS", TREE / "e2e" / "m6" / "idle_cost.sh"):
        r.vm("put", r.ip[vm], str(src), f"/tmp/{src.name}")
    r.on(vm, "sudo install -m 0644 /tmp/manager-ca.pem /etc/bitscan/ca.pem; mkdir -p ~/rel; mv /tmp/" + DEB + " /tmp/SHA256SUMS /tmp/idle_cost.sh ~/rel/")
    rc, out = r.on(vm, "curl -sS --max-time 10 --cacert /etc/bitscan/ca.pem https://bitscan-mgr.test:8443/readyz")
    r.row("CHK-M6-200", vm, None if r.dry else out.strip().endswith('{"status":"ok"}'), f"W0 quick re-check: the manager's /readyz from the VM by name: {out.strip()[:80]}")


def install_agent(r: Run, vm: str) -> None:
    rc, out = r.on(vm, "cd ~/rel && sha256sum -c --ignore-missing SHA256SUMS; echo rc=$?")
    r.row("CHK-M6-202", vm, None if r.dry else (f"{DEB}: OK" in out and "rc=0" in out), f"agent runbook §2 as written: {out.strip()}")
    rc, out = r.on(vm, f"cd ~/rel && cp {DEB} /tmp/x.deb && printf 'X' | dd of=/tmp/x.deb bs=1 seek=4096 conv=notrunc status=none && "
                   f"mkdir -p /tmp/bad && mv /tmp/x.deb /tmp/bad/{DEB} && cp SHA256SUMS /tmp/bad/ && cd /tmp/bad && sha256sum -c --ignore-missing SHA256SUMS; echo rc=$?; rm -rf /tmp/bad")
    r.row("CHK-M6-202", vm, None if r.dry else ("FAILED" in out and "rc=1" in out), f"one byte changed: {out.strip()}")
    # the bse_ goes VM-ward through a 0600 file, never a command line
    tok_local = r.work / "secrets" / f"{vm}.bse"
    r.sh(WSL + ["sh", "-c", f"umask 077; docker cp {CT}:/root/e2e/{vm}.bse /tmp/m6e2e-{vm}.bse && "
                f"cat /tmp/m6e2e-{vm}.bse > {r.wsl_work}/secrets/{vm}.bse;rm -f /tmp/m6e2e-{vm}.bse"])
    pin = ""
    if vm == "u2404":  # runbook §1: the pin is computed on the manager host from the served certificate
        rc, pin = r.mgr("openssl x509 -in /etc/bitscan/secrets/tls.crt -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1")
        pin = pin.strip()
        (r.work / "pin.txt").write_text(pin + "\n")
    lines = [f"bitscan-agent bitscan/manager_url string {AGENT_URL}",
             "bitscan-agent bitscan/enrol_token password " + (tok_local.read_text().strip() if tok_local.exists() else "bse_DRYRUN"),
             "bitscan-agent bitscan/ca_file string /etc/bitscan/ca.pem"]
    if pin:
        lines.append(f"bitscan-agent bitscan/manager_spki_sha256 string {pin}")
    pre = r.work / "secrets" / f"{vm}.preseed"
    if not r.dry:
        fd = os.open(pre, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
    # the copy lands in bstester's 0700 home (scp keeps the 0600 source mode), then goes into the
    # root-only preseed file the runbook creates; it is never in /tmp or on a command line
    r.on(vm, "install -d -m 0700 ~/in")
    r.vm("put", r.ip[vm], str(pre), "in/bitscan.preseed")
    # runbook §3a: root-only preseed, debconf-set-selections, apt install, delete
    rc, out = r.on(vm, "sudo install -m 0600 /dev/null /root/bitscan.preseed && sudo sh -c 'cat ~bstester/in/bitscan.preseed > /root/bitscan.preseed' && "
                   "rm -f ~/in/bitscan.preseed && sudo debconf-set-selections /root/bitscan.preseed && "
                   f"cd ~/rel && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ./{DEB} >/tmp/apt.log 2>&1; echo rc=$?; "
                   "sudo rm -f /root/bitscan.preseed; test -e /root/bitscan.preseed && echo PRESEED-LEFT; tail -2 /tmp/apt.log", timeout=900)
    if not r.dry:
        pre.unlink(missing_ok=True)
        tok_local.unlink(missing_ok=True)
    r.row("CHK-M6-203", vm, None if r.dry else ("rc=0" in out and "PRESEED-LEFT" not in out),
          f"preseeded install ({'ca_file + pin' if pin else 'ca_file only'}): {out.strip()[-200:]}")
    rc, out = r.on(vm, "for u in bitscan-agent.service bitscan-runner.socket bitscan-runner.service bitscan-capread.socket bitscan-capread.service; do "
                   "echo \"$u $(systemctl is-enabled $u 2>/dev/null) $(systemctl is-active $u 2>/dev/null)\"; done")
    want = {"bitscan-agent.service": ("enabled", "active"), "bitscan-runner.socket": ("enabled", "active")}
    states = {ln.split()[0]: ln.split()[1:] for ln in out.strip().split("\n") if ln.strip()}
    good = (all(tuple(states.get(u, [])) == w for u, w in want.items())
            and all(states.get(u, ["x", "x"])[0] != "enabled" and states.get(u, ["x", "x"])[1] != "active"
                    for u in ("bitscan-runner.service", "bitscan-capread.socket", "bitscan-capread.service")))
    r.row("CHK-M6-203", vm, None if r.dry else good, f"unit states: {states}")
    # the files appear after the agent's first enrolment call (agent runbook section 4)
    r.wait(f"{vm} agent_id and token written", lambda: "token" in r.on(vm, "sudo ls /var/lib/bitscan-agent")[1], 120, 5)
    # the glob must expand as root: /var/lib/bitscan-agent is 0700 bitscan (the ssh user can't list it)
    rc, out = r.on(vm, MODES_SH)
    r.row("CHK-M6-285", vm, None if r.dry else modes_ok(out),
          f"REQ-148 (6) modes, enroll.token gone, debconf answer empty, token in no file under /var/cache/debconf or /etc: {out.strip()}")


def held_and_approve(r: Run, vm: str) -> None:
    rc, mid = r.on(vm, "cat /etc/machine-id")
    rc, host = r.on(vm, "hostname")
    rc, pretty = r.on(vm, ". /etc/os-release; echo $PRETTY_NAME")
    found = r.wait(f"{vm}'s held request", lambda: [q for q in (r.api("GET", "/api/v1/enrollment-requests?state=pending")[1] or {}).get("items", [])
                                                  if q.get("machine_id") == mid.strip()], 300, 10)
    q = (found or [{}])[0]
    r.row("CHK-M6-204", vm, None if r.dry else (q.get("hostname") == host.strip() and q.get("os_pretty_name") == pretty.strip()
          and q.get("agent_version") == "0.1.0-1" and q.get("kind") == "new" and bool(q.get("source_ip"))),
          f"held: {json.dumps({k: q.get(k) for k in ('request_id', 'kind', 'hostname', 'os_pretty_name', 'agent_version', 'machine_id', 'source_ip')})}")
    aid = str(q.get("agent_id", "x"))
    r.agent[vm] = aid
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    r.row("CHK-M6-204", vm, None if r.dry else (isinstance(a, dict) and a.get("status") == "awaiting_approval" and a.get("os_info") is None),
          f"while held: status {a.get('status') if isinstance(a, dict) else a}, os_info {a.get('os_info') if isinstance(a, dict) else None}")
    st, _ = r.api("POST", f"/api/v1/enrollment-requests/{q.get('request_id', 0)}/approve")
    r.row("CHK-M6-205", vm, None if r.dry else st == 200, f"approve with the admin TOTP session: {st}")
    (r.work / f"{vm}.approved_at").write_text(str(time.time()))


def heartbeats(r: Run, vm: str) -> None:
    aid = r.agent.get(vm, "x")
    t_appr = float((r.work / f"{vm}.approved_at").read_text()) if (r.work / f"{vm}.approved_at").exists() else time.time()
    on = r.wait(f"{vm} online", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "online", 330, 10)
    r.row("CHK-M6-205", vm, None if r.dry else bool(on), f"online {time.time() - t_appr:.0f} s after approval (<= 330)")
    seen: list[str] = []

    def beat() -> bool:
        hb = (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("last_heartbeat_at")
        if hb and (not seen or hb != seen[-1]):
            seen.append(hb)
        return len(seen) >= 4

    r.wait(f"{vm} three heartbeat intervals", beat, 4 * 330 + 60, 15)
    from datetime import datetime
    ts = [datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() for s in seen]
    gaps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
    r.row("CHK-M6-205", vm, None if r.dry else (len(gaps) >= 3 and all(270 <= g <= 330 for g in gaps[:3])),
          f"last_heartbeat_at gaps {['%.0f' % g for g in gaps]} s (each 270-330)")
    rc, j = r.on(vm, "sudo journalctl -u bitscan-agent -o cat --no-pager | grep -m1 'bitscan-agent started'")
    r.row("CHK-M6-205", vm, None if r.dry else ('"version":"0.1.0-1"' in j.replace(" ", "") or "version=0.1.0-1" in j),
          f"REQ-142 (1) start line: {j.strip()[:200]}")


def inventory(r: Run, vm: str) -> None:
    aid = r.agent.get(vm, "x")
    t_appr = float((r.work / f"{vm}.approved_at").read_text()) if (r.work / f"{vm}.approved_at").exists() else time.time()
    st, s = r.api("GET", "/api/v1/settings")
    pull = (s or {}).get("job_pull_seconds", 300) if isinstance(s, dict) else 300
    snap = r.wait(f"{vm} first inventory", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("last_snapshot"), pull + 30 + 60, 10)
    r.row("CHK-M6-206", vm, None if r.dry else bool(snap) and time.time() - t_appr <= pull + 30 + 15,
          f"first inventory {time.time() - t_appr:.0f} s after approval (job_pull_seconds {pull} + 30)")
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    oi = (a or {}).get("os_info") or {} if isinstance(a, dict) else {}
    rc, facts = r.on(vm, ". /etc/os-release; echo $VERSION_ID; uname -r; nproc; awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo; "
                     "ip -4 -j addr show scope global | python3 -c 'import json,sys;print(\" \".join(a[\"local\"] for i in json.load(sys.stdin) for a in i[\"addr_info\"]))'")
    f = facts.split("\n")
    good = len(f) >= 5 and oi.get("os_id") == "ubuntu" and oi.get("os_version_id") == f[0] and oi.get("kernel_release") == f[1] \
        and oi.get("architecture") == "x86_64" and str(oi.get("cpu_count")) == f[2] and str(oi.get("memory_mb")) == f[3] \
        and r.ip.get(vm) in [str(a).split("/")[0] for a in (oi.get("ip_addresses") or [])]  # INET values keep their prefix
    r.row("CHK-M6-206", vm, None if r.dry else good,
          f"os_info {json.dumps({k: oi.get(k) for k in ('os_id', 'os_version_id', 'kernel_release', 'architecture', 'cpu_count', 'memory_mb', 'ip_addresses')})} vs VM {f}")
    rc, dq = r.on(vm, "dpkg-query -W -f='${Package}\\t${Version}\\t${Architecture}\\t${Status}\\n' | sort")
    want = sorted(tuple(ln.split("\t")) for ln in dq.strip().split("\n") if ln.count("\t") == 3)
    got: list[tuple[str, ...]] = []
    cur = None
    while True:
        p = f"/api/v1/agents/{aid}/packages?limit=500" + (f"&cursor={cur}" if cur else "")
        st, body = r.api("GET", p)
        if r.dry or not isinstance(body, dict):
            break
        got += [(i["name"], i["version"], i["architecture"], i["status"]) for i in body["items"]]
        cur = body.get("next_cursor")
        if not cur:
            break
    count = (snap or {}).get("package_count") if isinstance(snap, dict) else None
    r.row("CHK-M6-206", vm, None if r.dry else (sorted(got) == want and count == len(want)),
          f"packages: API {len(got)} rows, snapshot package_count {count}, dpkg-query {len(want)}; diff {sorted(set(want) ^ set(got))[:5]}")


def vm_bash(r: Run, vm: str) -> str:
    """bash's version on the VM: read live if it is up, else the value recorded in its session."""
    if r.state.get(f"{vm}.up"):
        rc, v = r.on(vm, "dpkg-query -W -f='${Version}' bash")
        r.state[f"{vm}.bash"] = v.strip()
    return str(r.state.get(f"{vm}.bash", ""))


def vm_cmp(r: Run, vm: str, op: str, ref: str) -> bool:
    """dpkg --compare-versions on the VM if it is up, else the result recorded in its session."""
    key = f"{vm}.bash.{op}.{ref}"
    if r.state.get(f"{vm}.up"):
        rc, _ = r.on(vm, f"dpkg --compare-versions \"$(dpkg-query -W -f='${{Version}}' bash)\" {op} {ref}")
        r.state[key] = rc == 0
    return bool(r.state.get(key))


def search(r: Run) -> None:
    """Rows of every enrolled host: u2404's rows stay while it is off; its dpkg facts were
    recorded live in its own session."""
    st, body = r.api("GET", "/api/v1/packages/search?name=bash")
    rows = body.get("items", []) if isinstance(body, dict) else []
    by = {i["agent_id"]: i["version"] for i in rows}
    ok = True
    for vm, aid in r.agent.items():
        ok &= by.get(aid) == vm_bash(r, vm)
    r.row("CHK-M6-207", "both", None if r.dry else (ok and len(rows) == len(r.agent)), f"name=bash: {by}")
    st, body = r.api("GET", "/api/v1/packages/search?name=bash&os=ubuntu:22.04")
    ids = {i["agent_id"] for i in (body or {}).get("items", [])} if isinstance(body, dict) else set()
    r.row("CHK-M6-207", "both", None if r.dry else ids == {r.agent.get("u2204")}, f"os=ubuntu:22.04 -> {ids}")
    st, body = r.api("GET", "/api/v1/packages/search?q=lib&group_by=host")
    hosts = {i["agent_id"]: i["package_count"] for i in (body or {}).get("items", [])} if isinstance(body, dict) else {}
    r.row("CHK-M6-207", "both", None if r.dry else set(hosts) == set(r.agent.values()), f"group_by=host: {hosts}")
    # version_op cross-check with dpkg on the VM: bash lt 5.2 / ge 5.2
    for op in ("lt", "ge"):
        st, body = r.api("GET", f"/api/v1/packages/search?name=bash&version=5.2&version_op={op}")
        ids = {i["agent_id"] for i in (body or {}).get("items", [])} if isinstance(body, dict) else set()
        want = {aid for vm, aid in r.agent.items() if vm_cmp(r, vm, op, "5.2")}
        r.row("CHK-M6-207", "both", None if r.dry else ids == want, f"version_op={op} 5.2: API {ids} dpkg {want}")
    r.metric("bitscan_agents")  # writes /root/e2e/viewer.hdr (0600)
    rc, csv = r.mgr("curl -sS --cacert /home/admin/rel/manager-ca.pem -H @/root/e2e/viewer.hdr "
                    f"'{URL_IN_CT}/api/v1/packages/search.csv?name=bash'")
    lines = [ln for ln in csv.replace("\r", "").split("\n") if ln]
    r.row("CHK-M6-207", "both", None if r.dry else (len(lines) == 1 + len(r.agent) and lines[0].startswith("name,version,architecture,status,agent_id,hostname")),
          f"CSV equals the JSON rows: {len(lines) - 1} data rows, header {lines[0] if lines else None}")


def dpkg_change(r: Run, vm: str, pkg: str, chk: str = "CHK-M6-208") -> None:
    """REQ-146 (8). The clean images have empty apt lists, so `apt-get update` first (W0 did the same);
    the package must be absent before and installed after, else the row is NOT RUN, never PASS.
    Timing: TS 3.4 L239, the watch debounces to once per 10 min and the manager takes one unscheduled
    upload per agent per 10 min, so the upload is due 60-120 s after the change or, inside 10 min of
    the previous upload, once that window has passed; the wait covers both and records which."""
    aid = r.agent.get(vm, "x")
    rc, pre = r.on(vm, f"sudo apt-get update -q >/dev/null 2>&1; dpkg-query -W -f='${{Status}}' {pkg} 2>/dev/null | grep -q 'ok installed' && echo present || echo absent")
    if pre.strip() != "absent" and not r.dry:
        r.row(chk, vm, None, f"{pkg} is already installed on {vm} (or the check failed: {pre.strip()!r}); row not run")
        return
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    before = ((a or {}).get("last_snapshot") or {}).get("snapshot_id") if isinstance(a, dict) else None
    li_before = (a or {}).get("last_inventory_at") if isinstance(a, dict) else None
    rc, out = r.on(vm, f"sudo DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg} >/tmp/m6-apt.log 2>&1; echo rc=$?; "
                   f"dpkg-query -W -f='${{Status}} ${{Version}}' {pkg} 2>&1; tail -1 /tmp/m6-apt.log")
    t_inst = time.time()
    if "rc=0" not in out or "install ok installed" not in out:
        r.row(chk, vm, None if r.dry else False, f"apt-get install {pkg} did not install it (harness/environment): {out.strip()[-200:]}")
        return
    new = r.wait(f"{vm} unscheduled upload", lambda: (((r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("last_snapshot") or {})
                                                      .get("snapshot_id") not in (None, before)), 12 * 60, 5)
    dt = time.time() - t_inst
    if not r.dry:
        time.sleep(60)  # exactly one upload: nothing more in the next minute
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    after = ((a or {}).get("last_snapshot") or {}).get("snapshot_id") if isinstance(a, dict) else None
    r.row(chk, vm, None if r.dry else (bool(new) and dt <= 12 * 60 and after is not None),
          f"apt-get install {pkg} ({out.strip().splitlines()[1] if len(out.strip().splitlines()) > 1 else ''}): new snapshot {dt:.0f} s "
          f"after the install (60-120 s, or after the 10-min debounce from the previous upload, TS 3.4 L239); snapshot {before} -> {after}; "
          f"last_inventory_at before {li_before}")
    st, body = r.api("GET", f"/api/v1/packages/search?name={pkg}")
    ids = {i["agent_id"] for i in (body or {}).get("items", [])} if isinstance(body, dict) else set()
    r.row(chk, vm, None if r.dry else ids == {aid}, f"search name={pkg} -> {ids} (only {aid})")
    (r.work / f"{vm}.last_upload").write_text(str(time.time()))


def security_static(r: Run, vm: str) -> None:
    rc, out = r.on(vm, "sudo ss -ltnupH | grep -c bitscan-agent; pid=$(systemctl show -p MainPID --value bitscan-agent); "
                   "grep -E '^(CapEff|CapPrm|CapBnd|CapAmb|NoNewPrivs)' /proc/$pid/status")
    caps = re.findall(r"^(Cap\w+):\s+(\w+)", out, re.M)
    r.row("CHK-M6-284", vm, None if r.dry else (out.split("\n")[0].strip() == "0" and len(caps) == 4
          and all(v == "0000000000000000" for _, v in caps) and "NoNewPrivs:\t1" in out),
          f"REQ-148 (5) no listening socket; capabilities: {out.strip()}")


def route_groups(r: Run) -> None:
    """REQ-148 (3), (4). The bsa_ goes VM -> scratch (0600) -> manager host (0600), never on a command line."""
    vm = "u2204"
    aid = r.agent.get(vm, "x")
    local = r.work / "secrets" / "u2204.bsa"
    r.sh(["bash", "-c", f"umask 077; bash '{VM_SH}' ssh {r.ip.get(vm, '')} 'sudo cat /var/lib/bitscan-agent/token' > '{local}'"])
    r.sh(WSL + ["docker", "cp", r.wsl_work + "/secrets/u2204.bsa", f"{CT}:/root/e2e/u2204.bsa"])
    r.mgr("chmod 600 /root/e2e/u2204.bsa")
    if not r.dry:
        local.unlink(missing_ok=True)
    rc, mid = r.on(vm, "cat /etc/machine-id")
    st, _ = r.api("GET", "/api/v1/agents", token_file="/root/e2e/u2204.bsa")
    r.row("CHK-M6-282", vm, None if r.dry else st == 401, f"bsa_ on GET /api/v1/agents: {st}")
    st, _ = r.api("POST", f"/api/v1/agent/{aid}/heartbeat", {"agent_version": "0.1.0-1"}, token_file="/root/e2e/session.bsu", machine_id=mid.strip())
    r.row("CHK-M6-282", vm, None if r.dry else st == 401, f"admin bsu_ on POST /api/v1/agent/{{id}}/heartbeat: {st}")
    new_bse(r, "/root/e2e/spare.bse", hours=1)
    st, _ = r.api("GET", "/api/v1/agents", token_file="/root/e2e/spare.bse")
    r.row("CHK-M6-282", vm, None if r.dry else st == 401, f"bse_ on GET /api/v1/agents: {st}")
    for path in ("/api/v1/enrollment-requests/1/approve", f"/api/v1/agents/{aid}/revoke"):
        st, body = r.api("POST", path, token_file="/root/e2e/admin.bsk")
        typ = body.get("type") if isinstance(body, dict) else body
        r.row("CHK-M6-283", vm, None if r.dry else (st == 403 and typ == "totp_session_required"), f"admin bsk_ on POST {path}: {st} {typ}")


def metrics_phase_a(r: Run, since: int, vm: str) -> None:
    """User ruling (one VM at a time): online 1 during each phase A; during u2204's session the
    counted total (every status except awaiting_approval and decommissioned, #65 (b)) is 2."""
    m = r.metric("bitscan_agents")
    r.row("CHK-M6-265", vm, None if r.dry else m.get('{status="online"}') == 1.0, f"viewer bsk_ GET /metrics: {m}")
    if vm == "u2204":
        counted = sum(v for k, v in m.items() if k not in ('{status="awaiting_approval"}', '{status="decommissioned"}'))
        r.row("CHK-M6-265", vm, None if r.dry else counted == 2.0, f"counted agents total {counted} (u2204 online + u2404 off but counted)")
    bad = [e for e in r.audit(since) if isinstance(e.get("detail"), dict) and e["detail"].get("alert")
           and e["detail"].get("alert_kind") in ("clock_skew", "runner_helper_changed", "machine_id_mismatch",
                                                   "reenrolment_approved", "inventory_stale", "agents_offline")]
    r.row("CHK-M6-265", "both", None if r.dry else not bad, f"REQ-147 (7) no alert of the phase-B kinds while healthy: {[e['detail']['alert_kind'] for e in bad]}")


# -------------------------------------------------------------------- phase B rows


def alert_checks(r: Run, kind: str, entries: list[dict], before: dict[str, float]) -> None:
    """REQ-147 (5) for every entry: detail.alert, the sink got the same audit_id within 5 s, counter +1."""
    from datetime import datetime
    rc, sink = r.mgr("cat /opt/m6b/sink.jsonl 2>/dev/null")
    arrivals: dict[int, float] = {}
    for ln in sink.split("\n"):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        b = e.get("body")
        for rec in (b if isinstance(b, list) else [b]):
            if isinstance(rec, dict) and "audit_id" in rec:
                arrivals.setdefault(int(rec["audit_id"]), float(e["t"]))
    after = r.metric("bitscan_alerts_total")
    lab = f'{{kind="{kind}"}}'
    for e in entries:
        at = datetime.fromisoformat(e["at"].replace("Z", "+00:00")).timestamp()
        got = arrivals.get(e["audit_id"])
        r.row("CHK-M6-264", kind, None if r.dry else (e["detail"].get("alert") is True and got is not None and got - at <= 5),
              f"audit_id {e['audit_id']} at {e['at']}: sink arrival {None if got is None else f'{got - at:+.2f} s'}")
    r.row("CHK-M6-264", kind, None if r.dry else after.get(lab, 0) - before.get(lab, 0) == len(entries),
          f"bitscan_alerts_total{lab} {before.get(lab, 0)} -> {after.get(lab, 0)} for {len(entries)} entries")


def last_audit_id(r: Run) -> int:
    items = r.audit(0)
    return max((e["audit_id"] for e in items), default=0)


def clock_skew(r: Run) -> None:
    vm, aid = "u2204", r.agent.get("u2204", "x")
    since, before = last_audit_id(r), r.metric("bitscan_alerts_total")
    r.on(vm, "sudo timedatectl set-ntp false && sudo date -s '+6 minutes' >/dev/null && date -u")
    got = r.wait("one clock_skew entry", lambda: [e for e in r.alerts("clock_skew", since) if e.get("target") == f"agent:{aid}"], 360, 10)
    r.row("CHK-M6-260", vm, None if r.dry else bool(got) and len(got) == 1, f"clock +6 min: {len(got or [])} clock_skew entry within 360 s")
    if not r.dry:
        time.sleep(15 * 60)
    n = len([e for e in r.alerts("clock_skew", since) if e.get("target") == f"agent:{aid}"])
    r.row("CHK-M6-260", vm, None if r.dry else n == 1, f"after 15 more minutes: still {n} entry (#65 (a))")
    r.on(vm, "sudo timedatectl set-ntp true; for i in $(seq 1 30); do [ \"$(timedatectl show -p NTPSynchronized --value)\" = yes ] && break; sleep 5; done; timedatectl show -p NTPSynchronized --value")
    if not r.dry:
        time.sleep(6 * 60)
    n2 = len([e for e in r.alerts("clock_skew", since) if e.get("target") == f"agent:{aid}"])
    r.row("CHK-M6-260", vm, None if r.dry else n2 == 1, f"NTP restored, one more heartbeat: {n2} entry in total")
    alert_checks(r, "clock_skew", [e for e in r.alerts("clock_skew", since)], before)


def runner_helper(r: Run) -> None:
    vm, aid = "u2404", r.agent.get("u2404", "x")
    since, before = last_audit_id(r), r.metric("bitscan_alerts_total")
    r.on(vm, "sudo systemctl enable --now bitscan-capread.socket")
    got = r.wait("runner_helpers [capread]", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("runner_helpers") == ["capread"], 360, 10)
    n = len(r.alerts("runner_helper_changed", since))
    r.row("CHK-M6-261", vm, None if r.dry else bool(got) and n == 1, f"capread socket on: runner_helpers ['capread'] {bool(got)}, entries {n}")
    r.on(vm, "sudo systemctl disable --now bitscan-capread.socket")
    got = r.wait("runner_helpers []", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("runner_helpers") == [], 360, 10)
    n = len(r.alerts("runner_helper_changed", since))
    svc = r.props(vm, "bitscan-capread.service", "ActiveEnterTimestampMonotonic", "NRestarts")
    r.row("CHK-M6-261", vm, None if r.dry else bool(got) and n == 2 and svc["ActiveEnterTimestampMonotonic"] == "0",
          f"off again: [] {bool(got)}, entries {n}; bitscan-capread.service never started ({svc})")
    alert_checks(r, "runner_helper_changed", r.alerts("runner_helper_changed", since), before)


def no_requests_window(r: Run, vm: str, minutes: int) -> tuple[bool, str]:
    """No access-log line from that agent for `minutes` (the manager journal, agent_id field)."""
    aid = r.agent.get(vm, "x")
    t0 = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    if not r.dry:
        time.sleep(minutes * 60)
    rc, n = r.mgr(f"TZ=UTC journalctl -u bitscan-manager -o cat --no-pager --since '{t0}' | grep -c '\"agent_id\": \"{aid}\"'; true")
    return n.strip() == "0", f"{n.strip()} access-log lines from agent {aid} in {minutes} min since {t0}Z"


def wrong_trust(r: Run, vm: str, chk: str) -> None:
    """REQ-148 (1) pin (u2404) / (2) CA (u2204): no request for 10 min, journal names it, restore, heartbeats resume."""
    aid = r.agent.get(vm, "x")
    if vm == "u2404":
        r.on(vm, "sudo cp -p /etc/bitscan/agent.yaml /root/agent.yaml.m6 && sudo sed -i 's/^manager_spki_sha256:.*/manager_spki_sha256: "
                 + "0" * 64 + "/' /etc/bitscan/agent.yaml && sudo systemctl restart bitscan-agent")
    else:
        r.vm("put", r.ip[vm], str(r.work / "other-ca.pem"), "/tmp/other-ca.pem")
        r.on(vm, "sudo install -m 0644 /tmp/other-ca.pem /etc/bitscan/other-ca.pem && sudo cp -p /etc/bitscan/agent.yaml /root/agent.yaml.m6 && "
                 "sudo sed -i 's#^ca_file:.*#ca_file: /etc/bitscan/other-ca.pem#' /etc/bitscan/agent.yaml && sudo systemctl restart bitscan-agent")
    quiet, ev = no_requests_window(r, vm, 10)
    rc, j = r.on(vm, "sudo journalctl -u bitscan-agent -o cat --no-pager --since '-11 min' | grep -c 'certificate or key pin failed verification'")
    r.row(chk, vm, None if r.dry else (quiet and j.strip() not in ("", "0")), f"{ev}; journal pin/verification lines {j.strip()}")
    r.on(vm, "sudo cp -p /root/agent.yaml.m6 /etc/bitscan/agent.yaml && sudo rm -f /root/agent.yaml.m6 /etc/bitscan/other-ca.pem && sudo systemctl restart bitscan-agent")
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    hb0 = (a or {}).get("last_heartbeat_at") if isinstance(a, dict) else None
    got = r.wait("heartbeats resume", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("last_heartbeat_at") != hb0, 360, 10)
    r.row(chk, vm, None if r.dry else bool(got), f"restored: a new heartbeat within 6 min: {bool(got)}")


def stale_inventory_setup(r: Run) -> int:
    vm = "u2204"
    since = last_audit_id(r)
    r.on(vm, "sudo chmod o-x /usr/bin/dpkg-query; stat -c '%a' /usr/bin/dpkg-query")
    r.state["u2204.chmod_at"] = time.time() - 2
    st, body = r.api("PATCH", "/api/v1/settings", {"inventory_interval_s": 3600})
    n = len(r.alerts("settings_changed", since))
    r.row("CHK-M6-263", vm, None if r.dry else (st == 200 and n == 1), f"PATCH inventory_interval_s 3600: {st}; settings_changed entries {n}")
    return since


def revoke(r: Run, vm: str) -> None:
    aid = r.agent.get(vm, "x")
    st, _ = r.api("POST", f"/api/v1/agents/{aid}/revoke")
    r.row("CHK-M6-209", vm, None if r.dry else st == 204, f"revoke: {st}")
    if not r.dry:
        time.sleep(6 * 60)  # the next heartbeat gets 401
    rc, j = r.on(vm, "sudo journalctl -u bitscan-agent -o cat --no-pager | grep -c 'the manager refused the agent token; all loops stopped'")
    r.row("CHK-M6-209", vm, None if r.dry else j.strip() == "1", f"re-enrol line in the journal {j.strip()} time(s)")
    quiet, ev = no_requests_window(r, vm, 10)
    u = r.props(vm, "bitscan-agent", "ActiveState", "NRestarts")
    r.row("CHK-M6-209", vm, None if r.dry else (quiet and u["ActiveState"] == "active" and u["NRestarts"] == "0"),
          f"{ev}; unit {u} (#81 (a))")


def revoke_purge(r: Run, vm: str) -> None:
    """User speed-up (main 17:11): after the revoke's 401, purge at once, inside the revoke's 10-min
    no-call window; that window checks both "no further call for 10 min" (REQ-146 (9)) and `stale`
    10 min after the last heartbeat (REQ-146 (11)). Each still gets its full 10 min."""
    aid = r.agent.get(vm, "x")
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    hb0 = (a or {}).get("last_heartbeat_at") if isinstance(a, dict) else None
    st, _ = r.api("POST", f"/api/v1/agents/{aid}/revoke")
    r.row("CHK-M6-209", vm, None if r.dry else st == 204, f"revoke: {st}")
    # the agent's next call gets 401 and it stops: wait for the one journal line (<= one heartbeat)
    line = "the manager refused the agent token; all loops stopped"
    got = r.wait(f"{vm} 401 and the re-enrol line", lambda: r.on(vm, f"sudo journalctl -u bitscan-agent -o cat --no-pager | grep -c '{line}'; true")[1].strip() not in ("", "0"), 360, 10)
    t401 = time.time()
    rc, j = r.on(vm, f"sudo journalctl -u bitscan-agent -o cat --no-pager | grep -c '{line}'; true")
    u = r.props(vm, "bitscan-agent", "ActiveState", "NRestarts")
    r.row("CHK-M6-209", vm, None if r.dry else (bool(got) and j.strip() == "1" and u["ActiveState"] == "active" and u["NRestarts"] == "0"),
          f"401 on the next call: re-enrol line {j.strip()} time(s); unit before purge {u} (#81 (a))")
    rc, hb = r.api("GET", f"/api/v1/agents/{aid}")
    last_hb = (hb or {}).get("last_heartbeat_at") if isinstance(hb, dict) else None
    purge(r, vm)  # inside the no-call window
    t_purge = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t401))
    left = max(0.0, t401 + 600 - time.time())
    if not r.dry:
        time.sleep(left)
    rc, n = r.mgr(f"TZ=UTC journalctl -u bitscan-manager -o cat --no-pager --since '{t_purge}' | grep -c '\"agent_id\": \"{aid}\"'; true")
    r.row("CHK-M6-209", vm, None if r.dry else n.strip() == "0",
          f"{n.strip()} access-log lines from agent {aid} in the 10 min after its 401 ({t_purge}Z), purge done inside that window")
    from datetime import datetime
    def is_stale() -> bool:
        return (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "stale"
    got_stale = r.wait(f"{vm} stale", is_stale, 4 * 60, 15)
    since_hb = (time.time() - datetime.fromisoformat(str(last_hb).replace("Z", "+00:00")).timestamp()) if last_hb else -1
    r.row("CHK-M6-211", vm, None if r.dry else bool(got_stale),
          f"stale {since_hb / 60:.1f} min after the last heartbeat {last_hb} (10 min + one 60 s sweep; heartbeat before revoke {hb0})")


def purge(r: Run, vm: str) -> None:
    rc, out = r.on(vm, "sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y bitscan-agent >/tmp/purge.log 2>&1; echo rc=$?; "
                   "ls -A /var/lib/bitscan-agent /etc/bitscan 2>&1; ls /usr/sbin/bitscan-* /lib/systemd/system/bitscan-* 2>&1 | grep -v 'No such' ; "
                   "pgrep -l bitscan; echo end")
    r.row("CHK-M6-210", vm, None if r.dry else ("rc=0" in out and "agent.yaml" not in out and "install.env" not in out
          and re.search(r"^/usr/sbin/bitscan|^/lib/systemd/system/bitscan|^\d+ bitscan", out, re.M) is None),
          f"purge (#82; /etc/bitscan keeps only ca.pem, which the runbook copied): {out.strip()}")
    (r.work / f"{vm}.purged_at").write_text(str(time.time()))


def stale_after_purge(r: Run, vm: str) -> None:
    aid = r.agent.get(vm, "x")
    got = r.wait(f"{vm} stale", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "stale", 13 * 60, 20)
    r.row("CHK-M6-211", vm, None if r.dry else bool(got), f"stale about 10 min after the last heartbeat: {bool(got)}")


def agents_offline(r: Run, since: int, before: dict[str, float]) -> None:
    aid = r.agent.get("u2404", "x")
    # offline is due 30 min after u2404's last heartbeat (just before its Stop-VM in session 1), plus a sweep
    left = max(0.0, float(r.state.get("u2404.stopped_at", time.time())) + 30 * 60 - time.time())
    got = r.wait("u2404 offline", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "offline", left + 5 * 60, 30)
    ent = r.wait("one agents_offline entry", lambda: r.alerts("agents_offline", since), 180, 15)
    r.row("CHK-M6-263", "u2404", None if r.dry else bool(got) and len(ent or []) == 1,
          f"(4a) offline: {bool(got)}; agents_offline entries {len(ent or [])} detail {(ent or [{}])[0].get('detail')}")
    alert_checks(r, "agents_offline", ent or [], before)


BACKDATE_SQL = r"""BEGIN;
SET ROLE bitscan_owner;
DO $$
DECLARE n int;
BEGIN
  UPDATE agent SET last_inventory_at = now() - interval '6600 seconds' WHERE agent_id = '{aid}' AND status = 'online';
  GET DIAGNOSTICS n = ROW_COUNT;
  RAISE NOTICE 'rows updated: %', n;
  IF n <> 1 THEN RAISE EXCEPTION 'expected exactly one row, got %', n; END IF;
END
$$;
COMMIT;
"""


def last_inv(r: Run, aid: str) -> str:
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    return str((a or {}).get("last_inventory_at")) if isinstance(a, dict) else "?"


def stale_inventory(r: Run, since: int, before: dict[str, float]) -> None:
    """User decision 2026-10-26: no 2 h wait. After one failed inventory attempt, last_inventory_at is
    backdated by 6600 s as a test fixture (DB owner, one row), then the real sweep must raise exactly one
    inventory_stale entry once the age passes 7200 s (about 10 min), with no manager restart."""
    vm, aid2204, aid2404 = "u2204", r.agent.get("u2204", "x"), r.agent.get("u2404", "y")
    t_chmod = float(r.state.get("u2204.chmod_at", time.time()))
    # 2. one failed inventory attempt after the chmod (the agent journal names it)
    def failed() -> bool:
        rc, n = r.on(vm, f"sudo journalctl -u bitscan-agent -o cat --no-pager --since @{int(t_chmod)} | grep -c 'inventory collection failed'; true")
        return n.strip() not in ("", "0")
    got_fail = r.wait("a failed inventory attempt after the chmod", failed, 6 * 60, 15)
    if not got_fail:  # the agent's next scheduled attempt: inventory_interval_s (3600 s) after the last one
        got_fail = r.wait("the next scheduled inventory attempt", failed, 62 * 60, 30)
    rc, jl = r.on(vm, f"sudo journalctl -u bitscan-agent -o cat --no-pager --since @{int(t_chmod)} | grep -m1 'inventory collection failed'")
    li0 = last_inv(r, aid2204)
    r.row("CHK-M6-263", vm, None if r.dry else bool(got_fail),
          f"failed inventory attempt after chmod o-x dpkg-query: {jl.strip()[:220]}; last_inventory_at {li0}")
    # 3. fixture: backdate last_inventory_at (one row, DB owner, no restart)
    if not r.dry:
        (r.work / "backdate.sql").write_bytes(BACKDATE_SQL.replace("{aid}", aid2204).encode())
    r.sh(WSL + ["sh", "-c", f"docker cp {r.wsl_work}/backdate.sql {CT}:/root/e2e/backdate.sql"])
    rc, out = r.mgr("sudo -u postgres psql -X -At -v ON_ERROR_STOP=1 -d bitscan -f /root/e2e/backdate.sql 2>&1; "
                    "echo audit=$(sudo -u postgres psql -X -At -d bitscan -c 'SELECT count(*) FROM audit_log')")
    li1 = last_inv(r, aid2204)
    r.row("CHK-M6-W4-fixture-4", vm, None if r.dry else (rc == 0 and "rows updated: 1" in out),
          f"test fixture (user decision): UPDATE agent SET last_inventory_at = now() - interval '6600 seconds' WHERE agent_id = "
          f"'{aid2204}' AND status = 'online' as bitscan_owner, one transaction, exactly 1 row: {out.strip()[-160:]}; "
          f"last_inventory_at {li0} -> {li1}; reason: REQ-147 (4) without the 2 h wait; no manager restart")
    # 4. exactly one inventory_stale entry, in real time
    got = r.wait("one inventory_stale entry for u2204", lambda: [e for e in r.alerts("inventory_stale", since) if e.get("target") == f"agent:{aid2204}"],
                 20 * 60, 20)
    if not r.dry:
        time.sleep(90)  # one more sweep: still exactly one
    got = [e for e in r.alerts("inventory_stale", since) if e.get("target") == f"agent:{aid2204}"]
    other = [e for e in r.alerts("inventory_stale", since) if e.get("target") == f"agent:{aid2404}"]
    li2 = last_inv(r, aid2204)
    r.row("CHK-M6-263", vm, None if r.dry else (len(got) == 1 and li2 == li1),
          f"backdated by 6600 s as a test fixture (user decision): inventory_stale for u2204 {len(got)} "
          f"(at {got[0]['at'] if got else None}); last_inventory_at unchanged by the failed attempts ({li1} -> {li2})")
    r.row("CHK-M6-263", "u2404", None, f"inventory_stale for u2404: {len(other)} (recorded, not failed: u2404 heartbeats again in session 2)")
    alert_checks(r, "inventory_stale", got, before)
    r.on(vm, "sudo chmod o+x /usr/bin/dpkg-query; stat -c '%a' /usr/bin/dpkg-query")


def machine_id(r: Run, vm: str = "u2204") -> None:
    aid = r.agent.get(vm, "x")
    since, before = last_audit_id(r), r.metric("bitscan_alerts_total")
    r.on(vm, "sudo cp -p /etc/machine-id /root/machine-id.m6 && sudo rm -f /etc/machine-id && sudo systemd-machine-id-setup >/dev/null && "
             "sudo systemctl restart bitscan-agent")
    got = r.wait("machine_id_mismatch", lambda: r.alerts("machine_id_mismatch", since), 360, 10)
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    r.row("CHK-M6-262", vm, None if r.dry else (len(got or []) == 1 and isinstance(a, dict) and a.get("token_revoked_at") is not None),
          f"new machine-id: entries {len(got or [])}, token_revoked_at {(a or {}).get('token_revoked_at') if isinstance(a, dict) else a}")
    alert_checks(r, "machine_id_mismatch", got or [], before)
    # restore and re-enrol as agent runbook section 7 says, with a new single-use bse_
    r.on(vm, "sudo cp -p /root/machine-id.m6 /etc/machine-id && sudo rm -f /root/machine-id.m6")
    new_bse(r, f"/root/e2e/{vm}-re.bse")
    # printf is a shell builtin: the bse_ goes into the 0600 file without being any process's argv
    r.sh(WSL + ["sh", "-c", f"umask 077; docker cp {CT}:/root/e2e/{vm}-re.bse /tmp/m6re.bse && "
                f"printf 'ENROL_TOKEN=%s\\n' \"$(cat /tmp/m6re.bse)\" > {r.wsl_work}/secrets/install.env; rm -f /tmp/m6re.bse"])
    r.on(vm, "install -d -m 0700 ~/in")
    r.vm("put", r.ip[vm], str(r.work / "secrets" / "install.env"), "in/install.env")
    if not r.dry:
        (r.work / "secrets" / "install.env").unlink(missing_ok=True)
    since2, before2 = last_audit_id(r), r.metric("bitscan_alerts_total")
    rc, out = r.on(vm, "sudo install -m 0600 -o root -g root /dev/null /etc/bitscan/install.env && "
                   "sudo sh -c 'cat ~bstester/in/install.env > /etc/bitscan/install.env' && rm -f ~/in/install.env && "
                   "sudo DEBIAN_FRONTEND=noninteractive dpkg-reconfigure bitscan-agent; echo rc=$?; test -e /etc/bitscan/install.env && echo LEFT")
    r.row("CHK-M6-262", vm, None if r.dry else ("rc=0" in out and "LEFT" not in out), f"agent runbook §7 install.env + dpkg-reconfigure: {out.strip()[-200:]}")
    rc, mid = r.on(vm, "cat /etc/machine-id")
    q = (r.wait("held reenrol", lambda: [x for x in (r.api("GET", "/api/v1/enrollment-requests?state=pending")[1] or {}).get("items", [])
                                         if x.get("machine_id") == mid.strip()], 360, 10) or [{}])[0]
    # TS §3.2: a held re-enrolment names the existing agent in its own agent_id; `matches` lists only
    # *other* agents with the same hostname or machine-id (repositories/enrolment.py matches(),
    # `agent_id <> request.agent_id`, for cloned images), so the agent itself is never in it
    others = [m.get("agent_id") for m in q.get("matches", [])]
    r.row("CHK-M6-262", vm, None if r.dry else (q.get("kind") == "reenrol" and q.get("agent_id") == aid and aid not in others),
          f"held: kind {q.get('kind')}, agent_id {q.get('agent_id')} (want {aid}), matches (other agents) {others}")
    st, body = r.api("POST", f"/api/v1/enrollment-requests/{q.get('request_id', 0)}/approve")
    on = r.wait("online again", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "online", 360, 10)
    n = len(r.alerts("reenrolment_approved", since2))
    r.row("CHK-M6-262", vm, None if r.dry else (st == 200 and isinstance(body, dict) and body.get("agent_id") == aid and bool(on) and n == 1),
          f"approve {st}: same agent_id {isinstance(body, dict) and body.get('agent_id') == aid}, online {bool(on)}, reenrolment_approved {n}")
    alert_checks(r, "reenrolment_approved", r.alerts("reenrolment_approved", since2), before2)


def idle_cost(r: Run) -> None:
    rc, out = r.on("u2404", "sudo bash ~/rel/idle_cost.sh 600 10", timeout=700)
    try:
        res = json.loads(out.strip().split("\n")[-1])
    except ValueError:
        res = {}
    r.row("CHK-M6-300", "u2404", None if r.dry else bool(res) and res.get("same_invocation") is True,
          f"REQ-149 (recorded, no gate): {json.dumps(res)}")
    (r.work / "idle_cost.json").write_text(json.dumps(res, indent=2))


PAT = r"bs[uaek]_[A-Za-z0-9_-]{20,}"


def vm_sweep(r: Run, vm: str) -> None:
    """Phase C for one VM (user ruling: per VM): its journal canary (tokscan_vm.py, every field, with a
    control), then restore to clean."""
    canary(r, vm, "sweep")
    name = VMS[vm][0]
    r.vm("stop", name)
    rc, st = r.vm("restore", name)
    r.state[f"{vm}.up"] = False
    r.row("CHK-M6-212", vm, None if r.dry else st.strip().endswith("Off"), f"restored to clean: {st.strip()}")


def manager_sweep(r: Run, what: str | None = "after the purges") -> None:
    # -o json: every field of every entry (a token in _CMDLINE would show too), not only MESSAGE
    rc, n = r.mgr(f"journalctl --no-pager -o json | grep -cE '{PAT}'; grep -cE '{PAT}' /opt/m6b/sink.jsonl; journalctl --no-pager -o json | wc -l; true")
    r.row("CHK-M6-286", "mgr", None if r.dry else n.split()[:2] == ["0", "0"] and len(n.split()) == 3 and int(n.split()[2]) > 0,
          f"manager journal (entries with a token-shaped string, all fields) / sink lines with one / journal entries: {n.split()}")
    if what is None:  # the fresh session doesn't wait for stale (CHK-M6-211 PASSED in W4; user: skew, not wait)
        return
    m = r.metric("bitscan_agents")
    r.row("CHK-M6-265", "mgr", None if r.dry else m.get('{status="online"}', 0) == 0, f"metrics {what}: {m}")


# -------------------------------------------------------------------- sessions
# User ruling 2026-10-26 "W4 runs one VM at a time"; work/plans/M6-e2e.md section 4 (planner, same day).


def phase_a_one(r: Run, vm: str, pkg: str) -> None:
    """Phase A for one VM (steps 1-7). The two-host search rows run in u2204's phase A."""
    since = last_audit_id(r)
    vm_prepare(r, vm)
    install_agent(r, vm)
    held_and_approve(r, vm)
    inventory(r, vm)
    heartbeats(r, vm)
    security_static(r, vm)
    vm_bash(r, vm)
    for op in ("lt", "ge"):
        vm_cmp(r, vm, op, "5.2")
    if vm == "u2204":
        search(r)
    dpkg_change(r, vm, pkg)
    metrics_phase_a(r, since, vm)
    r.save()


def stop_kept(r: Run, vm: str) -> None:
    rc, hb = r.api("GET", f"/api/v1/agents/{r.agent.get(vm, 'x')}")
    r.state[f"{vm}.last_hb"] = (hb or {}).get("last_heartbeat_at") if isinstance(hb, dict) else None
    r.state[f"{vm}.off_since"] = last_audit_id(r)  # the agents_offline watcher's baseline
    rc, st = r.vm("stop", VMS[vm][0])
    r.state[f"{vm}.up"] = False
    r.state[f"{vm}.stopped_at"] = time.time()
    r.row("CHK-M6-212", vm, None if r.dry else st.strip().endswith("Off"),
          f"Stop-VM with the disk kept (no restore, no revoke, no purge); last heartbeat {r.state[f'{vm}.last_hb']}: {st.strip()}")
    r.save()


def session_u2404_1(r: Run) -> bool:
    if not manager_up(r) and not r.dry:
        return False
    r.state["mgr.up"] = True
    tokens(r)
    r.save()
    if not vm_start(r, "u2404", restore=True):
        return False
    phase_a_one(r, "u2404", "jq")  # jq turned out to be preinstalled; CHK-M6-208 is re-run in session 2 with ncdu
    idle_cost(r)          # 25-35 (600 s since the speed-up; attempt 7 ran the earlier 1800 s)
    runner_helper(r)      # 35-45
    wrong_trust(r, "u2404", "CHK-M6-280")  # 45-60 pin
    stop_kept(r, "u2404")
    return True


def gate_mark(r: Run, what: str) -> None:
    """A marker file for the coordinating tester (it sends tester-m6c go/pause/resume); the harness
    itself sends no messages. Each line: time, event."""
    if not r.dry:
        with (r.work / "events.txt").open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {what}\n")
    print(f"EVENT {what}", flush=True)


def session_u2204(r: Run) -> bool:
    """Started straight after u2404's Stop-VM. u2404's offline and agents_offline fall inside this
    session (watched in a thread). Speed-up (user, 2026-10-26; plan section 4): once the stale window
    is open and u2404's agents_offline has been seen, u2404 session 2 runs alongside in a thread."""
    import threading
    # CHK-M6-201-r restarts the manager; it must run before u2404 turns offline (lead: no restart from
    # u2404 offline until the REQ-147 (4a) and stale-inventory rows are checked)
    if not r.state.get("leaf.rerun.done"):
        t_off = float(r.state.get("u2404.stopped_at", time.time())) + 30 * 60
        if time.time() < t_off - 5 * 60:
            rerun_leaf(r)
            r.state["leaf.rerun.done"] = True
            r.save()
        else:
            r.row("CHK-M6-201-r", "mgr", None, "not run: too close to u2404 turning offline (a restart would re-alert agents_offline)")
    gate_mark(r, "pause-before-start u2204")
    if not vm_start(r, "u2204", restore=True):
        return False
    gate_mark(r, "resume u2204-booted")
    off_since, off_before = last_audit_id(r), r.metric("bitscan_alerts_total")
    phase_a_one(r, "u2204", "tree")
    watcher = threading.Thread(target=agents_offline, args=(r, int(r.state.get("u2404.off_since", off_since)), off_before),
                               name="agents-offline")
    watcher.start()
    wrong_trust(r, "u2204", "CHK-M6-281")  # 25-40 CA
    clock_skew(r)                          # 40-55
    route_groups(r)                        # 55-65
    stale_since = stale_inventory_setup(r)  # 65: the stale window opens
    gate_mark(r, "go stale-window-open")
    watcher.join()
    s2 = threading.Thread(target=session_u2404_2_body, args=(r, True), name="u2404-2")
    gate_mark(r, "pause-before-start u2404-2")
    s2.start()
    stale_inventory(r, stale_since, r.metric("bitscan_alerts_total"))
    machine_id(r)
    s2.join()
    revoke(r, "u2204")
    purge(r, "u2204")
    stale_after_purge(r, "u2204")
    vm_sweep(r, "u2204")
    manager_sweep(r)  # after both VMs' last sessions (plan section 4, phase C)
    r.sh(WSL + ["sh", "-c", f"docker rm -f {CT} >/dev/null; docker rmi m6-e2e-mgr:walked >/dev/null; ss -ltnH 'sport = :18443' | wc -l"])
    r.state["mgr.up"] = False
    r.save()
    return True


def session_u2204_cont(r: Run) -> bool:
    """The u2204 column from the clock-skew row on, for a run whose first part (leaf re-run, Start-VM,
    phase A, agents_offline, CA test) finished under the 16:36 harness and was stopped at that
    boundary to load the fixed code (dpkg_change with apt-get update, the TASK-138 RC step)."""
    import threading
    if not r.state.get("u2204.up"):
        return r.row("CHK-M6-200", "u2204", False, "u2204 is not up per state.json; continuation not possible")
    # user speed-ups (main, 17:11): u2404 session 2 starts now, alongside clock skew and the route rows
    gate_mark(r, "pause-before-start u2404-2")
    s2 = threading.Thread(target=session_u2404_2_body, args=(r, True), name="u2404-2")
    s2.start()
    clock_skew(r)                          # 40-55 (u2204 keeps heartbeating, so u2404's online-2 check may fall here)
    route_groups(r)                        # 55-65
    dpkg_change(r, "u2204", "tree", "CHK-M6-208-r")  # inside the route rows, before the minute-65 chmod
    stale_since = stale_inventory_setup(r)  # 65: the stale window opens
    r.save()
    stale_inventory(r, stale_since, r.metric("bitscan_alerts_total"))
    machine_id(r)
    s2.join()
    gate_mark(r, "go one-vm-left")
    revoke_purge(r, "u2204")
    vm_sweep(r, "u2204")
    manager_sweep(r)
    r.sh(WSL + ["sh", "-c", f"docker rm -f {CT} >/dev/null; docker rmi m6-e2e-mgr:walked >/dev/null; ss -ltnH 'sport = :18443' | wc -l"])
    r.state["mgr.up"] = False
    r.save()
    return True


def session_u2404_2_body(r: Run, overlap: bool) -> bool:
    if not vm_start(r, "u2404", restore=False, allow_running="bitscan-u2204" if overlap else None):
        return False
    gate_mark(r, "resume u2404-2-booted")
    aid = r.agent.get("u2404", "x")
    since = last_audit_id(r)
    on = r.wait("u2404 first heartbeat in session 2",
                lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "online", 360, 10)
    r.row("CHK-M6-205", "u2404", None if r.dry else bool(on), f"session 2: same disk, online again (first heartbeat): {bool(on)}")
    new_rc(r, "u2404")       # TASK-138 RC (RemoveOnStop=yes), lead 2026-10-26
    helper_recheck(r)        # CHK-M6-261-r on the new RC
    rerun_modes(r, "u2404")  # CHK-M6-285-r
    dpkg_change(r, "u2404", "ncdu", "CHK-M6-208-r")  # jq was preinstalled in the 24.04 image
    m = r.metric("bitscan_agents")
    r.row("CHK-M6-265", "both", None if r.dry else m.get('{status="online"}') == 2.0,
          f"REQ-147 (6) while u2204 still heartbeats, before u2404's revoke: viewer bsk_ GET /metrics {m}")
    revoke_purge(r, "u2404")
    extra = [e["detail"].get("alert_kind") for e in r.audit(since) if isinstance(e.get("detail"), dict) and e["detail"].get("alert")
             and e.get("target") in (f"agent:{aid}", "fleet") and e["detail"].get("alert_kind") in ("inventory_stale", "agents_offline")]
    r.row("CHK-M6-263", "u2404", None, f"session 2 extra entries (recorded, not a failure; lead 2026-10-26): {extra}")
    vm_sweep(r, "u2404")
    r.save()
    return True


def session_u2404_2(r: Run) -> bool:
    """Stand-alone session 2 (only if the overlapping run inside the u2204 session did not happen)."""
    ok = session_u2404_2_body(r, False)
    manager_sweep(r)
    return ok


def rerun_leaf(r: Run) -> bool:
    """CHK-M6-201-r: the IP-SAN leaf step of manager_up as its own row (attempt 7 got a Git-Bash-mangled
    --walk-pki). Replaces the served leaf (cp onto the 0600 files, restart, as manager-operations.md
    section 2), then checks the served SAN from inside the host and from Windows through the portproxy."""
    # Same key, new certificate: u2404 pinned the served key's SPKI in session 1, so the key must not
    # change. The CSR is made from tls.key inside the host; the key never leaves it.
    wsl_w4 = r.wsl_work
    rc0, pin0 = r.mgr("openssl x509 -in /etc/bitscan/secrets/tls.crt -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -c1-64")
    r.mgr("openssl req -new -key /etc/bitscan/secrets/tls.key -subj /CN=bitscan-mgr.test -out /root/e2e-leaf.csr")
    sign = (f"set -e; cd {wsl_w4}/secrets; docker cp {CT}:/root/e2e-leaf.csr leaf.csr; "
            f"printf 'subjectAltName=DNS:bitscan-mgr.test,IP:{MGR_IP}\\nbasicConstraints=CA:FALSE\\nkeyUsage=digitalSignature\\nextendedKeyUsage=serverAuth\\n' > leaf.ext; "
            f"openssl x509 -req -in leaf.csr -CA {r.walk_pki}/ca.pem -CAkey {r.walk_pki}/ca.key -CAcreateserial -days 7 -extfile leaf.ext -out leaf.crt 2>/dev/null; "
            f"rm -f leaf.csr leaf.ext; docker cp leaf.crt {CT}:/root/e2e-leaf.crt; openssl x509 -in leaf.crt -noout -ext subjectAltName | tail -1")
    (r.work / "leaf.sh").write_bytes((sign + "\n").encode())
    rc, out = r.sh(WSL + ["bash", wsl_w4 + "/leaf.sh"], timeout=120)
    r.mgr("cp /root/e2e-leaf.crt /etc/bitscan/secrets/tls.crt && rm -f /root/e2e-leaf.crt /root/e2e-leaf.csr && systemctl restart bitscan-manager")
    rc1, pin1 = r.mgr("openssl x509 -in /etc/bitscan/secrets/tls.crt -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -c1-64")
    if r.dry:
        return r.row("CHK-M6-201-r", "mgr", None, "dry run")
    if pin0.strip() != pin1.strip() or not pin0.strip():
        return r.row("CHK-M6-201-r", "mgr", False, f"the served key's SPKI changed ({pin0.strip()[:16]} -> {pin1.strip()[:16]})")
    up = r.wait("readyz after the leaf swap", lambda: r.mgr("curl -sS --cacert /home/admin/rel/manager-ca.pem "
                "https://bitscan-mgr.test:8443/readyz")[1].strip().endswith('{"status":"ok"}'), 120, 5)
    rc2, san = r.mgr("echo | openssl s_client -connect 127.0.0.1:8443 -servername bitscan-mgr.test 2>/dev/null | openssl x509 -noout -ext subjectAltName | tail -1")
    rc3, win = r.sh(["curl.exe", "-sS", "--ssl-no-revoke", "--noproxy", "*", "--max-time", "10", "--cacert",
                     str(r.work / "manager-ca.pem"), f"https://{MGR_IP}:8443/readyz"])
    return r.row("CHK-M6-201-r", "mgr", None if r.dry else rc == 0 and f"IP Address:{MGR_IP}" in out and bool(up) and f"IP Address:{MGR_IP}" in san
                 and win.strip().endswith('{"status":"ok"}'),
                 f"walk-pki {r.walk_pki}; same key (SPKI {pin1.strip()[:16]}…, u2404's pin still valid); new cert {out.strip()}; "
                 f"served SAN {san.strip()}; readyz {bool(up)}; "
                 f"Windows https://{MGR_IP}:8443/readyz (IP SAN) {win.strip()[:60]}")


NEW_RC_SHA = "d98ef8c3978e99e65f27074be8613c04fcaddba6f774efece30a4f7aefe0f3bf"  # tester-m6c, TASK-138


def new_rc(r: Run, vm: str) -> None:
    """Lead 2026-10-26: reinstall the TASK-138 RC (same version, only RemoveOnStop=yes in the capread
    socket unit) with `sudo dpkg -i`, then a short check: unit states, heartbeat and inventory go on."""
    src = r.work / "new-rc" / DEB
    aid = r.agent.get(vm, "x")
    if not src.exists() and not r.dry:
        r.row("CHK-M6-261-rc", vm, None, f"new RC not found at {src}; the rm-socket diagnostic runs instead")
        return
    r.on(vm, "mkdir -p ~/newrc")
    r.vm("put", r.ip[vm], str(src), f"newrc/{DEB}")
    rc, out = r.on(vm, f"cd ~/newrc && sha256sum {DEB} && sudo DEBIAN_FRONTEND=noninteractive dpkg -i ./{DEB} >/tmp/m6-dpkg.log 2>&1; echo rc=$?; "
                   "dpkg-query -W -f='${Version}\\n' bitscan-agent; grep -c '^RemoveOnStop=yes' /lib/systemd/system/bitscan-capread.socket; "
                   "for u in bitscan-agent.service bitscan-runner.socket bitscan-capread.socket; do echo \"$u $(systemctl is-enabled $u) $(systemctl is-active $u)\"; done")
    st, a = r.api("GET", f"/api/v1/agents/{aid}")
    hb0, li0 = (a or {}).get("last_heartbeat_at"), (a or {}).get("last_inventory_at")
    hb = r.wait("a heartbeat after the reinstall", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("last_heartbeat_at") != hb0, 360, 10)
    rc2, ss = r.on(vm, "sudo journalctl -u bitscan-agent -o cat --no-pager --since '-7 min' | grep -cE 'inventory collection failed|the manager refused'; true")
    ok = (NEW_RC_SHA in out and "rc=0" in out and "\n1\n" in out and "bitscan-agent.service enabled active" in out
          and "bitscan-runner.socket enabled active" in out and "bitscan-capread.socket disabled inactive" in out and bool(hb)
          and ss.strip() == "0")
    r.row("CHK-M6-261-rc", vm, None if r.dry else ok,
          f"TASK-138 RC {NEW_RC_SHA[:16]}… reinstalled with dpkg -i: {out.strip()!r}; heartbeat after it {bool(hb)}; "
          f"no inventory failure or refusal in the journal ({ss.strip()}); last_inventory_at {li0}")


def helper_recheck(r: Run) -> None:
    """CHK-M6-261-r (main, 2026-10-26): enable, then disable the capread socket on u2404 again; then,
    as a separate diagnostic, remove the socket file systemd leaves behind (the verbatim unit has no
    RemoveOnStop=) to show the manager side alerts on a removal."""
    vm, aid = "u2404", r.agent.get("u2404", "x")
    helpers = lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("runner_helpers")  # noqa: E731
    since, before = last_audit_id(r), r.metric("bitscan_alerts_total")
    rc, pre = r.on(vm, "ls -la /run/bitscan/; systemctl is-active bitscan-capread.socket")
    r.on(vm, "sudo systemctl enable --now bitscan-capread.socket")
    on = r.wait("helpers [capread]", lambda: helpers() == ["capread"], 360, 10)
    n1 = len(r.alerts("runner_helper_changed", since))
    r.on(vm, "sudo systemctl disable --now bitscan-capread.socket")
    off = r.wait("helpers []", lambda: helpers() == [], 360, 10)
    rc, left = r.on(vm, "systemctl is-active bitscan-capread.socket; ls -la /run/bitscan/capread.sock 2>&1")
    n2 = len(r.alerts("runner_helper_changed", since))
    r.row("CHK-M6-261-r", vm, None if r.dry else (bool(on) and bool(off) and n1 == 1 and n2 == 2),
          f"before: {pre.strip()!r}; enable: ['capread'] {bool(on)}, entries {n1}; disable --now: [] {bool(off)}, entries {n2}; "
          f"after disable: {left.strip()!r} (TS 3.7 unit has no RemoveOnStop=)")
    if not off:
        r.on(vm, "sudo rm -f /run/bitscan/capread.sock")
        gone = r.wait("helpers [] after removing the file", lambda: helpers() == [], 360, 10)
        n3 = len(r.alerts("runner_helper_changed", since))
        r.row("CHK-M6-261-diag", vm, None if r.dry else (bool(gone) and n3 == 2),
              f"diagnostic: leftover socket file removed by hand: [] {bool(gone)}, runner_helper_changed entries {n3} (manager alerts on removal)")
    alert_checks(r, "runner_helper_changed", r.alerts("runner_helper_changed", since), before)


def rerun_modes(r: Run, vm: str, chk: str = "CHK-M6-285-r") -> bool:
    """CHK-M6-285-r: REQ-148 (6) with the glob expanded as root (attempt 7's row ran it as the ssh user)."""
    rc, out = r.on(vm, MODES_SH)
    return r.row(chk, vm, None if r.dry else modes_ok(out), f"as root: {out.strip()}")


# ------------------------------------------------- tester-m6d: one fresh u2404 with the fixed harness
# (decisions 2026-10-26: the CHK-M6-286 canary, CHK-M6-209 and CHK-M6-262 W4 FAILs were harness defects;
# each is re-checked here on a host where the harness never put a token on a command line)


def relogin(r: Run) -> bool:
    """The walk's admin session may have timed out since the walk: sign in again with the walk's
    password file and the TOTP seed in the session file (both 0600 inside the manager host)."""
    st, _ = r.api("GET", "/api/v1/settings")
    if st == 200 or r.dry:
        return r.row("CHK-M6-204", "mgr", None if r.dry else True, f"the walk's admin TOTP session still valid: GET /settings {st}")
    py = ("import json, sys\nsys.path.insert(0, '/opt/m6b')\nimport mgr_api\np = '/home/admin/stage/session.json'\n"
          "st = json.load(open(p))\nc = mgr_api.Client('https://bitscan-mgr.test:8443', '/home/admin/rel/manager-ca.pem')\n"
          "pw = open('/home/admin/stage/admin_pw').read().rstrip('\\n')\n"
          "s, out = c.call('POST', '/api/v1/auth/login', {'username': 'alice', 'password': pw, 'totp_code': mgr_api.next_code(st)}, token='')\n"
          "ok = s == 200 and isinstance(out, dict) and out.get('totp_verified') is True\n"
          "if ok:\n    st['token'] = out['token']\n    mgr_api.write_private(__import__('pathlib').Path(p), json.dumps(st))\n"
          "print('relogin', s, ok)\n")
    if not r.dry:
        (r.work / "relogin.py").write_bytes(py.encode())  # no secret in it
    r.sh(WSL + ["sh", "-c", f"docker cp {r.wsl_work}/relogin.py {CT}:/root/relogin.py"])
    rc, out = r.mgr("python3.12 -I /root/relogin.py; chown admin:admin /home/admin/stage/session.json; chmod 600 /home/admin/stage/session.json; "
                    "rm -f /root/relogin.py")
    st2, _ = r.api("GET", "/api/v1/settings")
    return r.row("CHK-M6-204", "mgr", st2 == 200, f"walk session had expired (GET /settings {st}); password + TOTP sign-in: {out.strip()}; "
                 f"GET /settings now {st2}")


def canary(r: Run, vm: str, label: str) -> bool:
    """CHK-M6-286 (REQ-148 (7)) on a VM, with the fixed harness. tokscan_vm.py reads the whole journal
    (every field) for token-shaped strings, and for the exact value of every bsa_ the host has held
    (copied root-only to /root/m6-tok-<label> at each sweep, never on a command line). A fake
    token-shaped control line, written by python into a 0600 file and logged with `logger -f`, must be
    found, so a scan that reads nothing can't pass. Evidence is masked (prefix and length only)."""
    ip = r.ip.get(vm, "")
    r.vm("put", ip, str(TREE / "e2e" / "m6" / "tokscan_vm.py"), "/tmp/tokscan_vm.py")
    gen = ("import os, secrets; os.umask(0o077); "
           f"open('/root/m6-canary-ctl-{label}', 'w').write('bsa_' + secrets.token_urlsafe(32) + chr(10))")
    rc, out = r.on(vm, "sudo install -m 0600 /tmp/tokscan_vm.py /root/tokscan_vm.py && rm -f /tmp/tokscan_vm.py && "
                   f"(sudo test -s /var/lib/bitscan-agent/token && sudo install -m 0600 /var/lib/bitscan-agent/token /root/m6-tok-{label} || true) && "
                   f"sudo python3 -I -c \"{gen}\" && sudo logger -t m6-canary-ctl -f /root/m6-canary-ctl-{label} && sleep 2 && "
                   "sudo python3 -I /root/tokscan_vm.py --exact '/root/m6-tok-*' --control '/root/m6-canary-ctl-*'", timeout=300)
    lines = [ln for ln in out.strip().split("\n") if ln.startswith("{")]
    try:
        summ = json.loads(lines[-1]) if lines else {}
    except ValueError:
        summ = {}
    ok = (summ.get("journalctl_rc") == 0 and summ.get("entries", 0) > 0 and summ.get("token_shaped") == 0 and summ.get("exact_hits") == 0
          and summ.get("exact_values", 0) >= 1 and summ.get("controls", 0) >= 1 and summ.get("controls_found") == summ.get("controls"))
    return r.row("CHK-M6-286", vm, None if r.dry else ok,
                 f"REQ-148 (7) {vm} journal canary ({label}): full journal (every field) token-shaped {summ.get('token_shaped')}, "
                 f"of which in the agent units {summ.get('token_shaped_agent_units')}; exact bsa_ values checked {summ.get('exact_values')}, hits "
                 f"{summ.get('exact_hits')}; controls found {summ.get('controls_found')}/{summ.get('controls')}; entries {summ.get('entries')}; "
                 f"matches (masked): {lines[:-1][:5]}")


def revoke_once(r: Run, vm: str) -> None:
    """CHK-M6-209 (REQ-146 (9), #81 (a)) with the fixed property check: revoke 204; the agent's next call
    gets 401 and it logs the token re-enrol line exactly once, counted from the revoke on; the unit stays
    active with NRestarts 0 (read by name). User ruling 2026-10-26 (skew, not wait): the "no call for
    10 min after the 401" sub-check PASSED in W4 (u2404 session 2) and is not repeated. The wait for the
    agent's next call is real: it runs on the agent's monotonic timers (a clock move doesn't advance it)
    and a restart is not allowed in this row, which tests restart and NRestarts behaviour."""
    aid = r.agent.get(vm, "x")
    line = "the manager refused the agent token; all loops stopped"
    rc, t0 = r.on(vm, "date +%s")
    t0 = t0.strip() if t0.strip().isdigit() else str(int(time.time()))
    tm = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    count = lambda: r.on(vm, f"sudo journalctl -u bitscan-agent -o cat --no-pager --since @{t0} | grep -c '{line}'; true")[1].strip()  # noqa: E731
    st, _ = r.api("POST", f"/api/v1/agents/{aid}/revoke")
    r.row("CHK-M6-209", vm, None if r.dry else st == 204, f"revoke with the admin TOTP session: {st}")
    t_rev = time.time()
    got = r.wait(f"{vm} 401 and the re-enrol line", lambda: count() not in ("", "0"), 400, 10)
    waited = time.time() - t_rev
    j = count()
    u = r.props(vm, "bitscan-agent", "ActiveState", "NRestarts")
    rc, acc = r.mgr(f"TZ=UTC journalctl -u bitscan-manager -o cat --no-pager --since '{tm}' | grep '\"agent_id\": \"{aid}\"' | "
                    "python3.12 -I -c \"import json,sys; print(sorted(json.loads(l).get('status') for l in sys.stdin if l.startswith('{')))\"")
    sts = acc.strip()
    r.row("CHK-M6-209", vm, None if r.dry else (bool(got) and j == "1" and u["ActiveState"] == "active" and u["NRestarts"] == "0"
          and sts.startswith("[401") and "20" not in sts),
          f"401 on the next call ({waited:.0f} s after the revoke, real wait: agent monotonic timers, no restart allowed in this row): "
          f"manager access-log statuses for the agent since the revoke {sts}; token re-enrol line {j} time(s) since "
          f"the revoke; unit {u} (#81 (a)); the 10-min no-call sub-check is not repeated (PASS in W4 u2404 session 2; user: skew, not wait)")


ACCESS_BY_PATH_PY = r"""import json, sys
aid = sys.argv[1]
pre = "/api/v1/agent/" + aid + "/"
for ln in sys.stdin:
    if not ln.startswith("{"):
        continue
    try:
        d = json.loads(ln)
    except ValueError:
        continue
    if d.get("logger") == "bitscan_manager.access" and str(d.get("path", "")).startswith(pre):
        print(d.get("time"), d.get("status"), d.get("method"), d["path"][len(pre) - 1:])
"""


def access_by_path(r: Run, aid: str, since: str) -> list[str]:
    """Every manager access-log line for /api/v1/agent/<aid>/… since `since` (UTC), refused ones included.
    A refused call carries no agent_id (it is set only after the token check, api/agent/dependencies.py
    L201), so the W4 no-call rows, which matched on agent_id, could not see it; the path always names it."""
    if not r.dry:
        (r.work / "access_by_path.py").write_bytes(ACCESS_BY_PATH_PY.encode())
    r.sh(WSL + ["sh", "-c", f"docker cp {r.wsl_work}/access_by_path.py {CT}:/root/access_by_path.py"])
    rc, out = r.mgr(f"TZ=UTC journalctl -u bitscan-manager -o cat --no-pager --since '{since}' | python3.12 -I /root/access_by_path.py {aid}")
    return [ln.strip() for ln in out.strip().split("\n") if ln.strip()]


def revoke_by_path(r: Run, vm: str) -> bool:
    """CHK-M6-209-r2 (main, 2026-10-27): revoke, then count the manager access-log lines for the agent's
    paths, refused ones included, for the full 10 minutes after its first 401. Expected: exactly the one
    401 (plus any request already in flight), nothing after it. A real wait: what is watched is the agent's
    monotonic timers (a clock move doesn't advance them) and a restart isn't allowed in this row."""
    aid = r.agent.get(vm, "x")
    line = "the manager refused the agent token; all loops stopped"
    rc, t0 = r.on(vm, "date +%s")
    t0 = t0.strip() if t0.strip().isdigit() else str(int(time.time()))
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 2))
    st, _ = r.api("POST", f"/api/v1/agents/{aid}/revoke")
    r.row("CHK-M6-209-r2", vm, None if r.dry else st == 204, f"revoke with the admin TOTP session: {st}")
    first = r.wait("the first 401 for the agent's paths", lambda: [x for x in access_by_path(r, aid, since) if x.split()[1:2] == ["401"]], 420, 10)
    t401 = time.time()
    if not r.dry:
        time.sleep(600)  # real wait: the agent's monotonic timers (see the docstring)
    lines = access_by_path(r, aid, since)
    i401 = next((i for i, x in enumerate(lines) if x.split()[1:2] == ["401"]), None)
    after = lines[i401 + 1:] if i401 is not None else lines
    j = r.on(vm, f"sudo journalctl -u bitscan-agent -o cat --no-pager --since @{t0} | grep -c '{line}'; true")[1].strip()
    u = r.props(vm, "bitscan-agent", "ActiveState", "NRestarts")
    # in flight: a call already sent when the revoke landed may also get 401 within a second or two
    late = [x for x in after if x.split()[1:2] != ["401"]]
    ok = (bool(first) and i401 is not None and not late and len(after) <= 1 and j == "1"
          and u["ActiveState"] == "active" and u["NRestarts"] == "0")
    return r.row("CHK-M6-209-r2", vm, None if r.dry else ok,
                 f"access-log lines for /api/v1/agent/{aid}/… since the revoke, refused included: {lines}; after the first 401 over "
                 f"{(time.time() - t401) / 60:.1f} min (real wait): {after}; token re-enrol line {j}; unit {u}. Not skewed: the agent's "
                 f"timers are monotonic, and a restart is not allowed in this row")


def session_u2404_209(r: Run) -> bool:
    """CHK-M6-209-r2 alone (main, 2026-10-27): fresh u2404 at 1 GB, install, enrol, approve, online, then
    revoke_by_path; restore and turn off."""
    if not manager_up(r) and not r.dry:
        return False
    r.state["mgr.up"] = True
    r.save()
    ok = True
    try:
        if not relogin(r) and not r.dry:
            return False
        tokens(r)
        if not vm_start(r, "u2404", restore=True):
            return False
        vm_prepare(r, "u2404")
        if not w0_recheck(r, "u2404") and not r.dry:
            return False
        install_agent(r, "u2404")
        held_and_approve(r, "u2404")
        aid = r.agent.get("u2404", "x")
        on = r.wait("u2404 online", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "online", 330, 10)
        r.row("CHK-M6-205", "u2404", None if r.dry else bool(on), f"online before the revoke: {bool(on)}")
        r.save()
        ok &= revoke_by_path(r, "u2404")
    finally:
        if r.state.get("u2404.up") or r.dry:
            vm_restore(r, "u2404")
        r.sh(WSL + ["sh", "-c", f"docker rm -f {CT} >/dev/null; docker rmi m6-e2e-mgr:walked >/dev/null; ss -ltnH 'sport = :18443' | wc -l"])
        r.state["mgr.up"] = False
        r.save()
    return ok


def w0_recheck(r: Run, vm: str) -> bool:
    """W0 quick re-check after the Default Switch moved to MGR_IP (main, 2026-10-26): from the VM, the
    manager's /readyz through the portproxy by name and by IP (the leaf's IP SAN, verified with the CA
    file), and the :8444 control (nothing listens there; Windows drops it, so curl times out, rc 28)."""
    rc, out = r.on(vm, "getent hosts bitscan-mgr.test; "
                   "curl -sS --max-time 10 --cacert /etc/bitscan/ca.pem https://bitscan-mgr.test:8443/readyz; echo \" rc=$?\"; "
                   f"curl -sS --max-time 10 --cacert /etc/bitscan/ca.pem https://{MGR_IP}:8443/readyz; echo \" rc=$?\"; "
                   f"curl -sS --max-time 8 -o /dev/null https://{MGR_IP}:8444/ 2>/dev/null; echo \"ctl rc=$?\"")
    lines = [ln.strip() for ln in out.strip().split("\n")]
    ok = (len(lines) >= 4 and lines[0].startswith(f"{MGR_IP} ") and lines[1].endswith('{"status":"ok"} rc=0')
          and lines[2].endswith('{"status":"ok"} rc=0') and lines[3] == "ctl rc=28")
    return r.row("CHK-M6-200-w0r", vm, None if r.dry else ok,
                 f"W0 quick re-check on {SWITCH}: hosts {lines[0] if lines else ''!r}; by name {lines[1] if len(lines) > 1 else ''!r}; "
                 f"by IP (IP SAN) {lines[2] if len(lines) > 2 else ''!r}; :8444 control {lines[3] if len(lines) > 3 else ''!r} (want rc 28, timeout)")


WS_MARK = "/root/m6-ws-marker"
# F2 (reviewer, REQ-148 (5)): paths dropped from the "newer than the marker" list on the VM, with reasons
VM_WS_EXCLUDE = {
    "/var/lib/bitscan-agent": "the agent's own state folder (allowed)",
    "/var/lib/dpkg /var/lib/apt /var/cache/apt /var/cache/debconf /var/log/apt /var/log/dpkg.log": "dpkg/apt state of the install itself",
    "/var/log/journal": "journald",
    "/var/lib/systemd": "systemd's own state (timers, random seed)",
    "/home/bstester /root": "the harness (ssh user files, scans, markers)",
    "/tmp /var/tmp": "harness temp files (the agent unit's /tmp is private)",
    "/var/log/cloud-init.log /var/log/cloud-init-output.log /var/lib/cloud": "cloud-init after boot",
    "/var/log/syslog /var/log/auth.log /var/log/kern.log /var/log/wtmp /var/log/lastlog /var/log/btmp": "rsyslog and login records (sudo, ssh)",
    "/etc/bitscan/agent.yaml /etc/machine-id": "the package's postinst and the harness's machine-id row (root-owned; the agent can't write /etc)",
}
MGR_WS_MARK = "/root/m6-mgr-ws-marker"
MGR_WS_EXCLUDE = {
    "/var/lib/bitscan/audit-queue /var/lib/bitscan/bits/uploaded": "the manager's two ReadWritePaths (allowed)",
    "/var/lib/postgresql /var/log/postgresql": "PostgreSQL's own data and log, written by the postgres server",
    "/var/log/journal": "journald",
    "/var/lib/systemd": "systemd's own state",
    "/root /home/admin": "the harness (session files, tokens, scans, markers)",
    "/opt/m6b": "the test doubles (fake OpenBao, the sink log)",
    "/tmp /var/tmp": "temp files (the manager unit's /tmp is private)",
}


def _ere(paths: list[str]) -> str:
    return "^(" + "|".join(p.replace(".", "\\.") for p in paths) + ")(/|$)"


def _sections(out: str, names: tuple[str, ...]) -> dict[str, list[str]]:
    sec: dict[str, list[str]] = {}
    cur = None
    for ln in out.split("\n"):
        if ln.strip() in names:
            cur = ln.strip()
            sec[cur] = []
        elif cur and ln.strip():
            sec[cur].append(ln.strip())
    return sec


def agent_mounts_ok(rw: list[str]) -> bool:
    """The writable persistent mounts in the agent's namespace ("TARGET FSTYPE" lines): exactly the state
    folder, or the state folder plus the unit's PrivateTmp /tmp and /var/tmp (verbatim TS unit L14)."""
    paths = sorted({x.split()[0] for x in rw if x.split()})
    return paths in (["/var/lib/bitscan-agent"], ["/tmp", "/var/lib/bitscan-agent", "/var/tmp"])


def agent_write_sweep(r: Run, vm: str) -> bool:
    """F2 (reviewer pre-read, REQ-148 (5)): the agent writes only under /var/lib/bitscan-agent. (1) files
    owned by the agent user or group `bitscan` changed since the marker (set before the install), on / and
    /run, outside /var/lib/bitscan-agent and the two systemd-made /run/bitscan sockets: none (the agent's
    uid can only create files it owns); (2) writable persistent mounts in the agent's own mount namespace:
    exactly /var/lib/bitscan-agent; (3) for the record, every file newer than the marker after the
    documented exclusions and the package's own files (dpkg -L)."""
    excl = [p for k in VM_WS_EXCLUDE for p in k.split()]
    cmd = ("sudo bash -c '"
           f"echo OWNED; find / /run -xdev -newer {WS_MARK} \\( -user bitscan -o -group bitscan \\) ! -path \"/var/lib/bitscan-agent*\" "
           # root-owned, group bitscan, made by systemd (the sockets and their folder) or by postinst (agent.yaml)
           "! -path /run/bitscan ! -path /run/bitscan/runner.sock ! -path /run/bitscan/capread.sock ! -path /etc/bitscan/agent.yaml -print 2>/dev/null; "
           "echo STAT; stat -c \"%U:%G %a %n\" /run/bitscan /run/bitscan/* /etc/bitscan/agent.yaml 2>&1; "
           "echo RWMOUNTS; pid=$(systemctl show -p MainPID --value bitscan-agent); "
           "nsenter -t $pid -m findmnt -rn -o TARGET,FSTYPE,OPTIONS | awk \"\\$3 ~ /(^|,)rw(,|$)/ && \\$2 !~ /^(proc|sysfs|tmpfs|devtmpfs|devpts|mqueue|cgroup|cgroup2|securityfs|debugfs|tracefs|bpf|pstore|hugetlbfs|configfs|fusectl|autofs|binfmt_misc|efivarfs|ramfs|nsfs)$/ {print \\$1, \\$2}\"; "
           "echo NEWER; dpkg -L bitscan-agent | LC_ALL=C sort > /root/m6-pkgfiles; "
           f"find / -xdev -newer {WS_MARK} -type f 2>/dev/null | grep -vE \"{_ere(excl)}\" | LC_ALL=C sort | LC_ALL=C comm -23 - /root/m6-pkgfiles; "
           # the unit's private /tmp and /var/tmp (PrivateTmp=yes, verbatim TS unit L14): writable but private,
           # so they are allowed as mounts and listed by entry count instead (main, 2026-10-27)
           "echo PRIVTMP; for d in /tmp/systemd-private-*-bitscan-agent.service-*/tmp /var/tmp/systemd-private-*-bitscan-agent.service-*/tmp; do "
           "echo \"$d $(find $d -mindepth 1 2>/dev/null | wc -l)\"; done; "
           "rm -f /root/m6-pkgfiles; echo END'")
    rc, out = r.on(vm, cmd, timeout=600)
    sec = _sections(out, ("OWNED", "STAT", "RWMOUNTS", "NEWER", "PRIVTMP", "END"))
    owned, rw, newer, st = sec.get("OWNED", []), sec.get("RWMOUNTS", []), sec.get("NEWER", []), sec.get("STAT", [])
    priv = sec.get("PRIVTMP", [])
    ok = "END" in sec and not owned and agent_mounts_ok(rw) and bool(st) and all(x.startswith("root:") for x in st)
    return r.row("CHK-M6-284-ws", vm, None if r.dry else ok,
                 f"REQ-148 (5) agent write sweep since the pre-install marker: files owned by bitscan outside /var/lib/bitscan-agent "
                 f"{owned[:10]}; the excluded group-bitscan paths are root-owned {st}; writable persistent mounts in the agent's namespace {rw} "
                 f"(/tmp and /var/tmp are the unit's PrivateTmp copies; entries {priv}); other files newer than the marker after "
                 f"exclusions and the package's own files ({len(newer)}): {newer[:25]}; exclusions: {VM_WS_EXCLUDE}")


def manager_secret_canary(r: Run) -> bool:
    """F3 (reviewer, REQ-140 (7)): check_manager_host.sh's secret patterns over the whole manager journal
    (every field) and the sink log: the 3 DB passwords, the admin password and the vault token the walk used
    (one file each in its 0600 secrets folder), plus a line of the served tls.key and of the walk's own key.
    The values reach a root-only pattern file through stdin, never a command line; blank lines are dropped
    (an empty -F pattern would match everything)."""
    r.sh(WSL + ["sh", "-c", "for f in /root/m6t/w4walk/secrets/*; do cat \"$f\"; echo; done | sed '/^$/d' | docker exec -i " + CT
                + " bash -c 'umask 077; cat > /root/canary.pat'"])
    r.sh(WSL + ["sh", "-c", "awk 'NR==2' /root/m6t/w4walk/pki/manager.key | docker exec -i " + CT + " bash -c 'cat >> /root/canary.pat'"])
    rc, out = r.mgr("awk 'NR==2' /etc/bitscan/secrets/tls.key >> /root/canary.pat; sed -i '/^$/d' /root/canary.pat; echo pat=$(grep -c . /root/canary.pat); "
                    "echo journal=$(journalctl --no-pager -o json | grep -cFf /root/canary.pat); "
                    "echo sink=$(grep -cFf /root/canary.pat /opt/m6b/sink.jsonl); echo sinklines=$(wc -l < /opt/m6b/sink.jsonl); "
                    "echo ctl=$(grep -cFf /root/canary.pat /etc/bitscan/secrets/app.dsn /etc/bitscan/secrets/vault.token | grep -c ':[1-9]'); "
                    "rm -f /root/canary.pat")
    v = dict(re.findall(r"^(\w+)=(\d+)$", out, re.M))
    ok = v.get("pat") == "7" and v.get("journal") == "0" and v.get("sink") == "0" and v.get("ctl") == "2" and int(v.get("sinklines", "0")) > 0
    return r.row("CHK-M6-286-mgr-secrets", "mgr", None if r.dry else ok,
                 f"REQ-140 (7) manager journal (every field) / sink: lines matching a secret value {v.get('journal')} / {v.get('sink')} "
                 f"(sink lines {v.get('sinklines')}); patterns {v.get('pat')} (3 DB passwords, admin password, vault token, 2 key lines); "
                 f"control: the patterns match app.dsn and vault.token ({v.get('ctl')}/2)")


def manager_write_sweep(r: Run) -> bool:
    """F3 (reviewer, REQ-140 (5), plan section 4 phase C): over the session the manager writes only under
    its two ReadWritePaths. (1) files owned by bitscan-manager changed since the session marker, outside
    them: none; (2) every other file changed since the marker, after the documented exclusions: none."""
    excl = [p for k in MGR_WS_EXCLUDE for p in k.split()]
    rc, out = r.mgr(f"echo OWNED; find / -xdev -newer {MGR_WS_MARK} -user bitscan-manager ! -path '/var/lib/bitscan/audit-queue*' "
                    f"! -path '/var/lib/bitscan/bits/uploaded*' -print 2>/dev/null; echo ALLOWED; "
                    f"find /var/lib/bitscan -newer {MGR_WS_MARK} -type f 2>/dev/null; echo NEWER; "
                    f"find / -xdev -newer {MGR_WS_MARK} -type f 2>/dev/null | grep -vE '{_ere(excl)}' | sort; echo END")
    sec = _sections(out, ("OWNED", "ALLOWED", "NEWER", "END"))
    ok = "END" in sec and not sec.get("OWNED") and not sec.get("NEWER")
    return r.row("CHK-M6-055-e2e", "mgr", None if r.dry else ok,
                 f"REQ-140 (5) manager-host write sweep over the session: files owned by bitscan-manager outside the two ReadWritePaths "
                 f"{sec.get('OWNED', [])[:10]}; files changed inside /var/lib/bitscan {sec.get('ALLOWED', [])[:10]}; other changed files after "
                 f"exclusions {sec.get('NEWER', [])[:25]}; exclusions: {MGR_WS_EXCLUDE}")


def modes_control(r: Run, vm: str) -> bool:
    """Test fixture (main, 2026-10-26): the fixed matcher must go red on a real host. chmod 0644 the
    token, check (want red), restore 0600, check (want green). The mode change lasts a few seconds."""
    r.on(vm, "sudo chmod 0644 /var/lib/bitscan-agent/token")
    rc, bad = r.on(vm, MODES_SH)
    r.on(vm, "sudo chmod 0600 /var/lib/bitscan-agent/token")
    rc, good = r.on(vm, MODES_SH)
    red, green = modes_ok(bad), modes_ok(good)
    tok = lambda s: [ln for ln in s.split("\n") if ln.strip().endswith("/var/lib/bitscan-agent/token")]  # noqa: E731
    return r.row("CHK-M6-285-ctl", vm, None if r.dry else (not red and green),
                 f"test fixture: token chmod 0644 -> modes_ok {red} (want False) {tok(bad)}; restored 0600 -> modes_ok {green} (want True) {tok(good)}")


def vm_restore(r: Run, vm: str) -> bool:
    name = VMS[vm][0]
    r.vm("stop", name)
    rc, st = r.vm("restore", name)
    r.state[f"{vm}.up"] = False
    return r.row("CHK-M6-212", vm, None if r.dry else st.strip().endswith("Off"), f"restored to clean and off: {st.strip()}")


def session_u2404_fresh(r: Run) -> bool:
    """tester-m6d: install the TASK-138 RC on a clean u2404 (1 GB), enrol, approve, then the canary
    (CHK-M6-286), the machine-id re-enrolment (CHK-M6-262) and the revoke (CHK-M6-209), then the
    canary again over the whole session, the manager-side sweep, and the restore. 262 runs before 209:
    after a revoke the agent has no valid token, so a machine-id change can't reach the manager."""
    if not manager_up(r) and not r.dry:
        return False
    r.state["mgr.up"] = True
    r.save()
    ok = True
    try:
        if not relogin(r) and not r.dry:
            return False
        tokens(r)
        r.mgr(f"touch {MGR_WS_MARK}")   # F3: the manager-host write sweep covers the session from here
        r.save()
        if not vm_start(r, "u2404", restore=True):
            return False
        vm_prepare(r, "u2404")
        if not w0_recheck(r, "u2404") and not r.dry:  # the new switch address must work before anything else
            return False
        r.on("u2404", f"sudo touch {WS_MARK}")  # F2: the agent write sweep covers everything after the install starts
        install_agent(r, "u2404")       # CHK-M6-202, -203, -285 (fixed check)
        held_and_approve(r, "u2404")    # CHK-M6-204, -205
        aid = r.agent.get("u2404", "x")
        t_appr = time.time()
        on = r.wait("u2404 online", lambda: (r.api("GET", f"/api/v1/agents/{aid}")[1] or {}).get("status") == "online", 330, 10)
        r.row("CHK-M6-205", "u2404", None if r.dry else bool(on), f"online {time.time() - t_appr:.0f} s after approval (<= 330)")
        inventory(r, "u2404")           # CHK-M6-206
        r.save()
        ok &= agent_write_sweep(r, "u2404")  # F2: after install, enrol, approve and the first inventory
        ok &= rerun_modes(r, "u2404", "CHK-M6-285-r2")  # main: the whole-line matcher, as its own row
        ok &= modes_control(r, "u2404")                  # main: negative control (0644 red, 0600 green)
        ok &= canary(r, "u2404", "after-approve")
        machine_id(r, "u2404")          # CHK-M6-262
        rerun_modes(r, "u2404", "CHK-M6-285-r3")  # the fixed check again, on the re-enrolled token
        revoke_once(r, "u2404")         # CHK-M6-209
        ok &= canary(r, "u2404", "end")
        manager_sweep(r, None)
        ok &= manager_secret_canary(r)  # F3 (REQ-140 (7))
        ok &= manager_write_sweep(r)    # F3 (REQ-140 (5))
    finally:
        if r.state.get("u2404.up") or r.dry:
            vm_restore(r, "u2404")
        r.sh(WSL + ["sh", "-c", f"docker rm -f {CT} >/dev/null; docker rmi m6-e2e-mgr:walked >/dev/null; ss -ltnH 'sport = :18443' | wc -l"])
        r.state["mgr.up"] = False
        r.save()
    return ok


SESSIONS = {"u2404-209": session_u2404_209, "u2404-fresh": session_u2404_fresh, "u2404-1": session_u2404_1, "u2204": session_u2204, "u2204-cont": session_u2204_cont, "u2404-2": session_u2404_2,
            "rerun-leaf": rerun_leaf, "rerun-modes-u2404": lambda r: rerun_modes(r, "u2404")}


def main() -> int:
    global NEED_MB
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--session", required=True, choices=list(SESSIONS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--walk-pki", default="/root/m6t/w4walk/pki", help="WSL path of the manager_walk.py run's pki folder (its CA signs the new leaf)")
    ap.add_argument("--rel", choices=("relout", "final"), default="relout",
                    help="RC source: relout = tester-m6b's release run (3b5c98a0…, W4); final = CHK-M6-319-final (d98ef8c3…, TASK-138)")
    ap.add_argument("--need-mb", type=int, default=NEED_MB, help="free Windows memory needed before each Start-VM")
    a = ap.parse_args()
    NEED_MB = a.need_mb
    a.work.mkdir(parents=True, exist_ok=True)
    (a.work / "secrets").mkdir(mode=0o700, exist_ok=True)
    (a.work / "rows.jsonl").touch()
    if not a.walk_pki.startswith("/root/"):
        print(f"--walk-pki must be a WSL path under /root (got {a.walk_pki!r}; run with MSYS_NO_PATHCONV=1 from Git Bash)")
        return 2
    r = Run(a.work, a.dry_run, walk_pki=a.walk_pki)
    if a.rel == "final":
        r.rel, r.deb_sha = REL_FINAL_WSL, DEB_SHA_FINAL
    import hashlib
    print(f"harness {__file__} sha256 {hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]}", flush=True)
    r.load()
    if a.session.startswith("rerun-"):  # single re-run rows against what is already up; no preflight, no VM start
        ok = SESSIONS[a.session](r)
        r.save()
        return 0 if ok else 1
    if not preflight(r):
        print("preflight failed: session not started (stop rule; nothing was changed)")
        return 1
    if a.dry_run:
        print("== dry run: the steps below would run; no VM, container, port or API is touched")
    done = SESSIONS[a.session](r)
    r.save()
    res = [x["result"] for x in r.rows]
    print(f"session {a.session} {'done' if done else 'STOPPED'}: rows {res.count('PASS')}/{len(res)} passed, "
          f"{res.count('FAIL')} failed, {res.count('NOT RUN')} not run")
    return 1 if ("FAIL" in res or not done) else 0


if __name__ == "__main__":
    sys.exit(main())
