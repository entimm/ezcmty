"""Resident house claim snapshots and independent authorization episodes."""

import sqlalchemy as sa
from alembic import op

revision = "20261017_house_claims"
down_revision = "20261017_miniapp_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_house_owner_house_id", "house_owners", ["house_id", "id"])
    op.execute("""
CREATE TABLE house_claim_applications (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        property_company_id UUID NOT NULL,
        community_id UUID NOT NULL,
        house_id UUID NOT NULL,
        house_label_snapshot VARCHAR(512) NOT NULL,
        applicant_name VARCHAR(80) NOT NULL,
        applicant_phone VARCHAR(11) NOT NULL,
        applicant_remark VARCHAR(1000),
        match_status VARCHAR(16) NOT NULL,
        matched_owner_id UUID,
        status VARCHAR(16) NOT NULL,
        reviewed_by_admin_id UUID,
        reviewed_at TIMESTAMP(6) WITH TIME ZONE,
        review_reason VARCHAR(1000),
        cancelled_at TIMESTAMP(6) WITH TIME ZONE,
        row_version BIGINT NOT NULL,
        idempotency_key VARCHAR(128) NOT NULL,
        request_fingerprint CHAR(64) NOT NULL,
        created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_house_claim_user FOREIGN KEY(user_id) REFERENCES miniapp_users (id),
        CONSTRAINT fk_house_claim_community FOREIGN KEY(property_company_id, community_id)
REFERENCES communities (property_company_id, id),
        CONSTRAINT fk_house_claim_house FOREIGN KEY(community_id, house_id) REFERENCES houses
(community_id, id),
        CONSTRAINT fk_house_claim_owner FOREIGN KEY(house_id, matched_owner_id) REFERENCES
house_owners (house_id, id),
        CONSTRAINT fk_house_claim_reviewer FOREIGN KEY(property_company_id,
reviewed_by_admin_id) REFERENCES admin_accounts (property_company_id, id),
        CONSTRAINT uq_house_claim_key UNIQUE (user_id, idempotency_key),
        CONSTRAINT uq_house_claim_scope_id UNIQUE (property_company_id, community_id, house_id,
user_id, id),
        CONSTRAINT ck_house_claim_applicant CHECK (applicant_name <> '' AND applicant_name =
btrim(applicant_name) AND applicant_phone ~ '^1[3-9][0-9]{9}$' AND house_label_snapshot <> ''),
        CONSTRAINT ck_house_claim_match CHECK ((match_status = 'matched' AND matched_owner_id IS
NOT NULL) OR (match_status = 'unmatched' AND matched_owner_id IS NULL)),
        CONSTRAINT ck_house_claim_status CHECK ((status = 'pending' AND reviewed_at IS NULL AND
reviewed_by_admin_id IS NULL AND review_reason IS NULL AND cancelled_at IS NULL) OR (status IN
('approved','rejected') AND reviewed_at IS NOT NULL AND reviewed_by_admin_id IS NOT NULL AND
cancelled_at IS NULL) OR (status = 'cancelled' AND cancelled_at IS NOT NULL AND reviewed_at IS
NULL AND reviewed_by_admin_id IS NULL AND review_reason IS NULL)),
        CONSTRAINT ck_house_claim_reasons CHECK ((review_reason IS NULL OR (review_reason <> ''
AND review_reason = btrim(review_reason))) AND (applicant_remark IS NULL OR (applicant_remark <>
'' AND applicant_remark = btrim(applicant_remark))) AND (NOT (status = 'rejected' OR (status =
'approved' AND match_status = 'unmatched')) OR review_reason IS NOT NULL)),
        CONSTRAINT ck_house_claim_keys CHECK (row_version > 0 AND idempotency_key ~
'^[A-Za-z0-9_-]{1,128}$' AND request_fingerprint ~ '^[0-9a-f]{64}$')
)
""")
    op.execute("""
CREATE INDEX ix_house_claim_community_time ON house_claim_applications (property_company_id,
community_id, status, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_house_claim_company_time ON house_claim_applications (property_company_id,
status, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_house_claim_house_fk ON house_claim_applications (community_id, house_id)
""")
    op.execute("""
CREATE INDEX ix_house_claim_house_time ON house_claim_applications (house_id, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_house_claim_owner_fk ON house_claim_applications (house_id, matched_owner_id)
""")
    op.execute("""
CREATE INDEX ix_house_claim_reviewer ON house_claim_applications (property_company_id,
reviewed_by_admin_id)
""")
    op.execute("""
CREATE INDEX ix_house_claim_user_time ON house_claim_applications (user_id, created_at, id)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_house_claim_pending ON house_claim_applications (user_id, house_id) WHERE
status = 'pending'
""")
    op.execute("""
CREATE TABLE resident_house_bindings (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        property_company_id UUID NOT NULL,
        community_id UUID NOT NULL,
        house_id UUID NOT NULL,
        claim_application_id UUID NOT NULL,
        status VARCHAR(16) NOT NULL,
        granted_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        ended_at TIMESTAMP(6) WITH TIME ZONE,
        ended_by_user_id UUID,
        ended_by_admin_id UUID,
        end_reason VARCHAR(1000),
        row_version BIGINT NOT NULL,
        created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_resident_binding_origin FOREIGN KEY(property_company_id, community_id,
house_id, user_id, claim_application_id) REFERENCES house_claim_applications
(property_company_id, community_id, house_id, user_id, id),
        CONSTRAINT fk_resident_binding_admin FOREIGN KEY(property_company_id, ended_by_admin_id)
REFERENCES admin_accounts (property_company_id, id),
        CONSTRAINT fk_resident_binding_user FOREIGN KEY(ended_by_user_id) REFERENCES
miniapp_users (id),
        CONSTRAINT uq_resident_binding_claim UNIQUE (claim_application_id),
        CONSTRAINT ck_resident_binding_status CHECK ((status = 'active' AND ended_at IS NULL AND
ended_by_user_id IS NULL AND ended_by_admin_id IS NULL AND end_reason IS NULL) OR (status =
'released' AND ended_at IS NOT NULL AND ended_by_user_id IS NOT NULL AND ended_by_user_id =
user_id AND ended_by_admin_id IS NULL) OR (status = 'revoked' AND ended_at IS NOT NULL AND
ended_by_user_id IS NULL AND ended_by_admin_id IS NOT NULL AND end_reason IS NOT NULL)),
        CONSTRAINT ck_resident_binding_details CHECK (row_version > 0 AND (end_reason IS NULL OR
(end_reason <> '' AND end_reason = btrim(end_reason))) AND (ended_at IS NULL OR ended_at >=
granted_at))
)
""")
    op.execute("""
CREATE INDEX ix_resident_binding_admin ON resident_house_bindings (property_company_id,
ended_by_admin_id)
""")
    op.execute("""
CREATE INDEX ix_resident_binding_company_time ON resident_house_bindings (property_company_id,
community_id, status, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_resident_binding_ender ON resident_house_bindings (ended_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_resident_binding_house_time ON resident_house_bindings (house_id, created_at,
id)
""")
    op.execute("""
CREATE INDEX ix_resident_binding_origin ON resident_house_bindings (property_company_id,
community_id, house_id, user_id, claim_application_id)
""")
    op.execute("""
CREATE INDEX ix_resident_binding_user_time ON resident_house_bindings (user_id, status,
created_at, id)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_resident_binding_active ON resident_house_bindings (user_id, house_id)
WHERE status = 'active'
""")
    op.execute("""
CREATE FUNCTION house_claim_freeze_facts() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    mutable text[];
    initial_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'house claim history is immutable' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_house_claim_immutable';
    END IF;
    IF TG_TABLE_NAME = 'house_claim_applications' THEN
        mutable := ARRAY['status','reviewed_by_admin_id','reviewed_at','review_reason',
                         'cancelled_at','row_version','updated_at'];
        initial_status := 'pending';
    ELSE
        mutable := ARRAY['status','ended_at','ended_by_user_id','ended_by_admin_id',
                         'end_reason','row_version','updated_at'];
        initial_status := 'active';
    END IF;
    IF OLD.status <> initial_status OR NEW.status = initial_status OR
       (to_jsonb(OLD) - mutable) IS DISTINCT FROM (to_jsonb(NEW) - mutable) OR
       NEW.row_version <> OLD.row_version + 1 THEN
        RAISE EXCEPTION 'invalid house claim transition' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_house_claim_immutable';
    END IF;
    RETURN NEW;
END $$
""")
    for table in ("house_claim_applications", "resident_house_bindings"):
        op.execute(
            f"CREATE TRIGGER house_claim_freeze_facts BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION house_claim_freeze_facts()"
        )


def downgrade() -> None:
    for table in ("resident_house_bindings", "house_claim_applications"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot downgrade while resident house data exists")
    op.drop_table("resident_house_bindings")
    op.drop_table("house_claim_applications")
    op.execute("DROP FUNCTION house_claim_freeze_facts()")
    op.drop_constraint("uq_house_owner_house_id", "house_owners")
