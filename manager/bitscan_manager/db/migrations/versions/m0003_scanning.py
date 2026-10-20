"""TS §5.2 L842-L938: scanning types, tables, the default partition and trigger.

The statements are the spec lines in order with the SQL comments removed. The
monthly scan_result partitions are created in m0005 (TS §5.3, PD-18).
"""

from alembic import op

revision: str = "m0003"
down_revision: str | None = "m0002"
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
CREATE TYPE scan_state   AS ENUM ('queued','dispatched','running','completed','partial','failed','cancelled','expired');
""",  # noqa: E501 - spec line kept verbatim
    """
CREATE TYPE check_result AS ENUM ('PASS','FAIL','ERROR');
""",
    """
CREATE TABLE scan_schedule (
  schedule_id  BIGSERIAL PRIMARY KEY,
  name         VARCHAR(128) NOT NULL,
  policy_id    BIGINT NOT NULL REFERENCES policy(policy_id),
  target       JSONB NOT NULL,
  cron         VARCHAR(64) NOT NULL,
  timezone     VARCHAR(64) NOT NULL DEFAULT 'UTC',
  enabled      BOOLEAN NOT NULL DEFAULT true,
  last_run_at  TIMESTAMPTZ,
  next_run_at  TIMESTAMPTZ,
  created_by   BIGINT NOT NULL
);
""",
    """
CREATE TABLE scan (
  scan_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_id      BIGINT NOT NULL REFERENCES policy(policy_id),
  policy_version INTEGER NOT NULL,
  trigger        VARCHAR(16) NOT NULL CHECK (trigger IN ('manual','scheduled')),
  schedule_id    BIGINT REFERENCES scan_schedule(schedule_id) ON DELETE SET NULL,
  target         JSONB NOT NULL,
  requested_by   BIGINT,
  state          scan_state NOT NULL DEFAULT 'queued',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at    TIMESTAMPTZ
);
""",
    """
CREATE TABLE scan_job (
  job_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind          VARCHAR(16) NOT NULL CHECK (kind IN ('compliance','inventory')),
  scan_id       UUID REFERENCES scan(scan_id) ON DELETE CASCADE,
  agent_id      UUID NOT NULL REFERENCES agent(agent_id),
  retry_of      UUID REFERENCES scan_job(job_id),
  state         scan_state NOT NULL DEFAULT 'queued',
  payload       JSONB NOT NULL,
  eval_spec     JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  pickup_by     TIMESTAMPTZ NOT NULL,
  dispatched_at TIMESTAMPTZ,
  started_at    TIMESTAMPTZ,
  deadline_at   TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ,
  CHECK ((kind = 'compliance') = (scan_id IS NOT NULL)),
  CHECK (kind = 'inventory' OR eval_spec IS NOT NULL)
);
""",
    """
CREATE INDEX ix_job_pending ON scan_job(agent_id) WHERE state = 'queued';
""",
    """
CREATE TABLE scan_result (
  job_id            UUID NOT NULL REFERENCES scan_job(job_id) ON DELETE CASCADE,
  job_created_at    TIMESTAMPTZ NOT NULL,
  plugin_uuid       UUID NOT NULL REFERENCES plugin(plugin_uuid),
  eval_code         SMALLINT NOT NULL CHECK (eval_code IN (0, 1, 2)),
  result            check_result GENERATED ALWAYS AS (
                      CASE eval_code WHEN 0 THEN 'PASS'::check_result
                                     WHEN 1 THEN 'FAIL'::check_result
                                     ELSE 'ERROR'::check_result END) STORED,
  eval_detail       TEXT,
  exit_code         INTEGER,
  stdout            TEXT,
  stderr            TEXT,
  timed_out         BOOLEAN NOT NULL DEFAULT false,
  truncated         BOOLEAN NOT NULL DEFAULT false,
  plugin_name_snap  VARCHAR(400) NOT NULL,
  execute_snap      TEXT NOT NULL,
  operator_snap     plugin_operator NOT NULL,
  expected_snap     TEXT NOT NULL,
  started_at        TIMESTAMPTZ NOT NULL,
  finished_at       TIMESTAMPTZ NOT NULL,
  received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, plugin_uuid, job_created_at)
) PARTITION BY RANGE (job_created_at);
""",
    """
CREATE TABLE scan_result_default PARTITION OF scan_result DEFAULT;
""",
    """
CREATE FUNCTION scan_result_check_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.job_created_at IS DISTINCT FROM (SELECT created_at FROM scan_job WHERE job_id = NEW.job_id) THEN
    RAISE EXCEPTION 'scan_result.job_created_at must equal scan_job.created_at';
  END IF;
  RETURN NEW;
END $$;
""",  # noqa: E501 - spec line kept verbatim
    """
CREATE TRIGGER scan_result_job_check BEFORE INSERT ON scan_result
  FOR EACH ROW EXECUTE FUNCTION scan_result_check_job();
""",
    """
CREATE TABLE scan_result_reeval (
  reeval_id      BIGSERIAL PRIMARY KEY,
  job_id         UUID NOT NULL REFERENCES scan_job(job_id) ON DELETE CASCADE,
  plugin_uuid    UUID NOT NULL REFERENCES plugin(plugin_uuid),
  policy_version INTEGER NOT NULL,
  eval_code      SMALLINT NOT NULL CHECK (eval_code IN (0, 1, 2)),
  eval_detail    TEXT,
  reevaluated_by BIGINT NOT NULL,
  reevaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
