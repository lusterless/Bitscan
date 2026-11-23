"""TS §3.8, §4.4, §5.2 (owner decision 2026-11-23): the ClusterMAX scanner
role's tables and columns.

- scan.clustermax (not cmax, a PostgreSQL system column name), the table's new last column (the spec puts it after finished_at).
- scan_job.kind gains 'cluster_audit', and the scan_id CHECK covers it. The two
  CHECKs keep the names PostgreSQL gave them in m0001 (scan_job_kind_check,
  scan_job_check), so the schema matches the spec DDL.
- kubeconfig, kubeconfig_fetch, cluster_audit_run and scan_file, verbatim from
  TS §5.2. bitscan_app gets SELECT and INSERT through the default privileges
  and UPDATE on kubeconfig only (replace and soft delete); bitscan_retention may
  DELETE the three job tables (their rows also go with their job, ON DELETE
  CASCADE).
"""

# ruff: noqa: E501 - the TS §5.2 DDL lines are kept verbatim
from alembic import op

revision: str = "m0008"
down_revision: str | None = "m0007"
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
ALTER TABLE scan ADD COLUMN clustermax JSONB;
""",
    """
ALTER TABLE scan_job DROP CONSTRAINT scan_job_kind_check;
""",
    """
ALTER TABLE scan_job ADD CONSTRAINT scan_job_kind_check
  CHECK (kind IN ('compliance','inventory','cluster_audit'));
""",
    """
ALTER TABLE scan_job DROP CONSTRAINT scan_job_check;
""",
    """
ALTER TABLE scan_job ADD CONSTRAINT scan_job_check
  CHECK ((kind IN ('compliance','cluster_audit')) = (scan_id IS NOT NULL));
""",
    """
CREATE TABLE kubeconfig (                -- uploaded cluster credentials for ClusterMAX scans (§3.8); admin only
  kubeconfig_id BIGSERIAL PRIMARY KEY,
  name          VARCHAR(128) NOT NULL UNIQUE,
  description   VARCHAR(1000) NOT NULL DEFAULT '',
  cluster_name  VARCHAR(253) NOT NULL,   -- from the current context, shown in the UI
  server        VARCHAR(2048) NOT NULL,  -- API server URL of that cluster, shown in the UI
  content_enc   TEXT NOT NULL,           -- the whole kubeconfig, encrypted with a vault key; never returned by the API
  created_by    BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  replaced_at   TIMESTAMPTZ,
  deleted_at    TIMESTAMPTZ               -- soft delete: content_enc is overwritten with '' and old scans keep the reference
);
""",
    """
CREATE TABLE kubeconfig_fetch (          -- the one allowed kubeconfig fetch per cluster_audit job (§6.1); insert only
  job_id        UUID PRIMARY KEY REFERENCES scan_job(job_id) ON DELETE CASCADE,
  kubeconfig_id BIGINT NOT NULL REFERENCES kubeconfig(kubeconfig_id),
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_ip     INET NOT NULL
);
""",
    """
CREATE TABLE cluster_audit_run (         -- one row per finished cluster_audit job, written once
  job_id        UUID PRIMARY KEY REFERENCES scan_job(job_id) ON DELETE CASCADE,
  exit_code     INTEGER NOT NULL,
  error_line    VARCHAR(512),            -- the redacted `cmax: error:` line, when exit_code <> 0
  started_at    TIMESTAMPTZ NOT NULL,
  finished_at   TIMESTAMPTZ NOT NULL,
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE TABLE scan_file (                 -- redacted ClusterMAX files of a cluster_audit job (§3.8)
  job_id        UUID NOT NULL REFERENCES scan_job(job_id) ON DELETE CASCADE,
  name          VARCHAR(32) NOT NULL CHECK (name IN ('report.txt','run.log','audit.out','audit.values.json')),
  size_bytes    BIGINT NOT NULL,         -- uncompressed
  sha256        CHAR(64) NOT NULL,       -- of the uncompressed content
  truncated     BOOLEAN NOT NULL DEFAULT false,
  content_gz    BYTEA NOT NULL,          -- gzip, at most 64 MiB each
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, name)
);
""",
    """
GRANT UPDATE ON kubeconfig TO bitscan_app;
""",
    """
GRANT DELETE ON kubeconfig_fetch, cluster_audit_run, scan_file TO bitscan_retention;
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
