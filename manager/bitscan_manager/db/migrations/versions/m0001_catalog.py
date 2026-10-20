"""TS §5.2 L638-L707: extensions, policy catalog types and tables.

The statements are the spec lines in order with the SQL comments removed.
"""

from alembic import op

revision: str = "m0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
CREATE EXTENSION IF NOT EXISTS pg_trgm;
""",
    """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
""",
    """
CREATE EXTENSION IF NOT EXISTS debversion;
""",
    """
CREATE TYPE policy_status AS ENUM ('enabled','disabled');
""",
    """
CREATE TYPE plugin_state  AS ENUM ('active','retired');
""",
    """
CREATE TYPE plugin_operator AS ENUM ('equals','not_equals','contains','not_contains',
  'regex','not_regex','eq','ne','gt','ge','lt','le','empty','not_empty');
""",
    """
CREATE TABLE family (
  family_id    BIGSERIAL PRIMARY KEY,
  family_name  VARCHAR(128) NOT NULL UNIQUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE TABLE policy (
  policy_id          BIGSERIAL PRIMARY KEY,
  policy_name        VARCHAR(128) NOT NULL UNIQUE,
  policy_description TEXT NOT NULL DEFAULT '',
  policy_status      policy_status NOT NULL,
  file_status        policy_status NOT NULL,
  status_overridden  BOOLEAN NOT NULL DEFAULT false,
  family_id          BIGINT NOT NULL REFERENCES family(family_id),
  format_version     VARCHAR(8) NOT NULL DEFAULT '1.0',
  version            INTEGER NOT NULL DEFAULT 1,
  source_file        TEXT NOT NULL UNIQUE,
  source_sha256      CHAR(64) NOT NULL,
  deleted_at         TIMESTAMPTZ,
  imported_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE TABLE plugin (
  plugin_uuid        UUID PRIMARY KEY,
  family_id          BIGINT NOT NULL REFERENCES family(family_id),
  owner_policy_id    BIGINT NOT NULL REFERENCES policy(policy_id),
  plugin_name        VARCHAR(255) NOT NULL,
  control_ref        VARCHAR(32),
  plugin_description TEXT NOT NULL DEFAULT '',
  execute            TEXT NOT NULL,
  execute_sha256     CHAR(64) NOT NULL,
  operator           plugin_operator NOT NULL,
  expected_result    TEXT NOT NULL DEFAULT '',
  timeout_s          INTEGER NOT NULL DEFAULT 60 CHECK (timeout_s BETWEEN 1 AND 600),
  state              plugin_state NOT NULL DEFAULT 'active',
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE TABLE policy_plugin (
  policy_id   BIGINT NOT NULL REFERENCES policy(policy_id) ON DELETE CASCADE,
  plugin_uuid UUID   NOT NULL REFERENCES plugin(plugin_uuid),
  sort_order  INTEGER NOT NULL,
  PRIMARY KEY (policy_id, plugin_uuid)
);
""",
    """
CREATE TABLE bit_import (
  import_id       BIGSERIAL PRIMARY KEY,
  file_name       TEXT NOT NULL,
  file_sha256     CHAR(64) NOT NULL,
  policy_version  INTEGER,
  mode            VARCHAR(16) NOT NULL CHECK (mode IN ('auto','manual','rebuild')),
  outcome         VARCHAR(16) NOT NULL CHECK (outcome IN ('success','skipped','rejected')),
  plugins_added   INTEGER NOT NULL DEFAULT 0,
  plugins_updated INTEGER NOT NULL DEFAULT 0,
  plugins_retired INTEGER NOT NULL DEFAULT 0,
  errors          JSONB NOT NULL DEFAULT '[]',
  imported_by     BIGINT,
  imported_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",  # noqa: E501 - spec line kept verbatim
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
