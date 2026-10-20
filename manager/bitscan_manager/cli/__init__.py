import argparse
import logging
import os
import sys
from collections.abc import Sequence

EPILOG = """commands:
  db migrate  upgrade the database schema to the latest revision"""


def _db_migrate() -> int:
    # Database modules are imported here only, so other commands load none.
    from bitscan_manager.config import ConfigError, load_db_config

    try:
        config = load_db_config(os.environ)
    except ConfigError as exc:
        for line in str(exc).splitlines():
            print(f"db migrate: {line}", file=sys.stderr)
        return 2

    from bitscan_manager.db import MigrationError, run_migrations

    alembic_log = logging.getLogger("alembic")
    alembic_log.setLevel(logging.INFO)
    if not alembic_log.handlers:
        alembic_log.addHandler(logging.StreamHandler(sys.stderr))
    try:
        head = run_migrations(config.migrate_dsn)
    except MigrationError as exc:
        print(f"db migrate: {exc}", file=sys.stderr)
        return 1
    print(head)
    return 0


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
    if args == ["db", "migrate"]:
        return _db_migrate()
    parser.print_usage(sys.stderr)
    print(
        "bitscan-manager: error: unknown or not yet implemented command",
        file=sys.stderr,
    )
    return 2
