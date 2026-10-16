"""Platform miniapp identity and durable phone authorization."""

import sqlalchemy as sa
from alembic import op

revision = "20261017_miniapp_identity"
down_revision = "20261016_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE miniapp_users (
        id UUID NOT NULL,
        wechat_openid VARCHAR(128) COLLATE "C" NOT NULL,
        enabled BOOLEAN DEFAULT true NOT NULL,
        session_version INTEGER DEFAULT '1' NOT NULL,
        last_login_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_miniapp_user_openid UNIQUE (wechat_openid),
        CONSTRAINT ck_miniapp_user_openid CHECK (wechat_openid <> '' AND wechat_openid =
btrim(wechat_openid)),
        CONSTRAINT ck_miniapp_user_version CHECK (session_version > 0)
)
"""
    )
    op.execute(
        """
CREATE TABLE miniapp_phone_bindings (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        phone VARCHAR(11) NOT NULL,
        status VARCHAR(16) NOT NULL,
        first_verified_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        last_verified_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        unbound_at TIMESTAMP(6) WITH TIME ZONE,
        row_version BIGINT DEFAULT '1' NOT NULL,
        created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_phone_binding_user FOREIGN KEY(user_id) REFERENCES miniapp_users (id),
        CONSTRAINT uq_phone_binding_number UNIQUE (user_id, phone),
        CONSTRAINT uq_phone_binding_user_id UNIQUE (user_id, id),
        CONSTRAINT ck_phone_binding_number CHECK (phone ~ '^1[3-9][0-9]{9}$'),
        CONSTRAINT ck_phone_binding_status CHECK ((status = 'active' AND unbound_at IS NULL) OR
(status = 'unbound' AND unbound_at IS NOT NULL)),
        CONSTRAINT ck_phone_binding_version_time CHECK (row_version > 0 AND first_verified_at <=
last_verified_at)
)
"""
    )
    op.execute(
        """
CREATE INDEX ix_phone_binding_user_time ON miniapp_phone_bindings (user_id, status, created_at,
id)
"""
    )
    op.execute(
        """
CREATE TABLE miniapp_phone_verifications (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        phone_binding_id UUID NOT NULL,
        method VARCHAR(32) NOT NULL,
        wechat_code_hash CHAR(64) NOT NULL,
        wechat_authorized_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        verified_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        idempotency_key VARCHAR(128) NOT NULL,
        request_fingerprint CHAR(64) NOT NULL,
        request_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_phone_verification_binding FOREIGN KEY(user_id, phone_binding_id)
REFERENCES miniapp_phone_bindings (user_id, id),
        CONSTRAINT uq_phone_verification_key UNIQUE (user_id, idempotency_key),
        CONSTRAINT uq_phone_verification_code UNIQUE (user_id, wechat_code_hash),
        CONSTRAINT ck_phone_verification_method CHECK (method = 'wechat_fast'),
        CONSTRAINT ck_phone_verification_keys CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$'
AND request_fingerprint ~ '^[0-9a-f]{64}$' AND wechat_code_hash ~ '^[0-9a-f]{64}$')
)
"""
    )
    op.execute(
        """
CREATE INDEX ix_phone_verification_binding_time ON miniapp_phone_verifications
(phone_binding_id, verified_at, id)
"""
    )
    op.execute("""
CREATE FUNCTION miniapp_freeze_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.id <> NEW.id OR OLD.created_at <> NEW.created_at OR
       (TG_TABLE_NAME = 'miniapp_users' AND to_jsonb(OLD)->'wechat_openid' IS DISTINCT FROM
to_jsonb(NEW)->'wechat_openid') OR
       (TG_TABLE_NAME = 'miniapp_phone_bindings' AND
          ((to_jsonb(OLD) -
ARRAY['status','last_verified_at','unbound_at','row_version','updated_at']) IS DISTINCT FROM
           (to_jsonb(NEW) -
ARRAY['status','last_verified_at','unbound_at','row_version','updated_at']) OR
           (to_jsonb(NEW)->>'row_version')::bigint <>
           (to_jsonb(OLD)->>'row_version')::bigint + 1)) THEN
        RAISE EXCEPTION 'miniapp identity facts are immutable' USING ERRCODE = '23514',
CONSTRAINT = 'ck_miniapp_identity_immutable';
    END IF;
    RETURN NEW;
END $$
""")
    for table in ("miniapp_users", "miniapp_phone_bindings"):
        op.execute(
            f"CREATE TRIGGER miniapp_freeze_identity BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION miniapp_freeze_identity()"
        )
    op.execute("""
CREATE FUNCTION miniapp_verification_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'phone verification history is immutable' USING ERRCODE = '23514',
CONSTRAINT = 'ck_phone_verification_immutable';
END $$
""")
    op.execute(
        """
CREATE TRIGGER miniapp_verification_immutable BEFORE UPDATE OR DELETE ON
miniapp_phone_verifications FOR EACH ROW EXECUTE FUNCTION miniapp_verification_immutable()
"""
    )


def downgrade() -> None:
    for table in ("miniapp_phone_verifications", "miniapp_phone_bindings", "miniapp_users"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot downgrade while miniapp identity data exists")
    for table in ("miniapp_phone_verifications", "miniapp_phone_bindings", "miniapp_users"):
        op.drop_table(table)
    op.execute("""
DROP FUNCTION miniapp_verification_immutable()
""")
    op.execute("""
DROP FUNCTION miniapp_freeze_identity()
""")
