"""bitscan-manager bits rebuild (TS §8.7 L1347, §4.2 L540, §4.6 L613;
REQ-175; open question #107).

Run as root on the server. The same rebuild as `POST /policies/rebuild`,
in the foreground: the `task` row (`requested_by` NULL), the catalog lock
(it waits for an import in progress), the alerts, actor `cli:root`. The
bitscan_app DSN is read from APP_DSN_FILE with the serve profile's checks
(TLS required); messages name the file, never its content. Nothing secret is
read from argv or the environment. #107: the folder is BITSCAN_BITS_DIR from
the environment, else from MANAGER_ENV, else the default, and it and its
`uploaded/` must exist (an empty wrong folder would delete every policy).
It neither finishes uploads nor runs the integrity check (serve's start-up),
and asks for no confirmation. Exit 0 when the rebuild committed (rejected
files included), 1 when it failed or did not run, 2 for a usage or
configuration error.
"""

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from bitscan_manager.cli.users import ACTOR, APP_DSN_FILE

if TYPE_CHECKING:
    from pydantic import SecretStr

    from bitscan_manager.services.importer.pipeline import ImportOutcome

MANAGER_ENV: Final = Path("/etc/bitscan/manager.env")  # non-secret (TS §8.6)
BITS_DIR_VAR: Final = "BITSCAN_BITS_DIR"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bitscan-manager bits")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "rebuild",
        help="re-import every file of both policy folders now",
        description="Re-import every .bit file of the server folder and its"
        " uploaded/ folder (never skipped), delete policies whose files are"
        " gone, and print one line per file.",
    )
    return parser


def _from_env_file(path: Path, name: str) -> str:
    """NAME's value in a systemd EnvironmentFile, the last one winning; ""
    when the file or the name is missing. Raises ConfigError if it cannot be
    read; no content is ever shown."""
    from bitscan_manager.config.startup import ConfigError

    text: str | None = None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError):
        pass
    if text is None:
        raise ConfigError(f"{path}: cannot read the file")
    value = ""
    for line in text.splitlines():
        key, eq, rest = line.strip().partition("=")
        if eq and key.strip() == name:
            rest = rest.strip()
            quoted = len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "\"'"
            value = rest[1:-1] if quoted else rest
    return value.strip()


def bits_dir(environ: Mapping[str, str], env_file: Path = MANAGER_ENV) -> Path:
    """#107 (a). Raises ConfigError when the folder or its uploaded/ is missing."""
    from bitscan_manager.config.startup import DEFAULT_BITS_DIR, ConfigError

    value = (environ.get(BITS_DIR_VAR) or "").strip()
    folder = Path(value or _from_env_file(env_file, BITS_DIR_VAR) or DEFAULT_BITS_DIR)
    if not (folder.is_dir() and (folder / "uploaded").is_dir()):
        raise ConfigError(f"{BITS_DIR_VAR}: the folder or its uploaded/ is missing")
    return folder


def _dsn(path: Path) -> "SecretStr":
    from bitscan_manager.config.startup import _Loader

    # As `users`: the serve profile's checks; the loader's key is the path.
    loader = _Loader({str(path): str(path)})
    dsn = loader.dsn_file(str(path))
    loader.finish()  # ConfigError: one line per problem, no file content
    return dsn


def _line(rel: str, outcome: "ImportOutcome") -> str:
    """#107 (b): `<outcome> <source_file>` and the policy or finding count."""
    if outcome.outcome == "success":
        return (
            f"success {rel} policy {outcome.policy_id} version {outcome.policy_version}"
        )
    return f"{outcome.outcome} {rel} ({len(outcome.findings)} findings)"


def _rebuild(dsn: "SecretStr", folder: Path) -> int:
    from bitscan_manager.db.pool import AppDatabase
    from bitscan_manager.runtime import SystemClock
    from bitscan_manager.services.importer import rebuild
    from bitscan_manager.services.importer.pipeline import Actor

    clock = SystemClock()
    db = AppDatabase(dsn, min_size=1, max_size=1)
    db.open()
    try:
        task_id = rebuild.start_task(db, clock, None)
        result = rebuild.run(db, clock, folder, task_id, Actor(ACTOR, None))
    except Exception as exc:  # database errors: type only (no DSN, no SQL)
        print(f"bits rebuild: database error ({type(exc).__name__})", file=sys.stderr)
        return 1
    finally:
        db.close()
    if result.reason is not None:  # rebuild.NOT_RUNNING
        print(f"bits rebuild: {result.reason}", file=sys.stderr)
        return 1
    if result.state != "succeeded":
        print(f"bits rebuild: {rebuild.FAILED} (task {task_id})", file=sys.stderr)
        return 1
    for rel, outcome in result.files:
        print(_line(rel, outcome))
    for rel in result.not_imported:
        print(f"not imported {rel}")
    for rel in result.removed_leftovers:
        print(f"removed leftover {rel}")
    for policy_id in result.deleted_policy_ids:
        print(f"deleted policy {policy_id}")
    rejected = sum(1 for _, o in result.files if o.outcome == "rejected")
    print(
        f"rebuild succeeded: {len(result.files)} files, {rejected} rejected,"
        f" {len(result.deleted_policy_ids)} policies deleted,"
        f" {result.plugins_retired} plugins retired (task {task_id})"
    )
    return 0


def bits_main(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    dsn_file: Path | None = None,
    env_file: Path | None = None,
) -> int:
    """Usage errors exit 2 before any configuration or database module loads."""
    try:
        _parser().parse_args(list(argv))
    except SystemExit as exc:  # usage error (2) or --help (0)
        return exc.code if isinstance(exc.code, int) else 2
    import os

    from bitscan_manager.api.request_log import configure_logging
    from bitscan_manager.config.startup import ConfigError

    configure_logging(level=logging.WARNING)  # JSON only; output stays short
    try:
        folder = bits_dir(
            os.environ if environ is None else environ, env_file or MANAGER_ENV
        )
        dsn = _dsn(dsn_file or APP_DSN_FILE)
    except ConfigError as exc:
        for line in str(exc).splitlines():
            print(f"bits rebuild: {line}", file=sys.stderr)
        return 2
    return _rebuild(dsn, folder)
