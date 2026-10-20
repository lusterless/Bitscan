"""TS §5.2 L709-L825: fleet and inventory types, tables and indexes.

The statements are the spec lines in order with the SQL comments removed.
"""

from alembic import op

revision: str = "m0002"
down_revision: str | None = "m0001"
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
CREATE TYPE agent_status AS ENUM ('awaiting_approval','enrolled','online','stale','offline','decommissioned');
""",  # noqa: E501 - spec line kept verbatim
    """
CREATE TABLE agent (
  agent_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  machine_id            CHAR(32) NOT NULL UNIQUE,
  hostname              VARCHAR(255) NOT NULL,
  agent_version         VARCHAR(32) NOT NULL,
  token_hash            CHAR(64) NOT NULL UNIQUE,
  token_issued_at       TIMESTAMPTZ NOT NULL,
  token_expires_at      TIMESTAMPTZ NOT NULL,
  token_revoked_at      TIMESTAMPTZ,
  prev_token_hash       CHAR(64),
  prev_token_expires_at TIMESTAMPTZ,
  last_rotation_at      TIMESTAMPTZ,
  status                agent_status NOT NULL DEFAULT 'awaiting_approval',
  last_heartbeat_at     TIMESTAMPTZ,
  last_inventory_at     TIMESTAMPTZ,
  last_seen_ip          INET,
  runner_helpers        JSONB NOT NULL DEFAULT '[]',
  enrolled_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE INDEX ix_agent_status ON agent(status, last_heartbeat_at);
""",
    """
CREATE INDEX ix_agent_hostname_trgm ON agent USING gin (hostname gin_trgm_ops);
""",
    """
CREATE TABLE agent_ip_seen (
  agent_id      UUID NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
  ip            INET NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (agent_id, ip)
);
""",
    """
CREATE TABLE agent_tag (
  agent_id UUID REFERENCES agent(agent_id) ON DELETE CASCADE,
  tag      VARCHAR(64) NOT NULL,
  PRIMARY KEY (agent_id, tag)
);
""",
    """
CREATE TABLE enrollment_token (
  token_id      BIGSERIAL PRIMARY KEY,
  token_hash    CHAR(64) NOT NULL UNIQUE,
  max_uses      INTEGER NOT NULL DEFAULT 1 CHECK (max_uses BETWEEN 1 AND 10000),
  uses          INTEGER NOT NULL DEFAULT 0 CHECK (uses <= max_uses),
  auto_approve  BOOLEAN NOT NULL DEFAULT false,
  allowed_cidrs CIDR[],
  expires_at    TIMESTAMPTZ NOT NULL,
  revoked_at    TIMESTAMPTZ,
  created_by    BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE TABLE enrollment_request (
  request_id          BIGSERIAL PRIMARY KEY,
  kind                VARCHAR(8) NOT NULL CHECK (kind IN ('new','reenrol')),
  agent_id            UUID NOT NULL REFERENCES agent(agent_id) ON DELETE RESTRICT,
  enrollment_token_id BIGINT NOT NULL REFERENCES enrollment_token(token_id),
  hostname            VARCHAR(255) NOT NULL,
  machine_id          CHAR(32) NOT NULL,
  os_pretty_name      VARCHAR(128),
  agent_version       VARCHAR(32) NOT NULL,
  new_token_hash      CHAR(64) NOT NULL UNIQUE,
  token_expires_at    TIMESTAMPTZ NOT NULL,
  source_ip           INET NOT NULL,
  requested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  decision            VARCHAR(8) CHECK (decision IN ('approved','rejected')),
  decided_by          BIGINT,
  decided_at          TIMESTAMPTZ
);
""",
    """
CREATE TABLE os_info (
  agent_id        UUID PRIMARY KEY REFERENCES agent(agent_id) ON DELETE CASCADE,
  os_id           VARCHAR(32),
  os_version_id   VARCHAR(16),
  os_pretty_name  VARCHAR(128),
  kernel_release  VARCHAR(64),
  architecture    VARCHAR(16),
  cpu_count       INTEGER,
  memory_mb       INTEGER,
  ip_addresses    INET[],
  uptime_s        BIGINT,
  raw             JSONB NOT NULL,
  collected_at    TIMESTAMPTZ NOT NULL
);
""",
    """
CREATE TABLE package (
  package_id   BIGSERIAL PRIMARY KEY,
  name         VARCHAR(255) NOT NULL,
  version      VARCHAR(255) NOT NULL,
  architecture VARCHAR(16)  NOT NULL,
  source_name  VARCHAR(255),
  UNIQUE (name, version, architecture)
);
""",
    """
CREATE INDEX ix_package_name_trgm ON package USING gin (name gin_trgm_ops);
""",
    """
CREATE INDEX ix_package_name_debver ON package (name, (version::debversion));
""",
    """
CREATE TABLE agent_package (
  agent_id          UUID   NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
  package_id        BIGINT NOT NULL REFERENCES package(package_id),
  status            VARCHAR(64) NOT NULL,
  installed_size_kb INTEGER,
  first_seen_at     TIMESTAMPTZ NOT NULL,
  last_seen_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (agent_id, package_id)
);
""",
    """
CREATE INDEX ix_agent_package_pkg ON agent_package(package_id);
""",
    """
CREATE TABLE inventory_snapshot (
  snapshot_id   BIGSERIAL PRIMARY KEY,
  agent_id      UUID NOT NULL REFERENCES agent(agent_id) ON DELETE CASCADE,
  list_sha256   CHAR(64) NOT NULL,
  package_count INTEGER NOT NULL,
  added         JSONB NOT NULL DEFAULT '[]',
  removed       JSONB NOT NULL DEFAULT '[]',
  collected_at  TIMESTAMPTZ NOT NULL
);
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
