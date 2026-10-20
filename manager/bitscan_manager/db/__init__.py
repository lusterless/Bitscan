"""Migration runner (TS §5.3): Alembic, forward-only, as bitscan_migrate with
SET ROLE bitscan_owner so that bitscan_owner owns everything it creates."""

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
OWNER_ROLE = "bitscan_owner"


class MigrationError(Exception):
    """Message is safe to print: the DSN and its password are removed."""


def _alembic_config(connection: Connection) -> Config:
    # Built in code (no alembic.ini), so no DSN is ever in a configuration file.
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR).replace("%", "%%"))
    config.attributes["connection"] = connection
    return config


def dsn_secrets(dsn: str) -> tuple[str, ...] | None:
    """The DSN and its password, for scrub(); None if the DSN does not parse.

    Never raises. psycopg's parse error quotes part of the DSN, so for an
    unparsable DSN no driver message may be shown at all.
    """
    params: dict[str, object] | None = None
    try:
        params = dict(conninfo_to_dict(dsn))
    except psycopg.Error:
        pass
    if params is None:
        return None
    password = params.get("password")
    return (dsn, str(password)) if password else (dsn,)


def scrub(message: str, secrets: tuple[str, ...] | None) -> str:
    if secrets is None:
        return "the DSN is not a valid PostgreSQL DSN"
    for secret in secrets:
        message = message.replace(secret, "**********")
    return message


def _upgrade(dsn: str) -> str:
    # creator keeps the DSN out of any SQLAlchemy URL, repr or log.
    engine = create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(dsn),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SET ROLE bitscan_owner"))
            role = connection.execute(text("SELECT current_user")).scalar_one()
            # Commit, or the autobegun transaction's rollback would undo SET ROLE.
            connection.commit()
            if role != OWNER_ROLE:
                raise MigrationError(f"SET ROLE gave {role!r}, not {OWNER_ROLE!r}")
            config = _alembic_config(connection)
            command.upgrade(config, "head")
            # With no pending migration, the version table is created inside an
            # autobegun transaction that only this commit makes durable.
            connection.commit()
    finally:
        engine.dispose()
    head = ScriptDirectory.from_config(config).get_current_head()
    return head or "base"


def run_migrations(dsn: SecretStr) -> str:
    """Upgrade to head as bitscan_owner and return the head revision id.

    There is no downgrade path. Raises MigrationError on any failure.
    """
    secret = dsn.get_secret_value()
    secrets = dsn_secrets(secret)
    message: str | None = None
    try:
        return _upgrade(secret)
    except Exception as exc:
        message = scrub(f"{type(exc).__name__}: {exc}", secrets)
    # Raised outside the except block, so the original error is not chained.
    raise MigrationError(message)
