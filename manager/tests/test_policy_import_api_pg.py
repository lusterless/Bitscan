"""TP-M7-23 (TASK-162): POST /api/v1/policies/import on PostgreSQL.

CHK-M7-262, -282, -324, -345, -358 (tests/m7/test-plan.md). Expected values
come from the spec and the approved answers, not from the code: TS §6.2 L1103
(admin uploads one `.bit`), L1084 (upload is not a sensitive action: an
admin's API token may upload; no TOTP session, no sink gate), §6.3 L1137 (one
`file` field, multipart/form-data), L1138 (`.bit` 5 MB, larger bodies 413),
§6 L1056 (user routes take only bsu_ and bsk_), §4.1 L522 (client name only
metadata, parsed in memory, stored as `uploaded/policy-<id>.bit`; a server-
folder policy is 409 `policy_managed_on_server`); REQ-170 (1)-(5), REQ-163
(1), (3), (5), REQ-174 (2); #57 (MB = MiB), #98 (d), (j), #99 (a)-(e), #101
(`policy.import`, `policy.import_refused`), #102 (d) (503 `about:blank`,
`Retry-After: 10`), plan work/plans/TASK-162.md §2-§5 (the multipart limits
and 400 cases), the TASK-155 review carry (a stale temp file is an internal
error, 503). Lead ruling 2026-10-28: the parser's decoded `filename` value is
the #99 (d) input, so a Windows path keeps only its last part and a quoted
pair is unescaped.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from bitscan_manager.app import create_app

from .bit_unit import BT, fixture
from .canary import new_canary, sweep
from .catalog_api import (
    BODY_CAP,
    BOUNDARY,
    FORM_DETAIL,
    IMPORT,
    MANAGED_DETAIL,
    MIB,
    PART_CAP,
    STARTING,
    CatEnv,
    Feed,
    alerts,
    drive,
    make_env,
    multipart,
    padded,
    part,
    policy_doc,
    sha,
    wrong_group_headers,
)
from .catalog_rows import tag
from .conftest import PgServer, own_migrated_server
from .test_users_api_pg import problem

pytestmark = pytest.mark.pg

RESULT_KEYS = [
    "import_id",
    "outcome",
    "policy_id",
    "policy_name",
    "policy_version",
    "plugins_added",
    "plugins_updated",
    "plugins_retired",
    "errors",
]  # fmt: skip  (#98 (d), in this order)
CTYPE = f"multipart/form-data; boundary={BOUNDARY.decode()}"
HOSTILE: dict[str, Any] = json.loads(
    (BT / "hostile_names.json").read_text(encoding="utf-8")
)
BS = b"\\"


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("import-api")) as s:
        yield s


@pytest.fixture
def env(server: PgServer, tmp_path: Path) -> Iterator[CatEnv]:
    yield from make_env(server, tmp_path)


def form99(raw: bytes | None) -> str:
    """#99 (d): UTF-8 with replacement; C0 and DEL to U+FFFD; 255 characters."""
    if raw is None:
        return ""
    text = raw.decode("utf-8", "replace")
    text = "".join("�" if ord(c) < 0x20 or ord(c) == 0x7F else c for c in text)
    return text[:255]


def post_raw(e: CatEnv, token: str, body: bytes, ctype: str | None = CTYPE) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    if ctype is not None:
        headers["Content-Type"] = ctype
    return e.client.post(IMPORT, content=body, headers=headers)


def ok(r: Any) -> dict[str, Any]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body: dict[str, Any] = r.json()
    assert list(body) == RESULT_KEYS
    return body


# CHK-M7-262: REQ-170 (1) success and rejected answers (#98 (d)) ---------------


@pytest.mark.parametrize("kind", ["session", "api"])
def test_an_admin_uploads_with_a_session_or_an_api_token(
    env: CatEnv, kind: str
) -> None:
    uid = env.user("admin", totp=True)
    tok = env.token(uid, kind)
    name = f"m7up-{tag()}"
    data = policy_doc(name, plugins=2)
    mark, before_alerts = env.last_audit(), alerts("policy_imported")
    body = ok(env.upload(tok, data, filename=b"client-name.bit"))
    pid = body["policy_id"]
    assert type(body["import_id"]) is int and type(pid) is int  # #98 (i)
    assert body == {
        "import_id": body["import_id"], "outcome": "success", "policy_id": pid,
        "policy_name": name, "policy_version": 1, "plugins_added": 2,
        "plugins_updated": 0, "plugins_retired": 0, "errors": [],
    }  # fmt: skip
    row = env.import_row(body["import_id"])
    assert (row["mode"], row["outcome"], row["imported_by"]) == (
        "manual",
        "success",
        uid,
    )
    assert (row["file_name"], row["file_sha256"]) == ("client-name.bit", sha(data))
    assert row["policy_version"] == 1 and row["errors"] == []
    # TS §4.1 L522: stored only as uploaded/policy-<id>.bit, byte-identical
    assert env.tree() == {f"uploaded/policy-{pid}.bit": data}
    pol = env.policy(pid)
    assert (pol["source_file"], pol["source_sha256"]) == (
        f"uploaded/policy-{pid}.bit",
        sha(data),
    )
    assert pol["deleted_at"] is None and pol["policy_name"] == name
    imported = [a for a in env.audit_after(mark) if a["action"] == "policy.import"]
    assert len(imported) == 1
    assert (imported[0]["actor"], imported[0]["target"]) == (
        f"user:{uid}",
        f"policy:{pid}",
    )
    assert imported[0]["detail"]["alert"] is True
    assert alerts("policy_imported") == before_alerts + 1


def test_the_sr_example_uploads_and_a_changed_file_bumps_the_version(
    env: CatEnv,
) -> None:
    _, tok = env.admin_api()
    sr = fixture("valid/sr-1.1-example.bit")
    first = ok(env.upload(tok, sr))
    assert first["outcome"] == "success" and first["errors"] == []
    pid, v = first["policy_id"], first["policy_version"]
    # manual is never skipped (TS §4.1 L532): the same bytes import again
    again = ok(env.upload(tok, sr))
    assert again["outcome"] == "success" and again["import_id"] > first["import_id"]
    assert (again["policy_id"], again["policy_version"]) == (pid, v)  # same hash
    assert env.import_row(again["import_id"])["outcome"] == "success"
    changed = sr.replace(b"</PolicyDescription>", b" (changed)</PolicyDescription>")
    assert changed != sr
    third = ok(env.upload(tok, changed))
    assert (third["policy_id"], third["policy_version"]) == (pid, v + 1)
    assert env.tree() == {f"uploaded/policy-{pid}.bit": changed}  # replaced


def test_a_rejected_file_answers_200_with_every_finding_and_stores_nothing(
    env: CatEnv,
) -> None:
    uid, tok = env.admin_api()
    data = fixture("content/bit003-on.bit")
    before = alerts("policy_import_rejected")
    body = ok(env.upload(tok, data, filename=b"bad.bit"))
    assert body["outcome"] == "rejected"
    assert (body["policy_id"], body["policy_name"], body["policy_version"]) == (
        None, None, None,
    )  # fmt: skip
    assert [f["code"] for f in body["errors"]] == ["BIT003"]
    assert all(
        list(f) == ["line", "element", "code", "message"] for f in body["errors"]
    )
    row = env.import_row(body["import_id"])
    assert body["errors"] == row["errors"]  # exactly as stored
    assert (row["mode"], row["outcome"], row["imported_by"]) == (
        "manual",
        "rejected",
        uid,
    )
    assert row["file_name"] == "bad.bit" and row["policy_version"] is None
    assert env.tree() == {}  # only a successful import keeps a file
    assert alerts("policy_import_rejected") == before + 1


def test_several_faults_come_back_together_in_line_order(env: CatEnv) -> None:
    _, tok = env.admin_api()
    data = policy_doc(f"m7up-{tag()}", status="on", fv='formatVersion="2.0"')
    body = ok(env.upload(tok, data))
    assert body["outcome"] == "rejected"
    assert {f["code"] for f in body["errors"]} == {"BIT003", "BIT016"}
    lines = [f["line"] for f in body["errors"]]
    assert lines == sorted(lines)


def test_warnings_are_returned_on_a_success(env: CatEnv) -> None:
    _, tok = env.admin_api()
    body = ok(env.upload(tok, fixture("valid/warnings-only.bit")))
    assert body["outcome"] == "success"
    assert sorted({f["code"] for f in body["errors"]}) == ["BIT101", "BIT103"]  # #110
    assert body["errors"] == env.import_row(body["import_id"])["errors"]


def test_a_bit102_command_is_rejected_through_the_route(env: CatEnv) -> None:
    _, tok = env.admin_api()
    body = ok(env.upload(tok, policy_doc(f"m7up-{tag()}").replace(
        b"cat /etc/hostname", b"rm -rf /tmp/x"
    )))  # fmt: skip
    assert body["outcome"] == "rejected"
    assert "BIT102" in [f["code"] for f in body["errors"]]
    assert env.tree() == {}


def test_an_empty_file_part_is_a_recorded_bit001_rejection(env: CatEnv) -> None:
    _, tok = env.admin_api()
    body = ok(env.upload(tok, b""))
    assert body["outcome"] == "rejected"
    assert [f["code"] for f in body["errors"]] == ["BIT001"]
    assert env.import_row(body["import_id"])["file_sha256"] == sha(b"")


# CHK-M7-262: REQ-163 (3) a rejected re-upload changes nothing ------------------


def test_a_rejected_reupload_leaves_the_file_and_the_catalog(env: CatEnv) -> None:
    _, tok = env.admin_api()
    name = f"m7up-{tag()}"
    good = policy_doc(name, plugins=2)
    pid = env.uploaded(tok, good)
    state = env.state()
    bad = policy_doc(name, status="on")
    body = ok(env.upload(tok, bad))
    assert body["outcome"] == "rejected"
    sums, (rows, tasks, jobs, schedules), tree = env.state()
    assert (sums, tasks, jobs, schedules) == (state[0], *state[1][1:])
    assert rows == state[1][0] + 1  # only its bit_import row
    assert tree == {f"uploaded/policy-{pid}.bit": good}  # byte-identical


# CHK-M7-262: REQ-163 (5), #99 (e) the server folder wins -----------------------


def test_a_server_folder_name_is_409_with_no_row_and_one_refused_entry(
    env: CatEnv,
) -> None:
    name = f"m7srv-{tag()}"
    server_file = policy_doc(name)
    env.put_server("srv.bit", server_file)
    env.restart()  # the start-up reconcile imports the server file
    (pid,) = env.one("SELECT policy_id FROM policy WHERE policy_name = %s", (name,))
    assert env.policy(pid)["source_file"] == "srv.bit"
    uid, tok = env.admin_api()
    state = env.state()
    mark = env.last_audit()
    counts = {k: alerts(k) for k in ("policy_imported", "policy_import_rejected")}
    r = env.upload(tok, policy_doc(name, plugins=3), filename=b"srv.bit")
    problem(r, 409, "policy_managed_on_server")
    assert r.json()["detail"] == MANAGED_DETAIL
    assert env.state() == state  # no bit_import row, no file, no catalog change
    entries = env.audit_after(mark)
    assert [e["action"] for e in entries] == ["policy.import_refused"]
    assert entries[0]["actor"] == f"user:{uid}"
    assert not (entries[0]["detail"] or {}).get("alert")
    assert {k: alerts(k) for k in counts} == counts


# CHK-M7-262: REQ-170 (2), #99 (a), (b) the caps (plant CHK-M7-324) ------------


def test_a_part_of_exactly_5_mib_is_accepted(env: CatEnv) -> None:
    _, tok = env.admin_api()
    data = padded(policy_doc(f"m7cap-{tag()}"), PART_CAP)
    body = ok(env.upload(tok, data))
    assert body["outcome"] == "success", body["errors"]
    assert env.tree() == {f"uploaded/policy-{body['policy_id']}.bit": data}


def test_a_part_one_byte_over_5_mib_is_413_with_no_row_and_nothing_on_disk(
    env: CatEnv,
) -> None:
    _, tok = env.admin_api()
    data = padded(policy_doc(f"m7cap-{tag()}"), PART_CAP + 1)
    imports, mark = env.last_import(), env.last_audit()
    r = env.upload(tok, data)
    problem(r, 413, "too_large")
    assert r.headers.get("connection") == "close"
    assert env.last_import() == imports  # #99 (b): not an import
    assert env.audit_after(mark) == []  # no alert, no audit entry
    assert env.tree() == {}


def test_a_body_of_exactly_the_cap_is_read_and_one_byte_more_is_413(
    env: CatEnv,
) -> None:
    _, tok = env.admin_api()
    data = policy_doc(f"m7cap-{tag()}")
    bare = multipart([part(data)])
    # padded after the closing boundary (an epilogue, RFC 2046 §5.1.1), so the
    # part stays small and only the body cap is tested
    exact = multipart([part(data)], epilogue=b"p" * (BODY_CAP - len(bare)))
    assert len(exact) == BODY_CAP
    body = ok(post_raw(env, tok, exact))
    assert body["outcome"] == "success"
    imports = env.last_import()
    over = multipart([part(data)], epilogue=b"p" * (BODY_CAP - len(bare) + 1))
    assert len(over) == BODY_CAP + 1
    problem(post_raw(env, tok, over), 413, "too_large")
    assert env.last_import() == imports


def test_a_6_mib_body_is_refused_unread_or_after_the_crossing_chunk(
    env: CatEnv,
) -> None:
    _, tok = env.admin_api()
    auth = [
        (b"authorization", f"Bearer {tok}".encode()),
        (b"content-type", CTYPE.encode()),
    ]
    imports = env.last_import()
    feed = Feed([b"a" * 65536] * 96)
    status, headers, _ = drive(
        env.client.app, "POST", IMPORT,
        [*auth, (b"content-length", str(6 * MIB).encode())], feed,
    )  # fmt: skip
    assert (status, feed.pulled) == (413, 0)  # refused unread
    assert headers.get("connection") == "close"
    feed = Feed([b"a" * 65536] * 96)
    status, _, _ = drive(env.client.app, "POST", IMPORT, auth, feed)  # chunked
    assert status == 413
    assert BODY_CAP < feed.pulled <= BODY_CAP + 65536
    assert env.last_import() == imports


# CHK-M7-262: the token and role check come before any body byte ----------------


@pytest.mark.parametrize(
    "caller", ["none", "bsa", "bse", "garbage_bsk", "viewer", "operator"]
)
def test_no_body_byte_is_read_before_the_token_and_role_check(
    env: CatEnv, caller: str
) -> None:
    if caller in ("viewer", "operator"):
        tok = env.token(env.user(caller, totp=True), "api")
        auth = [(b"authorization", f"Bearer {tok}".encode())]
        want = 403
    else:
        auth = [
            (k.lower().encode(), v.encode())
            for k, v in wrong_group_headers()[caller].items()
        ]
        want = 401
    for length in ([(b"content-length", str(6 * MIB).encode())], []):
        feed = Feed([b"a" * MIB] * 6)
        status, _, _ = drive(
            env.client.app, "POST", IMPORT,
            [*auth, *length, (b"content-type", CTYPE.encode())], feed,
        )  # fmt: skip
        assert status == want, (caller, length)
        assert feed.pulled == 0, (caller, length)


def test_every_other_route_keeps_the_1_mib_json_cap(env: CatEnv) -> None:
    _, tok = env.admin_api()
    pid = env.uploaded(tok, policy_doc(f"m7cap-{tag()}"))
    path = f"/api/v1/policies/{pid}"
    pad = json.dumps({"policy_status": "disabled", "x": ""}).encode()
    over = pad[:-2] + b"a" * (MIB + 1 - len(pad)) + pad[-2:]
    assert len(over) == MIB + 1
    r = env.client.patch(
        path, content=over,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )  # fmt: skip
    problem(r, 413, "too_large")
    for route in ("/api/v1/scans", "/api/v1/policies/rebuild", "/api/v1/users"):
        r = env.client.post(
            route,
            content=b"{" + b" " * (2 * MIB) + b"}",
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
            },
        )
        problem(r, 413, "too_large")
    assert env.policy(pid)["policy_status"] == "enabled"


# CHK-M7-262: REQ-170 (3) malformed multipart, fixed text, no echo -------------


def malformed(canary: bytes) -> dict[str, tuple[bytes, str | None]]:
    data = policy_doc(f"m7bad-{tag()}") + canary
    fn = canary + b".bit"
    one = part(data, filename=fn)
    b71 = b"b" * 71
    many = [b"X-H%d: v" % i for i in range(16)]
    return {
        "json": (b'{"file": "' + canary + b'"}', "application/json"),
        "text_plain": (multipart([one]), f"text/plain; boundary={BOUNDARY.decode()}"),
        "multipart_mixed": (
            multipart([one]),
            f"multipart/mixed; boundary={BOUNDARY.decode()}",
        ),
        "no_content_type": (multipart([one]), None),
        "no_boundary": (multipart([one]), "multipart/form-data"),
        "empty_boundary": (multipart([one]), 'multipart/form-data; boundary=""'),
        "boundary_71": (
            multipart([one], boundary=b71),
            f"multipart/form-data; boundary={b71.decode()}",
        ),
        "wrong_boundary": (multipart([one]), "multipart/form-data; boundary=other"),
        "no_closing_boundary": (multipart([one], close=False), CTYPE),
        "two_file_parts": (multipart([one, part(data, filename=fn)]), CTYPE),
        "extra_text_field": (
            multipart([part(canary, name=b"note", filename=None), one]),
            CTYPE,
        ),
        "file_then_extra": (
            multipart([one, part(canary, name=b"note", filename=None)]),
            CTYPE,
        ),
        "part_named_files": (
            multipart([part(data, name=b"files", filename=fn)]),
            CTYPE,
        ),
        "part_named_FILE": (multipart([part(data, name=b"FILE", filename=fn)]), CTYPE),
        "no_disposition": (multipart([part(data, disposition=b"")]), CTYPE),
        "attachment": (
            multipart([part(data, disposition=b'attachment; name="file"')]),
            CTYPE,
        ),
        "no_name": (
            multipart([part(data, disposition=b'form-data; filename="' + fn + b'"')]),
            CTYPE,
        ),
        "17_headers": (multipart([part(data, filename=fn, headers=many)]), CTYPE),
        "header_8k_plus_1": (
            multipart([part(data, filename=fn, headers=[b"X-Pad: " + b"v" * 8193])]),
            CTYPE,
        ),
        "no_parts": (b"--" + BOUNDARY + b"--\r\n", CTYPE),
        "empty_body": (b"", CTYPE),
        "garbage": (canary * 50, CTYPE),
        "cr_in_name": (multipart([part(data, filename=b"a\rb" + canary)]), CTYPE),
    }


CASES = list(malformed(b"x"))


@pytest.mark.parametrize("case", CASES)
def test_malformed_multipart_is_400_with_fixed_text_and_no_echo(
    env: CatEnv, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    _, tok = env.admin_api()
    canary = new_canary("m7mp")
    body, ctype = malformed(canary.encode())[case]
    imports, mark = env.last_import(), env.last_audit()
    with caplog.at_level(logging.DEBUG):
        r = post_raw(env, tok, body, ctype)
    problem(r, 400, "invalid_request")
    assert r.json()["detail"] == FORM_DETAIL
    assert sweep([canary], r, caplog.text) == []  # neither body nor name echoed
    assert env.last_import() == imports  # not an import
    assert [a["action"] for a in env.audit_after(mark)] == []
    assert env.tree() == {}


def test_the_accepted_edges_of_the_multipart_rules(env: CatEnv) -> None:
    _, tok = env.admin_api()
    b70 = b"B" * 70
    cases: list[tuple[bytes, str]] = []

    def add(build: Any, ctype: str = CTYPE) -> None:
        data = policy_doc(f"m7edge-{tag()}")
        cases.append((build(data), ctype))

    add(
        lambda d: multipart([part(d)], boundary=b70),
        f"multipart/form-data; boundary={b70.decode()}",
    )
    add(
        lambda d: multipart([part(d)]),
        f'Multipart/Form-Data; boundary="{BOUNDARY.decode()}"',
    )
    add(
        lambda d: multipart(
            [part(d, disposition=b'Form-Data; name="file"; filename="a"')]
        )
    )
    add(lambda d: multipart([part(d, headers=[b"X-H%d: v" % i for i in range(15)])]))
    add(lambda d: multipart([part(d, headers=[b"X-Pad: " + b"v" * 8192])]))
    add(lambda d: multipart([part(d, headers=[b"Content-Type: image/png"])]))  # ignored
    add(lambda d: multipart([part(d, headers=[])]))  # no part Content-Type
    add(lambda d: multipart([part(d)], epilogue=b"epilogue\r\n"))
    for body, ctype in cases:
        got = ok(post_raw(env, tok, body, ctype))
        assert got["outcome"] == "success", (ctype, got["errors"])


@pytest.mark.parametrize(
    "name", ["std.bit", "a\rb.bit", "a\nb.bit", 'a"b.bit', "a\x00b.bit", "../../x"]
)
def test_a_standard_client_form_upload_works(env: CatEnv, name: str) -> None:
    # httpx encodes the name itself (HTML5 form rules); whatever arrives is
    # stored only as metadata and the file is uploaded/policy-<id>.bit
    _, tok = env.admin_api()
    data = policy_doc(f"m7std-{tag()}")
    r = env.client.post(
        IMPORT,
        files={"file": (name, data, "application/octet-stream")},
        headers={"Authorization": f"Bearer {tok}"},
    )
    body = ok(r)
    assert body["outcome"] == "success"
    stored = env.import_row(body["import_id"])["file_name"]
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in stored)
    if name == "std.bit":
        assert stored == "std.bit"
    assert env.tree() == {f"uploaded/policy-{body['policy_id']}.bit": data}


# CHK-M7-262: REQ-163 (1) hostile client names (plant CHK-M7-358) --------------


def hostile_raw() -> list[tuple[str, bytes]]:
    out = [(f"name{i}", n.encode("utf-8")) for i, n in enumerate(HOSTILE["names"])]
    out += [(f"hex{i}", bytes.fromhex(h)) for i, h in enumerate(HOSTILE["hex"])]
    return [(k, raw) for k, raw in out if b"\r" not in raw]  # raw CR: 400 above


def expected_name(raw: bytes) -> str:
    # Lead ruling 2026-10-28: the parser's value of the parameter is the input;
    # a Windows path keeps its last part (RFC 7578 §4.2).
    if raw[1:3] == b":" + BS:
        raw = raw.rsplit(BS, 1)[-1]
    return form99(raw)


@pytest.mark.parametrize(
    ("key", "raw"), hostile_raw(), ids=[k for k, _ in hostile_raw()]
)
def test_a_hostile_client_name_is_metadata_only(
    env: CatEnv, key: str, raw: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    _, tok = env.admin_api()
    data = policy_doc(f"m7host-{tag()}")
    with caplog.at_level(logging.DEBUG):
        body = ok(env.upload(tok, data, filename=raw))
    assert body["outcome"] == "success", body["errors"]
    pid = body["policy_id"]
    assert env.tree() == {f"uploaded/policy-{pid}.bit": data}  # nothing else
    stored = env.import_row(body["import_id"])["file_name"]
    assert stored == expected_name(raw)
    assert len(stored) <= 255
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in stored)
    assert env.policy(pid)["source_file"] == f"uploaded/policy-{pid}.bit"
    if len(stored) > 6:  # a distinctive name never reaches a log line
        assert stored not in caplog.text


def test_a_windows_path_and_a_quoted_pair_follow_the_parser(env: CatEnv) -> None:
    _, tok = env.admin_api()
    for raw, want in (
        (b"C:" + BS + b"Windows" + BS + b"x.bit", "x.bit"),
        (b"a" + BS + b'"b.bit', 'a"b.bit'),
    ):
        body = ok(env.upload(tok, policy_doc(f"m7q-{tag()}"), filename=raw))
        assert env.import_row(body["import_id"])["file_name"] == want


def test_a_missing_name_is_stored_as_the_empty_string(env: CatEnv) -> None:
    _, tok = env.admin_api()
    body = ok(env.upload(tok, policy_doc(f"m7nn-{tag()}"), filename=None))
    assert env.import_row(body["import_id"])["file_name"] == ""


def test_a_canary_name_never_reaches_a_log_or_the_answer(
    env: CatEnv, caplog: pytest.LogCaptureFixture
) -> None:
    _, tok = env.admin_api()
    canary = new_canary("m7fn")
    with caplog.at_level(logging.DEBUG):
        good = env.upload(
            tok, policy_doc(f"m7c-{tag()}"), filename=f"../{canary}".encode()
        )
        bad = env.upload(
            tok, fixture("content/bit003-on.bit"), filename=canary.encode()
        )
    assert ok(good)["outcome"] == "success" and ok(bad)["outcome"] == "rejected"
    assert sweep([canary], good, bad, caplog.text) == []


# CHK-M7-262: REQ-170 (4), REQ-174 (2) roles and token groups (plant -345) -----


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("operator", "session"),
        ("operator", "api"),
        ("viewer", "session"),
        ("viewer", "api"),
    ],
)
def test_operator_and_viewer_get_403_and_nothing_changes(
    env: CatEnv, role: str, kind: str
) -> None:
    tok = env.token(env.user(role, totp=True), kind)
    state, mark = env.state(), env.last_audit()
    problem(env.upload(tok, policy_doc(f"m7rb-{tag()}")), 403, "forbidden")
    assert env.state() == state
    assert env.audit_after(mark) == []


def test_an_admin_without_totp_is_refused(env: CatEnv) -> None:
    uid = env.user("admin", totp=False)
    state = env.state()
    for tok in (env.token(uid, "session", verified=False), env.token(uid, "api")):
        problem(
            env.upload(tok, policy_doc(f"m7rt-{tag()}")), 403, "totp_enrolment_required"
        )
    assert env.state() == state


@pytest.mark.parametrize("token", list(wrong_group_headers()))
def test_agent_and_bad_tokens_get_401(env: CatEnv, token: str) -> None:
    state = env.state()
    r = env.client.post(
        IMPORT,
        content=multipart([part(policy_doc(f"m7wg-{tag()}"))]),
        headers={**wrong_group_headers()[token], "Content-Type": CTYPE},
    )
    problem(r, 401, "unauthorized")
    assert env.state() == state


def test_upload_is_not_sensitive_it_works_during_a_sink_outage(env: CatEnv) -> None:
    _, tok = env.admin_api()  # an API token: TS §6.2 L1084
    env.sink_outage(seconds=16 * 60)
    assert env.shipper.refusing()
    assert ok(env.upload(tok, policy_doc(f"m7so-{tag()}")))["outcome"] == "success"


# CHK-M7-262: 503 answers (#102 (d), #98 (j), the TASK-155 carry) --------------


def test_before_the_catalog_start_up_ends_the_upload_is_503_retry_after_10(
    env: CatEnv,
) -> None:
    starting = env.new_service(start=False)
    client = env.app_with(starting)
    _, tok = env.admin_api()
    imports = env.last_import()
    r = client.post(
        IMPORT, content=multipart([part(policy_doc(f"m7st-{tag()}"))]),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": CTYPE},
    )  # fmt: skip
    problem(r, 503, "about:blank")
    assert r.headers["retry-after"] == "10"
    assert r.json()["detail"] == STARTING
    assert env.last_import() == imports and env.tree() == {}
    r = client.post(IMPORT, content=b"x", headers={"Content-Type": CTYPE})
    problem(r, 401, "unauthorized")  # the token check still comes first


def test_without_a_catalog_service_the_upload_is_503(env: CatEnv) -> None:
    _, tok = env.admin_api()
    r = env.app_with(None).post(
        IMPORT, content=multipart([part(policy_doc(f"m7nc-{tag()}"))]),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": CTYPE},
    )  # fmt: skip
    problem(r, 503, "about:blank")


def test_a_stale_temp_file_is_503_with_no_row_and_the_planted_file_kept(
    env: CatEnv,
) -> None:
    _, tok = env.admin_api()
    name = f"m7tmp-{tag()}"
    v1 = policy_doc(name)
    pid = env.uploaded(tok, v1)
    v2 = policy_doc(name, plugins=2)
    stale = env.bits / "uploaded" / f".tmp-{pid}-{sha(v2)}"
    stale.write_bytes(b"stale bytes")
    imports, pol = env.last_import(), env.policy(pid)
    r = env.upload(tok, v2)
    problem(r, 503, "about:blank")
    assert r.json()["detail"] == "The policy file could not be stored; retry shortly."
    assert env.last_import() == imports  # #98 (j): an internal error is no import
    assert stale.read_bytes() == b"stale bytes"
    assert (env.bits / "uploaded" / f"policy-{pid}.bit").read_bytes() == v1
    assert env.policy(pid) == pol  # rolled back


# CHK-M7-262: nothing is spooled to disk while parsing (D5, TS §4.1 L522) -------


def test_the_upload_is_parsed_in_memory(
    env: CatEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    import python_multipart.multipart as pm
    import starlette.formparsers as sf
    import starlette.requests as sr

    def refuse(*a: Any, **k: Any) -> Any:
        raise AssertionError("spooled or form-parsed")

    for mod, attr in [
        (tempfile, "SpooledTemporaryFile"), (tempfile, "TemporaryFile"),
        (tempfile, "NamedTemporaryFile"), (tempfile, "mkstemp"), (tempfile, "mkdtemp"),
        (sf, "SpooledTemporaryFile"), (pm, "FormParser"), (pm, "File"),
        (sr.Request, "form"),
    ]:  # fmt: skip
        monkeypatch.setattr(mod, attr, refuse)
    _, tok = env.admin_api()
    data = padded(policy_doc(f"m7mem-{tag()}"), 2 * MIB)  # over any 1 MiB spool
    assert ok(env.upload(tok, data))["outcome"] == "success"


# REQ-170 (5) the OpenAPI description (G6 itself runs in test_openapi.py) -------


def test_the_operation_documents_the_multipart_body_and_its_answers() -> None:
    doc = create_app().openapi()
    op = doc["paths"][IMPORT]["post"]
    body = op["requestBody"]
    assert body["required"] is True
    assert list(body["content"]) == ["multipart/form-data"]
    schema = body["content"]["multipart/form-data"]["schema"]
    assert schema["properties"] == {"file": {"type": "string", "format": "binary"}}
    assert schema["required"] == ["file"] and schema["additionalProperties"] is False
    assert {"200", "400", "401", "403", "409", "413", "503"} <= set(op["responses"])
    for status in ("400", "401", "403", "409", "413", "503"):
        assert list(op["responses"][status]["content"]) == ["application/problem+json"]
    ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    result = doc["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert list(result["properties"]) == RESULT_KEYS
    assert result["additionalProperties"] is False
    assert result["properties"]["outcome"]["enum"] == ["success", "rejected"]
    assert "parameters" not in op  # nothing but the multipart body
