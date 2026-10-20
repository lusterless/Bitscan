"""TS §5.2 L827-L831, L835-L840 and L941-L990: system tables.

The statements are the spec lines in order with the SQL comments removed. The
system_schedule seed INSERT (L832-L833) runs in m0005 with the other seeds (PD-18).
"""

from alembic import op

revision: str = "m0004"
down_revision: str | None = "m0003"
branch_labels: str | None = None
depends_on: str | None = None

STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE system_schedule (
  job_kind   VARCHAR(32) PRIMARY KEY CHECK (job_kind IN ('inventory','offline_sweep','retention')),
  interval_s INTEGER NOT NULL CHECK (interval_s BETWEEN 60 AND 86400),
  CHECK (job_kind <> 'inventory' OR interval_s BETWEEN 3600 AND 86400)
);
""",  # noqa: E501 - spec line kept verbatim
    """
CREATE TABLE setting (
  key        VARCHAR(64) PRIMARY KEY,
  value      JSONB NOT NULL,
  updated_by BIGINT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE TABLE task (
  task_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind         VARCHAR(16) NOT NULL CHECK (kind IN ('rebuild')),
  state        VARCHAR(16) NOT NULL DEFAULT 'running' CHECK (state IN ('running','succeeded','failed')),
  requested_by BIGINT,
  result       JSONB,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ
);
""",  # noqa: E501 - spec line kept verbatim
    """
CREATE TYPE user_role AS ENUM ('viewer','operator','admin');
""",
    """
CREATE TABLE app_user (
  user_id         BIGSERIAL PRIMARY KEY,
  username        VARCHAR(64) NOT NULL UNIQUE,
  password_hash   TEXT NOT NULL,
  totp_secret_enc TEXT,
  totp_last_step  BIGINT,
  role            user_role NOT NULL DEFAULT 'viewer',
  disabled        BOOLEAN NOT NULL DEFAULT false,
  failed_logins   SMALLINT NOT NULL DEFAULT 0,
  next_login_at   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    """
CREATE TABLE user_token (
  token_id      BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
  kind          VARCHAR(8) NOT NULL CHECK (kind IN ('session','api')),
  name          VARCHAR(64),
  token_hash    CHAR(64) NOT NULL UNIQUE,
  totp_verified BOOLEAN NOT NULL DEFAULT false,
  expires_at    TIMESTAMPTZ NOT NULL,
  last_used_at  TIMESTAMPTZ,
  revoked_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (kind = 'session' OR NOT totp_verified)
);
""",
    """
CREATE INDEX ix_user_token_active ON user_token(user_id) WHERE revoked_at IS NULL;
""",
    """
CREATE TABLE audit_log (
  audit_id   BIGSERIAL PRIMARY KEY,
  actor      VARCHAR(128) NOT NULL,
  action     VARCHAR(64)  NOT NULL,
  target     VARCHAR(255),
  detail     JSONB,
  at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  prev_hash  CHAR(64) NOT NULL,
  row_hash   CHAR(64) NOT NULL
);
""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("forward-only (TS §5.3)")
