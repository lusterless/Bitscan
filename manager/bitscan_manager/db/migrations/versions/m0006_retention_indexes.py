"""TS §5.2 L893-L894 and L943: indexes for retention deletes (owner-approved
spec change 68d3881, user decisions 2026-11-11; TASK-261).

The statements are the spec lines in order with the SQL comments removed.
Without them each deleted scan_job row seq-scans scan_job (the retry_of FK
check) and scan_result_reeval (the job_id cascade). Indexes take the table's
owner and need no grant; no grant changes here.
"""

from alembic import op

revision: str = "m0006"
down_revision: str | None = "m0005"
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
CREATE INDEX ix_job_scan     ON scan_job(scan_id);
""",
    """
CREATE INDEX ix_job_retry_of ON scan_job(retry_of);
""",
    """
CREATE INDEX ix_reeval_job ON scan_result_reeval(job_id);
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
