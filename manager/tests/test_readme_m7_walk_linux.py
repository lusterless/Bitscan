"""CHK-M7-305 (TASK-167, REQ-184): walk the README "Policies" section against
a real `serve` over HTTPS with a temporary bits folder, on PostgreSQL, with
the fake OpenBao and audit sink and the real clock (Linux: inotify).

Expected answers come from README.md, not from the code. Each documented
step is one row; a row that differs from the README is a deviation, the run
collects them all, and the test fails if there is any. With WALK_OUT set, the
rows are written there as JSON lines. The UI steps ("Upload policy",
"Rebuild catalog" pages) are covered by the web batch (TASK-168–173); here the
HTTP side of each step is walked. `sudo bitscan-manager bits rebuild` is
walked through `bits_main` with a temporary DSN file in place of
/etc/bitscan/secrets/app.dsn (the fixed path is tested in TASK-166).
"""

import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from bitscan_manager.auth.totp import code_at, step_at

from .catalog_rows import owner
from .certs import make_pki
from .conftest import PgServer, own_migrated_server
from .fake_sink import https_sink, server_context
from .fake_vault import fake_vault
from .test_cli_users_pg import run as run_users
from .test_readme_m5_walk_linux import V1, Totp, Walk, section, start_serve
from .test_serve_linux import CANARY_VAULT, Serve, env_for, free_port

pytestmark = pytest.mark.pg

if sys.platform == "win32":
    pytest.skip("not run: Linux only (serve, inotify)", allow_module_level=True)


def bit(
    name: str,
    uuids: list[str],
    execute: str = "cat /etc/hostname",
    status: str = "enabled",
    desc: str = "walk",
) -> bytes:
    plugins = "".join(
        "    <Plugin>\n"
        f"      <PluginName>{i}.1 - Check {i}</PluginName>\n"
        "      <PluginDescription>d</PluginDescription>\n"
        f"      <PluginId>{u}</PluginId>\n"
        f'      <Execute timeout="30"><![CDATA[{execute}]]></Execute>\n'
        "      <Operator>not_empty</Operator>\n"
        "      <ExpectedResult></ExpectedResult>\n"
        "    </Plugin>\n"
        for i, u in enumerate(uuids, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Policy formatVersion="1.0">\n'
        f"  <PolicyName>{name}</PolicyName>\n"
        f"  <PolicyDescription>{desc}</PolicyDescription>\n"
        f"  <PolicyStatus>{status}</PolicyStatus>\n"
        "  <Family>\n    <FamilyName>Walk Family</FamilyName>\n  </Family>\n"
        f"  <PluginsGroups>\n{plugins}  </PluginsGroups>\n</Policy>\n"
    ).encode()


def ids(n: int = 1) -> list[str]:
    return [str(uuid4()) for _ in range(n)]


def multipart(data: bytes, filename: str) -> tuple[bytes, dict[str, str]]:
    b = "walk" + secrets.token_hex(8)
    body = (
        (
            f'--{b}\r\nContent-Disposition: form-data; name="file";'
            f' filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode()
        + data
        + f"\r\n--{b}--\r\n".encode()
    )
    return body, {"Content-Type": f"multipart/form-data; boundary={b}"}


def until(pred: Callable[[], Any], bound: float = 15.0) -> Any:
    t0 = time.monotonic()
    while time.monotonic() - t0 < bound:
        got = pred()
        if got:
            return got
        time.sleep(0.2)
    return None


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("m7walk-db")) as server:
        yield server


@pytest.fixture
def stack(migrated_db: PgServer, tmp_path: Path) -> Iterator[dict[str, Any]]:
    pki = make_pki(tmp_path / "pki")
    sink_leaf, vault_leaf = pki.leaf("sink"), pki.leaf("vault")
    ui = tmp_path / "no-ui"
    ui.mkdir()
    with (
        https_sink(server_context(sink_leaf.cert, sink_leaf.key)) as sink,
        fake_vault(server_context(vault_leaf.cert, vault_leaf.key), CANARY_VAULT) as v,
    ):
        started: list[Serve] = []

        def serve(bits: Path) -> Serve:
            leaf = pki.leaf("srv-" + secrets.token_hex(3))
            port = free_port()
            run = tmp_path / ("run-" + secrets.token_hex(3))
            run.mkdir()
            env = env_for(
                migrated_db,
                run,
                pki,
                leaf,
                f"https://localhost:{sink.port}/audit",
                port,
                BITSCAN_VAULT_ADDR=f"https://127.0.0.1:{v.port}",
                BITSCAN_BITS_DIR=str(bits),
            )
            s = start_serve(env, run, ui, port, pki.ca, leaf.cert, leaf.key)
            started.append(s)
            return s

        try:
            yield {"serve": serve}
        finally:
            for s in started:
                if s.proc.poll() is None:
                    s.stop()


def test_the_m7_policies_section_behaves_as_written(  # noqa: PLR0915
    stack: dict[str, Any], migrated_db: PgServer, tmp_path: Path
) -> None:
    text = section("Policies")
    totp = Totp()
    bits = tmp_path / "bits"
    (bits / "uploaded").mkdir(parents=True)
    t = secrets.token_hex(3)

    # A file there before start-up is imported at start-up.
    pre = f"Walk pre {t}"
    (bits / "pre.bit").write_bytes(bit(pre, ids()))
    s = stack["serve"](bits)
    w = Walk(s.port, s.ca)

    # ----------------------------------------------------- an admin with TOTP
    admin, pw = f"m7-adm-{t}", "m7 walk pass " + secrets.token_hex(6)
    w.secrets.append(pw)
    dsn = next(tmp_path.glob("run-*/creds/app_dsn"))
    assert run_users(["create-admin", admin], dsn, stdin=pw + "\n").returncode == 0
    _, _, out = w.req(
        "POST",
        V1 + "/auth/login",
        body={"username": admin, "password": pw, "totp_code": None},
    )
    s0 = json.loads(out)["token"]
    w.secrets.append(s0)
    _, _, out = w.req("POST", V1 + "/auth/totp/enrol", token=s0, body={})
    secret = json.loads(out)["secret"]
    w.secrets.append(secret)
    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    _, _, out = w.req(
        "POST", V1 + "/auth/totp/enrol", token=s0, body={"totp_code": totp.code(seed)}
    )
    S = json.loads(out)["token"]  # a TOTP-verified session
    w.secrets.append(S)
    _, _, out = w.req("POST", V1 + "/api-tokens", token=S, body={"name": "m7-walk"})
    K = json.loads(out)["token"]  # an admin bsk_ token
    w.secrets.append(K)

    def policies(token: str = S, q: str = "") -> list[dict[str, Any]]:
        st, _, out = w.req("GET", V1 + "/policies?limit=500" + q, token=token)
        assert st == 200, out
        items: list[dict[str, Any]] = json.loads(out)["items"]
        return items

    def by_name(name: str) -> dict[str, Any] | None:
        return next((p for p in policies() if p["policy_name"] == name), None)

    def imports() -> list[dict[str, Any]]:
        _, _, out = w.req("GET", V1 + "/imports?limit=500", token=K)
        items: list[dict[str, Any]] = json.loads(out)["items"]
        return items

    def audit(action: str) -> list[dict[str, Any]]:
        _, _, out = w.req("GET", V1 + "/audit-log?limit=500", token=K)
        return [e for e in json.loads(out)["items"] if e["action"] == action]

    p_pre = until(lambda: by_name(pre))
    w.check(
        "start-up imports what is in the folder",
        "serve with pre.bit",
        "listed",
        "listed" if p_pre else "missing",
        p_pre is not None,
    )

    # ----------------------------------------------------- the server folder
    name_a = f"Walk A {t}"
    src = tmp_path / "a.bit"
    src.write_bytes(bit(name_a, ids()))
    shutil.copy(src, bits / "a.bit")
    p_a = until(lambda: by_name(name_a))
    w.check(
        "the watcher imports a copied file within seconds",
        "cp a.bit",
        "listed within 15 s",
        "listed" if p_a else "missing",
        p_a is not None,
    )
    assert p_a is not None
    pid_a = p_a["policy_id"]
    (bits / ".hidden.bit").write_bytes(bit(f"Walk hidden {t}", ids()))
    (bits / "sub").mkdir()
    (bits / "sub" / "s.bit").write_bytes(bit(f"Walk sub {t}", ids()))
    (bits / "link.bit").symlink_to(src)
    (bits / "notes.txt").write_bytes(bit(f"Walk txt {t}", ids()))
    sentinel = f"Walk sentinel {t}"
    (bits / "zz-sentinel.bit").write_bytes(bit(sentinel, ids()))
    until(lambda: by_name(sentinel))
    names = {p["policy_name"] for p in policies()}
    ignored = {f"Walk hidden {t}", f"Walk sub {t}", f"Walk txt {t}"}
    w.check(
        "hidden files, sub-folders, symlinks and other names are ignored",
        "write .hidden.bit, sub/s.bit, link.bit, notes.txt",
        "none imported",
        str(sorted(ignored & names)),
        not (ignored & names)
        and not any(i["file_name"] in ("link.bit",) for i in imports()),
    )
    rename = f"Walk A renamed {t}"
    uu = ids()
    (bits / "a.bit").write_bytes(bit(rename, uu))
    got = until(lambda: by_name(rename))
    w.check(
        "renaming PolicyName in the same file keeps its id",
        "edit a.bit",
        f"policy_id {pid_a}",
        str(got and got["policy_id"]),
        bool(got) and got["policy_id"] == pid_a,
    )
    (bits / "b.bit").write_bytes(bit(rename, ids()))
    rej = until(lambda: next((i for i in imports() if i["file_name"] == "b.bit"), None))
    w.check(
        "a second server file with that name is rejected with BIT007",
        "write b.bit",
        "rejected BIT007",
        str(rej and (rej["outcome"], [e["code"] for e in rej["errors"]])),
        bool(rej)
        and rej["outcome"] == "rejected"
        and [e["code"] for e in rej["errors"]] == ["BIT007"],
    )
    (bits / "b.bit").unlink()
    data_a = (bits / "a.bit").read_bytes()
    (bits / "a.bit").write_bytes(data_a)  # unchanged content, written again
    sk = until(
        lambda: next(
            (
                i
                for i in imports()
                if i["file_name"] == "a.bit" and i["outcome"] == "skipped"
            ),
            None,
        )
    )
    w.check(
        "an automatic import of unchanged content is skipped",
        "rewrite a.bit",
        "skipped, mode auto",
        str(sk and (sk["outcome"], sk["mode"])),
        bool(sk) and sk["mode"] == "auto",
    )
    v0 = (by_name(rename) or {}).get("version", 0)
    (bits / "a.bit").write_bytes(bit(rename, uu, desc="changed"))
    v1 = until(lambda: (p := by_name(rename)) and p["version"] > v0 and p["version"])
    w.check(
        "changed content adds 1 to version",
        "edit a.bit",
        f"version {v0 + 1}",
        str(v1),
        v1 == v0 + 1,
    )

    # ----------------------------------------------------- upload
    up_name = f"Walk upload {t}"
    up_ids = ids(2)
    body, h = multipart(bit(up_name, up_ids), "my-client-name.bit")
    st, _, out = w.req("POST", V1 + "/policies/import", token=S, raw=body, headers=h)
    res = json.loads(out) if st == 200 else {}
    keys = [
        "import_id",
        "outcome",
        "policy_id",
        "policy_name",
        "policy_version",
        "plugins_added",
        "plugins_updated",
        "plugins_retired",
        "errors",
    ]
    w.check(
        "upload: 200 with the documented keys",
        "POST /policies/import (session)",
        f"200 {keys} success",
        f"{st} {sorted(res)} {res.get('outcome')}",
        st == 200 and sorted(res) == sorted(keys) and res["outcome"] == "success",
    )
    up_pid = res.get("policy_id")
    stored = bits / "uploaded" / f"policy-{up_pid}.bit"
    w.check(
        "kept as uploaded/policy-<id>.bit only",
        "ls uploaded/",
        f"policy-{up_pid}.bit",
        str(sorted(p.name for p in (bits / "uploaded").iterdir())),
        sorted(p.name for p in (bits / "uploaded").iterdir()) == [stored.name],
    )
    hist = next((i for i in imports() if i["import_id"] == res.get("import_id")), {})
    w.check(
        "the uploaded name is kept only in the import history",
        "GET /imports",
        "file_name my-client-name.bit",
        str(hist.get("file_name")),
        hist.get("file_name") == "my-client-name.bit",
    )
    body, h = multipart(bit(f"Walk api {t}", ids()), "k.bit")
    st, _, out = w.req("POST", V1 + "/policies/import", token=K, raw=body, headers=h)
    w.check(
        "an admin bsk_ token may upload",
        "POST /policies/import (bsk_)",
        "200",
        str(st),
        st == 200,
    )
    body, h = multipart(bit(f"Walk bad {t}", ids(), execute="rm x"), "bad.bit")
    st, _, out = w.req("POST", V1 + "/policies/import", token=S, raw=body, headers=h)
    r = json.loads(out) if st == 200 else {}
    errs = r.get("errors") or []
    w.check(
        "a rejected upload is 200 with every finding",
        "POST /policies/import (rm x)",
        "200 rejected BIT102 {line,element,code,message}",
        f"{st} {r.get('outcome')} {[e.get('code') for e in errs]}",
        st == 200
        and r.get("outcome") == "rejected"
        and [e["code"] for e in errs] == ["BIT102"]
        and set(errs[0]) == {"line", "element", "code", "message"},
    )
    body, h = multipart(b"<!--" + b"a" * (5 * 1024 * 1024 + 1) + b"-->", "big.bit")
    st, _, _ = w.req("POST", V1 + "/policies/import", token=S, raw=body, headers=h)
    w.check(
        "a file larger than 5 MiB gets 413",
        "POST /policies/import (5 MiB + 1)",
        "413",
        str(st),
        st == 413,
    )
    body, h = multipart(bit(rename, ids()), "srv.bit")
    w.expect(
        "a server-folder policy can't be uploaded",
        "POST",
        V1 + "/policies/import",
        409,
        "policy_managed_on_server",
        token=S,
        raw=body,
        headers=h,
    )
    (bits / "takeover.bit").write_bytes(bit(up_name, up_ids, desc="server"))
    moved = until(
        lambda: next(
            (
                p
                for p in policies()
                if p["policy_name"] == up_name and p["source_file"] == "takeover.bit"
            ),
            None,
        )
    )
    w.check(
        "a server file with an uploaded policy's name takes it over",
        "write takeover.bit",
        "same id, source_file takeover.bit, copy deleted, move audited",
        f"{bool(moved)} copy={stored.exists()} moves={len(audit('policy.move'))}",
        bool(moved)
        and moved["policy_id"] == up_pid
        and not stored.exists()
        and len(audit("policy.move")) >= 1,
    )

    # ----------------------------------------------------- status, delete, history
    item = by_name(rename) or {}
    item_keys = [
        "policy_id",
        "policy_name",
        "policy_description",
        "policy_status",
        "file_status",
        "status_overridden",
        "family_id",
        "family_name",
        "format_version",
        "version",
        "source_file",
        "plugin_count",
        "imported_at",
        "updated_at",
    ]
    w.check(
        "the list item keys",
        "GET /policies",
        str(item_keys),
        str(list(item)),
        list(item) == item_keys,
    )
    _, _, out = w.req("GET", V1 + f"/policies/{pid_a}", token=K)
    d = json.loads(out)
    w.check(
        "the detail adds deleted_at and plugins",
        f"GET /policies/{pid_a}",
        "deleted_at, plugins",
        str([k for k in d if k not in item_keys]),
        [k for k in d if k not in item_keys] == ["deleted_at", "plugins"],
    )
    st, _, out = w.req(
        "PATCH", V1 + f"/policies/{pid_a}", token=K, body={"policy_status": "disabled"}
    )
    pj = json.loads(out)
    w.check(
        "PATCH disabled sets an override (API token)",
        "PATCH policy_status",
        "200 disabled, status_overridden true",
        f"{st} {pj.get('policy_status')} {pj.get('status_overridden')}",
        st == 200 and pj["policy_status"] == "disabled" and pj["status_overridden"],
    )
    w.check(
        "?status=disabled lists it",
        "GET /policies?status=disabled",
        "listed",
        str(any(p["policy_id"] == pid_a for p in policies(q="&status=disabled"))),
        any(p["policy_id"] == pid_a for p in policies(q="&status=disabled")),
    )
    n0 = len(
        [
            e
            for e in audit("policy.status_change")
            if e["detail"].get("alert_kind") == "policy_reenabled"
        ]
    )
    st, _, out = w.req(
        "PATCH", V1 + f"/policies/{pid_a}", token=K, body={"status_overridden": False}
    )
    pj = json.loads(out)
    n1 = len(
        [
            e
            for e in audit("policy.status_change")
            if e["detail"].get("alert_kind") == "policy_reenabled"
        ]
    )
    w.check(
        "clearing the override takes the file's status, and re-enabling alerts",
        "PATCH status_overridden false",
        "enabled, override false, policy_reenabled",
        f"{pj.get('policy_status')} {pj.get('status_overridden')} alerts+{n1 - n0}",
        pj.get("policy_status") == "enabled"
        and pj.get("status_overridden") is False
        and n1 == n0 + 1,
    )
    api_pid = (by_name(f"Walk api {t}") or {}).get("policy_id")
    w.expect(
        "DELETE refuses an API token",
        "DELETE",
        V1 + f"/policies/{api_pid}",
        403,
        "totp_session_required",
        token=K,
    )
    w.expect(
        "DELETE answers 204 (TOTP session)",
        "DELETE",
        V1 + f"/policies/{api_pid}",
        204,
        token=S,
    )
    w.check(
        "a delete raises policy_deleted",
        "GET /audit-log",
        "policy.delete alert",
        str(len(audit("policy.delete"))),
        any(
            e["detail"].get("alert_kind") == "policy_deleted"
            for e in audit("policy.delete")
        ),
    )
    w.expect(
        "an already deleted policy: 409 conflict",
        "DELETE",
        V1 + f"/policies/{api_pid}",
        409,
        "conflict",
        token=S,
    )
    w.expect("an unknown id: 404", "DELETE", V1 + "/policies/999999999", 404, token=S)
    w.expect(
        "a server-folder policy: 409",
        "DELETE",
        V1 + f"/policies/{pid_a}",
        409,
        "policy_managed_on_server",
        token=S,
    )
    w.expect(
        "PATCH of a deleted policy: 409",
        "PATCH",
        V1 + f"/policies/{api_pid}",
        409,
        token=K,
        body={"policy_status": "enabled"},
    )
    body, h = multipart(bit(f"Walk api {t}", ids()), "again.bit")
    st, _, out = w.req("POST", V1 + "/policies/import", token=S, raw=body, headers=h)
    back = json.loads(out) if st == 200 else {}
    w.check(
        "uploading the same name brings it back: same id, new version",
        "POST /policies/import (same name)",
        f"policy_id {api_pid}",
        f"{back.get('policy_id')} v{back.get('policy_version')}",
        back.get("policy_id") == api_pid and (back.get("policy_version") or 0) >= 2,
    )
    history = imports()
    ih_keys = [
        "import_id",
        "file_name",
        "file_sha256",
        "policy_version",
        "mode",
        "outcome",
        "plugins_added",
        "plugins_updated",
        "plugins_retired",
        "errors",
        "imported_by",
        "imported_at",
    ]
    w.check(
        "import history: keys, newest first, modes and outcomes",
        "GET /imports",
        "documented keys; ids descending",
        f"{list(history[0])} {sorted({i['mode'] for i in history})}",
        list(history[0]) == ih_keys
        and [i["import_id"] for i in history]
        == sorted((i["import_id"] for i in history), reverse=True)
        and {i["mode"] for i in history} <= {"auto", "manual", "rebuild"}
        and {i["outcome"] for i in history} == {"success", "skipped", "rejected"},
    )

    # ----------------------------------------------------- rebuild
    w.expect(
        "rebuild refuses an API token",
        "POST",
        V1 + "/policies/rebuild",
        403,
        "totp_session_required",
        token=K,
        body={},
    )
    st, _, out = w.req("POST", V1 + "/policies/rebuild", token=S, body={})
    tid = json.loads(out).get("task_id") if st == 202 else None
    w.check(
        "rebuild answers 202 with task_id",
        "POST /policies/rebuild",
        "202 task_id",
        f"{st} {bool(tid)}",
        st == 202 and bool(tid),
    )

    def task() -> dict[str, Any] | None:
        _, _, out = w.req("GET", V1 + f"/tasks/{tid}", token=K)
        j: dict[str, Any] = json.loads(out)
        return j if j.get("state") != "running" else None

    tj = until(task, 60) or {}
    res_keys = [
        "files",
        "deleted_policy_ids",
        "plugins_retired",
        "removed_leftovers",
        "not_imported",
    ]
    w.check(
        "the task succeeds with the documented result",
        f"GET /tasks/{tid}",
        f"succeeded {res_keys}",
        f"{tj.get('state')} {sorted(tj.get('result') or {})}",
        tj.get("state") == "succeeded"
        and sorted(tj["result"]) == sorted(res_keys)
        and set(tj)
        == {
            "task_id",
            "kind",
            "state",
            "requested_by",
            "result",
            "started_at",
            "finished_at",
        }
        and all(
            set(f)
            == {"source_file", "import_id", "outcome", "policy_id", "policy_version"}
            for f in tj["result"]["files"]
        ),
    )
    w.check(
        "a rebuild raises policy_rebuilt",
        "GET /audit-log",
        "bits.rebuild alert",
        str(len(audit("bits.rebuild"))),
        any(
            e["detail"].get("alert_kind") == "policy_rebuilt"
            for e in audit("bits.rebuild")
        ),
    )
    cli = (
        "import sys, pathlib\nfrom bitscan_manager.cli.bits import bits_main\n"
        f"sys.exit(bits_main(['rebuild'], dsn_file=pathlib.Path({str(dsn)!r}),"
        " env_file=pathlib.Path('/nonexistent/m.env')))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    env["BITSCAN_BITS_DIR"] = str(bits)
    p = subprocess.run(  # noqa: S603 - fixed argv, no untrusted input
        [sys.executable, "-c", cli],
        capture_output=True,
        text=True,  # noqa: S603
        env=env,
        timeout=120,
    )
    lines = p.stdout.splitlines()
    w.check(
        "bits rebuild: a line per file, a summary, exit 0",
        "bits rebuild",
        "success ... lines, 'rebuild succeeded:' summary, exit 0",
        f"exit {p.returncode}, {len(lines)} lines",
        p.returncode == 0
        and any(x.startswith("success ") for x in lines)
        and lines[-1].startswith("rebuild succeeded:"),
    )
    (bits / "pre.bit").unlink()  # deleted by the watcher
    until(lambda: by_name(pre) is None)
    w.check(
        "removing a file deletes its policy",
        "rm pre.bit",
        "gone from the list",
        str(by_name(pre) is None),
        by_name(pre) is None,
    )

    # ----------------------------------------------------- start-up
    s.stop()
    with owner(migrated_db) as c:  # a damaged catalog while the manager is down
        c.execute(
            "UPDATE plugin SET state = 'retired' WHERE plugin_uuid = %s", (uu[0],)
        )
    s2 = stack["serve"](bits)
    w2 = Walk(s2.port, s2.ca, secrets=w.secrets)

    def integrity() -> list[dict[str, Any]]:
        _, _, out = w2.req("GET", V1 + "/audit-log?limit=500", token=K)
        return [
            e
            for e in json.loads(out)["items"]
            if e["action"] == "catalog.integrity_check"
        ]

    found = until(integrity, 30)
    w.check(
        "a damaged catalog raises catalog_integrity_failed at start-up",
        "restart serve",
        "one alert listing the policy",
        str(found and found[0]["detail"].get("differences")),
        bool(found)
        and found[0]["detail"].get("alert_kind") == "catalog_integrity_failed"
        and any(
            d["subject"] == f"policy:{pid_a}" for d in found[0]["detail"]["differences"]
        ),
    )
    s2.stop()
    broken = tmp_path / "broken-bits"
    broken.mkdir()  # no uploaded/: the start-up never finishes
    s3 = stack["serve"](broken)
    w3 = Walk(s3.port, s3.ca)
    body, h = multipart(bit(f"Walk starting {t}", ids()), "s.bit")
    st, hdrs, _ = w3.req("POST", V1 + "/policies/import", token=S, raw=body, headers=h)
    w.check(
        "until start-up has finished: 503 with Retry-After: 10",
        "POST /policies/import during start-up",
        "503 Retry-After 10",
        f"{st} {hdrs.get('retry-after')}",
        st == 503 and hdrs.get("retry-after") == "10",
    )
    s3.stop()
    w.check(
        "the README names the hard-link warning and the sink size note",
        "Policies",
        "both stated",
        "checked",
        "don't hard-link files into the bits folder" in text and "8 KiB" in text,
    )

    out_path = os.environ.get("WALK_OUT")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            for row in w.rows:
                f.write(json.dumps(row.__dict__) + "\n")
    deviations = [row for row in w.rows if not row.ok]
    assert not deviations, "\n".join(
        f"{row.label}: {row.request}: expected {row.expected}, got {row.actual}"
        for row in deviations
    )
    assert len(w.rows) >= 30
    _ = (datetime, UTC, code_at, step_at)
