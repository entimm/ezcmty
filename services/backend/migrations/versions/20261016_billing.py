"""Add immutable fee bases, bills, settlements and idempotent operations."""

import sqlalchemy as sa
from alembic import op

revision = "20261016_billing"
down_revision = "20261015_property_housing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_community_company_id", "communities", ["property_company_id", "id"]
    )
    op.create_unique_constraint("uq_house_community_id", "houses", ["community_id", "id"])
    op.execute(
        """
CREATE TABLE property_fee_basis_versions (
    id UUID NOT NULL,
    house_id UUID NOT NULL,
    version_no BIGINT NOT NULL,
    effective_from_month DATE NOT NULL,
    house_usage VARCHAR(32) NOT NULL,
    area_sqm NUMERIC(12, 4),
    unit_price_cents BIGINT,
    fixed_amount_cents BIGINT,
    change_reason VARCHAR(1000) NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_fee_basis_house_version UNIQUE (house_id, version_no),
    CONSTRAINT uq_fee_basis_house_id UNIQUE (house_id, id),
    CONSTRAINT fk_fee_basis_house FOREIGN KEY(house_id) REFERENCES houses (id),
    CONSTRAINT fk_fee_basis_creator FOREIGN KEY(created_by) REFERENCES admin_accounts (id),
    CONSTRAINT ck_fee_basis_version CHECK (version_no > 0),
    CONSTRAINT ck_fee_basis_month CHECK (EXTRACT(DAY FROM effective_from_month) = 1),
    CONSTRAINT ck_fee_basis_usage CHECK (house_usage IN
        ('residential','commercial','office','other')),
    CONSTRAINT ck_fee_basis_area CHECK (area_sqm IS NULL OR area_sqm > 0),
    CONSTRAINT ck_fee_basis_rate CHECK (unit_price_cents IS NULL OR unit_price_cents BETWEEN 0
        AND 9007199254740991),
    CONSTRAINT ck_fee_basis_fixed CHECK (fixed_amount_cents IS NULL OR fixed_amount_cents
        BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_fee_basis_inputs CHECK (fixed_amount_cents IS NOT NULL OR (area_sqm IS NOT
        NULL AND unit_price_cents IS NOT NULL)),
    CONSTRAINT ck_fee_basis_calculated_range CHECK (fixed_amount_cents IS NOT NULL OR
        round(area_sqm * unit_price_cents) <= 9007199254740991),
    CONSTRAINT ck_fee_basis_reason CHECK (btrim(change_reason) <> '')
)
        """
    )
    op.execute("CREATE INDEX ix_fee_basis_creator ON property_fee_basis_versions (created_by)")
    op.execute(
        "CREATE INDEX ix_fee_basis_effective ON property_fee_basis_versions (house_id, "
        "effective_from_month DESC, version_no DESC)"
    )
    op.execute(
        """
CREATE TABLE bills (
    id UUID NOT NULL,
    property_company_id UUID NOT NULL,
    community_id UUID NOT NULL,
    house_id UUID NOT NULL,
    bill_type VARCHAR(32) NOT NULL,
    period_granularity VARCHAR(16) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    external_bill_no VARCHAR(128),
    basis_version_id UUID,
    amount_source VARCHAR(16) NOT NULL,
    calculation_rule_version SMALLINT,
    receivable_cents BIGINT NOT NULL,
    settled_cents BIGINT NOT NULL,
    outstanding_cents BIGINT GENERATED ALWAYS AS (CASE WHEN lifecycle_status = 'voided' THEN 0
        ELSE receivable_cents - settled_cents END) STORED NOT NULL,
    lifecycle_status VARCHAR(16) NOT NULL,
    settlement_status VARCHAR(32) GENERATED ALWAYS AS (CASE WHEN lifecycle_status = 'voided'
        THEN NULL WHEN settled_cents = receivable_cents THEN 'settled' WHEN settled_cents = 0
        THEN 'unpaid' ELSE 'partially_settled' END) STORED,
    due_date DATE,
    house_label_snapshot VARCHAR(512) NOT NULL,
    manual_amount_reason VARCHAR(1000),
    void_reason VARCHAR(1000),
    voided_at TIMESTAMP(6) WITH TIME ZONE,
    voided_by UUID,
    row_version BIGINT NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_bill_company_id UNIQUE (property_company_id, id),
    CONSTRAINT fk_bill_community FOREIGN KEY(property_company_id, community_id) REFERENCES
        communities (property_company_id, id),
    CONSTRAINT fk_bill_house FOREIGN KEY(community_id, house_id) REFERENCES houses
        (community_id, id),
    CONSTRAINT fk_bill_basis FOREIGN KEY(house_id, basis_version_id) REFERENCES
        property_fee_basis_versions (house_id, id),
    CONSTRAINT fk_bill_creator FOREIGN KEY(created_by) REFERENCES admin_accounts (id),
    CONSTRAINT fk_bill_void_actor FOREIGN KEY(voided_by) REFERENCES admin_accounts (id),
    CONSTRAINT ck_bill_type_period CHECK (bill_type = 'property_fee' AND period_granularity =
        'month'),
    CONSTRAINT ck_bill_month CHECK (EXTRACT(DAY FROM period_start) = 1 AND period_end =
        (period_start + INTERVAL '1 month')::date),
    CONSTRAINT ck_bill_amounts CHECK (receivable_cents BETWEEN 0 AND 9007199254740991 AND
        settled_cents BETWEEN 0 AND receivable_cents),
    CONSTRAINT ck_bill_source CHECK ((amount_source = 'basis' AND basis_version_id IS NOT NULL
        AND calculation_rule_version IS NOT NULL AND calculation_rule_version = 1 AND
        manual_amount_reason IS NULL) OR (amount_source = 'manual' AND calculation_rule_version
        IS NULL AND manual_amount_reason IS NOT NULL AND btrim(manual_amount_reason) <> '')),
    CONSTRAINT ck_bill_lifecycle CHECK ((lifecycle_status = 'active' AND void_reason IS NULL AND
        voided_at IS NULL AND voided_by IS NULL) OR (lifecycle_status = 'voided' AND
        settled_cents = 0 AND void_reason IS NOT NULL AND btrim(void_reason) <> '' AND voided_at
        IS NOT NULL AND voided_by IS NOT NULL)),
    CONSTRAINT ck_bill_snapshot_version CHECK (house_label_snapshot <> '' AND row_version > 0),
    CONSTRAINT ck_bill_external CHECK (external_bill_no IS NULL OR (external_bill_no <> '' AND
        external_bill_no = btrim(external_bill_no)))
)
        """
    )
    op.execute("CREATE INDEX ix_bill_basis_fk ON bills (house_id, basis_version_id)")
    op.execute(
        "CREATE INDEX ix_bill_community_period ON bills (property_company_id, "
        "community_id, period_start DESC, id DESC)"
    )
    op.execute("CREATE INDEX ix_bill_creator ON bills (created_by)")
    op.execute(
        "CREATE INDEX ix_bill_due ON bills (property_company_id, due_date, id) WHERE "
        "lifecycle_status = 'active' AND outstanding_cents > 0 AND due_date IS NOT "
        "NULL"
    )
    op.execute(
        "CREATE INDEX ix_bill_external ON bills (property_company_id, "
        "external_bill_no) WHERE external_bill_no IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_bill_house_fk ON bills (community_id, house_id)")
    op.execute("CREATE INDEX ix_bill_house_period ON bills (house_id, period_start DESC, id DESC)")
    op.execute(
        "CREATE INDEX ix_bill_pending ON bills (property_company_id, community_id, "
        "period_start DESC, id DESC) WHERE lifecycle_status = 'active' AND "
        "outstanding_cents > 0"
    )
    op.execute("CREATE INDEX ix_bill_void_actor ON bills (voided_by)")
    op.execute(
        "CREATE UNIQUE INDEX uq_bills_active_house_month ON bills (house_id, "
        "bill_type, period_start) WHERE lifecycle_status = 'active' AND "
        "period_granularity = 'month'"
    )
    op.execute(
        """
CREATE TABLE bill_operations (
    id UUID NOT NULL,
    property_company_id UUID NOT NULL,
    bill_id UUID NOT NULL,
    bill_version BIGINT NOT NULL,
    action VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint CHAR(64) NOT NULL,
    result JSONB NOT NULL,
    response_status SMALLINT NOT NULL,
    reason VARCHAR(1000),
    actor_id UUID NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_bill_operation_key UNIQUE (property_company_id, idempotency_key),
    CONSTRAINT uq_bill_operation_version UNIQUE (bill_id, bill_version),
    CONSTRAINT uq_bill_operation_bill_id UNIQUE (bill_id, id),
    CONSTRAINT fk_bill_operation_bill FOREIGN KEY(property_company_id, bill_id) REFERENCES bills
        (property_company_id, id),
    CONSTRAINT fk_bill_operation_actor FOREIGN KEY(property_company_id, actor_id) REFERENCES
        admin_accounts (property_company_id, id),
    CONSTRAINT ck_bill_operation_action CHECK (action IN
        ('create','update','receipt','correct_receipt','reverse_receipt','void')),
    CONSTRAINT ck_bill_operation_reason CHECK (action NOT IN
        ('correct_receipt','reverse_receipt','void') OR (reason IS NOT NULL AND btrim(reason) <>
        '')),
    CONSTRAINT ck_bill_operation_identifiers CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$'
        AND request_fingerprint ~ '^[0-9a-f]{64}$' AND bill_version > 0)
)
        """
    )
    op.execute(
        "CREATE INDEX ix_bill_operation_actor ON bill_operations (property_company_id, actor_id)"
    )
    op.execute(
        """
CREATE TABLE bill_settlement_entries (
    id UUID NOT NULL,
    bill_id UUID NOT NULL,
    operation_id UUID NOT NULL,
    entry_type VARCHAR(16) NOT NULL,
    source_type VARCHAR(16) NOT NULL,
    amount_cents BIGINT NOT NULL,
    reverses_entry_id UUID,
    received_on DATE,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_bill_entry_bill_id UNIQUE (bill_id, id),
    CONSTRAINT fk_bill_entry_bill FOREIGN KEY(bill_id) REFERENCES bills (id),
    CONSTRAINT fk_bill_entry_operation FOREIGN KEY(bill_id, operation_id) REFERENCES
        bill_operations (bill_id, id),
    CONSTRAINT fk_bill_entry_original FOREIGN KEY(bill_id, reverses_entry_id) REFERENCES
        bill_settlement_entries (bill_id, id),
    CONSTRAINT ck_bill_entry_source CHECK (source_type = 'offline'),
    CONSTRAINT ck_bill_entry_range CHECK (amount_cents BETWEEN -9007199254740991 AND
        9007199254740991),
    CONSTRAINT ck_bill_entry_type CHECK ((entry_type = 'receipt' AND amount_cents > 0 AND
        reverses_entry_id IS NULL) OR (entry_type = 'reversal' AND amount_cents < 0 AND
        reverses_entry_id IS NOT NULL AND received_on IS NULL))
)
        """
    )
    op.execute(
        "CREATE INDEX ix_bill_entry_operation ON bill_settlement_entries (bill_id, operation_id)"
    )
    op.execute(
        "CREATE INDEX ix_bill_entry_time ON bill_settlement_entries (bill_id, "
        "created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_bill_entry_reversed ON bill_settlement_entries "
        "(reverses_entry_id) WHERE reverses_entry_id IS NOT NULL"
    )
    op.execute("""
CREATE FUNCTION billing_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'billing history is immutable' USING ERRCODE = '23514', CONSTRAINT =
        'ck_billing_immutable';
END $$
""")
    for table in ("property_fee_basis_versions", "bill_operations", "bill_settlement_entries"):
        op.execute(
            f"CREATE TRIGGER billing_immutable BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION billing_immutable()"
        )
    op.execute("""
CREATE FUNCTION billing_freeze_bill() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    mutable_columns CONSTANT text[] := ARRAY[
        'settled_cents', 'outstanding_cents', 'settlement_status', 'lifecycle_status',
        'void_reason', 'voided_at', 'voided_by', 'external_bill_no', 'due_date',
        'row_version', 'updated_at'
    ];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'bills cannot be deleted' USING ERRCODE = '23514', CONSTRAINT =
            'ck_billing_immutable';
    END IF;
    IF OLD.lifecycle_status = 'voided' OR
       (to_jsonb(NEW) - mutable_columns)
       IS DISTINCT FROM
       (to_jsonb(OLD) - mutable_columns) OR
       NEW.row_version <> OLD.row_version + 1 THEN
        RAISE EXCEPTION 'bill facts are immutable' USING ERRCODE = '23514', CONSTRAINT =
            'ck_billing_immutable';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute(
        "CREATE TRIGGER billing_freeze_bill BEFORE UPDATE OR DELETE ON bills FOR EACH "
        "ROW EXECUTE FUNCTION billing_freeze_bill()"
    )
    op.execute("""
CREATE FUNCTION billing_validate_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    original bill_settlement_entries%ROWTYPE;
    bill_status text;
BEGIN
    SELECT lifecycle_status INTO bill_status FROM bills WHERE id = NEW.bill_id FOR UPDATE;
    IF bill_status IS DISTINCT FROM 'active' THEN
        RAISE EXCEPTION 'bill is not active' USING ERRCODE = '23514', CONSTRAINT =
            'ck_bill_entry_active';
    END IF;
    IF NEW.entry_type = 'reversal' THEN
        SELECT * INTO original FROM bill_settlement_entries
        WHERE id = NEW.reverses_entry_id AND bill_id = NEW.bill_id;
        IF NOT FOUND OR original.entry_type <> 'receipt' OR NEW.amount_cents <>
           -original.amount_cents THEN
            RAISE EXCEPTION 'invalid reversal' USING ERRCODE = '23514', CONSTRAINT =
                'ck_bill_entry_reversal';
        END IF;
    END IF;
    RETURN NEW;
END $$
""")
    op.execute(
        "CREATE TRIGGER billing_validate_entry BEFORE INSERT ON "
        "bill_settlement_entries FOR EACH ROW EXECUTE FUNCTION "
        "billing_validate_entry()"
    )
    op.execute("""
CREATE FUNCTION billing_check_totals() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target uuid;
    current_bill bills%ROWTYPE;
    total numeric;
    latest bigint;
BEGIN
    IF TG_TABLE_NAME = 'bills' THEN target := NEW.id; ELSE target := NEW.bill_id; END IF;
    SELECT * INTO current_bill FROM bills WHERE id = target;
    SELECT COALESCE(SUM(amount_cents),0) INTO total FROM bill_settlement_entries
    WHERE bill_id = target;
    SELECT MAX(bill_version) INTO latest FROM bill_operations WHERE bill_id = target;
    IF current_bill.settled_cents IS DISTINCT FROM total OR
       current_bill.row_version IS DISTINCT FROM latest THEN
        RAISE EXCEPTION 'bill totals or operation version do not reconcile' USING ERRCODE =
            '23514', CONSTRAINT = 'ck_bill_reconciled';
    END IF;
    RETURN NULL;
END $$
""")
    op.execute(
        "CREATE CONSTRAINT TRIGGER billing_check_totals AFTER INSERT OR UPDATE ON "
        "bills DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
        "billing_check_totals()"
    )
    for table in ("bill_settlement_entries", "bill_operations"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER billing_check_totals AFTER INSERT ON "
            f"{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            f"billing_check_totals()"
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("bills", "property_fee_basis_versions"):
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot downgrade while billing data exists")
    for table in (
        "bill_settlement_entries",
        "bill_operations",
        "bills",
        "property_fee_basis_versions",
    ):
        op.drop_table(table)
    for function in (
        "billing_check_totals",
        "billing_validate_entry",
        "billing_freeze_bill",
        "billing_immutable",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_constraint("uq_house_community_id", "houses")
    op.drop_constraint("uq_community_company_id", "communities")
