"""Add generic extra client identities without changing resident business facts."""

from alembic import op
from sqlalchemy import text

revision = "20261027_client_identities"
down_revision = "20261023_import_preparation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE miniapp_user_identities (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    identity_type VARCHAR(32) COLLATE "C" NOT NULL,
    subject_id UUID NOT NULL,
    status VARCHAR(16) DEFAULT 'active' NOT NULL,
    row_version BIGINT DEFAULT 1 NOT NULL,
    revoked_at TIMESTAMP(6) WITH TIME ZONE,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_miniapp_user_identities PRIMARY KEY (id),
    CONSTRAINT fk_miniapp_identity_user FOREIGN KEY (user_id) REFERENCES miniapp_users (id),
    CONSTRAINT ck_miniapp_identity_type CHECK (identity_type ~ '^[a-z][a-z0-9_]{0,31}$'),
    CONSTRAINT ck_miniapp_identity_non_resident CHECK (identity_type <> 'resident'),
    CONSTRAINT ck_miniapp_identity_status CHECK (
        (status = 'active' AND revoked_at IS NULL) OR
        (status = 'revoked' AND revoked_at IS NOT NULL)),
    CONSTRAINT ck_miniapp_identity_revoked_time CHECK (
        revoked_at IS NULL OR revoked_at >= created_at),
    CONSTRAINT ck_miniapp_identity_version CHECK (row_version > 0)
)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_miniapp_identity_active ON miniapp_user_identities
    (user_id, identity_type, subject_id) WHERE status = 'active'
""")
    op.execute("""
CREATE INDEX ix_miniapp_identity_user_status_time ON miniapp_user_identities
    (user_id, status, created_at, id)
""")


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(text("LOCK TABLE miniapp_user_identities IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(text("SELECT EXISTS (SELECT 1 FROM miniapp_user_identities)")):
        raise RuntimeError("Cannot downgrade while client identity history exists")
    op.drop_table("miniapp_user_identities")
