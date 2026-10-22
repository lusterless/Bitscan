import argparse
import logging
import os
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import SecretStr

EPILOG = """commands:
  serve        run the manager (HTTPS API) until SIGTERM
  users create-admin <name>      create an admin (no TOTP yet); asks for a password
  users create-api-token <user>  print a new API token once [--name N] [--days D]
  users reset-totp <user>        clear a user's TOTP and end their sessions
  db migrate   upgrade the database schema to the latest revision
  db maintain  create upcoming scan_result partitions, drop expired ones"""


def _migrate(dsn: "SecretStr") -> int:
    from bitscan_manager.db import MigrationError, run_migrations

    alembic_log = logging.getLogger("alembic")
    alembic_log.setLevel(logging.INFO)
    if not alembic_log.handlers:
        alembic_log.addHandler(logging.StreamHandler(sys.stderr))
    try:
        head = run_migrations(dsn)
    except MigrationError as exc:
        print(f"db migrate: {exc}", file=sys.stderr)
        return 1
    print(head)
    return 0


def _maintain(dsn: "SecretStr") -> int:
    from bitscan_manager.db.maintain import MaintainError, run_maintain

    try:
        plan = run_maintain(dsn)
    except MaintainError as exc:
        print(f"db maintain: {exc}", file=sys.stderr)
        return 1
    for part in plan.create:
        print(f"created {part.name}")
    for name in plan.drop:
        print(f"dropped {name}")
    if plan.drops_refused is not None:
        print(f"db maintain: {plan.drops_refused}", file=sys.stderr)
        return 1
    if not plan.create and not plan.drop:
        print("nothing to do")
    return 0


def _db(command: str) -> int:
    # Database modules are imported only after the configuration has loaded,
    # so other commands, and a missing variable, load none.
    from bitscan_manager.config import ConfigError, load_db_config

    try:
        config = load_db_config(os.environ)
    except ConfigError as exc:
        for line in str(exc).splitlines():
            print(f"db {command}: {line}", file=sys.stderr)
        return 2
    if command == "migrate":
        return _migrate(config.migrate_dsn)
    return _maintain(config.migrate_dsn)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bitscan-manager",
        description="Bitscan manager server CLI.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        parser.print_help()
        return 0
    if args in (["db", "migrate"], ["db", "maintain"]):
        return _db(args[1])
    if args[:1] == ["users"] and len(args) > 1:
        from bitscan_manager.cli.users import users_main

        return users_main(args[1:])
    if args == ["serve"]:
        from bitscan_manager.cli.serve import serve_main

        return serve_main(os.environ)
    parser.print_usage(sys.stderr)
    print(
        "bitscan-manager: error: unknown or not yet implemented command",
        file=sys.stderr,
    )
    return 2
