"""/api/v1/kubeconfigs on PostgreSQL (TS §3.8, §5.2, §6.2, §8.1; owner
decision 2026-11-23).

Expected values come from the spec: listing is admin; upload, replace and
delete need an admin TOTP session and refuse API tokens; the content is
encrypted with the vault and never returned or audit-logged; only inline
credentials are accepted; every change alerts (kubeconfig_changed).
"""

import secrets
from typing import Any

import pytest
import yaml

from . import test_users_api_pg as users_api
from .test_users_api_pg import Env

pytestmark = pytest.mark.pg

env = users_api.env

ROUTE = "/api/v1/kubeconfigs"
CANARY = "CANARY-kubeconfig-7f3a9e1d"
ITEM_KEYS = {
    "kubeconfig_id",
    "name",
    "description",
    "cluster_name",
    "server",
    "created_by",
    "created_at",
    "replaced_at",
    "deleted_at",
}


def config(**user: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {
                "name": "gpu-a",
                "cluster": {
                    "server": "https://10.0.0.1:6443",
                    "certificate-authority-data": "Q0E=",
                },
            }
        ],
        "contexts": [
            {"name": "admin@gpu-a", "context": {"cluster": "gpu-a", "user": "admin"}}
        ],
        "users": [{"name": "admin", "user": user or {"token": CANARY}}],
        "current-context": "admin@gpu-a",
    }


def text(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc)


def upload(
    e: Env, tok: str, name: str | None = None, content: str | None = None
) -> Any:
    name = name or f"k-{secrets.token_hex(4)}"
    body = {"name": name, "description": "lab", "content": content or text(config())}
    return e.call("POST", tok, ROUTE, json=body)


def stored(e: Env, kid: int) -> dict[str, Any]:
    with e.conn() as c:
        cur = c.execute("SELECT * FROM kubeconfig WHERE kubeconfig_id = %s", (kid,))
        cols = [d.name for d in cur.description or []]
        row = cur.fetchone()
    assert row is not None
    return dict(zip(cols, row, strict=True))


def audit_text(e: Env) -> str:
    with e.conn() as c:
        rows = c.execute(
            "SELECT action, target, detail::text FROM audit_log"
        ).fetchall()
    return repr(rows)


def test_upload_encrypts_and_never_returns_the_content(env: Env) -> None:
    uid, tok = env.admin()
    r = upload(env, tok)
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == ITEM_KEYS
    assert (body["cluster_name"], body["server"]) == (
        "gpu-a",
        "https://10.0.0.1:6443",
    )
    assert body["created_by"] == uid and body["deleted_at"] is None
    row = stored(env, body["kubeconfig_id"])
    assert row["content_enc"].startswith("enc:")
    assert CANARY not in row["content_enc"]
    for path in (ROUTE, f"{ROUTE}/{body['kubeconfig_id']}"):
        got = env.call("GET", tok, path)
        assert got.status_code == 200 and CANARY not in got.text
    assert CANARY not in audit_text(env)
    assert "kubeconfig.create" in audit_text(env)


def test_name_is_unique(env: Env) -> None:
    _, tok = env.admin()
    assert upload(env, tok, name="same-name").status_code == 201
    assert upload(env, tok, name="same-name").status_code == 409


@pytest.mark.parametrize(
    ("name", "doc"),
    [
        ("exec", {"exec": "x"}),
        ("auth-provider", {"auth-provider": "x"}),
        ("tokenFile", {"tokenFile": "/var/run/secrets/token"}),
        ("client-certificate path", {"client-certificate": "/c", "client-key": "/k"}),
        ("cert without key", {"client-certificate-data": "Yw=="}),
        (
            "token and cert",
            {
                "token": "t",
                "client-certificate-data": "Yw==",
                "client-key-data": "aw==",
            },
        ),
    ],
)
def test_user_must_have_inline_credentials(
    env: Env, name: str, doc: dict[str, str]
) -> None:
    _, tok = env.admin()
    label = f"refused-{secrets.token_hex(4)}"
    r = upload(env, tok, name=label, content=text(config(**doc)))
    assert r.status_code == 422, (name, r.text)
    with env.conn() as c:
        row = c.execute(
            "SELECT count(*) FROM kubeconfig WHERE name = %s", (label,)
        ).fetchone()
    assert row is not None and row[0] == 0


def _mutate(path: str, value: Any) -> str:
    doc = config()
    target: Any = doc
    keys = path.split(".")
    for k in keys[:-1]:
        target = target[int(k)] if k.isdigit() else target[k]
    target[keys[-1]] = value
    return text(doc)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("clusters.0.cluster.certificate-authority", "/etc/ca.crt"),
        ("clusters.0.cluster.insecure-skip-tls-verify", True),
        ("clusters.0.cluster.server", "http://10.0.0.1:6443"),
        ("clusters.0.cluster.server", "https://u:p@10.0.0.1:6443"),
        ("clusters.0.cluster.proxy-url", "http://proxy"),
        ("current-context", "other"),
        ("preferences2", {}),
    ],
)
def test_cluster_and_document_rules(env: Env, path: str, value: Any) -> None:
    _, tok = env.admin()
    assert upload(env, tok, content=_mutate(path, value)).status_code == 422


def test_two_contexts_and_yaml_tricks_are_refused(env: Env) -> None:
    _, tok = env.admin()
    doc = config()
    doc["contexts"].append(
        {"name": "b", "context": {"cluster": "gpu-a", "user": "admin"}}
    )
    assert upload(env, tok, content=text(doc)).status_code == 422
    aliases = "a: &x [1]\nb: *x\n"
    assert upload(env, tok, content=aliases).status_code == 422
    assert upload(env, tok, content="!!python/object:os.system x").status_code == 422
    assert upload(env, tok, content="[not, a, mapping]").status_code == 422


def test_client_certificate_data_is_accepted(env: Env) -> None:
    _, tok = env.admin()
    content = text(
        config(**{"client-certificate-data": "Yw==", "client-key-data": "aw=="})
    )
    assert upload(env, tok, content=content).status_code == 201


def test_writes_need_an_admin_totp_session(env: Env) -> None:
    admin = env.user("admin", totp=True)
    api = env.token(admin, kind="api")
    unverified = env.token(admin, verified=False)
    operator = env.token(env.user("operator"))
    for tok in (api, unverified, operator):
        assert upload(env, tok).status_code in (401, 403), tok[:4]
    assert env.call("GET", operator, ROUTE).status_code == 403
    assert env.call("GET", api, ROUTE).status_code == 200  # listing is admin


def test_replace_and_delete(env: Env) -> None:
    _, tok = env.admin()
    kid = upload(env, tok).json()["kubeconfig_id"]
    before = stored(env, kid)["content_enc"]
    doc = config()
    doc["clusters"][0]["cluster"]["server"] = "https://10.0.0.2:6443"
    r = env.call("PUT", tok, f"{ROUTE}/{kid}", json={"content": text(doc)})
    assert r.status_code == 200, r.text
    assert r.json()["server"] == "https://10.0.0.2:6443" and r.json()["replaced_at"]
    assert stored(env, kid)["content_enc"] != before
    assert env.call("DELETE", tok, f"{ROUTE}/{kid}").status_code == 204
    row = stored(env, kid)
    assert row["content_enc"] == "" and row["deleted_at"] is not None
    assert env.call("DELETE", tok, f"{ROUTE}/{kid}").status_code == 404
    assert (
        env.call(
            "PUT", tok, f"{ROUTE}/{kid}", json={"content": text(config())}
        ).status_code
        == 404
    )
    listed = env.call("GET", tok, ROUTE, params={"limit": 200}).json()["items"]
    gone = [k for k in listed if k["kubeconfig_id"] == kid]
    assert len(gone) == 1 and gone[0]["deleted_at"] is not None
    actions = audit_text(env)
    for action in ("kubeconfig.create", "kubeconfig.replace", "kubeconfig.delete"):
        assert action in actions
    assert CANARY not in actions
