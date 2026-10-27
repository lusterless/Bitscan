"""Manager install walk (TP-M6-03, CHK-M6-042..058) on a fresh systemd Ubuntu 24.04 container.

Runs in WSL as root with Docker:
  python3 -I e2e/m6/manager_walk.py --tree TREE --rel RELDIR --work WORK [--keep]

TREE is a copy of the M6 tree (the runbook is read from it), RELDIR holds the
release files the runbook lists (wheel, requirements copy, four units) and the
`SHA256SUMS` text as the release page would show it. Every ```sh block of
deploy/runbooks/manager-install.md runs **verbatim**, in order, as the
administrator `admin` with sudo in the release folder; the only substitution is
the example host name (`mgr.example` -> `bitscan-mgr.test`). Text steps are done
the way the runbook says: blocks saved as files, `sudoedit` for every secret and
config file (SUDO_EDITOR copies a staged file, so sudoedit itself keeps the
mode), passwords typed at prompts through a pty (psql `\\password`,
`users create-admin`, the apt confirmation). OpenBao and the audit sink are the
test doubles (#93). Rows go to WORK/out/walk.jsonl; the container is
`m6b-host` (image `m6b-mgrhost`, e2e/m6/manager-host.Dockerfile), with no
published port, and is removed at the end unless --keep.
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import secrets
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

CT, IMG, NET = "m6b-host", "m6b-mgrhost", "m6b-net"
URL = "https://bitscan-mgr.test:8443"
REL = "/home/admin/rel"
TRAP = "trap 'echo \"!! rc=$? at: $BASH_COMMAND\"' ERR\n"
ROWS: list[dict] = []
OUT = Path()
SECRET_VALUES: list[str] = []


def mask(text: str) -> str:
    for s in SECRET_VALUES:
        if s:
            text = text.replace(s, "<secret>")
    return re.sub(r"\bbs[uaek]_[A-Za-z0-9_-]{8,}", lambda m: m.group(0)[:4] + "<masked>", text)


def row(chk: str, step: str, expected: str, actual: str, ok: bool) -> bool:
    r = {"chk": chk, "step": step, "expected": expected, "actual": mask(actual)[-1500:], "ok": bool(ok)}
    ROWS.append(r)
    with (OUT / "walk.jsonl").open("a") as f:
        f.write(json.dumps(r) + "\n")
    print(("PASS " if ok else "FAIL ") + chk + " " + step + " :: " + mask(actual).strip().replace("\n", " | ")[-400:], flush=True)
    return bool(ok)


def run(argv: list[str], stdin: str | None = None, timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(argv, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode, p.stdout.replace("\r", "")


def sh(cmd: str, user: str = "admin", env: dict[str, str] | None = None, stdin: str | None = None,
       timeout: int = 900, wd: str = REL) -> tuple[int, str]:
    argv = ["docker", "exec", "-i", "-u", user, "-w", wd]
    for k, v in (env or {}).items():
        argv += ["-e", f"{k}={v}"]
    return run(argv + [CT, "bash", "-o", "pipefail", "-c", TRAP + cmd], stdin, timeout)


def root(cmd: str, **kw: object) -> tuple[int, str]:
    return sh(cmd, user="root", wd="/root", **kw)  # type: ignore[arg-type]


def pty_run(cmd: str, script: list[tuple[str, str]], timeout: int = 900) -> tuple[int, str, bool]:
    """Run cmd in the container under a pty as admin; answer prompts in order."""
    argv = ["docker", "exec", "-it", "-u", "admin", "-w", REL, CT, "bash", "-c", cmd]
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(argv[0], argv)
    buf, log, i, end = "", "", 0, time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                data = os.read(fd, 4096).decode(errors="replace")
            except OSError:
                break
            if not data:
                break
            buf += data
            log += data
        if i < len(script) and re.search(script[i][0], buf):
            time.sleep(0.3)
            os.write(fd, script[i][1].encode() + b"\n")
            buf, i = "", i + 1
    else:
        os.kill(pid, 9)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), log.replace("\r", ""), i == len(script)


def blocks(md: str) -> list[tuple[str, str, str]]:
    """(section, lang, body) for every fenced block, in order."""
    out, sec, cur, lang = [], "", None, ""
    for line in md.split("\n"):
        if line.startswith("## "):
            sec = line[3:].split(".")[0]
        s = line.strip()
        if cur is None and re.fullmatch(r"```[a-z]+", s):
            cur, lang = [], s[3:]
        elif cur is not None and s == "```":
            out.append((sec, lang, "\n".join(cur)))
            cur = None
        elif cur is not None:
            cur.append(line)
    return out


def sub(body: str) -> str:
    return body.replace("mgr.example", "bitscan-mgr.test")


def stage(name: str, content: str) -> None:
    rc, out = sh(f"umask 077; cat > /home/admin/stage/{name}", stdin=content, wd="/home/admin")
    assert rc == 0, out


def sudoedit(path: str, staged: str, mode: str = "replace") -> tuple[int, str]:
    return sh(f"sudoedit {path}", env={"SUDO_EDITOR": "/home/admin/bin/m6b-editor", "M6B_STAGE": staged, "M6B_MODE": mode})


def snapshot(tag: str) -> str:
    prune = " -o ".join(f"-path {p}" for p in (
        "/proc", "/sys", "/dev", "/run", "/tmp", "/var/tmp", "/var/lib/postgresql", "/var/log/journal",
        "/var/log/postgresql", "/opt/m6b", "/home/admin", "/var/cache/apt", "/var/lib/apt", "/root"))
    rc, out = root(f"find / -xdev \\( {prune} \\) -prune -o -printf '%p\\t%T@\\t%s\\t%m\\t%u:%g\\n' | sort > /root/sweep-{tag}.txt; wc -l < /root/sweep-{tag}.txt")
    return out.strip()


def openssl_pki(pki: Path) -> None:
    pki.mkdir(parents=True, exist_ok=True)
    os.chmod(pki, 0o700)
    def ossl(*a: str) -> None:
        subprocess.run(["openssl", *a], check=True, capture_output=True)
    ossl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "30",
         "-subj", "/CN=m6b test CA", "-keyout", str(pki / "ca.key"), "-out", str(pki / "ca.pem"),
         "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    for name, san in (("manager", "DNS:bitscan-mgr.test"), ("manager-new", "DNS:bitscan-mgr.test"),
                      ("doubles", "DNS:openbao.test,DNS:audit.test,IP:127.0.0.1")):
        ext = pki / f"{name}.ext"
        ext.write_text(f"subjectAltName={san}\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=serverAuth\n")
        ossl("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-subj", f"/CN={name}",
             "-keyout", str(pki / f"{name}.key"), "-out", str(pki / f"{name}.csr"))
        ossl("x509", "-req", "-in", str(pki / f"{name}.csr"), "-CA", str(pki / "ca.pem"), "-CAkey", str(pki / "ca.key"),
             "-CAcreateserial", "-days", "30", "-extfile", str(ext), "-out", str(pki / f"{name}.crt"))


def setup(tree: Path, rel: Path, work: Path) -> dict[str, str]:
    sec = work / "secrets"
    if sec.exists():
        shutil.rmtree(sec)
    sec.mkdir(mode=0o700, parents=True)
    vals = {k: secrets.token_urlsafe(24) for k in ("pg_app", "pg_retention", "pg_migrate", "admin_pw")}
    vals["vault_token"] = "m6b-vault-" + secrets.token_hex(16)
    for k, v in vals.items():
        (sec / k).write_text(v + "\n")
        os.chmod(sec / k, 0o600)
    SECRET_VALUES.extend(vals.values())
    openssl_pki(work / "pki")
    SECRET_VALUES.append((work / "pki" / "manager.key").read_text().split("\n")[1])
    run(["docker", "rm", "-f", CT])
    if run(["docker", "network", "inspect", NET])[0] != 0:
        run(["docker", "network", "create", NET])
    rc, out = run(["docker", "run", "-d", "--name", CT, "--hostname", "bitscan-mgr", "--privileged", "--cgroupns=private",
                   "--tmpfs", "/run", "--tmpfs", "/run/lock", "--network", NET, "--network-alias", "bitscan-mgr.test",
                   "--add-host", "bitscan-mgr.test:127.0.0.1", "--add-host", "openbao.test:127.0.0.1",
                   "--add-host", "audit.test:127.0.0.1", "--memory", "1500m", IMG])
    assert rc == 0, out
    for _ in range(60):
        if root("systemctl is-system-running")[1].strip() in ("running", "degraded"):
            break
        time.sleep(1)
    # environment: the doubles' and the manager's test CA in the system store (runbook §1 prerequisite)
    for src, dst in ((work / "pki" / "ca.pem", "/usr/local/share/ca-certificates/m6b-test-ca.crt"),):
        run(["docker", "cp", str(src), f"{CT}:{dst}"])
    root("update-ca-certificates >/dev/null; install -d -m 0700 -o admin -g admin /home/admin/stage /home/admin/bin; install -d -o admin -g admin /home/admin/rel; install -d -m 0755 /opt/m6b")
    for f in rel.iterdir():
        run(["docker", "cp", str(f), f"{CT}:{REL}/{f.name}"])
    for f, name in ((work / "pki" / "manager.crt", "manager.crt"), (work / "pki" / "manager.key", "manager.key"),
                    (work / "pki" / "ca.pem", "manager-ca.pem")):
        run(["docker", "cp", str(f), f"{CT}:{REL}/{name}"])
    root(f"chown -R admin:admin {REL}; chmod 0600 {REL}/manager.key")
    editor = ('#!/bin/sh\n# SUDO_EDITOR for the walk: copy the staged content into the file sudoedit opened\nset -e\n'
              'case "${M6B_MODE:-replace}" in\n'
              '  replace) cat "/home/admin/stage/$M6B_STAGE" > "$1" ;;\n'
              '  prepend) { cat "/home/admin/stage/$M6B_STAGE"; cat "$1"; } > "$1.m6b" && cat "$1.m6b" > "$1" && rm -f "$1.m6b" ;;\n'
              'esac\n')
    sh("cat > /home/admin/bin/m6b-editor && chmod 0700 /home/admin/bin/m6b-editor", stdin=editor, wd="/home/admin")
    for f in ("doubles.py",):
        run(["docker", "cp", str(tree / "e2e" / "m6" / f), f"{CT}:/opt/m6b/{f}"])
    for f in ("mgr_api.py",):
        run(["docker", "cp", str(tree / "e2e" / "m6" / f), f"{CT}:/opt/m6b/{f}"])
    run(["docker", "cp", str(tree / "manager" / "tests" / "fake_vault.py"), f"{CT}:/opt/m6b/fake_vault.py"])
    for f in ("doubles.crt", "doubles.key"):
        run(["docker", "cp", str(work / "pki" / f), f"{CT}:/opt/m6b/{f}"])
    run(["docker", "cp", str(sec / "vault_token"), f"{CT}:/opt/m6b/vault.token"])
    root("chmod 0600 /opt/m6b/doubles.key /opt/m6b/vault.token")
    return vals


def api(*args: str, timeout: int = 120) -> tuple[int, str]:
    return sh("python3.12 -I /opt/m6b/mgr_api.py " + " ".join(args), wd="/home/admin", timeout=timeout)


def walk(tree: Path, vals: dict[str, str], work: Path) -> None:  # noqa: PLR0915
    md = (tree / "deploy" / "runbooks" / "manager-install.md").read_text()
    b = blocks(md)
    langs = [lang for _, lang, _ in b]
    row("CHK-M6-042", "runbook block layout", "22 fenced blocks (17 sh)", f"{len(b)} blocks, {langs.count('sh')} sh", len(b) == 22 and langs.count("sh") == 17)
    B = {i + 1: (s, lang, body) for i, (s, lang, body) in enumerate(b)}

    # CHK-M6-042 probe on this host
    rc, out = root("echo m6b-probe > /root/p.cred; chmod 600 /root/p.cred; systemd-run --wait --pipe -q -p DynamicUser=yes "
                   "-p LoadCredential=c:/root/p.cred -p ProtectSystem=strict -p PrivateTmp=yes -p ProtectHome=yes "
                   "-p NoNewPrivileges=yes -p CapabilityBoundingSet= bash -c 'id -u; stat -c \"%A %a\" \"$CREDENTIALS_DIRECTORY\" \"$CREDENTIALS_DIRECTORY/c\"; "
                   "cat \"$CREDENTIALS_DIRECTORY/c\"; findmnt -no FSTYPE,OPTIONS \"$CREDENTIALS_DIRECTORY\"; cat /root/p.cred 2>&1 | head -1'; rm -f /root/p.cred")
    row("CHK-M6-042", "probe: DynamicUser= and LoadCredential= work under the units' sandbox", "dynamic uid, credential readable, source denied",
        out, "m6b-probe" in out and "Permission denied" in out and re.search(r"^6\d{4}$", out, re.M) is not None)

    # §2 release check
    rc, out = sh(sub(B[2][2]))
    oks = re.findall(r"^\S+: OK$", out, re.M)
    row("CHK-M6-043", "§2 sha256sum -c --ignore-missing SHA256SUMS", "rc 0, OK for each of the six files", f"rc {rc}; {out}", rc == 0 and len(oks) == 6 and "FAILED" not in out)
    rc, out = sh("rm -rf /tmp/relmod && cp -r . /tmp/relmod && cd /tmp/relmod && printf 'X' | dd of=bitscan_manager-0.1.0-py3-none-any.whl bs=1 seek=100 conv=notrunc status=none && "
                 + sub(B[2][2]) + "; echo rc=$?; rm -rf /tmp/relmod")
    row("CHK-M6-043", "§2 one byte changed in the wheel", "FAILED line, non-zero rc", out, "FAILED" in out and "rc=1" in out)

    # §3 PostgreSQL
    rc, out, done = pty_run(sub(B[3][2]), [(r"\[Y/n\]", "Y")], timeout=1200)
    if "Unable to locate package" in out or rc != 0:
        row("CHK-M6-044", "§3 apt install on the fresh host, as written", "rc 0", f"rc {rc}; {out[-600:]}", False)
        rc2, o2 = sh("sudo apt-get update -qq", timeout=900)
        rc, out, done = pty_run(sub(B[3][2]), [(r"\[Y/n\]", "Y")], timeout=1200)
        row("CHK-M6-044", "§3 apt install after `sudo apt update` (not in the runbook)", "rc 0", f"update rc {rc2}; install rc {rc}; {out[-300:]}", rc == 0)
    else:
        row("CHK-M6-044", "§3 apt install (answered Y at the prompt)", "rc 0", f"rc {rc}; {out[-300:]}", rc == 0)
    rc, out = sh(sub(B[4][2]))
    row("CHK-M6-044", "§3 SHOW ssl", "on", out, rc == 0 and out.strip() == "on")
    sql = B[5][2] + "\n"
    rc, out = sh("cat > bitscan-bootstrap.sql", stdin=sql)
    rc, out = sh(sub(B[6][2]))
    row("CHK-M6-044", "§3 Bootstrap run once as the superuser", "rc 0, no ERROR", f"rc {rc}; {out}", rc == 0 and "ERROR" not in out)
    assert B[7][2].strip() == "sudo -u postgres psql -X" and B[8][2].startswith("\\password bitscan_app")
    script: list[tuple[str, str]] = []
    for line in B[8][2].split("\n"):
        line = line.strip()
        m = re.fullmatch(r"\\password (\w+)", line)
        if m:
            pw = vals["pg_" + m.group(1).removeprefix("bitscan_")]
            script += [(r"=# $", line), (r"Enter new password[^:]*: $", pw), (r"Enter it again: $", pw)]
        elif line == "\\q":
            script.append((r"=# $", "\\q"))
    rc, out, done = pty_run(B[7][2], script, timeout=120)
    row("CHK-M6-044", "§3 \\password for the three roles at the psql prompt", "rc 0, all prompts answered", f"rc {rc}; done {done}; {out[-400:]}", rc == 0 and done)
    rc, hist = root("cat /var/lib/postgresql/.psql_history 2>/dev/null; true")
    row("CHK-M6-044", "§3 no password in psql history", "no password text", hist or "(no history file)",
        not any(vals[k] in hist for k in ("pg_app", "pg_retention", "pg_migrate")))
    stage("pg_hba.lines", B[9][2] + "\n")
    rc, out = sudoedit("/etc/postgresql/16/main/pg_hba.conf", "pg_hba.lines", "prepend")
    rc2, hba = root("head -5 /etc/postgresql/16/main/pg_hba.conf; stat -c '%U:%G %a' /etc/postgresql/16/main/pg_hba.conf")
    row("CHK-M6-044", "§3 pg_hba.conf lines above every other line (sudoedit)", "the four lines first; postgres:postgres 640", f"rc {rc}; {hba}",
        rc == 0 and hba.split("\n")[0].startswith("# Bitscan roles") and "postgres:postgres 640" in hba)
    rc, out = sh(sub(B[10][2]))
    row("CHK-M6-044", "§3 reload; pg_hba_file_rules errors", "rc 0, prints nothing", f"rc {rc}; [{out}]", rc == 0 and out.strip() == "")
    for role in ("bitscan_app", "bitscan_retention", "bitscan_migrate"):
        cmd = sub(B[11][2]).replace("user=bitscan_app", f"user={role}")
        rc, out = sh(cmd + " </dev/null")
        row("CHK-M6-045", f"§3 {role} sslmode=disable over TCP", "refused: pg_hba.conf rejects connection ... no encryption, no password asked",
            f"rc {rc}; {out}", rc != 0 and "rejects connection" in out and "no encryption" in out and "password" not in out.lower())
        rc, out = sh(f"psql -X -h /var/run/postgresql -d bitscan -U {role} </dev/null")
        row("CHK-M6-045", f"{role} over the Unix socket", "refused by pg_hba.conf", f"rc {rc}; {out}", rc != 0 and "rejects connection" in out)
        pw = vals["pg_" + role.removeprefix("bitscan_")]
        stage("pgpass", f"127.0.0.1:5432:bitscan:{role}:{pw}\n")
        rc, out = sh(f"PGPASSFILE=/home/admin/stage/pgpass psql -X -At \"host=127.0.0.1 dbname=bitscan user={role} sslmode=require\" -c 'select ssl from pg_stat_ssl where pid = pg_backend_pid()' </dev/null")
        row("CHK-M6-045", f"{role} sslmode=require to 127.0.0.1", "accepted, ssl t", f"rc {rc}; {out}", rc == 0 and out.strip() == "t")
        rc, out = sh(f"PGPASSFILE=/home/admin/stage/pgpass psql -X -At \"host=127.0.0.1 dbname=postgres user={role} sslmode=require\" -c 'select 1' </dev/null")
        row("CHK-M6-045", f"{role} to another database (postgres)", "refused by pg_hba.conf", f"rc {rc}; {out}", rc != 0 and "rejects connection" in out)
    sh("rm -f /home/admin/stage/pgpass")

    # §4 user and folders
    rc, out = sh(sub(B[12][2]))
    rc2, u = root("getent passwd bitscan-manager; getent group bitscan-manager; test -e /nonexistent && echo HOME-EXISTS; true")
    row("CHK-M6-046", "§4 system user and folders", "rc 0; shell /usr/sbin/nologin, home /nonexistent (absent)", f"rc {rc}; {u}",
        rc == 0 and u.split("\n")[0].endswith(":/nonexistent:/usr/sbin/nologin") and "HOME-EXISTS" not in u)

    # §5 config and secrets
    rc, out = sh(sub(B[13][2]))
    rc2, m = root("find /etc/bitscan -printf '%u:%g %m %s %p\\n' | sort -k4")
    row("CHK-M6-047", "§5 files created empty with their mode before content", "rc 0; 0755 /etc/bitscan, 0700 secrets, 0600 x7 all size 0", f"rc {rc}; {m}",
        rc == 0 and m.count("root:root 600 0 ") == 7 and "root:root 700 " in m and "root:root 755 " in m)
    assert B[14][2].startswith("BITSCAN_VAULT_ADDR=")
    env_text = ("BITSCAN_VAULT_ADDR=https://openbao.test:18200\nBITSCAN_TOTP_KEY_REF=bitscan-totp\n"
                "BITSCAN_AUDIT_SINK=https://audit.test:18300/bitscan\n"
                "# Optional: BITSCAN_LISTEN=0.0.0.0:8443 and BITSCAN_BITS_DIR=/var/lib/bitscan/bits\n")
    stage("manager.env", env_text)
    rc, out = sudoedit("/etc/bitscan/manager.env", "manager.env")
    row("CHK-M6-047", "§5 manager.env written with sudoedit (test-double addresses; #93)", "rc 0", f"rc {rc}; {out}", rc == 0)
    for f, role in (("app.dsn", "app"), ("retention.dsn", "retention"), ("migrate.dsn", "migrate")):
        stage(f, f"host=127.0.0.1 port=5432 dbname=bitscan user=bitscan_{role} password={vals['pg_' + role]} sslmode=require\n")
        rc, out = sudoedit(f"/etc/bitscan/secrets/{f}", f)
        row("CHK-M6-047", f"§5 {f} written with sudoedit (the table's same-host line)", "rc 0", f"rc {rc}; {out}", rc == 0)
    row("CHK-M6-047", "§5 database on another host (postgres-ca.pem, verify-full)", "NOT RUN: same-host path walked (#97 variant)", "not run", True)
    stage("vault.token", vals["vault_token"] + "\n")
    rc, out = sh(sub(B[16][2]), env={"SUDO_EDITOR": "/home/admin/bin/m6b-editor", "M6B_STAGE": "vault.token"})
    rc2, _ = sh("rm -f manager.key")
    rc3, m = root("find /etc/bitscan -printf '%u:%g %m %p\\n' | sort -k3; cmp /etc/bitscan/secrets/tls.crt /home/admin/rel/manager.crt && echo CRT-SAME")
    row("CHK-M6-047", "§5 cert, key (cp onto the 0600 files) and vault.token (sudoedit); working key deleted",
        "rc 0; every file still root:root 600", f"rc {rc}; {m}", rc == 0 and m.count("root:root 600 ") == 7 and "CRT-SAME" in m)
    rc, envf = root("grep -v '^#' /etc/bitscan/manager.env")
    row("CHK-M6-047", "§5 manager.env holds no secret and no *_FILE", "only the three settings", envf,
        not any(v in envf for v in vals.values()) and "_FILE" not in envf and "password" not in envf.lower())
    sh("rm -f /home/admin/stage/*.dsn /home/admin/stage/vault.token")

    # §6 software
    rc, out = sh(sub(B[17][2]), timeout=1200)
    helpok = all(w in out for w in ("serve", "users", "migrate", "maintain"))
    findout = out.split("bitscan-manager --help")[-1] if "--help" in out else out
    rc2, perm = root("find /opt/bitscan-manager ! -type l -perm /022 | head; readlink /usr/bin/bitscan-manager; stat -c '%U:%G %a' /opt/bitscan-manager")
    row("CHK-M6-048", "§6 venv from the hashed lock and the wheel, link, --help, find -perm /022", "rc 0; help lists serve, users, db migrate, db maintain; find prints nothing",
        f"rc {rc}; {out[-900:]} || {perm}", rc == 0 and helpok and "!! rc=" not in out and perm.split("\n")[0] == "/opt/bitscan-manager/bin/bitscan-manager")

    # §7 units
    rc, out = sh(sub(B[18][2]))
    row("CHK-M6-049", "§7 units installed, daemon-reload, systemd-analyze verify", "rc 0, verify prints nothing", f"rc {rc}; [{out}]", rc == 0 and out.strip() == "")

    # §8 migrate and maintain
    rc, out = sh(sub(B[19][2]))
    head = re.findall(r"\b(m\d{4}\w*)\b", out)
    want_head = sorted(re.findall(r'^revision: str = "(\w+)"', "\n".join(p.read_text() for p in (tree / "manager/bitscan_manager/db/migrations/versions").glob("m*.py")), re.M))[-1]
    rc_j, mj = root("journalctl -u bitscan-manager-migrate --no-pager -o cat | grep -vE '^(Starting |Finished |bitscan-manager-migrate.service: )' | tail -1")
    row("CHK-M6-049", "§8 migrate start, journal, maintain run, timer", f"rc 0; the migrate CLI's last journal line is the head revision {want_head}; timer listed",
        f"rc {rc}; migrate CLI last line [{mj.strip()}]; {out[-1500:]}", rc == 0 and "!! rc=" not in out and mj.strip() == want_head
        and "bitscan-manager-maintain.timer" in out)
    rc, mout = root("journalctl -u bitscan-manager-maintain --no-pager -o cat")
    row("CHK-M6-049", "§8 'the maintenance run prints created <name> or nothing to do'", "printed by the run (the block shows no maintain output; it is in the unit's journal)",
        f"terminal output of the block: {'created' in out or 'nothing to do' in out}; journal: {mout}", "created" in mout or "nothing to do" in mout)
    rc, before = root("journalctl -u bitscan-manager-migrate --no-pager -o cat | wc -l")
    n_before = int(before.strip() or 0)
    rc, out = sh(f"sudo systemctl start bitscan-manager-migrate; echo rc=$?; sudo journalctl -u bitscan-manager-migrate --no-pager -o cat | tail -n +{n_before + 1}")
    row("CHK-M6-049", "§8 a second migrate start changes nothing (journal lines of the second run)", "rc 0, same head, no upgrade step", out,
        "rc=0" in out and "Running upgrade" not in out and any(h in out for h in head[-1:]))
    rc, out = root("systemctl show -p UnitFileState,ActiveState bitscan-manager-maintain.timer; systemctl cat bitscan-manager-maintain.timer | grep OnCalendar; "
                   "systemctl show -p Result,ExecMainStatus,User,DynamicUser bitscan-manager-maintain.service bitscan-manager-migrate.service")
    row("CHK-M6-049", "§8 timer enabled with OnCalendar=daily; both oneshots exit 0 as dynamic users", "enabled, active, OnCalendar=daily, Result=success, ExecMainStatus=0, DynamicUser=yes",
        out, "UnitFileState=enabled" in out and "OnCalendar=daily" in out and out.count("Result=success") == 2 and out.count("ExecMainStatus=0") == 2 and out.count("DynamicUser=yes") == 2)

    # doubles up (OpenBao Transit fake and HTTPS sink, #93)
    rc, out = root("systemd-run --unit m6b-doubles -p WorkingDirectory=/opt/m6b /usr/bin/python3.12 -I /opt/m6b/doubles.py --dir /opt/m6b "
                   "--cert /opt/m6b/doubles.crt --key /opt/m6b/doubles.key; sleep 2; systemctl is-active m6b-doubles; "
                   "curl -s -o /dev/null -w '%{http_code}' -X POST https://audit.test:18300/probe -d '{}'")
    row("CHK-M6-050", "test doubles running (OpenBao fake, HTTPS sink), certs in the system store", "active, sink answers 200", out, "active" in out and out.strip().endswith("200"))
    root("rm -f /opt/m6b/sink.jsonl")

    # §9 start
    rc, out = sh(sub(B[20][2]))
    row("CHK-M6-050", "§9 enable --now, is-active, /readyz (block run as one script)", "active; {\"status\":\"ok\"}", f"rc {rc}; {out}", rc == 0 and "active" in out and out.strip().endswith('{"status":"ok"}'))
    curls = [ln for ln in sub(B[20][2]).split("\n") if ln.startswith("curl ")]
    if curls:  # a bare curl line (no retry in the block): show it works once the listener is up
        t0, got = time.time(), ""
        while time.time() - t0 < 30:
            rc, got = sh(curls[0] + " 2>/dev/null")
            if got.strip().endswith('{"status":"ok"}'):
                break
            time.sleep(1)
        row("CHK-M6-050", "§9 the block's curl line repeated until the listener is up", '{"status":"ok"} within 30 s', f"after {time.time() - t0:.1f} s: {got}",
            got.strip().endswith('{"status":"ok"}'))
    rc, out = root("ps -o user=,pid=,cmd= -C bitscan-manager; systemctl show -p User,MainPID bitscan-manager")
    row("CHK-M6-050", "§9 service runs as bitscan-manager", "User=bitscan-manager", out, "User=bitscan-manager" in out)

    n0 = snapshot("before")
    # §10 first admin (pty), then sign-in and TOTP through the API (#93 (f))
    rc, out, done = pty_run(sub(B[21][2]), [(r"New password: $", vals["admin_pw"]), (r"Repeat the password: $", vals["admin_pw"])], timeout=120)
    row("CHK-M6-051", "§10 sudo bitscan-manager users create-admin alice (password twice at the prompt)", "rc 0", f"rc {rc}; done {done}; {out[-300:]}", rc == 0 and done)
    stage("admin_pw", vals["admin_pw"] + "\n")
    rc, out = api("admin", "--url", URL, "--ca", f"{REL}/manager-ca.pem", "--user", "alice", "--password-file", "/home/admin/stage/admin_pw", "--state", "/home/admin/stage/session.json")
    row("CHK-M6-051", "§10 sign in; TOTP Start + Confirm give a TOTP-verified session (API, not the browser)", "login 200 totp_enrolled false; confirm 200 totp_verified; /settings 200",
        f"rc {rc}; {out}", rc == 0)
    sess = ["--url", URL, "--ca", f"{REL}/manager-ca.pem", "--state", "/home/admin/stage/session.json"]
    rc, out = api("call", *sess, "--save-token", "/home/admin/stage/bse", "POST", "/api/v1/enrollment-tokens", "--body", "'{\"max_uses\": 1, \"expires_in_hours\": 24}'")
    row("CHK-M6-055", "session: enrolment token created with the TOTP session", "201", out, out.startswith("201"))
    mid = secrets.token_hex(16)
    body = json.dumps({"hostname": "m6b-agent-sim", "machine_id": mid, "agent_version": "0.1.0-1", "os_id": "ubuntu", "os_version_id": "24.04", "os_pretty_name": "Ubuntu 24.04 LTS"})
    rc, out = api("call", "--url", URL, "--ca", f"{REL}/manager-ca.pem", "--token-file", "/home/admin/stage/bse", "--save-token", "/home/admin/stage/bsa",
                  "POST", "/api/v1/agent/enroll", "--body", f"'{body}'")
    row("CHK-M6-055", "agent call: enrol with the bse_ (held)", "2xx awaiting_approval", out, out[:1] == "2" and "awaiting_approval" in out)
    aid_m = re.search(r'"agent_id": "([0-9a-f-]{36})"', out)
    aid = aid_m.group(1) if aid_m else "x"
    rc, out = api("call", *sess, "GET", "'/api/v1/enrollment-requests?state=pending&limit=10'")
    req = re.search(r'"request_id": (\d+)', out)
    rc, out2 = api("call", *sess, "POST", f"/api/v1/enrollment-requests/{req.group(1) if req else 'x'}/approve")
    row("CHK-M6-055", "approve with the TOTP session", "200", out2, out2.startswith("200"))
    hb = json.dumps({"agent_version": "0.1.0-1", "uptime_s": 10, "last_pull_at": None, "current_job_id": None, "spool_bytes": 0,
                     "last_error": None, "runner_helpers": [], "clock": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    tok = ["--url", URL, "--ca", f"{REL}/manager-ca.pem", "--token-file", "/home/admin/stage/bsa", "--machine-id", mid]
    rc, out = api("call", *tok, "POST", f"/api/v1/agent/{aid}/heartbeat", "--body", f"'{hb}'")
    row("CHK-M6-055", "agent call: heartbeat with the bsa_", "200", out, out.startswith("200"))
    rc, out = api("call", *tok, "GET", f"/api/v1/agent/{aid}/jobs")
    row("CHK-M6-055", "agent call: job pull", "200", out[:300], out.startswith("200"))
    for path in ("/api/v1/agents", f"/api/v1/agents/{aid}", "/api/v1/audit-log?limit=50", "/api/v1/settings", "/", "/healthz"):
        rc, out = api("call", *sess, "GET", f"'{path}'")
        row("CHK-M6-055", f"session: GET {path}", "200", out[:200], out.startswith("200"))
    time.sleep(3)
    n1 = snapshot("after")
    rc, diff = root("{ diff /root/sweep-before.txt /root/sweep-after.txt || true; } | grep '^[<>] ' | cut -f1 | sort -u || true")
    changed = sorted({ln[2:] for ln in diff.split("\n") if ln.startswith(("< ", "> "))})
    allowed = ("/var/lib/bitscan/bits/uploaded", "/var/lib/bitscan/audit-queue", "/var/lib/systemd/")
    bad = [p for p in changed if not p.startswith(allowed)]
    row("CHK-M6-055", "write sweep after the session (excl. /proc,/sys,/dev,/run,/tmp,/var/tmp, PostgreSQL data and logs, the journal, apt, /root, /home/admin, /opt/m6b)",
        "changes only under the two ReadWritePaths (and systemd state)", f"{n0}->{n1} entries; changed {changed}", not bad)
    probe = ("pid=$(systemctl show -p MainPID --value bitscan-manager); u=$(id -u bitscan-manager); g=$(id -g bitscan-manager); "
             "for p in / /etc /etc/bitscan /opt/bitscan-manager /usr /var /var/lib /var/lib/bitscan /var/lib/bitscan/bits /var/log /var/cache /srv /run "
             "/var/lib/bitscan/bits/uploaded /var/lib/bitscan/audit-queue /tmp /var/tmp /run/lock /dev/shm; do "
             "if nsenter -t $pid -m -S $u -G $g touch $p/.m6b-w 2>/dev/null; then echo W $p; nsenter -t $pid -m rm -f $p/.m6b-w; fi; done; true")
    rc, wr = root(probe)
    writable = [ln[2:] for ln in wr.split("\n") if ln.startswith("W ")]
    rw_bad = [p for p in writable if p not in ("/var/lib/bitscan/bits/uploaded", "/var/lib/bitscan/audit-queue", "/tmp", "/var/tmp", "/run/lock", "/dev/shm")]
    row("CHK-M6-055", "write probe as bitscan-manager inside the service's mount namespace",
        "persistent paths writable: only the two ReadWritePaths (private /tmp, /var/tmp, /dev/shm and the /run/lock tmpfs are non-persistent)", "writable: " + ", ".join(writable),
        not rw_bad and "/var/lib/bitscan/bits/uploaded" in writable and "/var/lib/bitscan/audit-queue" in writable)

    # §11 install check
    rc, out = sh(sub(B[22][2]))
    caps = re.findall(r"^(Cap\w+):\s+(\w+)", out, re.M)
    nnp = re.search(r"^NoNewPrivs:\s+(\d)", out, re.M)
    lines = out
    expect_modes = ["root:root 755 /etc/bitscan", "root:root 700 /etc/bitscan/secrets", "root:root 600 /etc/bitscan/manager.env",
                    "root:root 755 /var/lib/bitscan", "root:bitscan-manager 750 /var/lib/bitscan/bits",
                    "bitscan-manager:bitscan-manager 750 /var/lib/bitscan/bits/uploaded", "bitscan-manager:bitscan-manager 700 /var/lib/bitscan/audit-queue"]
    expect_modes += [f"root:root 600 /etc/bitscan/secrets/{f}" for f in ("app.dsn", "retention.dsn", "migrate.dsn", "tls.crt", "tls.key", "vault.token")]
    missing = [e for e in expect_modes if e not in lines]
    row("CHK-M6-052", "§11 install check as written", "User=bitscan-manager active; four Cap 0, NoNewPrivs 1; modes of §4-§5; migrate.dsn Permission denied; cmp silent",
        out, "User=bitscan-manager" in out and "ActiveState=active" in out and len(caps) == 4 and all(v == "0000000000000000" for _, v in caps)
        and nnp is not None and nnp.group(1) == "1" and not missing and "Permission denied" in out and "differ" not in out)
    row("CHK-M6-046", "folder owners and modes equal TS §8.7 L1344-L1345 and plan §2", "every expected line", f"missing {missing}", not missing)
    row("CHK-M6-054", "REQ-140 (4) CapEff/CapPrm/CapBnd/CapAmb 0, NoNewPrivs 1", "all 0; 1", str(caps) + f" NoNewPrivs {nnp.group(1) if nnp else None}",
        len(caps) == 4 and all(v == "0000000000000000" for _, v in caps) and nnp is not None and nnp.group(1) == "1")


def main() -> int:
    global OUT  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--rel", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    OUT = a.work / "out"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "walk.jsonl").write_text("")
    vals = setup(a.tree, a.rel, a.work)
    try:
        walk(a.tree, vals, a.work)
    finally:
        if not a.keep:
            run(["docker", "rm", "-f", CT])
    failed = [r for r in ROWS if not r["ok"]]
    print(f"walk rows: {len(ROWS) - len(failed)}/{len(ROWS)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
