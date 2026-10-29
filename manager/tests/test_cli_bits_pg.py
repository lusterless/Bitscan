"""TP-M7-26 (TASK-166): `bitscan-manager bits rebuild` on PostgreSQL.

CHK-M7-290 (tests/m7/test-plan.md). Expected values come from the spec and
the approved answers, not from the code: TS §8.7 L1347 (run as root; the DSN
from /etc/bitscan/secrets/app.dsn), §4.2 L540; REQ-175 (1)–(6); #107 (a) the
folder (BITSCAN_BITS_DIR from the environment, else /etc/bitscan/manager.env,
else /var/lib/bitscan/bits; exit 2 if it or its uploaded/ is missing), (b) one
line per file then `deleted policy` lines and a summary, (c) exit 0 when the
rebuild committed (rejected files included), 1 when it failed, 2 for a
configuration error, (d) `requested_by` NULL, actor `cli:root`, (e) no upload
finish or integrity check, (f) no prompt; the TASK-046 rule (no DSN content in
any output); TASK-157 r2 (a task no longer running: nothing runs, exit 1).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import re2  # type: ignore[import-untyped]
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from bitscan_manager.repositories import catalog_admin as adm
from bitscan_manager.repositories import imports as imports_repo

from .canary import new_canary
from .catalog_rows import T2, app, tag
from .conftest import PgServer, own_migrated_server, run_cli
from .test_import_pipeline_pg import doc, plug

pytestmark = pytest.mark.pg

CANARY = new_canary("bitsdsn")
SUMMARY = re2.compile(
    r"^rebuild succeeded: (\d+) files, (\d+) rejected, (\d+) policies deleted,"
    r" (\d+) plugins retired \(task ([0-9a-f-]{36})\)$"
)


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgServer]:
    with own_migrated_server(tmp_path_factory.mktemp("cli-bits")) as s:
        yield s


@pytest.fixture(autouse=True)
def clean(server: PgServer) -> None:
    # Each test owns its folders: earlier live policies would be "gone".
    with app(server) as c, c.transaction():
        live = c.execute("SELECT policy_id FROM policy WHERE deleted_at IS NULL")
        for (pid,) in live.fetchall():
            adm.soft_delete_effects(c, pid, T2)


@pytest.fixture
def bits(tmp_path: Path) -> Path:
    b = tmp_path / "bits"
    (b / "uploaded").mkdir(parents=True)
    return b


@pytest.fixture
def dsn(server: PgServer, tmp_path: Path) -> Path:
    p = tmp_path / "app.dsn"
    p.write_text(server.dsn("bitscan_app") + "\n", encoding="utf-8")
    return p


def run(
    dsn_file: Path,
    *argv: str,
    env: dict[str, str] | None = None,
    env_file: Path | None = None,
    pre: str = "",
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    code = (
        "import sys, pathlib\n"
        f"{pre}"
        "from bitscan_manager.cli.bits import bits_main\n"
        f"ef = {str(env_file)!r}\n"
        "env_path = pathlib.Path(ef if ef != 'None' else '/nonexistent/m.env')\n"
        "sys.exit(bits_main(sys.argv[1:],"
        f" dsn_file=pathlib.Path({str(dsn_file)!r}), env_file=env_path))\n"
    )
    base = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    base.update(env or {})
    return subprocess.run(  # noqa: S603 - fixed argv, no untrusted input
        [sys.executable, "-c", code, *argv],
        capture_output=True,
        text=True,
        env=base,
        timeout=timeout,
    )


def task_row(server: PgServer, tid: str) -> imports_repo.TaskRow | None:
    from uuid import UUID

    with app(server) as c:
        return imports_repo.get_task(c, UUID(tid))


def tasks_count(server: PgServer) -> int:
    with app(server) as c:
        row = c.execute("SELECT count(*) FROM task").fetchone()
    assert row is not None
    return int(row[0])


def entries_after(server: PgServer, mark: int) -> list[tuple[str, str, Any]]:
    with app(server) as c:
        return [
            (a, b, d)
            for a, b, d in c.execute(
                "SELECT actor, action, detail FROM audit_log WHERE audit_id > %s"
                " ORDER BY audit_id",
                (mark,),
            ).fetchall()
        ]


def mark(server: PgServer) -> int:
    with app(server) as c:
        row = c.execute("SELECT coalesce(max(audit_id), 0) FROM audit_log").fetchone()
    assert row is not None
    return int(row[0])


def no_secret(p: subprocess.CompletedProcess[str], *secrets: str) -> None:
    for s in secrets:
        assert s not in p.stdout and s not in p.stderr


# REQ-175 (1), (2) -----------------------------------------------------------------


def test_a_rebuild_prints_a_line_per_file_and_exits_0(
    server: PgServer, bits: Path, dsn: Path
) -> None:
    t = tag()
    (bits / "a.bit").write_bytes(doc(f"CA {t}", [plug()]))
    (bits / "uploaded" / "foreign.bit").write_bytes(doc(f"CF {t}", [plug()]))
    m0 = mark(server)
    p = run(dsn, "rebuild", env={"BITSCAN_BITS_DIR": str(bits)})
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert re2.fullmatch(r"success a\.bit policy \d+ version 1", lines[0]), lines
    assert re2.fullmatch(
        r"success uploaded/foreign\.bit policy \d+ version 1", lines[1]
    )
    m = SUMMARY.match(lines[-1])
    assert m is not None and m.groups()[:4] == ("2", "0", "0", "0")
    assert len(lines) == 3
    tr = task_row(server, m.group(5))
    assert tr is not None and (tr.state, tr.requested_by) == ("succeeded", None)
    entries = entries_after(server, m0)
    reb = [e for e in entries if e[1] == "bits.rebuild"]
    assert [(e[0], e[2]["alert_kind"]) for e in reb] == [("cli:root", "policy_rebuilt")]
    assert sum(1 for e in entries if e[1] == "policy.import") == 2
    assert {e[0] for e in entries} == {"cli:root"}
    pw = conninfo_to_dict(dsn.read_text().strip()).get("password") or "x" * 40
    no_secret(p, str(pw))
    assert not (bits / "uploaded" / "foreign.bit").exists()  # relocated


def test_a_rejected_file_is_named_and_still_exits_0(
    server: PgServer, bits: Path, dsn: Path
) -> None:
    t = tag()
    (bits / "ok.bit").write_bytes(doc(f"OK {t}", [plug()]))
    (bits / "bad.bit").write_bytes(doc(f"BAD {t}", [plug("rm x")]))
    p = run(dsn, "rebuild", env={"BITSCAN_BITS_DIR": str(bits)})
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert "rejected bad.bit (1 findings)" in lines
    m = SUMMARY.match(lines[-1])
    assert m is not None and m.groups()[:2] == ("2", "1")


def test_deleted_policies_and_leftovers_are_listed(
    server: PgServer, bits: Path, dsn: Path
) -> None:
    t = tag()
    gone = bits / "gone.bit"
    gone.write_bytes(doc(f"GONE {t}", [plug()]))
    assert run(dsn, "rebuild", env={"BITSCAN_BITS_DIR": str(bits)}).returncode == 0
    gone.unlink()
    p = run(dsn, "rebuild", env={"BITSCAN_BITS_DIR": str(bits)})
    assert p.returncode == 0, p.stderr
    dels = [x for x in p.stdout.splitlines() if x.startswith("deleted policy ")]
    assert len(dels) == 1
    m = SUMMARY.match(p.stdout.splitlines()[-1])
    assert m is not None and m.group(3) == "1"


# REQ-175 (3): configuration errors exit 2 before any database work -----------------


def test_configuration_errors_exit_2_with_no_secret(
    server: PgServer, bits: Path, tmp_path: Path
) -> None:
    good = conninfo_to_dict(server.dsn("bitscan_app"))
    plain = dict(good, password=CANARY, sslmode="disable")
    nossl = {k: v for k, v in dict(good, password=CANARY).items() if k != "sslmode"}
    cases: dict[str, tuple[Path, dict[str, str]]] = {}
    for name, info in (("plain", plain), ("nossl", nossl)):
        f = tmp_path / f"{name}.dsn"
        f.write_text(make_conninfo(**info))  # type: ignore[arg-type]
        cases[name] = (f, {"BITSCAN_BITS_DIR": str(bits)})
    ok_dsn = tmp_path / "ok.dsn"
    ok_dsn.write_text(server.dsn("bitscan_app"))
    no_up = tmp_path / "no-uploaded"
    no_up.mkdir()
    cases["missing dsn"] = (tmp_path / "absent.dsn", {"BITSCAN_BITS_DIR": str(bits)})
    cases["missing folder"] = (ok_dsn, {"BITSCAN_BITS_DIR": str(tmp_path / "nope")})
    cases["missing uploaded"] = (ok_dsn, {"BITSCAN_BITS_DIR": str(no_up)})
    n0 = tasks_count(server)
    for name, (f, env) in cases.items():
        p = run(f, "rebuild", env=env)
        assert p.returncode == 2, (name, p.stdout, p.stderr)
        assert p.stdout == "", name
        assert p.stderr.startswith("bits rebuild: "), (name, p.stderr)
        no_secret(p, CANARY)
    assert tasks_count(server) == n0  # nothing reached the database


# REQ-175 (4): it waits for the lock ------------------------------------------------


def test_it_waits_for_the_catalog_lock_then_runs(
    server: PgServer, bits: Path, dsn: Path
) -> None:
    (bits / "w.bit").write_bytes(doc(f"W {tag()}", [plug()]))
    code = run.__code__  # noqa: F841 - documentation only
    base = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    base["BITSCAN_BITS_DIR"] = str(bits)
    launcher = (
        "import sys, pathlib\nfrom bitscan_manager.cli.bits import bits_main\n"
        f"sys.exit(bits_main(['rebuild'], dsn_file=pathlib.Path({str(dsn)!r}),"
        " env_file=pathlib.Path('/nonexistent/m.env')))\n"
    )
    with app(server) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        proc = subprocess.Popen(  # noqa: S603 - fixed argv
            [sys.executable, "-c", launcher], env=base, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip
        time.sleep(3)
        assert proc.poll() is None  # waiting
        with app(server) as c:
            waiting = c.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                " AND NOT granted"
            ).fetchone()
        assert waiting is not None and waiting[0] >= 1
        holder.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert SUMMARY.match(out.splitlines()[-1])


# TASK-157 r2 through the CLI: the task failed before the lock -----------------------


def test_a_task_failed_while_waiting_exits_1_and_changes_nothing(
    server: PgServer, bits: Path, dsn: Path
) -> None:
    (bits / "n.bit").write_bytes(doc(f"NR {tag()}", [plug()]))
    base = {k: v for k, v in os.environ.items() if not k.startswith("BITSCAN_")}
    base["BITSCAN_BITS_DIR"] = str(bits)
    launcher = (
        "import sys, pathlib\nfrom bitscan_manager.cli.bits import bits_main\n"
        f"sys.exit(bits_main(['rebuild'], dsn_file=pathlib.Path({str(dsn)!r}),"
        " env_file=pathlib.Path('/nonexistent/m.env')))\n"
    )
    m0 = mark(server)
    with app(server) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext('catalog'))")
        proc = subprocess.Popen(  # noqa: S603 - fixed argv
            [sys.executable, "-c", launcher], env=base, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with app(server) as c:
                row = c.execute(
                    "SELECT count(*) FROM task WHERE state = 'running'"
                ).fetchone()
            if row and row[0]:
                break
            time.sleep(0.1)
        with app(server) as c, c.transaction():  # a start-up between the two
            assert imports_repo.fail_running_tasks(c, {"error": "start-up"}, T2)
        holder.execute("SELECT pg_advisory_unlock(hashtext('catalog'))")
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 1
    assert out == ""
    assert err.strip() == "bits rebuild: interrupted by manager start-up; run it again"
    assert [e for e in entries_after(server, m0) if e[1] != "audit.checkpoint"] == []


# Failed rebuild and database errors exit 1 ------------------------------------------


def test_a_failed_rebuild_exits_1(server: PgServer, bits: Path, dsn: Path) -> None:
    (bits / "f.bit").write_bytes(doc(f"F {tag()}", [plug()]))
    pre = (
        "import psycopg\nfrom bitscan_manager.services.importer import rebuild as r\n"
        "def boom(*a, **k): raise psycopg.errors.QueryCanceled('injected')\n"
        "r.store_in_savepoint = boom\n"
    )
    p = run(dsn, "rebuild", env={"BITSCAN_BITS_DIR": str(bits)}, pre=pre)
    assert p.returncode == 1
    assert p.stdout == ""
    assert re2.fullmatch(
        r"bits rebuild: The rebuild failed; the catalog was left unchanged\."
        r" \(task [0-9a-f-]{36}\)\n",
        p.stderr.split("\n", 1)[-1] if p.stderr.startswith("{") else p.stderr,
    ), p.stderr


def test_a_database_down_exits_1_naming_only_the_error_type(
    server: PgServer, bits: Path, tmp_path: Path
) -> None:
    info = dict(conninfo_to_dict(server.dsn("bitscan_app")), password=CANARY)
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    info["port"] = str(s.getsockname()[1])
    s.close()
    f = tmp_path / "down.dsn"
    f.write_text(make_conninfo(**info))  # type: ignore[arg-type]
    p = run(f, "rebuild", env={"BITSCAN_BITS_DIR": str(bits)})
    assert p.returncode == 1
    assert re2.search(r"bits rebuild: database error \(\w+\)", p.stderr), p.stderr
    no_secret(p, CANARY)


# REQ-175 (5), #107 (a): where the folder and the DSN come from ----------------------


def test_the_folder_comes_from_the_environment_then_manager_env(
    server: PgServer, bits: Path, dsn: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    (other / "uploaded").mkdir(parents=True)
    (other / "o.bit").write_bytes(doc(f"O {tag()}", [plug()]))
    (bits / "e.bit").write_bytes(doc(f"E {tag()}", [plug()]))
    menv = tmp_path / "manager.env"
    menv.write_text(f'# comment\nBITSCAN_BITS_DIR=/nope\nBITSCAN_BITS_DIR="{other}"\n')
    p = run(dsn, "rebuild", env_file=menv)  # not in the environment: manager.env
    assert p.returncode == 0, p.stderr
    assert any(x.startswith("success o.bit ") for x in p.stdout.splitlines())
    p = run(dsn, "rebuild", env={"BITSCAN_BITS_DIR": str(bits)}, env_file=menv)
    assert p.returncode == 0, p.stderr
    assert any(x.startswith("success e.bit ") for x in p.stdout.splitlines())
    bad = tmp_path / "bad.env"
    bad.write_bytes(b"BITSCAN_BITS_DIR=\xff" + CANARY.encode() + b"\n")
    p = run(dsn, "rebuild", env_file=bad)
    assert p.returncode == 2 and CANARY not in p.stderr + p.stdout


def test_no_dsn_or_folder_from_argv_or_the_environment(
    server: PgServer, bits: Path, tmp_path: Path, dsn: Path
) -> None:
    absent = tmp_path / "absent.dsn"
    env = {
        "BITSCAN_BITS_DIR": str(bits),
        "BITSCAN_DB_DSN": server.dsn("bitscan_app"),
        "BITSCAN_DB_DSN_FILE": str(dsn),
        "DATABASE_URL": server.dsn("bitscan_app"),
        "PGPASSWORD": "x",
    }
    p = run(absent, "rebuild", env=env)  # only the fixed DSN file counts
    assert p.returncode == 2 and "absent.dsn" in p.stderr
    for argv in (["rebuild", "--dsn", str(dsn)], ["rebuild", str(bits)],
                 ["rebuild", "--bits-dir", str(bits)]):  # fmt: skip
        assert run(dsn, *argv, env={"BITSCAN_BITS_DIR": str(bits)}).returncode == 2


# REQ-175 (6): help -----------------------------------------------------------------


def test_help_lists_bits_rebuild(server: PgServer) -> None:
    p = run_cli(["--help"], {})
    assert p.returncode == 0 and "bits rebuild" in p.stdout
    assert run_cli(["bits", "rebuild", "--help"], {}).returncode == 0
    assert run_cli(["bits"], {}).returncode == 2
    assert run_cli(["bits", "nonsense"], {}).returncode == 2


def test_the_cli_entry_point_reaches_bits_main(server: PgServer, bits: Path) -> None:
    # Through the installed console script: the fixed DSN path does not exist
    # in the test environment, so it exits 2 naming it, with no prompt.
    p = run_cli(["bits", "rebuild"], {"BITSCAN_BITS_DIR": str(bits)}, timeout=60)
    assert p.returncode == 2
    assert "/etc/bitscan/secrets/app.dsn" in p.stderr
    _ = psycopg
