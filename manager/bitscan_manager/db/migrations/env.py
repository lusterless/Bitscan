"""Alembic environment: online only, on the connection bitscan_manager.db hands in.

Migration files are versions/m000N_<name>.py with revision "m000N", a typed
upgrade(), and a downgrade() that raises NotImplementedError (forward-only, TS §5.3).
"""

from alembic import context
from sqlalchemy.engine import Connection


def _run() -> None:
    if context.is_offline_mode():
        raise RuntimeError("offline (SQL script) migrations are not supported")
    connection = context.config.attributes.get("connection")
    if not isinstance(connection, Connection):
        raise RuntimeError("run migrations with bitscan-manager db migrate")
    context.configure(
        connection=connection,
        target_metadata=None,
        transaction_per_migration=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


_run()
