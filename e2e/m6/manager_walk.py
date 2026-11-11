"""Manager install walk (TP-M6-03, CHK-M6-042..058; M11 TP-M11-17, CHK-M11-290..293)
on a fresh systemd Ubuntu 24.04 container.

Runs in WSL as root with Docker:
  python3 -I e2e/m6/manager_walk.py --tree TREE --rel RELDIR --work WORK
      [--runbook FILE] [--name m6b-host] [--keep]

TREE is a copy of the tree (the runbook is read from it unless --runbook names
another copy, as the REQ-291 plant does), RELDIR holds the release files the
runbook lists (wheel, requirements copy, four units) and the `SHA256SUMS` text
as the release page would show it.

Blocks are found by their section and an anchor text, never by position
(M10 finding: the M6 walk asserted on the wrong blocks once the runbook grew).
The first row checks that every fenced block of the runbook is either walked
or listed below as NOT RUN with its reason, and that each anchor matches
exactly one block; a new, removed or changed block stops the walk there.

Walked blocks run **verbatim** as the administrator `admin` with sudo in the
release folder; the only substitution is the example host name (`mgr.example`
-> `bitscan-mgr.test`). The §1.1 lab-CA blocks run on the "admin workstation"
(a scratch folder in WSL, as the runbook says: not on the manager host). Text
steps are done the way the runbook says: blocks saved as files, `sudoedit` for
every secret and config file (SUDO_EDITOR copies a staged file, so sudoedit
itself keeps the mode), passwords typed at prompts through a pty (psql
`\\password`, `users create-admin`, the apt confirmation). OpenBao and the
audit sink are the test doubles of e2e/m6/doubles.py (#93), whose OpenBao
token behaves as one from the §1.2 role, so the §5 token check and renewal
timer run as written. The real OpenBao and rsyslog blocks were walked in
TASK-133 r2 (CHK-M6-133r2-07..26) and are NOT RUN here.

REQ-291: manager.env sets BITSCAN_BITS_DIR, and before the manager starts the
start check (`bits_dir_check`) stops the walk with a clear message when the
folder or its uploaded/ is missing or has other owners or modes than §4 gives.

Environment on the manager host besides the image: /etc/pip.conf with a 60 s
read timeout and 10 retries (PyPI reads through the TLS-inspecting proxy stall
at times; the §6 block itself runs verbatim).

Rows go to WORK/out/walk.jsonl (status PASS, FAIL or NOT RUN); secrets never
leave 0600 files and every printed text is masked. The container (default
`m6b-host`, image `m6b-mgrhost`, e2e/m6/manager-host.Dockerfile) has no
published port and is removed at the end unless --keep.
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import secrets
import select
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

IMG, NET = "m6b-mgrhost", "m6b-net"
CT = "m6b-host"
HOSTNAME = "bitscan-mgr.test"
URL = f"https://{HOSTNAME}:8443"
REL = "/home/admin/rel"
BITS_DIR = "/var/lib/bitscan/bits"
TRAP = "trap 'echo \"!! rc=$? at: $BASH_COMMAND\"' ERR\n"
ROWS: list[dict] = []
OUT = Path()
SECRET_VALUES: list[str] = []
TOKEN_RE = re.compile(r"\bbs[uaek]_[A-Za-z0-9_-]{8,}")


class Stop(Exception):
    """The walk cannot go on (layout changed, or the REQ-291 start check refused)."""


def mask(text: str) -> str:
    for s in SECRET_VALUES:
        if s:
            text = text.replace(s, "<secret>")
    return TOKEN_RE.sub(lambda m: m.group(0)[:4] + "<masked>", text)


def _masked_excepthook(kind: type[BaseException], value: BaseException, tb: object) -> None:
    """An uncaught exception's traceback reaches the walk log masked, like every row."""
    import traceback
    sys.stderr.write(mask("".join(traceback.format_exception(kind, value, tb))))  # type: ignore[arg-type]


sys.excepthook = _masked_excepthook


def row(chk: str, step: str, expected: str, actual: str, ok: bool, status: str | None = None) -> bool:
    st = status or ("PASS" if ok else "FAIL")
    r = {"chk": chk, "step": step, "expected": expected, "actual": mask(actual)[-1500:], "status": st, "ok": st != "FAIL"}
    ROWS.append(r)
    with (OUT / "walk.jsonl").open("a") as f:
        f.write(json.dumps(r) + "\n")
    print(f"{st} {chk} {step} :: " + mask(actual).strip().replace("\n", " | ")[-400:], flush=True)
    return st == "PASS"


def notrun(chk: str, step: str, reason: str, evidence: str = "") -> None:
    row(chk, step, "NOT RUN: " + reason, evidence or "not run", True, status="NOT RUN")


def run(argv: list[str], stdin: str | None = None, timeout: int = 900, cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(argv, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, cwd=cwd)
    return p.returncode, p.stdout.replace("\r", "")


def sh(cmd: str, user: str = "admin", env: dict[str, str] | None = None, stdin: str | None = None,
       timeout: int = 900, wd: str = REL) -> tuple[int, str]:
    argv = ["docker", "exec", "-i", "-u", user, "-w", wd]
    for k, v in (env or {}).items():  # only non-secret values (editor and stage names)
        argv += ["-e", f"{k}={v}"]
    return run(argv + [CT, "bash", "-o", "pipefail", "-c", TRAP + cmd], stdin, timeout)


def root(cmd: str, **kw: object) -> tuple[int, str]:
    return sh(cmd, user="root", wd="/root", **kw)  # type: ignore[arg-type]


def ws(cmd: str, cwd: Path) -> tuple[int, str]:
    """A block on the admin workstation (a scratch folder in WSL, never the manager host)."""
    cwd.mkdir(parents=True, exist_ok=True)
    os.chmod(cwd, 0o700)
    return run(["bash", "--noprofile", "--norc", "-o", "pipefail", "-c", TRAP + cmd], cwd=cwd, timeout=120)


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


# ---------------------------------------------------------------- runbook blocks

HEADING = re.compile(r"^#{2,3} (\d+(?:\.\d+)?)\.? ")


@dataclass
class Block:
    sec: str
    lang: str
    body: str
    line: int


def blocks(md: str) -> list[Block]:
    """Every fenced block in order, with its section number (`1`, `1.1`, ... `11`)
    and its first line; bodies are dedented (blocks inside list items)."""
    out: list[Block] = []
    sec, cur, lang, start = "", None, "", 0
    for n, line in enumerate(md.split("\n"), 1):
        s = line.strip()
        if cur is None:
            m = HEADING.match(line)
            if m:
                sec = m.group(1)
            elif re.fullmatch(r"```[a-z]*", s):
                cur, lang, start = [], s[3:], n
        elif s == "```":
            out.append(Block(sec, lang, textwrap.dedent("\n".join(cur)), start))
            cur = None
        else:
            cur.append(line)
    return out


# key, section, language, anchor (a substring of the block, or "=" + the whole
# block), and what the walk does with it. Every block of the runbook must be here.
PLAN: list[tuple[str, str, str, str, str]] = [
    ("ntp", "1", "sh", "timedatectl set-ntp true", "host"),
    ("org_csr", "1.1", "sh", "-out manager.csr", "workstation"),
    ("crt_check", "1.1", "sh", "openssl verify -untrusted manager.crt", "host"),
    ("lab_ca", "1.1", "sh", "-keyout manager-ca.key", "workstation"),
    ("pin", "1.1", "sh", "openssl pkey -pubin -outform DER", "host, after §5"),
    ("bao_ca", "1.2", "sh", "openbao-ca.crt", "host"),
    ("bao_admin", "1.2", "sh", "bao secrets enable transit", "NOT RUN (OpenBao double)"),
    ("sink_install", "1.3", "sh", "apt install rsyslog rsyslog-gnutls", "NOT RUN (HTTPS sink double)"),
    ("sink_conf", "1.3", "text", "DefaultNetstreamDriver=", "NOT RUN (HTTPS sink double)"),
    ("sink_check", "1.3", "sh", "rsyslogd -N1", "NOT RUN (HTTPS sink double)"),
    ("sink_tls", "1.3", "sh", "openssl s_client -connect sink.example:6514", "NOT RUN (HTTPS sink double)"),
    ("sums", "2", "sh", "sha256sum -c --ignore-missing SHA256SUMS", "host"),
    ("apt", "3", "sh", "apt install postgresql-16", "host (pty)"),
    ("ssl", "3", "sh", "SHOW ssl", "host"),
    ("bootstrap", "3", "sql", "CREATE ROLE bitscan_owner NOLOGIN;", "saved as a file"),
    ("bootstrap_run", "3", "sh", "< bitscan-bootstrap.sql", "host"),
    ("psql", "3", "sh", "=sudo -u postgres psql -X", "host (pty)"),
    ("passwords", "3", "text", "\\password bitscan_app", "typed at the prompt"),
    ("hba", "3", "text", "hostnossl", "sudoedit, above every line"),
    ("hba_reload", "3", "sh", "pg_hba_file_rules", "host"),
    ("nossl", "3", "sh", "sslmode=disable", "host, x3 roles"),
    ("folders", "4", "sh", "adduser --system", "host"),
    ("files", "5", "sh", "/dev/null /etc/bitscan/manager.env", "host"),
    ("env", "5", "text", "BITSCAN_VAULT_ADDR=", "sudoedit (double addresses)"),
    ("pgca", "5", "sh", "postgres-ca.pem", "NOT RUN (same-host database)"),
    ("certcp", "5", "sh", "cp manager.crt /etc/bitscan/secrets/tls.crt", "host"),
    ("bao_token", "5", "sh", "bao token create", "NOT RUN (OpenBao double; workstation path)"),
    ("vault_check", "5", "sh", "transit/encrypt/$key", "host"),
    ("renew", "5", "sh", "bitscan-openbao-renew.timer", "host"),
    ("venv", "6", "sh", "python3.12 -m venv /opt/bitscan-manager", "host"),
    ("units", "7", "sh", "systemd-analyze verify /etc/systemd/system/bitscan-manager.service", "host"),
    ("migrate", "8", "sh", "systemctl start bitscan-manager-migrate", "host"),
    ("start", "9", "sh", "enable --now bitscan-manager", "host"),
    ("admin", "10", "sh", "users create-admin", "host (pty)"),
    ("sink_grep", "10", "sh", "/var/log/bitscan-audit.log", "NOT RUN as written (HTTPS sink: equivalent row)"),
    ("check", "11", "sh", "CapEff", "host"),
]


def resolve(md: str) -> tuple[dict[str, str], list[str], list[str], int, int]:
    bl = blocks(md)
    used: set[int] = set()
    found: dict[str, str] = {}
    errors: list[str] = []
    for key, sec, lang, anchor, _ in PLAN:
        hits = [i for i, b in enumerate(bl) if b.sec == sec and b.lang == lang
                and (b.body.strip() == anchor[1:] if anchor.startswith("=") else anchor in b.body)]
        if len(hits) != 1:
            errors.append(f"{key}: §{sec} {lang} block with {anchor!r} found {len(hits)} times")
            continue
        used.add(hits[0])
        found[key] = bl[hits[0]].body
    loose = [f"§{b.sec} L{b.line} ```{b.lang}: {b.body.strip().split(chr(10))[0][:60]}" for i, b in enumerate(bl) if i not in used]
    return found, errors, loose, len(bl), sum(1 for b in bl if b.lang == "sh")


def sub(body: str) -> str:
    return body.replace("mgr.example", HOSTNAME)


# ---------------------------------------------------------------- host helpers

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


def bits_dir_check(shell=root) -> str:  # noqa: ANN001
    """REQ-291 (2): the start check every test manager of the M11 harness runs before
    the manager starts. BITSCAN_BITS_DIR (manager.env, else the default) and its
    uploaded/ must exist with the owners and modes of manager-install.md §4;
    otherwise the walk stops here with a clear message (Stop)."""
    rc, env = shell("sed -n 's/^BITSCAN_BITS_DIR=//p' /etc/bitscan/manager.env")
    d = (env.strip().split("\n")[-1] if env.strip() else "") or BITS_DIR
    q = shlex.quote(d)
    rc, st = shell(f"stat -c '%U:%G %a %n' {q} {q}/uploaded 2>&1; true")
    want = [f"root:bitscan-manager 750 {d}", f"bitscan-manager:bitscan-manager 750 {d}/uploaded"]
    have = st.strip().split("\n")
    bad = [w for w in want if w not in have]
    msg = (f"BITSCAN_BITS_DIR={d}: ready" if not bad else
           f"start check refused: BITSCAN_BITS_DIR={d}: the policy folder or its uploaded/ is missing or not as "
           f"manager-install.md section 4 creates it (want {want}; have {have}). Create them as section 4 says "
           f"before the manager starts.")
    row("CHK-M11-292", "start check before the manager starts: BITSCAN_BITS_DIR and its uploaded/ exist, owners and modes as §4",
        "; ".join(want), msg, not bad)
    if bad:
        print(msg, file=sys.stderr, flush=True)
        raise Stop(msg)
    return d


# ---------------------------------------------------------------- set-up

PUBLISH: list[str] = []  # --publish: docker -p values (the M11 nightly's agents reach the manager through one)
RELDIR = Path()  # --rel


def wheel_head(rel: Path) -> str:
    """The head migration revision of the wheel being installed (from --rel), never the tree's: the
    N / N−1 runs install manager 0.1.0 (head m0005) from a tree whose head is later (m0006 since
    M11's retention indexes), and the walk must expect the installed code's own head."""
    import zipfile
    whl = next(rel.glob("bitscan_manager-*-py3-none-any.whl"))
    with zipfile.ZipFile(whl) as z:
        names = [n for n in z.namelist() if re.search(r"/db/migrations/versions/m\d{4}\w*\.py$", n)]
        text = "\n".join(z.read(n).decode("utf-8") for n in names)
    return sorted(re.findall(r'^revision: str = "(\w+)"', text, re.MULTILINE))[-1]


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
    run(["docker", "rm", "-f", CT])
    if run(["docker", "network", "inspect", NET])[0] != 0:
        run(["docker", "network", "create", NET])
    rc, out = run(["docker", "run", "-d", "--name", CT, "--hostname", "bitscan-mgr", "--privileged", "--cgroupns=private",
                   "--tmpfs", "/run", "--tmpfs", "/run/lock", "--network", NET, "--network-alias", HOSTNAME,
                   "--add-host", f"{HOSTNAME}:127.0.0.1", "--add-host", "openbao.test:127.0.0.1",
                   "--add-host", "audit.test:127.0.0.1", "--memory", "1500m", *(x for p in PUBLISH for x in ("-p", p)), IMG])
    assert rc == 0, out
    for _ in range(60):
        if root("systemctl is-system-running")[1].strip() in ("running", "degraded"):
            break
        time.sleep(1)
    root("install -d -m 0700 -o admin -g admin /home/admin/stage /home/admin/bin; install -d -o admin -g admin /home/admin/rel; install -d -m 0755 /opt/m6b")
    # environment, not a runbook step: §6 downloads from PyPI through a TLS-inspecting proxy whose
    # reads stall at times (ReadTimeoutError, 2 of 4 runs on 2026-11-08); a global pip.conf (read
    # under sudo too) gives pip a 60 s read timeout and 10 retries, and the §6 block stays verbatim
    root("printf '[global]\\ntimeout = 60\\nretries = 10\\n' > /etc/pip.conf && chmod 0644 /etc/pip.conf")
    for f in rel.iterdir():
        run(["docker", "cp", str(f), f"{CT}:{REL}/{f.name}"])
    root(f"chown -R admin:admin {REL}")
    editor = ('#!/bin/sh\n# SUDO_EDITOR for the walk: copy the staged content into the file sudoedit opened\nset -e\n'
              'case "${M6B_MODE:-replace}" in\n'
              '  replace) cat "/home/admin/stage/$M6B_STAGE" > "$1" ;;\n'
              '  prepend) { cat "/home/admin/stage/$M6B_STAGE"; cat "$1"; } > "$1.m6b" && cat "$1.m6b" > "$1" && rm -f "$1.m6b" ;;\n'
              'esac\n')
    sh("cat > /home/admin/bin/m6b-editor && chmod 0700 /home/admin/bin/m6b-editor", stdin=editor, wd="/home/admin")
    for f in ("doubles.py", "mgr_api.py"):
        run(["docker", "cp", str(tree / "e2e" / "m6" / f), f"{CT}:/opt/m6b/{f}"])
    run(["docker", "cp", str(tree / "manager" / "tests" / "fake_vault.py"), f"{CT}:/opt/m6b/fake_vault.py"])
    run(["docker", "cp", str(sec / "vault_token"), f"{CT}:/opt/m6b/vault.token"])
    root("chmod 0600 /opt/m6b/vault.token")
    return vals


def api(*args: str, timeout: int = 120) -> tuple[int, str]:
    return sh("python3.12 -I /opt/m6b/mgr_api.py " + " ".join(args), wd="/home/admin", timeout=timeout)


def secret_line(path: Path) -> None:
    """Mask a PEM key's base64 body lines wherever they might be echoed."""
    SECRET_VALUES.extend(ln for ln in path.read_text().split("\n")[1:-2] if len(ln) > 16)


# ---------------------------------------------------------------- the walk

def walk_pki(B: dict[str, str], work: Path) -> Path:
    """§1.1 on the admin workstation; the doubles' certificate from the same lab CA."""
    org = work / "ws-org"
    shutil.rmtree(org, ignore_errors=True)
    rc, out = ws(sub(B["org_csr"]), org)
    rc2, csr = run(["openssl", "req", "-in", str(org / "manager.csr"), "-noout", "-text"])
    mode = oct((org / "manager.key").stat().st_mode & 0o777) if (org / "manager.key").exists() else "missing"
    sans = re.findall(r"DNS:[^ ,\n]+", csr)
    row("CHK-M11-290", "§1.1 organisation-CA request block (workstation)", f"rc 0; CSR with DNS:{HOSTNAME}; key 0600",
        f"rc {rc}; key {mode}; SAN {sans}", rc == 0 and f"DNS:{HOSTNAME}" in csr and mode == "0o600")
    shutil.rmtree(org, ignore_errors=True)
    lab = work / "ws-lab"
    shutil.rmtree(lab, ignore_errors=True)
    rc, out = ws(sub(B["lab_ca"]), lab)
    for k in ("manager-ca.key", "manager.key"):
        if (lab / k).exists():
            secret_line(lab / k)
    modes = {k: oct((lab / k).stat().st_mode & 0o777) if (lab / k).exists() else "missing" for k in ("manager-ca.key", "manager.key")}
    _, ca_ext = run(["openssl", "x509", "-in", str(lab / "manager-ca.pem"), "-noout", "-ext", "basicConstraints,keyUsage"])
    _, ver = run(["openssl", "verify", "-CAfile", str(lab / "manager-ca.pem"), "-verify_hostname", HOSTNAME, str(lab / "manager.crt")])
    row("CHK-M11-290", "§1.1 private-CA lab block (workstation): CA and the manager's certificate",
        "rc 0; keys 0600; CA:TRUE with Certificate Sign, CRL Sign; manager.crt verifies for the host name",
        f"rc {rc}; {out[-300:]}; modes {modes}; {ca_ext}; {ver}",
        rc == 0 and set(modes.values()) == {"0o600"} and "CA:TRUE" in ca_ext and "Certificate Sign, CRL Sign" in ca_ext and ver.strip().endswith(": OK"))
    # environment: the doubles' leaf from the same lab CA (both double names, one process)
    (lab / "doubles.ext").write_text("subjectAltName=DNS:openbao.test,DNS:audit.test,IP:127.0.0.1\nbasicConstraints=critical,CA:FALSE\n"
                                     "keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n")
    for argv in (["req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-noenc", "-keyout", "doubles.key",
                  "-out", "doubles.csr", "-subj", "/CN=bitscan test doubles"],
                 ["x509", "-req", "-in", "doubles.csr", "-CA", "manager-ca.pem", "-CAkey", "manager-ca.key", "-CAcreateserial",
                  "-days", "30", "-extfile", "doubles.ext", "-out", "doubles.crt"]):
        subprocess.run(["openssl", *argv], cwd=lab, check=True, capture_output=True)
    os.chmod(lab / "doubles.key", 0o600)
    secret_line(lab / "doubles.key")
    for src, dst in (("manager.crt", f"{REL}/manager.crt"), ("manager.key", f"{REL}/manager.key"), ("manager-ca.pem", f"{REL}/manager-ca.pem"),
                     ("manager-ca.pem", f"{REL}/openbao-ca.pem"), ("doubles.crt", "/opt/m6b/doubles.crt"), ("doubles.key", "/opt/m6b/doubles.key")):
        run(["docker", "cp", str(lab / src), f"{CT}:{dst}"])
    root(f"chown admin:admin {REL}/manager.crt {REL}/manager.key {REL}/manager-ca.pem {REL}/openbao-ca.pem; chmod 0600 {REL}/manager.key /opt/m6b/doubles.key")
    rc, found = root("find / -xdev -name manager-ca.key 2>/dev/null; true")
    row("CHK-M11-290", "§1.1 'keep manager-ca.key off every Bitscan host'", "no manager-ca.key on the manager host", found.strip() or "none", found.strip() == "")
    return lab


def walk(tree: Path, runbook: Path, vals: dict[str, str], work: Path) -> None:  # noqa: PLR0915
    md = runbook.read_text()
    B, errors, loose, n, n_sh = resolve(md)
    row("CHK-M6-042", "runbook block layout: every fenced block is walked or NOT RUN with a reason, each anchor matches one block",
        f"{len(PLAN)} planned blocks found once each; no block outside the plan",
        f"{n} blocks ({n_sh} sh); errors {errors}; outside the plan {loose}", not errors and not loose and n == len(PLAN))
    if errors or loose or n != len(PLAN):
        raise Stop("the runbook's blocks differ from the walk's plan; update PLAN in e2e/m6/manager_walk.py")

    rc, out = root("echo m6b-probe > /root/p.cred; chmod 600 /root/p.cred; systemd-run --wait --pipe -q -p DynamicUser=yes "
                   "-p LoadCredential=c:/root/p.cred -p ProtectSystem=strict -p PrivateTmp=yes -p ProtectHome=yes "
                   "-p NoNewPrivileges=yes -p CapabilityBoundingSet= bash -c 'id -u; stat -c \"%A %a\" \"$CREDENTIALS_DIRECTORY\" \"$CREDENTIALS_DIRECTORY/c\"; "
                   "cat \"$CREDENTIALS_DIRECTORY/c\"; findmnt -no FSTYPE,OPTIONS \"$CREDENTIALS_DIRECTORY\"; cat /root/p.cred 2>&1 | head -1'; rm -f /root/p.cred")
    row("CHK-M6-042", "probe: DynamicUser= and LoadCredential= work under the units' sandbox", "dynamic uid, credential readable, source denied",
        out, "m6b-probe" in out and "Permission denied" in out and re.search(r"^6\d{4}$", out, re.M) is not None)

    # §1 time
    rc, out = sh(sub(B["ntp"]))
    if "System clock synchronized: yes" in out:
        row("CHK-M11-290", "§1 timedatectl set-ntp true; timedatectl (a container shares the host's synchronized clock; "
            "'NTP not supported' from set-ntp is the case the runbook names)", "System clock synchronized: yes", out, True)
    elif "NTP not supported" in out:
        notrun("CHK-M11-290", "§1 timedatectl set-ntp true; timedatectl",
               "a container has no NTP service (systemd-timesyncd is ConditionVirtualization=!container, CHK-M6-133r2-24); "
               "the block printed the runbook's quoted 'NTP not supported'", out)
    else:
        row("CHK-M11-290", "§1 timedatectl set-ntp true; timedatectl", "synchronized, or 'NTP not supported' as the runbook names", out, False)

    # §1.1 workstation, then §1.2 trust on the host, then the §1.1 certificate check
    walk_pki(B, work)
    rc, out = sh(sub(B["bao_ca"]))
    rc2, st = root("stat -c '%U:%G %a' /usr/local/share/ca-certificates/openbao-ca.crt")
    row("CHK-M11-290", "§1.2 the OpenBao CA (the doubles' lab CA) into the system store", "rc 0; root:root 644; update-ca-certificates done",
        f"rc {rc}; {out[-200:]}; {st}", rc == 0 and st.strip() == "root:root 644" and "!! rc=" not in out)
    rc, out = sh(sub(B["crt_check"]))
    row("CHK-M11-290", "§1.1 certificate check block on the manager host (CA now in the system store)",
        f"subject CN={HOSTNAME}, SAN DNS:{HOSTNAME}, cmp silent, 'manager.crt: OK'", f"rc {rc}; {out}",
        rc == 0 and f"DNS:{HOSTNAME}" in out and "manager.crt: OK" in out and "differ" not in out)
    notrun("CHK-M11-290", "§1.2 OpenBao admin block (Transit, key, policy, role)", "OpenBao is the test double (#93); walked on a real OpenBao 2.4.1 in CHK-M6-133r2-10")
    notrun("CHK-M11-290", "§1.3 rsyslog receiver: install, configuration, rsyslogd -N1, s_client (4 blocks)",
           "the audit sink is the HTTPS sink double (#93), the runbook's preferred form; walked in CHK-M6-133r2-19..22")

    # §2 release check
    rc, out = sh(sub(B["sums"]))
    oks = re.findall(r"^\S+: OK$", out, re.M)
    row("CHK-M6-043", "§2 sha256sum -c --ignore-missing SHA256SUMS", "rc 0, OK for each of the six files", f"rc {rc}; {out}", rc == 0 and len(oks) == 6 and "FAILED" not in out)
    rc, out = sh("rm -rf /tmp/relmod && cp -r . /tmp/relmod && cd /tmp/relmod && w=$(ls bitscan_manager-*-py3-none-any.whl) && "
                 "printf 'X' | dd of=\"$w\" bs=1 seek=100 conv=notrunc status=none && " + sub(B["sums"]) + "; echo rc=$?; rm -rf /tmp/relmod")
    row("CHK-M6-043", "§2 one byte changed in the wheel", "FAILED line, non-zero rc", out, "FAILED" in out and "rc=1" in out)

    # §3 PostgreSQL
    rc, out, done = pty_run(sub(B["apt"]), [(r"\[Y/n\]", "Y")], timeout=1500)
    row("CHK-M6-044", "§3 apt update and apt install (answered Y at the prompt)", "rc 0", f"rc {rc}; {out[-300:]}", rc == 0 and done)
    rc, out = sh(sub(B["ssl"]))
    row("CHK-M6-044", "§3 SHOW ssl", "on", out, rc == 0 and out.strip() == "on")
    sh("cat > bitscan-bootstrap.sql", stdin=B["bootstrap"] + "\n")
    rc, out = sh(sub(B["bootstrap_run"]))
    row("CHK-M6-044", "§3 Bootstrap run once as the superuser", "rc 0, no ERROR", f"rc {rc}; {out}", rc == 0 and "ERROR" not in out)
    script: list[tuple[str, str]] = []
    for line in B["passwords"].split("\n"):
        line = line.strip()
        m = re.fullmatch(r"\\password (\w+)", line)
        if m:
            pw = vals["pg_" + m.group(1).removeprefix("bitscan_")]
            script += [(r"=# $", line), (r"Enter new password[^:]*: $", pw), (r"Enter it again: $", pw)]
        elif line == "\\q":
            script.append((r"=# $", "\\q"))
    rc, out, done = pty_run(B["psql"], script, timeout=120)
    row("CHK-M6-044", "§3 \\password for the three roles at the psql prompt", "rc 0, all prompts answered", f"rc {rc}; done {done}; {out[-400:]}", rc == 0 and done)
    rc, hist = root("cat /var/lib/postgresql/.psql_history 2>/dev/null; true")
    row("CHK-M6-044", "§3 no password in psql history", "no password text", hist or "(no history file)",
        not any(vals[k] in hist for k in ("pg_app", "pg_retention", "pg_migrate")))
    stage("pg_hba.lines", B["hba"] + "\n")
    rc, out = sudoedit("/etc/postgresql/16/main/pg_hba.conf", "pg_hba.lines", "prepend")
    rc2, hba = root("head -5 /etc/postgresql/16/main/pg_hba.conf; stat -c '%U:%G %a' /etc/postgresql/16/main/pg_hba.conf")
    row("CHK-M6-044", "§3 pg_hba.conf lines above every other line (sudoedit)", "the four lines first; postgres:postgres 640", f"rc {rc}; {hba}",
        rc == 0 and hba.split("\n")[0].startswith("# Bitscan roles") and "postgres:postgres 640" in hba)
    rc, out = sh(sub(B["hba_reload"]))
    row("CHK-M6-044", "§3 reload; pg_hba_file_rules errors", "rc 0, prints nothing", f"rc {rc}; [{out}]", rc == 0 and out.strip() == "")
    for role in ("bitscan_app", "bitscan_retention", "bitscan_migrate"):
        cmd = sub(B["nossl"]).replace("user=bitscan_app", f"user={role}")
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

    # the doubles need python3.12, which §3 installed; the §5 token check needs them
    rc, out = root("systemd-run --unit m6b-doubles -p WorkingDirectory=/opt/m6b /usr/bin/python3.12 -I /opt/m6b/doubles.py --dir /opt/m6b "
                   "--cert /opt/m6b/doubles.crt --key /opt/m6b/doubles.key --transit-key bitscan-totp; sleep 2; systemctl is-active m6b-doubles; "
                   "curl -s -o /dev/null -w 'sink %{http_code} ' -X POST https://audit.test:18300/probe -d '{}'; "
                   "curl -s -o /dev/null -w 'bao %{http_code}' https://openbao.test:18200/v1/sys/mounts")
    row("CHK-M6-050", "test doubles running (OpenBao double, HTTPS sink); both verified through the §1.2 system store (no --cacert)",
        "active; sink 200; bao 403 (the role's policy denies sys/mounts)", out, "active" in out and "sink 200" in out and out.strip().endswith("bao 403"))
    root("rm -f /opt/m6b/sink.jsonl /opt/m6b/vault.jsonl")

    # §4 user and folders (REQ-291 set-up)
    rc, out = sh(sub(B["folders"]))
    rc2, u = root("getent passwd bitscan-manager; getent group bitscan-manager; test -e /nonexistent && echo HOME-EXISTS; true")
    row("CHK-M6-046", "§4 system user and folders", "rc 0; shell /usr/sbin/nologin, home /nonexistent (absent)", f"rc {rc}; {u}",
        rc == 0 and u.split("\n")[0].endswith(":/nonexistent:/usr/sbin/nologin") and "HOME-EXISTS" not in u)
    rc, st = root(f"stat -c '%U:%G %a %n' /var/lib/bitscan {BITS_DIR} {BITS_DIR}/uploaded /var/lib/bitscan/audit-queue 2>&1")
    want = ["root:root 755 /var/lib/bitscan", f"root:bitscan-manager 750 {BITS_DIR}", f"bitscan-manager:bitscan-manager 750 {BITS_DIR}/uploaded",
            "bitscan-manager:bitscan-manager 700 /var/lib/bitscan/audit-queue"]
    row("CHK-M11-291", "§4 the policy folder BITSCAN_BITS_DIR and its uploaded/ (and the audit queue) exist before the first start, owners and modes as §4",
        "; ".join(want), st, all(w in st.split("\n") for w in want))

    # §5 config and secrets
    rc, out = sh(sub(B["files"]))
    rc2, m = root("find /etc/bitscan -printf '%u:%g %m %s %p\\n' | sort -k4")
    row("CHK-M6-047", "§5 files created empty with their mode before content", "rc 0; 0755 /etc/bitscan, 0700 secrets, 0600 x7 all size 0", f"rc {rc}; {m}",
        rc == 0 and m.count("root:root 600 0 ") == 7 and "root:root 700 " in m and "root:root 755 " in m)
    env_text = ("BITSCAN_VAULT_ADDR=https://openbao.test:18200\nBITSCAN_TOTP_KEY_REF=bitscan-totp\n"
                "BITSCAN_AUDIT_SINK=https://audit.test:18300/bitscan\n"
                f"BITSCAN_BITS_DIR={BITS_DIR}\n")
    stage("manager.env", env_text)
    rc, out = sudoedit("/etc/bitscan/manager.env", "manager.env")
    row("CHK-M6-047", "§5 manager.env written with sudoedit (test-double addresses, #93; BITSCAN_BITS_DIR set, REQ-291)", "rc 0", f"rc {rc}; {out}", rc == 0)
    for f, role in (("app.dsn", "app"), ("retention.dsn", "retention"), ("migrate.dsn", "migrate")):
        stage(f, f"host=127.0.0.1 port=5432 dbname=bitscan user=bitscan_{role} password={vals['pg_' + role]} sslmode=require\n")
        rc, out = sudoedit(f"/etc/bitscan/secrets/{f}", f)
        row("CHK-M6-047", f"§5 {f} written with sudoedit (the table's same-host line)", "rc 0", f"rc {rc}; {out}", rc == 0)
    notrun("CHK-M6-047", "§5 database on another host (postgres-ca.pem, verify-full)", "the same-host path is walked (#97 variant)")
    rc, out = sh(sub(B["certcp"]))
    sh("rm -f manager.key")
    notrun("CHK-M11-290", "§5 bao token create (on-host variant)", "OpenBao is the test double; the token is pasted with sudoedit as the preferred workstation path says (next row)")
    stage("vault.token", vals["vault_token"] + "\n")
    rc_t, out_t = sudoedit("/etc/bitscan/secrets/vault.token", "vault.token")
    rc3, m = root("find /etc/bitscan -printf '%u:%g %m %p\\n' | sort -k3; cmp /etc/bitscan/secrets/tls.crt /home/admin/rel/manager.crt && echo CRT-SAME; "
                  "test -e /home/admin/rel/manager.key && echo KEY-LEFT; true")
    row("CHK-M6-047", "§5 cert, key (cp onto the 0600 files) and vault.token (sudoedit); working key deleted",
        "rc 0; every file still root:root 600; tls.crt equals manager.crt; no manager.key in the release folder",
        f"rc {rc}/{rc_t}; {m}", rc == 0 and rc_t == 0 and m.count("root:root 600 ") == 7 and "CRT-SAME" in m and "KEY-LEFT" not in m)
    rc, envf = root("grep -v '^#' /etc/bitscan/manager.env")
    names = sorted(ln.split("=", 1)[0] for ln in envf.strip().split("\n") if "=" in ln)
    row("CHK-M6-047", "§5 manager.env holds no secret and no *_FILE", "only BITSCAN_AUDIT_SINK, BITSCAN_BITS_DIR, BITSCAN_TOTP_KEY_REF, BITSCAN_VAULT_ADDR",
        f"{names}", names == ["BITSCAN_AUDIT_SINK", "BITSCAN_BITS_DIR", "BITSCAN_TOTP_KEY_REF", "BITSCAN_VAULT_ADDR"]
        and not any(v in envf for v in vals.values()) and "_FILE" not in envf and "password" not in envf.lower())
    sh("rm -f /home/admin/stage/*.dsn /home/admin/stage/vault.token")
    rc, out = sh(sub(B["vault_check"]))
    lines = [ln for ln in out.strip().split("\n") if ln and not ln.startswith("!!")]
    codes = [ln for ln in lines if re.fullmatch(r"\d{3} \S+", ln)]
    row("CHK-M11-290", "§5 OpenBao token check block (against the double, whose token acts as the §1.2 role's)",
        "Yml0c2Nhbg==; 604800 True ['bitscan-manager']; five lines starting 403",
        f"rc {rc}; {out}", rc == 0 and "Yml0c2Nhbg==" in lines and "604800 True ['bitscan-manager']" in lines
        and len(codes) == 5 and all(c.startswith("403 ") for c in codes))
    rc, out = sh(sub(B["renew"]))
    rc2, st = root("systemctl show -p Result,ExecMainStatus bitscan-openbao-renew.service; systemctl is-enabled bitscan-openbao-renew.timer; "
                   "grep -c '\"path\": \"/v1/auth/token/renew-self\", \"status\": 200' /opt/m6b/vault.jsonl; "
                   "stat -c '%U:%G %a %n' /usr/local/sbin/bitscan-openbao-renew /etc/systemd/system/bitscan-openbao-renew.service /etc/systemd/system/bitscan-openbao-renew.timer")
    _, jr = root("journalctl -u bitscan-openbao-renew --no-pager -o cat")
    # the block's own output also holds list-timers, so its verify line is re-run alone
    _, ver = root("systemd-analyze verify /etc/systemd/system/bitscan-openbao-renew.service /etc/systemd/system/bitscan-openbao-renew.timer 2>&1")
    row("CHK-M11-290", "§5 renewal script, service and timer: verify prints nothing, the first renewal succeeds, timer enabled",
        "rc 0; verify silent; Result=success, ExecMainStatus=0; enabled; a renew-self 200 at the double; script 755, units 644; the token not in the journal",
        f"rc {rc}; {out[-500:]}; {st}; verify [{ver.strip()}]",
        rc == 0 and "!! rc=" not in out and ver.strip() == "" and "Result=success" in st and "ExecMainStatus=0" in st and "\nenabled" in "\n" + st
        and re.search(r"^[1-9]\d*$", st, re.M) is not None and "root:root 755 /usr/local/sbin/bitscan-openbao-renew" in st
        and st.count("root:root 644 ") == 2 and vals["vault_token"] not in jr)
    rc, pin = sh(sub(B["pin"]))
    _, pin_ws = run(["bash", "-c", "openssl x509 -in \"$1\" -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d' ' -f1",
                     "pin", str(work / "ws-lab" / "manager.crt")])
    row("CHK-M11-290", "§1.1 SPKI pin block on the manager host after §5", "64 hex characters, equal to the pin of the workstation's manager.crt",
        f"rc {rc}; host {pin.strip()}; workstation {pin_ws.strip()}", rc == 0 and re.fullmatch(r"[0-9a-f]{64}", pin.strip()) is not None and pin.strip() == pin_ws.strip())

    # §6 software
    rc, out = sh(sub(B["venv"]), timeout=1500)
    helpok = all(w in out for w in ("serve", "users", "migrate", "maintain"))
    rc2, perm = root("find /opt/bitscan-manager ! -type l -perm /022 | head; readlink /usr/bin/bitscan-manager; stat -c '%U:%G %a' /opt/bitscan-manager")
    errs = [ln for ln in out.split("\n") if re.search(r"^!! rc=|ERROR|Could not|Timeout|SSLError|HTTPSConnection|hash", ln)]
    row("CHK-M6-048", "§6 venv from the hashed lock and the wheel, link, --help, find -perm /022", "rc 0; help lists serve, users, db migrate, db maintain; find prints nothing",
        f"rc {rc}; errors {errs[:8]}; {out[-700:]} || {perm}", rc == 0 and helpok and "!! rc=" not in out and perm.split("\n")[0] == "/opt/bitscan-manager/bin/bitscan-manager")

    # §7 units
    rc, out = sh(sub(B["units"]))
    row("CHK-M6-049", "§7 units installed, daemon-reload, systemd-analyze verify", "rc 0, verify prints nothing", f"rc {rc}; [{out}]", rc == 0 and out.strip() == "")

    # §8 migrate and maintain
    rc, out = sh(sub(B["migrate"]))
    want_head = wheel_head(RELDIR)
    rc_j, mj = root("journalctl -u bitscan-manager-migrate --no-pager -o cat | grep -vE '^(Starting |Finished |bitscan-manager-migrate.service: )' | tail -1")
    row("CHK-M6-049", "§8 migrate start, journal, maintain run, timer", f"rc 0; the migrate CLI's last journal line is the head revision {want_head}; timer listed",
        f"rc {rc}; migrate CLI last line [{mj.strip()}]; {out[-1500:]}", rc == 0 and "!! rc=" not in out and mj.strip() == want_head
        and "bitscan-manager-maintain.timer" in out)
    rc, mout = root("journalctl -u bitscan-manager-maintain --no-pager -o cat")
    row("CHK-M6-049", "§8 'the maintenance run writes created <name> or nothing to do to its journal'", "in the unit's journal",
        mout, "created" in mout or "nothing to do" in mout)
    rc, before = root("journalctl -u bitscan-manager-migrate --no-pager -o cat | wc -l")
    n_before = int(before.strip() or 0)
    rc, out = sh(f"sudo systemctl start bitscan-manager-migrate; echo rc=$?; sudo journalctl -u bitscan-manager-migrate --no-pager -o cat | tail -n +{n_before + 1}")
    row("CHK-M6-049", "§8 a second migrate start changes nothing (journal lines of the second run)", "rc 0, same head, no upgrade step", out,
        "rc=0" in out and "Running upgrade" not in out and want_head in out)
    rc, out = root("systemctl show -p UnitFileState,ActiveState bitscan-manager-maintain.timer; systemctl cat bitscan-manager-maintain.timer | grep OnCalendar; "
                   "systemctl show -p Result,ExecMainStatus,User,DynamicUser bitscan-manager-maintain.service bitscan-manager-migrate.service")
    row("CHK-M6-049", "§8 timer enabled with OnCalendar=daily; both oneshots exit 0 as dynamic users", "enabled, active, OnCalendar=daily, Result=success, ExecMainStatus=0, DynamicUser=yes",
        out, "UnitFileState=enabled" in out and "OnCalendar=daily" in out and out.count("Result=success") == 2 and out.count("ExecMainStatus=0") == 2 and out.count("DynamicUser=yes") == 2)

    # REQ-291 start check, then §9 start
    bits_dir_check()
    rc, out = sh(sub(B["start"]))
    row("CHK-M6-050", "§9 enable --now, is-active, the 10-try /readyz loop (block run as one script)", "active; {\"status\":\"ok\"}", f"rc {rc}; {out}",
        rc == 0 and "active" in out and out.strip().endswith('{"status":"ok"}'))
    rc, out = root("ps -o user=,pid=,cmd= -C bitscan-manager; systemctl show -p User,MainPID bitscan-manager")
    row("CHK-M6-050", "§9 service runs as bitscan-manager", "User=bitscan-manager", out, "User=bitscan-manager" in out)
    # `|| true`: grep -c exits 1 on a count of 0, which would trip the ERR trap
    rc, out = root("journalctl -u bitscan-manager --no-pager -o cat | grep -c -e 'catalog start-up failed' -e FileNotFoundError || true")
    row("CHK-M11-291", "the catalog starts on the runbook's folder (no 'catalog start-up failed' or FileNotFoundError, the M10 G79 symptom)", "0",
        out.strip(), out.strip() == "0")

    n0 = snapshot("before")
    # §10 first admin (pty), then sign-in and TOTP through the API (#93 (f))
    rc, out, done = pty_run(sub(B["admin"]), [(r"New password: $", vals["admin_pw"]), (r"Repeat the password: $", vals["admin_pw"])], timeout=120)
    row("CHK-M6-051", "§10 sudo bitscan-manager users create-admin alice (password twice at the prompt)", "rc 0", f"rc {rc}; done {done}; {out[-300:]}", rc == 0 and done)
    stage("admin_pw", vals["admin_pw"] + "\n")
    rc, out = api("admin", "--url", URL, "--ca", f"{REL}/manager-ca.pem", "--user", "alice", "--password-file", "/home/admin/stage/admin_pw", "--state", "/home/admin/stage/session.json")
    row("CHK-M6-051", "§10 sign in; TOTP Start + Confirm give a TOTP-verified session (API, not the browser)", "login 200 totp_enrolled false; confirm 200 totp_verified; /settings 200",
        f"rc {rc}; {out}", rc == 0)
    t0, sink = time.time(), ""
    while time.time() - t0 < 60:
        _, sink = root("cat /opt/m6b/sink.jsonl 2>/dev/null; true")
        if '"action": "auth.login"' in sink and '"action": "auth.totp_enrol"' in sink:
            break
        time.sleep(2)
    actions = sorted({e.get("body", {}).get("action", "?") for e in (json.loads(ln) for ln in sink.split("\n") if ln.strip()) if isinstance(e.get("body"), dict)})
    row("CHK-M11-290", "§10 audit entries reach the sink (the rsyslog grep is NOT RUN as written: HTTPS sink double; same check on its file)",
        "auth.login and auth.totp_enrol in the sink within a minute", f"after {time.time() - t0:.0f} s: actions {actions}",
        "auth.login" in actions and "auth.totp_enrol" in actions)
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
    for f in ("bse", "bsa", "session.json"):  # held in memory only, to mask and to sweep for
        _, v = sh(f"cat /home/admin/stage/{f} 2>/dev/null; true", wd="/home/admin")
        SECRET_VALUES.extend(TOKEN_RE.findall(v))
        if f == "session.json" and v.strip().startswith("{"):
            SECRET_VALUES.append(str(json.loads(v).get("secret", "")))  # the TOTP seed
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
    allowed = (f"{BITS_DIR}/uploaded", "/var/lib/bitscan/audit-queue", "/var/lib/systemd/")
    bad = [p for p in changed if not p.startswith(allowed)]
    row("CHK-M6-055", "write sweep after the session (excl. /proc,/sys,/dev,/run,/tmp,/var/tmp, PostgreSQL data and logs, the journal, apt, /root, /home/admin, /opt/m6b)",
        "changes only under the two ReadWritePaths (and systemd state)", f"{n0}->{n1} entries; changed {changed}", not bad)
    probe = ("pid=$(systemctl show -p MainPID --value bitscan-manager); u=$(id -u bitscan-manager); g=$(id -g bitscan-manager); "
             f"for p in / /etc /etc/bitscan /opt/bitscan-manager /usr /var /var/lib /var/lib/bitscan {BITS_DIR} /var/log /var/cache /srv /run "
             f"{BITS_DIR}/uploaded /var/lib/bitscan/audit-queue /tmp /var/tmp /run/lock /dev/shm; do "
             "if nsenter -t $pid -m -S $u -G $g touch $p/.m6b-w 2>/dev/null; then echo W $p; nsenter -t $pid -m rm -f $p/.m6b-w; fi; done; true")
    rc, wr = root(probe)
    writable = [ln[2:] for ln in wr.split("\n") if ln.startswith("W ")]
    rw_bad = [p for p in writable if p not in (f"{BITS_DIR}/uploaded", "/var/lib/bitscan/audit-queue", "/tmp", "/var/tmp", "/run/lock", "/dev/shm")]
    row("CHK-M6-055", "write probe as bitscan-manager inside the service's mount namespace",
        "persistent paths writable: only the two ReadWritePaths (private /tmp, /var/tmp, /dev/shm and the /run/lock tmpfs are non-persistent)", "writable: " + ", ".join(writable),
        not rw_bad and f"{BITS_DIR}/uploaded" in writable and "/var/lib/bitscan/audit-queue" in writable)

    # §11 install check
    rc, out = sh(sub(B["check"]))
    caps = re.findall(r"^(Cap\w+):\s+(\w+)", out, re.M)
    nnp = re.search(r"^NoNewPrivs:\s+(\d)", out, re.M)
    expect_modes = ["root:root 755 /etc/bitscan", "root:root 700 /etc/bitscan/secrets", "root:root 600 /etc/bitscan/manager.env",
                    "root:root 755 /var/lib/bitscan", f"root:bitscan-manager 750 {BITS_DIR}",
                    f"bitscan-manager:bitscan-manager 750 {BITS_DIR}/uploaded", "bitscan-manager:bitscan-manager 700 /var/lib/bitscan/audit-queue"]
    expect_modes += [f"root:root 600 /etc/bitscan/secrets/{f}" for f in ("app.dsn", "retention.dsn", "migrate.dsn", "tls.crt", "tls.key", "vault.token")]
    missing = [e for e in expect_modes if e not in out.split("\n")]
    row("CHK-M6-052", "§11 install check as written", "User=bitscan-manager active; four Cap 0, NoNewPrivs 1; modes of §4-§5; migrate.dsn Permission denied; cmp silent",
        out, "User=bitscan-manager" in out and "ActiveState=active" in out and len(caps) == 4 and all(v == "0000000000000000" for _, v in caps)
        and nnp is not None and nnp.group(1) == "1" and not missing and "Permission denied" in out and "differ" not in out)
    row("CHK-M6-046", "folder owners and modes equal TS §8.7 and §4-§5 of the runbook", "every expected line", f"missing {missing}", not missing)
    row("CHK-M6-054", "REQ-140 (4) CapEff/CapPrm/CapBnd/CapAmb 0, NoNewPrivs 1", "all 0; 1", str(caps) + f" NoNewPrivs {nnp.group(1) if nnp else None}",
        len(caps) == 4 and all(v == "0000000000000000" for _, v in caps) and nnp is not None and nnp.group(1) == "1")


def secret_sweep(log: Path | None) -> None:
    """CHK-M11-293: no secret value or token in the rows, the walk log or the
    manager-host journal. Values are compared in memory, never put on a command line."""
    texts = {"walk.jsonl": (OUT / "walk.jsonl").read_text()}
    if log is not None and log.exists():
        texts["walk log"] = log.read_text(errors="replace")
    rc, jr = root("journalctl --no-pager -o cat")
    texts["host journal"] = jr
    hits = []
    for name, text in texts.items():
        n = sum(text.count(v) for v in SECRET_VALUES if len(v) >= 8)
        n += len(re.findall(r"\bbs[uaek]_[A-Za-z0-9_-]{43}", text))
        if n:
            hits.append(f"{name}: {n}")
    row("CHK-M11-293", "secret sweep: no password, token, DSN or key line in the rows, the walk log or the host journal",
        "0 hits", f"values checked {len([v for v in SECRET_VALUES if len(v) >= 8])}; sources {sorted(texts)}; hits {hits or 0}", not hits)


def main() -> int:
    global OUT, CT, RELDIR  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--rel", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--runbook", type=Path, help="a copy of manager-install.md to walk (default: the tree's)")
    ap.add_argument("--name", default=CT, help="container name (default m6b-host)")
    ap.add_argument("--log", type=Path, help="the file this run's stdout goes to, for the secret sweep")
    ap.add_argument("--publish", action="append", default=[], help="docker -p value, e.g. 127.0.0.1:18443:8443 (default: none)")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    CT = a.name
    RELDIR = a.rel
    PUBLISH.extend(a.publish)
    OUT = a.work / "out"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "walk.jsonl").write_text("")
    runbook = a.runbook or a.tree / "deploy" / "runbooks" / "manager-install.md"
    vals = setup(a.tree, a.rel, a.work)
    try:
        walk(a.tree, runbook, vals, a.work)
    except Stop as e:
        print(f"walk stopped: {mask(str(e))}", flush=True)
    finally:
        secret_sweep(a.log)
        for d in ("ws-lab", "ws-org"):  # the workstation's keys go once §5 is done
            shutil.rmtree(a.work / d, ignore_errors=True)
        if not a.keep:  # without the host the test passwords serve nothing (kept hosts need them for the host checks)
            run(["docker", "rm", "-f", CT])
            shutil.rmtree(a.work / "secrets", ignore_errors=True)
    failed = [r for r in ROWS if r["status"] == "FAIL"]
    nr = [r for r in ROWS if r["status"] == "NOT RUN"]
    print(f"walk rows: {len(ROWS) - len(failed) - len(nr)}/{len(ROWS)} passed, {len(failed)} failed, {len(nr)} not run", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
