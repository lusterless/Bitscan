"""TP-M7-20 (TASK-160): the real `bitscan-manager serve` with the catalog, on
Linux.

CHK-M7-243 (tests/m7/test-plan.md): `serve` with a temporary bits folder
imports a folder file at start-up, and `/healthz` stays 200 with the database
down (#102 (d): the start-up runs on a background thread and retries; REQ-056:
`/healthz` never waits for the database). TS §4.1 L528.
"""

from __future__ import annotations

import secrets
import signal
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from .catalog_rows import app, tag
from .certs import Pki, make_pki
from .conftest import PgServer, own_migrated_server
from .fake_sink import https_sink, server_context
from .test_import_pipeline_pg import doc, plug
from .test_serve_linux import Serve, env_for, free_port, https_get, start, wait_ready

if not hasattr(signal, "SIGHUP"):
    pytest.skip("not run: Linux only", allow_module_level=True)

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("serve-catalog")) as s:
        yield s


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> Pki:
    return make_pki(tmp_path_factory.mktemp("serve-catalog-pki"))


@pytest.fixture
def sink(pki: Pki) -> Iterator[Any]:
    leaf = pki.leaf("sink-catalog")
    with https_sink(server_context(leaf.cert, leaf.key)) as s:
        yield s


def bits_folder(tmp: Path) -> Path:
    bits = tmp / "bits"
    (bits / "uploaded").mkdir(parents=True)
    return bits


def launch(
    server: PgServer,
    tmp: Path,
    pki: Pki,
    sink: Any,
    bits: Path,
    app_dsn: str | None = None,
) -> Serve:
    leaf = pki.leaf(f"serve-cat-{secrets.token_hex(4)}")
    port = free_port()
    env = env_for(server, tmp, pki, leaf, f"https://localhost:{sink.port}/a", port)
    env["BITSCAN_BITS_DIR"] = str(bits)
    if app_dsn is not None:  # env_for wrote the real one; replace it
        (tmp / "creds" / "app_dsn").write_text(app_dsn)
    return start(env, tmp, port, pki, leaf)


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port: int = s.getsockname()[1]
    s.close()
    return port


def rows_for(server: PgServer, name: str) -> list[tuple[str, str]]:
    with app(server) as c:
        return [
            (r[0], r[1])
            for r in c.execute(
                "SELECT file_name, outcome FROM bit_import WHERE file_name = %s",
                (name,),
            ).fetchall()
        ]


def test_serve_imports_a_folder_file_at_start_up(
    server: PgServer, tmp_path: Path, pki: Pki, sink: Any
) -> None:
    bits = bits_folder(tmp_path)
    name = f"serve-{tag()}.bit"
    (bits / name).write_bytes(doc(f"Serve {tag()}", [plug()]))
    s = launch(server, tmp_path, pki, sink, bits)
    try:
        wait_ready(s)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not rows_for(server, name):
            time.sleep(0.2)
        assert rows_for(server, name) == [(name, "success")]
        assert "catalog ready" in s.output()
        assert s.stop() == 0  # SIGTERM: the catalog stops, then the rest
    finally:
        if s.proc.poll() is None:
            s.proc.kill()


def test_healthz_stays_200_with_the_database_down(
    server: PgServer, tmp_path: Path, pki: Pki, sink: Any
) -> None:
    bits = bits_folder(tmp_path)
    (bits / "x.bit").write_bytes(doc(f"Down {tag()}", [plug()]))
    dsn = conninfo_to_dict(server.dsn("bitscan_app"))
    dsn["port"] = str(closed_port())  # nothing listens there: the database is down
    s = launch(server, tmp_path, pki, sink, bits, app_dsn=make_conninfo(**dsn))  # type: ignore[arg-type]
    try:
        wait_ready(s)
        for _ in range(10):
            assert https_get(s.port, s.ca)[0] == 200
            time.sleep(0.3)
        assert "catalog ready" not in s.output()
        t0 = time.monotonic()
        assert s.stop() == 0
        assert time.monotonic() - t0 < 15  # the start-up's wait is stoppable
    finally:
        if s.proc.poll() is None:
            s.proc.kill()
    assert rows_for(server, "x.bit") == []
