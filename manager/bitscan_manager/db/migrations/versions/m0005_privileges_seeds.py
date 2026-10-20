"""TS §5.2 L994-L1013 and L1038-L1041, seeds and the first scan_result partitions.

Privilege, view and system_schedule statements are the spec lines with the SQL
comments removed. Settings are inserted with bound parameters (TS §8.6, #42).
Partitions come last so the default privileges apply to them (TS §5.3, #43).
"""

from datetime import UTC, datetime

import psycopg
import sqlalchemy as sa
from alembic import op
from psycopg import sql
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "m0005"
down_revision: str | None = "m0004"
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
ALTER DEFAULT PRIVILEGES FOR ROLE bitscan_owner IN SCHEMA public GRANT SELECT, INSERT ON TABLES TO bitscan_app;
""",  # noqa: E501 - spec line kept verbatim
    """
ALTER DEFAULT PRIVILEGES FOR ROLE bitscan_owner IN SCHEMA public GRANT USAGE ON SEQUENCES TO bitscan_app;
""",  # noqa: E501 - spec line kept verbatim
    """
ALTER DEFAULT PRIVILEGES FOR ROLE bitscan_owner IN SCHEMA public GRANT SELECT ON TABLES TO bitscan_retention;
""",  # noqa: E501 - spec line kept verbatim
    """
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO bitscan_app;
""",
    """
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO bitscan_app;
""",
    """
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bitscan_retention;
""",
    """
GRANT DELETE ON scan, scan_job, scan_result, scan_result_reeval, inventory_snapshot,
  enrollment_request, user_token, audit_log, package TO bitscan_retention;
""",
    """
GRANT INSERT ON audit_log TO bitscan_retention;
""",
    """
GRANT USAGE ON SEQUENCE audit_log_audit_id_seq TO bitscan_retention;
""",
    """
GRANT UPDATE ON policy, family, plugin, agent, enrollment_token, enrollment_request, os_info,
  agent_package, agent_ip_seen, scan_schedule, setting, system_schedule,
  app_user, user_token, task TO bitscan_app;
""",  # noqa: E501 - spec line kept verbatim
    """
GRANT UPDATE (state, dispatched_at, started_at, deadline_at, finished_at) ON scan_job TO bitscan_app;
""",  # noqa: E501 - spec line kept verbatim
    """
GRANT UPDATE (state, finished_at) ON scan TO bitscan_app;
""",
    """
GRANT DELETE ON policy_plugin, agent_tag, agent_package, agent_ip_seen, scan_schedule TO bitscan_app;
""",  # noqa: E501 - spec line kept verbatim
    """
CREATE VIEW v_plugin AS
SELECT p.*, f.family_name || ' - ' || p.plugin_name AS display_name
FROM plugin p JOIN family f USING (family_id);
""",
    """
GRANT SELECT ON v_plugin TO bitscan_app;
""",
    """
INSERT INTO system_schedule (job_kind, interval_s) VALUES
  ('inventory', 21600), ('offline_sweep', 60), ('retention', 86400);
""",
)

# TS §8.6 L1332-L1336, one per line, exactly as written.
REDACTION_PATTERNS: tuple[str, ...] = (
    r"\$(?:1|2[abxy]?|5|6|7|y|gy|sha1|md5)\$[^:\s]+",
    r"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\z)",  # noqa: E501 - spec line kept verbatim
    r"\bbs[aeku]_[A-Za-z0-9_-]{20,}",
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    r"(?i)(?:password|secret|api[_-]?key|token)\s*[=:]\s*\S+",
)

# TS §8.6 L1321-L1326 in table order; inventory_interval_s lives in system_schedule.
SETTINGS: tuple[tuple[str, object], ...] = (
    ("agent_token_ttl_days", 365),
    ("job_pull_seconds", 300),
    ("decommission_after_days", 7),
    ("redaction_patterns", list(REDACTION_PATTERNS)),
    ("max_parallel_plugins", 2),
    ("enrolment_alert_per_hour", 50),
)

PARTITION_MONTHS = 4  # the current month and the next three (TS §5.3)


def month_starts(now: datetime, count: int) -> list[datetime]:
    """First instants of `count` consecutive UTC months, starting with now's month."""
    first = now.astimezone(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    starts = []
    for offset in range(count):
        years, month_index = divmod(first.month - 1 + offset, 12)
        starts.append(first.replace(year=first.year + years, month=month_index + 1))
    return starts


def _create_partitions(now: datetime) -> None:
    connection = op.get_bind().connection.driver_connection
    if not isinstance(connection, psycopg.Connection):
        raise RuntimeError("m0005 needs a psycopg connection")
    template = sql.SQL(
        "CREATE TABLE {} PARTITION OF scan_result FOR VALUES FROM ({}) TO ({})"
    )
    bounds = month_starts(now, PARTITION_MONTHS + 1)
    with connection.cursor() as cursor:
        for low, high in zip(bounds, bounds[1:], strict=False):
            name = low.strftime("scan_result_%Y_%m")
            cursor.execute(
                template.format(
                    sql.Identifier(name), sql.Literal(low), sql.Literal(high)
                )
            )


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    setting = sa.table(
        "setting", sa.column("key", sa.String), sa.column("value", JSONB)
    )
    op.bulk_insert(setting, [{"key": key, "value": value} for key, value in SETTINGS])
    _create_partitions(datetime.now(UTC))


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
