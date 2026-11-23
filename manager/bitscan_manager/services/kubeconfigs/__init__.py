"""Uploaded kubeconfigs for ClusterMAX scans (TS §3.8, §5.2, §6.2, §8.1;
owner decision 2026-11-23).

An admin with a TOTP session uploads, replaces and deletes them. A kubeconfig
is accepted only with its credentials inline: one context, one cluster with an
https server, one user with a token or a client certificate and key as data.
Anything that names a file, runs a program or turns TLS checks off is refused,
so the scanner never needs the disk. The content is encrypted with the vault
before it reaches the database and is never returned, logged or audit-logged;
the audit log records names, the cluster and the SHA-256 only. Every upload,
replacement and deletion alerts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

import yaml

MAX_BYTES: Final = 1024 * 1024
ALERT_KIND: Final = "kubeconfig_changed"

_TOP: Final = frozenset(
    {
        "apiVersion",
        "kind",
        "clusters",
        "contexts",
        "users",
        "current-context",
        "preferences",
    }
)
_CLUSTER: Final = frozenset({"server", "certificate-authority-data", "tls-server-name"})
_CONTEXT: Final = frozenset({"cluster", "user", "namespace"})
_USER: Final = frozenset({"token", "client-certificate-data", "client-key-data"})


class KubeconfigInvalid(Exception):
    """The upload is refused (422); the message names the rule, never content."""


class NotFound(Exception):
    pass


class NameTaken(Exception):
    pass


@dataclass(frozen=True)
class Checked:
    cluster_name: str
    server: str
    sha256: str


def _named(
    items: Any, kind: str, inner: str, allowed: frozenset[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise KubeconfigInvalid(f"{kind} must be a non-empty list")
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"name", inner}:
            raise KubeconfigInvalid(
                f"each entry of {kind} needs exactly name and {inner}"
            )
        name, body = item["name"], item[inner]
        if not isinstance(name, str) or not name or name in out:
            raise KubeconfigInvalid(f"{kind} names must be unique strings")
        if not isinstance(body, dict):
            raise KubeconfigInvalid(f"{kind}.{inner} must be a mapping")
        extra = set(body) - allowed
        if extra:
            raise KubeconfigInvalid(
                f"{kind}.{inner} has a field that is not allowed: {sorted(extra)[0]}"
            )
        if not all(isinstance(v, str) and v for v in body.values()):
            raise KubeconfigInvalid(f"{kind}.{inner} values must be non-empty strings")
        out[name] = body
    return out


def check(content: str) -> Checked:
    """Parse and check one kubeconfig (TS §6.2). Anchors, aliases and tags
    are refused before loading, so a crafted file cannot expand in memory."""
    raw = content.encode("utf-8")
    if not raw.strip():
        raise KubeconfigInvalid("the kubeconfig is empty")
    if len(raw) > MAX_BYTES:
        raise KubeconfigInvalid("the kubeconfig is larger than 1 MiB")
    try:
        for token in yaml.scan(content, Loader=yaml.SafeLoader):
            if isinstance(token, (yaml.AnchorToken, yaml.AliasToken, yaml.TagToken)):
                raise KubeconfigInvalid(
                    "YAML anchors, aliases and tags are not allowed"
                )
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        raise KubeconfigInvalid("the kubeconfig is not valid YAML") from None
    if not isinstance(doc, dict):
        raise KubeconfigInvalid("the kubeconfig must be a mapping")
    extra = set(doc) - _TOP
    if extra:
        raise KubeconfigInvalid(f"a top-level field is not allowed: {sorted(extra)[0]}")
    if doc.get("kind", "Config") != "Config" or doc.get("apiVersion", "v1") != "v1":
        raise KubeconfigInvalid("kind must be Config and apiVersion v1")
    clusters = _named(doc.get("clusters"), "clusters", "cluster", _CLUSTER)
    contexts = _named(doc.get("contexts"), "contexts", "context", _CONTEXT)
    users = _named(doc.get("users"), "users", "user", _USER)
    if len(contexts) != 1:
        raise KubeconfigInvalid("the kubeconfig must have exactly one context")
    ((context_name, context),) = contexts.items()
    current = doc.get("current-context", context_name)
    if current != context_name:
        raise KubeconfigInvalid("current-context must name the one context")
    cluster = clusters.get(context.get("cluster", ""))
    user = users.get(context.get("user", ""))
    if cluster is None or user is None:
        raise KubeconfigInvalid("the context must name a listed cluster and user")
    server = cluster.get("server", "")
    parts = urlsplit(server)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or "@" in parts.netloc
        or len(server) > 2048
    ):
        raise KubeconfigInvalid(
            "the cluster server must be an https:// URL without credentials"
        )
    has_token = "token" in user
    has_cert = "client-certificate-data" in user or "client-key-data" in user
    if has_token == has_cert or (has_cert and len(user) != 2):
        raise KubeconfigInvalid(
            "the user needs either a token or both client-certificate-data"
            " and client-key-data"
        )
    cluster_name = context["cluster"]
    if len(cluster_name) > 253:
        raise KubeconfigInvalid("the cluster name is longer than 253 characters")
    return Checked(cluster_name, server, hashlib.sha256(raw).hexdigest())


class Cipher(Protocol):  # runtime.TotpCipher (the vault's Transit key)
    def encrypt(self, seed: bytes) -> str: ...


class Store(Protocol):  # repositories.kubeconfigs.KubeconfigRepo
    def insert(
        self,
        *,
        name: str,
        description: str,
        cluster_name: str,
        server: str,
        content_enc: str,
        created_by: int,
        now: datetime,
    ) -> int | None: ...
    def replace(
        self,
        kubeconfig_id: int,
        *,
        description: str | None,
        cluster_name: str,
        server: str,
        content_enc: str,
        now: datetime,
    ) -> str | None: ...
    def soft_delete(self, kubeconfig_id: int, now: datetime) -> str | None: ...


class AuditSink(Protocol):  # services.users.TxAudit
    def alert(
        self,
        kind: str,
        actor: str,
        action: str,
        target: str,
        detail: Mapping[str, object],
    ) -> None: ...


def create(
    store: Store,
    audit: AuditSink,
    *,
    name: str,
    description: str,
    checked: Checked,
    content_enc: str,
    admin_id: int,
    now: datetime,
) -> int:
    kubeconfig_id = store.insert(
        name=name,
        description=description,
        cluster_name=checked.cluster_name,
        server=checked.server,
        content_enc=content_enc,
        created_by=admin_id,
        now=now,
    )
    if kubeconfig_id is None:
        raise NameTaken
    audit.alert(
        ALERT_KIND,
        f"user:{admin_id}",
        "kubeconfig.create",
        f"kubeconfig:{kubeconfig_id}",
        {
            "name": name,
            "cluster_name": checked.cluster_name,
            "server": checked.server,
            "sha256": checked.sha256,
        },
    )
    return kubeconfig_id


def replace(
    store: Store,
    audit: AuditSink,
    kubeconfig_id: int,
    *,
    description: str | None,
    checked: Checked,
    content_enc: str,
    admin_id: int,
    now: datetime,
) -> None:
    name = store.replace(
        kubeconfig_id,
        description=description,
        cluster_name=checked.cluster_name,
        server=checked.server,
        content_enc=content_enc,
        now=now,
    )
    if name is None:
        raise NotFound
    audit.alert(
        ALERT_KIND,
        f"user:{admin_id}",
        "kubeconfig.replace",
        f"kubeconfig:{kubeconfig_id}",
        {
            "name": name,
            "cluster_name": checked.cluster_name,
            "server": checked.server,
            "sha256": checked.sha256,
        },
    )


def delete(
    store: Store, audit: AuditSink, kubeconfig_id: int, *, admin_id: int, now: datetime
) -> None:
    name = store.soft_delete(kubeconfig_id, now)
    if name is None:
        raise NotFound
    audit.alert(
        ALERT_KIND,
        f"user:{admin_id}",
        "kubeconfig.delete",
        f"kubeconfig:{kubeconfig_id}",
        {"name": name},
    )
