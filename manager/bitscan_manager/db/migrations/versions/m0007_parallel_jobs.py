"""TS §4.4, §5.2, §8.6 (owner decision 2026-11-14): scan_job.cancel_reason and
the max_parallel_jobs setting.

The column is the spec line `cancel_reason VARCHAR(32) CHECK (cancel_reason IN
('already_running'))`, added after finished_at, the table's last column. It is
written only at INSERT (a new scan's job for a host that already runs the same
policy), so bitscan_app needs no new UPDATE grant: its scan_job UPDATE columns
stay state, dispatched_at, started_at, deadline_at and finished_at (TS §5.2).
The setting row is seeded like m0005's (updated_by NULL = seeded by the system).
"""

from alembic import op

revision: str = "m0007"
down_revision: str | None = "m0006"
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
ALTER TABLE scan_job ADD COLUMN cancel_reason VARCHAR(32) CHECK (cancel_reason IN ('already_running'));
""",  # noqa: E501 - spec line kept verbatim
    """
INSERT INTO setting (key, value) VALUES ('max_parallel_jobs', '2'::jsonb);
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
