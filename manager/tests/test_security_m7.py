"""TP-M7-30: the M7 importer security suite (REQ-177; CHK-M7-285).

TS §8.3 Security (L1283), importer half, end to end through the real routes,
the real catalog service, start-up sequence, sink gate and auth, on a
database of this module's own with a temporary bits folder:
- XML attacks (XXE by file and URL, parameter entities, external DTDs, DTDs,
  billion laughs, quadratic blow-up) and oversize files are refused (TS §4.1,
  §8.1 L1251; SR §4.1 BIT001), by upload, at start-up and by rebuild, and
  nothing is stored, opened or fetched;
- symlinks and FIFOs in either folder are never followed (#102 (b)), and a
  symlink at an upload's temp or final path is never written through
  (REQ-163 (2));
- an uploaded file never lands at a client-chosen path (TS §4.1 L522, #99 (d));
- tokens on the wrong route group are refused on every M7 route (TS §6
  L1056); API tokens are refused on delete and rebuild (TS §6.2 L1084,
  L1104, L1105); non-admins cannot upload or delete (TS §8.1 L1241, L1253);
- sensitive catalog actions are refused during a long sink outage (TS §5.3
  L1051, #1);
- no plugin text or token reaches a log line (TS §8.1, §8.4; security
  invariants "Secrets and output");
- every import, rejection, delete, rebuild and re-enable alerts (TS §4.1 L530,
  §8.4 L1289-L1291; #100, #101), and the alert reaches the sink;
- BIT015 and BIT102 rejections (TS §8.3 L1283). BIT102 uses only the cases
  settled before TASK-146 r2 (lead 2026-10-28): `rm x` is rejected and the
  shipped samples pass.
Expected values come from the spec and the approved answers, not from code.
An oversize **upload** is a 413 with no row (#99 (b)); an oversize folder
file is a BIT001 rejection with its row.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from bitscan_manager.app import create_app
from bitscan_manager.auth.tokens import AgentTokenKind, new_agent_token, token_hash

from .bit_unit import BT, SAMPLES, connected, fixture, listener
from .canary import new_canary, sweep
from .catalog_api import (
    IMPORT,
    PART_CAP,
    POLICIES,
    REBUILD,
    TASKS,
    CatEnv,
    RecordingSink,
    alerts,
    make_env,
    multipart,
    padded,
    part,
    policy_doc,
    sha,
    until,
)
from .catalog_rows import app, tag
from .conftest import PgServer, own_migrated_server
from .test_users_api_pg import problem

pytestmark = pytest.mark.pg

CTYPE = "multipart/form-data; boundary=bsTesterM7dBoundary"
IMPORTS = "/api/v1/imports"

# --- every open() of a watched path, from any thread (the import runs in the
# thread pool or on the catalog worker) -----------------------------------------
WATCHED: set[str] = set()
OPENED: list[str] = []


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event == "open" and WATCHED and args and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0])
        if path in WATCHED:
            OPENED.append(path)


sys.addaudithook(_audit)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("security-m7")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[CatEnv]:
    yield from make_env(server, tmp_path)


@pytest.fixture
def watched() -> Iterator[set[str]]:
    WATCHED.clear()
    OPENED.clear()
    yield WATCHED
    WATCHED.clear()


def mkfifo(path: Path) -> None:
    if sys.platform == "win32":
        pytest.fail("FIFOs need POSIX; the PostgreSQL suites run on Linux only")
    else:
        os.mkfifo(path)


def names_in_catalog(e: CatEnv) -> set[str]:
    return {n for (n,) in e.q("SELECT policy_name FROM policy")}


def rows_after(e: CatEnv, mark: int) -> list[dict[str, Any]]:
    rows = e.q(
        "SELECT import_id, file_name, file_sha256, mode::text, outcome::text, errors"
        " FROM bit_import WHERE import_id > %s ORDER BY import_id",
        (mark,),
    )
    keys = ("import_id", "file_name", "file_sha256", "mode", "outcome", "errors")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def codes(errors: list[dict[str, Any]]) -> list[str]:
    return [f["code"] for f in errors]


def rebuild(e: CatEnv) -> dict[str, Any]:
    _, tok = e.admin_session()
    r = e.call("POST", tok, REBUILD)
    assert r.status_code == 202, r.text
    tid = r.json()["task_id"]

    def done() -> Any:
        t = e.call("GET", tok, f"{TASKS}/{tid}").json()
        return t if t["state"] != "running" else None

    got: dict[str, Any] = until(done, 60)
    assert got["state"] == "succeeded", got
    return got


# --- XML attacks and oversize (TS §8.1 L1251; SR §4.1 BIT001) ------------------

XML_ATTACKS = [
    "bit001/xxe-file.bit",
    "bit001/xxe-url.bit",
    "bit001/parameter-entity.bit",
    "bit001/parameter-entity-internal.bit",
    "bit001/external-dtd-file.bit",
    "bit001/external-dtd-url.bit",
    "bit001/billion-laughs.bit",
    "bit001/quadratic-blowup.bit",
    "bit001/dtd-only.bit",
    "bit001/dtd-element-decl.bit",
    "bit001/undefined-entity.bit",
]
MANIFEST: dict[str, dict[str, Any]] = {
    f["file"]: f
    for f in json.loads((BT / "manifest.json").read_text(encoding="utf-8"))["fixtures"]
}


def fixture_name(data: bytes) -> str:
    start = data.index(b"<PolicyName>") + len(b"<PolicyName>")
    return data[start : data.index(b"</PolicyName>")].decode()


@pytest.mark.parametrize("name", XML_ATTACKS)
def test_an_xml_attack_upload_is_bit001_and_nothing_is_stored_read_or_fetched(
    env: CatEnv,
    name: str,
    tmp_path: Path,
    watched: set[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = new_canary("xxe")
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary.txt"
    canary.write_text(secret, encoding="utf-8")
    watched.add(str(canary))
    _, tok = env.admin_api()
    before = names_in_catalog(env)
    with listener() as (port, srv), caplog.at_level(logging.DEBUG):
        data = fixture(name, canary=str(canary), port=port)
        assert MANIFEST[name]["codes"] == ["BIT001"]
        t0 = time.monotonic()
        r = env.upload(tok, data)
        elapsed = time.monotonic() - t0
        assert not connected(srv), "the parser fetched an external resource"
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "rejected"
    assert codes(body["errors"]) == ["BIT001"]
    assert body["policy_id"] is None
    assert env.tree() == {}  # nothing stored
    assert fixture_name(data) not in names_in_catalog(env)
    assert names_in_catalog(env) == before
    assert OPENED == []  # the external file was never opened
    row = env.import_row(body["import_id"])
    assert sweep([secret], r, json.dumps(row["errors"]), caplog.text) == []
    assert elapsed < 10, elapsed  # bounded (manifest: billion laughs < 2 s)


def test_an_oversize_upload_is_413_with_no_row(env: CatEnv) -> None:
    _, tok = env.admin_api()
    mark = env.last_import()
    data = padded(policy_doc(f"m7sec-big-{tag()}"), PART_CAP + 1)
    problem(env.upload(tok, data), 413, "too_large")
    assert env.last_import() == mark  # #99 (b): an HTTP refusal, not an import
    assert env.tree() == {}


def test_attacks_and_oversize_in_the_server_folder_are_bit001_at_start_up_and_rebuild(
    env: CatEnv, tmp_path: Path, watched: set[str]
) -> None:
    secret = new_canary("xxe-folder")
    canary = tmp_path / "canary.txt"
    canary.write_text(secret, encoding="utf-8")
    watched.add(str(canary))
    big_name = f"m7sec-bigfolder-{tag()}"
    files = {
        "xxe.bit": fixture("bit001/xxe-file.bit", canary=str(canary)),
        "laughs.bit": fixture("bit001/billion-laughs.bit"),
        "blowup.bit": fixture("bit001/quadratic-blowup.bit"),
        "dtd.bit": fixture("bit001/dtd-only.bit"),
        "big.bit": padded(policy_doc(big_name), PART_CAP + 1),
    }
    for rel, data in files.items():
        env.put_server(rel, data)
    mark = env.last_import()
    env.restart()  # the start-up reconcile (auto mode)
    after_start = rows_after(env, mark)
    task = rebuild(env)  # and a rebuild (rebuild mode)
    rows = rows_after(env, mark)
    for mode in ("auto", "rebuild"):
        mine = {r["file_sha256"]: r for r in rows if r["mode"] == mode}
        for rel, data in files.items():
            hit = mine[sha(data)]  # a rejected row for each file in each mode
            assert (hit["outcome"], codes(hit["errors"])) == ("rejected", ["BIT001"]), (
                mode, rel,
            )  # fmt: skip
    assert len(after_start) == len(files)
    by_file = {f["source_file"]: f for f in task["result"]["files"]}
    assert {rel: by_file[rel]["outcome"] for rel in files} == dict.fromkeys(
        files, "rejected"
    )
    assert big_name not in names_in_catalog(env)
    assert OPENED == []
    assert secret not in json.dumps([r["errors"] for r in rows])


# --- symlinks and FIFOs are never followed (#102 (b), REQ-163 (2)) -------------


def test_symlinks_and_fifos_in_both_folders_are_never_followed(
    env: CatEnv, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    n1, n2, n3 = (f"m7sec-link-{tag()}" for _ in range(3))
    targets = {
        "srv": outside / "srv-target.bit",
        "upl": outside / "upl-target.bit",
        "pol": outside / "pol-target.bit",
    }
    targets["srv"].write_bytes(policy_doc(n1))
    targets["upl"].write_bytes(policy_doc(n2))
    targets["pol"].write_bytes(policy_doc(n3))
    before = {k: (p.read_bytes(), p.stat().st_mtime_ns) for k, p in targets.items()}
    links = {
        "link.bit": targets["srv"],
        "uploaded/link.bit": targets["upl"],
        "uploaded/policy-999999.bit": targets["pol"],
    }
    for rel, target in links.items():
        os.symlink(target, env.bits / rel)
    mkfifo(env.bits / "fifo.bit")
    mkfifo(env.bits / "uploaded" / "fifo.bit")
    mark = env.last_import()
    env.restart()  # start-up must finish: a FIFO never blocks it
    task = rebuild(env)
    assert {n1, n2, n3}.isdisjoint(names_in_catalog(env))
    skipped = {*links, "fifo.bit", "uploaded/fifo.bit"}
    assert skipped.isdisjoint(f["source_file"] for f in task["result"]["files"])
    assert rows_after(env, mark) == []  # not even a rejected row
    for rel, target in links.items():
        assert (env.bits / rel).is_symlink() and os.readlink(env.bits / rel) == str(
            target
        )
    assert {
        k: (p.read_bytes(), p.stat().st_mtime_ns) for k, p in targets.items()
    } == before


def test_a_symlink_at_the_temp_or_final_upload_path_is_never_written_through(
    env: CatEnv, tmp_path: Path
) -> None:
    _, tok = env.admin_api()
    name = f"m7sec-tmp-{tag()}"
    v1, v2, v3 = (policy_doc(name, plugins=n) for n in (1, 2, 3))
    pid = env.uploaded(tok, v1)
    target = tmp_path / "keep.txt"
    target.write_bytes(b"keep")
    # (1) at the temp path: the O_EXCL | O_NOFOLLOW create fails, no import
    temp = env.bits / "uploaded" / f".tmp-{pid}-{sha(v2)}"
    os.symlink(target, temp)
    mark = env.last_import()
    problem(env.upload(tok, v2), 503, "about:blank")
    assert target.read_bytes() == b"keep" and temp.is_symlink()
    assert env.last_import() == mark
    assert (env.bits / "uploaded" / f"policy-{pid}.bit").read_bytes() == v1
    # (2) at the final path: the rename replaces the link, never its target
    final = env.bits / "uploaded" / f"policy-{pid}.bit"
    final.unlink()
    os.symlink(target, final)
    assert env.upload(tok, v3).json()["outcome"] == "success"
    assert target.read_bytes() == b"keep"
    assert not final.is_symlink() and final.read_bytes() == v3


# --- an upload never lands at a client-chosen path (TS §4.1 L522) --------------

CLIENT_PATHS = [
    b"../../etc/passwd",
    b"/abs.bit",
    b"a/b.bit",
    b"..",
    b"../outside.bit",
    b".tmp-1-" + b"0" * 64,
    b"policy-1.bit",
    b"uploaded/policy-1.bit",
    b"C:\\Windows\\x.bit",
]


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "q" not in p.relative_to(root).parts[:1]
    }


@pytest.mark.parametrize("raw", CLIENT_PATHS)
def test_an_upload_lands_only_at_its_policy_path(
    env: CatEnv, tmp_path: Path, raw: bytes
) -> None:
    _, tok = env.admin_api()
    before = snapshot(tmp_path)
    data = policy_doc(f"m7sec-path-{tag()}")
    body = env.upload(tok, data, filename=raw).json()
    assert body["outcome"] == "success", body
    pid = body["policy_id"]
    after = snapshot(tmp_path)
    assert {k: v for k, v in after.items() if k not in before} == {
        f"bits/uploaded/policy-{pid}.bit": data
    }
    assert all(after[k] == v for k, v in before.items())
    assert env.policy(pid)["source_file"] == f"uploaded/policy-{pid}.bit"


# --- token groups, API tokens, roles, the sink gate (TS §6, §6.2, §5.3) --------


def m7_operations(pid: int) -> list[tuple[str, str, dict[str, Any]]]:
    upload = {
        "content": multipart([part(policy_doc(f"m7sec-op-{tag()}"))]),
        "headers": {"Content-Type": CTYPE},
    }
    return [
        ("GET", POLICIES, {}),
        ("GET", f"{POLICIES}/{pid}", {}),
        ("PATCH", f"{POLICIES}/{pid}", {"json": {"policy_status": "disabled"}}),
        ("DELETE", f"{POLICIES}/{pid}", {}),
        ("POST", IMPORT, upload),
        ("POST", REBUILD, {}),
        ("GET", f"{TASKS}/{uuid4()}", {}),
        ("GET", IMPORTS, {}),
    ]


def test_the_walk_covers_every_m7_operation() -> None:
    doc = create_app().openapi()
    found = {
        (method.upper(), path)
        for path, ops in doc["paths"].items()
        if path.startswith((POLICIES, TASKS, IMPORTS))
        for method in ops
    }
    expected = {
        (m, p.replace("/1", "/{id}") if p.startswith(f"{POLICIES}/1") else p)
        for m, p, _ in m7_operations(1)
    }
    expected = {
        (m, f"{TASKS}/{{id}}" if p.startswith(f"{TASKS}/") else p) for m, p in expected
    }
    assert found == expected


def agent_headers(e: CatEnv) -> dict[str, dict[str, str]]:
    stored = new_agent_token(AgentTokenKind.AGENT)
    with app(e.server) as c, c.transaction():
        c.execute(
            "INSERT INTO agent (machine_id, hostname, agent_version, token_hash,"
            " token_issued_at, token_expires_at, status) VALUES (%s, 'h', 'v', %s,"
            " now(), now() + interval '30 days', 'online')",
            (uuid4().hex, token_hash(stored)),
        )
    return {
        "bsa": {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.AGENT)}"},
        "bsa_enrolled": {"Authorization": f"Bearer {stored}"},
        "bse": {"Authorization": f"Bearer {new_agent_token(AgentTokenKind.ENROLMENT)}"},
    }


def test_agent_tokens_are_refused_on_every_m7_route(env: CatEnv) -> None:
    _, tok = env.admin_api()
    pid = env.uploaded(tok, policy_doc(f"m7sec-ag-{tag()}"))
    groups = agent_headers(env)
    state = env.state()
    for kind, auth in groups.items():
        # 8 failed checks per minute stay under the 20/min per-IP limit (TS §6.3)
        env.clock.at += timedelta(seconds=61)
        for method, path, kw in m7_operations(pid):
            headers = {**kw.get("headers", {}), **auth}
            extra = {k: v for k, v in kw.items() if k != "headers"}
            r = env.client.request(method, path, headers=headers, **extra)
            problem(r, 401, "unauthorized")
            assert "policy_id" not in r.text, (kind, method, path)
    assert env.state() == state
    assert env.policy(pid)["policy_status"] == "enabled"


def test_api_tokens_are_refused_on_delete_and_rebuild(env: CatEnv) -> None:
    uid, api = env.admin_api()
    pid = env.uploaded(api, policy_doc(f"m7sec-api-{tag()}"))
    state = env.state()
    problem(env.call("DELETE", api, f"{POLICIES}/{pid}"), 403, "totp_session_required")
    problem(env.call("POST", api, REBUILD), 403, "totp_session_required")
    assert env.state() == state
    # the same admin's TOTP session may do both
    session = env.token(uid, "session")
    assert env.call("DELETE", session, f"{POLICIES}/{pid}").status_code == 204
    r = env.call("POST", session, REBUILD)
    assert r.status_code == 202, r.text
    tid = r.json()["task_id"]
    until(lambda: env.call("GET", api, f"{TASKS}/{tid}").json()["state"] != "running")


@pytest.mark.parametrize("role", ["operator", "viewer"])
@pytest.mark.parametrize("kind", ["session", "api"])
def test_non_admins_cannot_upload_or_delete(env: CatEnv, role: str, kind: str) -> None:
    _, admin = env.admin_api()
    pid = env.uploaded(admin, policy_doc(f"m7sec-rb-{tag()}"))
    tok = env.token(env.user(role, totp=True), kind)
    state = env.state()
    r = env.upload(tok, policy_doc(f"m7sec-rb-{tag()}"))
    problem(r, 403, "forbidden")
    r = env.call("DELETE", tok, f"{POLICIES}/{pid}")
    assert r.status_code == 403, r.text
    if kind == "session":
        assert r.json()["type"] == "forbidden"
    assert env.state() == state


def test_the_sink_gate_refuses_delete_and_rebuild_after_15_minutes(env: CatEnv) -> None:
    _, api = env.admin_api()
    pid = env.uploaded(api, policy_doc(f"m7sec-sink-{tag()}"))
    _, tok = env.admin_session()
    env.sink_outage(seconds=15 * 60)
    assert env.shipper.refusing()
    state = env.state()
    problem(env.call("DELETE", tok, f"{POLICIES}/{pid}"), 503, "audit_sink_unavailable")
    problem(env.call("POST", tok, REBUILD), 503, "audit_sink_unavailable")
    assert env.state() == state
    env.sink_back()
    assert env.call("DELETE", tok, f"{POLICIES}/{pid}").status_code == 204


# --- no plugin text or token in the logs (TS §8.1, §8.4) ------------------------


def test_no_plugin_text_or_token_reaches_a_log_line(
    env: CatEnv,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    c_exec, c_desc, c_exp = (new_canary(k) for k in ("exec", "desc", "exp"))
    name = f"m7sec-log-{tag()}"
    data = (
        policy_doc(name, desc=c_desc)
        .replace(b"cat /etc/hostname", f"cat /etc/{c_exec}".encode())
        .replace(
            b"Check 1.</PluginDescription>", f"{c_desc}</PluginDescription>".encode()
        )
    )
    data = data.replace(
        b"<Operator>not_empty</Operator>\n      <ExpectedResult></ExpectedResult>",
        b"<Operator>contains</Operator>\n      <ExpectedResult>"
        + c_exp.encode()
        + b"</ExpectedResult>",
    )
    bad = policy_doc(f"m7sec-log-{tag()}").replace(
        b"cat /etc/hostname", f"rm {c_exec}".encode()
    )
    uid, api = env.admin_api()
    session = env.token(uid, "session")
    wrong = new_agent_token(AgentTokenKind.AGENT)
    with caplog.at_level(logging.DEBUG):
        ok = env.upload(api, data)
        assert ok.json()["outcome"] == "success", ok.json()
        pid = ok.json()["policy_id"]
        assert env.upload(api, bad).json()["outcome"] == "rejected"
        detail = env.call("GET", api, f"{POLICIES}/{pid}")
        assert c_exec in detail.text  # the catalog shows it (#98 (b)); logs never
        for status in ("disabled", "enabled"):
            r = env.call(
                "PATCH", api, f"{POLICIES}/{pid}", json={"policy_status": status}
            )
            assert r.status_code == 200, r.text
        rebuild(env)
        assert env.call("DELETE", session, f"{POLICIES}/{pid}").status_code == 204
        env.client.get(POLICIES, headers={"Authorization": f"Bearer {wrong}"})
    out, err = capfd.readouterr()
    secrets_ = [c_exec, c_desc, c_exp, api, session, wrong]
    assert sweep(secrets_, caplog.text, out, err) == []
    assert caplog.records, "nothing was logged, so the sweep proves nothing"


# --- every import alert is written and reaches the sink (TS §8.4, #100, #101) --


@pytest.fixture
def rec_env(server: PgServer, tmp_path: Path) -> Iterator[CatEnv]:
    yield from make_env(server, tmp_path, sink=RecordingSink())


def shipped(e: CatEnv) -> list[dict[str, Any]]:
    for _ in range(5):
        e.clock.at += timedelta(seconds=31)
        e.shipper.run_once()
    sink = e.sink
    assert isinstance(sink, RecordingSink)
    return [
        {
            "audit_id": r.audit_id,
            "action": r.action,
            "detail": json.loads(r.detail_text),
        }
        for r in sink.records
        if r.detail_text
    ]


def test_every_catalog_alert_is_written_and_reaches_the_sink(rec_env: CatEnv) -> None:
    e = rec_env
    kinds = (
        "policy_imported", "policy_import_rejected", "policy_reenabled",
        "policy_rebuilt", "policy_deleted",
    )  # fmt: skip
    counts = {k: alerts(k) for k in kinds}
    uid, api = e.admin_api()
    session = e.token(uid, "session")
    mark = e.last_audit()
    flagged = "test -f /root/.ssh/authorized_keys"
    data = policy_doc(f"m7sec-al-{tag()}").replace(
        b"cat /etc/hostname", flagged.encode()
    )
    pid = e.uploaded(api, data)
    assert (
        e.upload(api, policy_doc(f"m7sec-al-{tag()}", status="on")).json()["outcome"]
        == "rejected"
    )
    for status in ("disabled", "enabled"):
        r = e.call("PATCH", api, f"{POLICIES}/{pid}", json={"policy_status": status})
        assert r.status_code == 200, r.text
    rebuild(e)
    assert e.call("DELETE", session, f"{POLICIES}/{pid}").status_code == 204
    entries = [a for a in e.audit_after(mark) if (a["detail"] or {}).get("alert")]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for a in entries:
        by_kind.setdefault(a["detail"]["alert_kind"], []).append(a)
    for k in kinds:
        assert len(by_kind.get(k, [])) >= 1, (k, sorted(by_kind))
    assert {k: alerts(k) - counts[k] for k in kinds} == {
        k: float(len(by_kind[k])) for k in kinds
    }
    (imp,) = [a for a in by_kind["policy_imported"] if a["target"] == f"policy:{pid}"]
    assert imp["actor"] == f"user:{uid}"
    (change,) = imp["detail"]["changed_executes"]
    assert (change["execute"], change["reason"]) == (flagged, "new")
    assert change["flags"] == [".ssh"]  # #100: the flagged path is named
    assert [a["target"] for a in by_kind["policy_deleted"]] == [f"policy:{pid}"]
    assert [a["target"] for a in by_kind["policy_reenabled"]] == [f"policy:{pid}"]
    sent = shipped(e)
    sent_kinds = {
        s["detail"].get("alert_kind") for s in sent if s["detail"].get("alert")
    }
    assert set(kinds) <= sent_kinds  # each alert entry reached the sink


# --- BIT102 (stable cases only) and BIT015 (TS §8.3 L1283) ----------------------

RM = "rm x"


def test_bit102_rejects_rm_in_every_mode(env: CatEnv) -> None:
    _, api = env.admin_api()
    up = env.upload(api, policy_doc(f"m7sec-rm-{tag()}").replace(
        b"cat /etc/hostname", RM.encode()
    )).json()  # fmt: skip
    assert up["outcome"] == "rejected" and "BIT102" in codes(up["errors"])
    name = f"m7sec-rmf-{tag()}"
    folder = policy_doc(name).replace(b"cat /etc/hostname", RM.encode())
    env.put_server("rm.bit", folder)
    mark = env.last_import()
    env.restart()
    rebuild(env)
    rows = [r for r in rows_after(env, mark) if r["file_sha256"] == sha(folder)]
    assert {r["mode"] for r in rows} == {"auto", "rebuild"}
    assert all(
        r["outcome"] == "rejected" and "BIT102" in codes(r["errors"]) for r in rows
    )
    assert name not in names_in_catalog(env)


@pytest.mark.parametrize("sample", sorted(p.name for p in SAMPLES.glob("*.bit")))
def test_each_shipped_sample_uploads_with_no_reject_and_no_bit102(
    env: CatEnv, sample: str
) -> None:
    _, api = env.admin_api()
    body = env.upload(api, (SAMPLES / sample).read_bytes()).json()
    assert body["outcome"] == "success", body["errors"]
    assert "BIT102" not in codes(body["errors"])


def test_bit015_a_claimer_of_another_live_policys_plugin_is_rejected(
    env: CatEnv,
) -> None:
    _, api = env.admin_api()
    owner = env.upload(api, fixture("db/bit015-owner.bit")).json()
    assert owner["outcome"] == "success", owner
    state = env.state()
    claimer = env.upload(api, fixture("db/bit015-claimer.bit")).json()
    assert claimer["outcome"] == "rejected"
    assert "BIT015" in codes(claimer["errors"])
    sums, (rows, *rest), tree = env.state()
    assert (sums, rest, tree) == (state[0], list(state[1][1:]), state[2])
    assert rows == state[1][0] + 1
