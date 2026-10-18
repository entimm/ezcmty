"""Add frozen payment aggregates, durable execution and shared online receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20261019_bill_payments"
down_revision = "20261017_house_claims"
branch_labels = None
depends_on = None

TABLES = (
    "payment_reconciliation_runs",
    "profit_sharing_rule_versions",
    "property_merchant_bindings",
    "payment_orders",
    "profit_sharing_rule_version_items",
    "payment_channel_notifications",
    "payment_unfreeze_orders",
    "profit_sharing_allocations",
    "profit_sharing_orders",
    "payment_channel_requests",
    "payment_tasks",
    "profit_sharing_order_items",
    "payment_order_items",
    "payment_reconciliation_discrepancies",
    "bill_payment_reservations",
)


def upgrade() -> None:
    op.execute("""
CREATE TABLE payment_reconciliation_runs (
    id UUID NOT NULL,
    business_date DATE NOT NULL,
    statement_type VARCHAR(32) NOT NULL,
    service_provider_merchant_no VARCHAR(64) NOT NULL,
    merchant_no VARCHAR(64),
    status VARCHAR(16) NOT NULL,
    statement_hash_type VARCHAR(32),
    statement_hash VARCHAR(256),
    summary JSONB NOT NULL,
    finished_at TIMESTAMP(6) WITH TIME ZONE,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_payment_reconciliation_scope UNIQUE NULLS NOT DISTINCT (business_date,
        statement_type, service_provider_merchant_no, merchant_no),
    CONSTRAINT ck_payment_reconciliation_scope CHECK ((statement_type IN
        ('trade','profit_sharing') AND merchant_no IS NOT NULL AND btrim(merchant_no) <> '') OR
        (statement_type = 'platform_fundflow' AND merchant_no IS NULL)),
    CONSTRAINT ck_payment_reconciliation_source CHECK (btrim(service_provider_merchant_no) <>
        '' AND ((statement_hash_type IS NULL AND statement_hash IS NULL) OR (statement_hash_type
        IS NOT NULL AND btrim(statement_hash_type) <> '' AND statement_hash IS NOT NULL AND
        btrim(statement_hash) <> ''))),
    CONSTRAINT ck_payment_reconciliation_status CHECK (status IN
        ('ready','running','completed','failed') AND (status <> 'completed' OR (statement_hash IS
        NOT NULL AND finished_at IS NOT NULL)) AND (status NOT IN ('ready','running') OR
        finished_at IS NULL) AND jsonb_typeof(summary) = 'object')
)
""")
    op.execute("""
CREATE INDEX ix_payment_reconciliation_date ON payment_reconciliation_runs (business_date,
    statement_type, id)
""")
    op.execute("""
CREATE TABLE profit_sharing_rule_versions (
    id UUID NOT NULL,
    property_company_id UUID NOT NULL,
    version_no BIGINT NOT NULL,
    calculation_version SMALLINT NOT NULL,
    created_by UUID NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint CHAR(64) NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_sharing_rule_company_version UNIQUE (property_company_id, version_no),
    CONSTRAINT uq_sharing_rule_company_id UNIQUE (property_company_id, id),
    CONSTRAINT uq_sharing_rule_key UNIQUE (property_company_id, idempotency_key),
    CONSTRAINT fk_sharing_rule_company FOREIGN KEY(property_company_id) REFERENCES
        property_companies (id),
    CONSTRAINT fk_sharing_rule_creator FOREIGN KEY(created_by) REFERENCES admin_accounts (id),
    CONSTRAINT ck_sharing_rule_version CHECK (version_no > 0 AND calculation_version = 1),
    CONSTRAINT ck_sharing_rule_identifiers CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{1,128}$'
        AND request_fingerprint ~ '^[0-9a-f]{64}$')
)
""")
    op.execute("""
CREATE INDEX ix_sharing_rule_creator ON profit_sharing_rule_versions (created_by)
""")
    op.execute("""
CREATE TABLE property_merchant_bindings (
    id UUID NOT NULL,
    property_company_id UUID NOT NULL,
    service_provider_merchant_no VARCHAR(64) NOT NULL,
    merchant_no VARCHAR(64) NOT NULL,
    merchant_name VARCHAR(256) NOT NULL,
    enabled BOOLEAN NOT NULL,
    max_ratio_bps INTEGER,
    ratio_checked_at TIMESTAMP(6) WITH TIME ZONE,
    created_by UUID NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint CHAR(64) NOT NULL,
    row_version BIGINT NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_merchant_binding_company_id UNIQUE (property_company_id, id),
    CONSTRAINT uq_merchant_binding_key UNIQUE (property_company_id, idempotency_key),
    CONSTRAINT fk_merchant_binding_company FOREIGN KEY(property_company_id) REFERENCES
        property_companies (id),
    CONSTRAINT fk_merchant_binding_creator FOREIGN KEY(created_by) REFERENCES admin_accounts (id),
    CONSTRAINT ck_merchant_binding_identity CHECK (btrim(service_provider_merchant_no) <> ''
        AND btrim(merchant_no) <> '' AND btrim(merchant_name) <> ''),
    CONSTRAINT ck_merchant_binding_ratio CHECK ((max_ratio_bps IS NULL AND ratio_checked_at IS
        NULL) OR (max_ratio_bps IS NOT NULL AND max_ratio_bps BETWEEN 0 AND 10000 AND
        ratio_checked_at IS NOT NULL)),
    CONSTRAINT ck_merchant_binding_identifiers CHECK (row_version > 0 AND idempotency_key ~
        '^[A-Za-z0-9_-]{1,128}$' AND request_fingerprint ~ '^[0-9a-f]{64}$')
)
""")
    op.execute("""
CREATE INDEX ix_merchant_binding_creator ON property_merchant_bindings (created_by)
""")
    op.execute("""
CREATE INDEX ix_merchant_binding_identity ON property_merchant_bindings
    (service_provider_merchant_no, merchant_no, created_at)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_merchant_binding_enabled ON property_merchant_bindings
    (property_company_id) WHERE enabled
""")
    op.execute("""
CREATE TABLE payment_orders (
    id UUID NOT NULL,
    property_company_id UUID NOT NULL,
    payer_user_id UUID NOT NULL,
    merchant_binding_id UUID NOT NULL,
    rule_version_id UUID NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    channel_transaction_no VARCHAR(64),
    amount_cents BIGINT NOT NULL,
    payer_total_cents BIGINT,
    status VARCHAR(32) NOT NULL,
    prepay_token VARCHAR(256),
    expires_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    paid_at TIMESTAMP(6) WITH TIME ZONE,
    closed_at TIMESTAMP(6) WITH TIME ZONE,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint CHAR(64) NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_payment_order_number UNIQUE (order_no),
    CONSTRAINT uq_payment_order_key UNIQUE (payer_user_id, idempotency_key),
    CONSTRAINT uq_payment_order_company_id UNIQUE (property_company_id, id),
    CONSTRAINT fk_payment_order_binding FOREIGN KEY(property_company_id, merchant_binding_id)
        REFERENCES property_merchant_bindings (property_company_id, id),
    CONSTRAINT fk_payment_order_rule FOREIGN KEY(property_company_id, rule_version_id)
        REFERENCES profit_sharing_rule_versions (property_company_id, id),
    CONSTRAINT fk_payment_order_payer FOREIGN KEY(payer_user_id) REFERENCES miniapp_users (id),
    CONSTRAINT ck_payment_order_amount CHECK (amount_cents BETWEEN 1 AND 9007199254740991 AND
        (payer_total_cents IS NULL OR payer_total_cents BETWEEN 0 AND 9007199254740991)),
    CONSTRAINT ck_payment_order_status CHECK (status IN
        ('pending','unknown','payable','closing','succeeded','closed')),
    CONSTRAINT ck_payment_order_confirmation CHECK ((status = 'succeeded' AND
        channel_transaction_no IS NOT NULL AND btrim(channel_transaction_no) <> '' AND paid_at IS
        NOT NULL AND closed_at IS NULL) OR (status = 'closed' AND closed_at IS NOT NULL AND
        paid_at IS NULL AND channel_transaction_no IS NULL) OR (status IN
        ('pending','unknown','payable','closing') AND paid_at IS NULL AND closed_at IS NULL AND
        channel_transaction_no IS NULL)),
    CONSTRAINT ck_payment_order_identifiers CHECK (btrim(order_no) <> '' AND idempotency_key ~
        '^[A-Za-z0-9_-]{1,128}$' AND request_fingerprint ~ '^[0-9a-f]{64}$' AND expires_at >
        created_at)
)
""")
    op.execute("""
CREATE INDEX ix_payment_order_binding ON payment_orders (property_company_id, merchant_binding_id)
""")
    op.execute("""
CREATE INDEX ix_payment_order_company_time ON payment_orders (property_company_id, created_at
    DESC, id DESC)
""")
    op.execute("""
CREATE INDEX ix_payment_order_expiry ON payment_orders (expires_at, id) WHERE status IN
    ('pending','unknown','payable','closing')
""")
    op.execute("""
CREATE INDEX ix_payment_order_payer_time ON payment_orders (payer_user_id, created_at DESC, id DESC)
""")
    op.execute("""
CREATE INDEX ix_payment_order_rule ON payment_orders (property_company_id, rule_version_id)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_payment_order_transaction ON payment_orders (channel_transaction_no)
    WHERE channel_transaction_no IS NOT NULL
""")
    op.execute("""
CREATE TABLE profit_sharing_rule_version_items (
    id UUID NOT NULL,
    rule_version_id UUID NOT NULL,
    receiver_type VARCHAR(32) NOT NULL,
    receiver_account VARCHAR(128) NOT NULL,
    receiver_name VARCHAR(256) NOT NULL,
    relation_type VARCHAR(32) NOT NULL,
    rate_bps INTEGER NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_sharing_rule_receiver UNIQUE (rule_version_id, receiver_type, receiver_account),
    CONSTRAINT fk_sharing_rule_item_version FOREIGN KEY(rule_version_id) REFERENCES
        profit_sharing_rule_versions (id),
    CONSTRAINT ck_sharing_rule_receiver CHECK (receiver_type = 'merchant' AND relation_type =
        'service_provider' AND btrim(receiver_account) <> '' AND btrim(receiver_name) <> ''),
    CONSTRAINT ck_sharing_rule_rate CHECK (rate_bps BETWEEN 0 AND 10000)
)
""")
    op.execute("""
CREATE TABLE payment_channel_notifications (
    id UUID NOT NULL,
    channel_notification_id VARCHAR(64) NOT NULL,
    notification_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    payment_order_id UUID,
    status VARCHAR(16) NOT NULL,
    processed_at TIMESTAMP(6) WITH TIME ZONE,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_payment_notification_number UNIQUE (channel_notification_id),
    CONSTRAINT fk_payment_notification_order FOREIGN KEY(payment_order_id) REFERENCES
        payment_orders (id),
    CONSTRAINT ck_payment_notification_identity CHECK (btrim(channel_notification_id) <> ''
        AND btrim(notification_type) <> ''),
    CONSTRAINT ck_payment_notification_status CHECK ((status = 'pending' AND processed_at IS
        NULL) OR (status IN ('processed','ignored','quarantined') AND processed_at IS NOT NULL)),
    CONSTRAINT ck_payment_notification_payload CHECK (jsonb_typeof(payload) = 'object')
)
""")
    op.execute("""
CREATE INDEX ix_payment_notification_order ON payment_channel_notifications (payment_order_id,
    created_at)
""")
    op.execute("""
CREATE TABLE payment_unfreeze_orders (
    id UUID NOT NULL,
    payment_order_id UUID NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    channel_order_no VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    unfrozen_cents BIGINT,
    channel_detail_no VARCHAR(64),
    fail_reason VARCHAR(1000),
    finished_at TIMESTAMP(6) WITH TIME ZONE,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_unfreeze_order_number UNIQUE (order_no),
    CONSTRAINT fk_unfreeze_order_payment FOREIGN KEY(payment_order_id) REFERENCES
        payment_orders (id),
    CONSTRAINT ck_unfreeze_order_number CHECK (order_no ~ '^uf_[A-Za-z0-9_-]+$'),
    CONSTRAINT ck_unfreeze_order_status CHECK (status IN
        ('pending','unknown','processing','succeeded','failed','no_remaining')),
    CONSTRAINT ck_unfreeze_order_amount CHECK (unfrozen_cents IS NULL OR unfrozen_cents
        BETWEEN 0 AND 9007199254740991),
    CONSTRAINT ck_unfreeze_order_finished CHECK ((status = 'succeeded' AND unfrozen_cents IS
        NOT NULL AND finished_at IS NOT NULL) OR (status IN ('failed','no_remaining') AND
        finished_at IS NOT NULL) OR (status IN ('pending','unknown','processing') AND finished_at
        IS NULL))
)
""")
    op.execute("""
CREATE INDEX ix_unfreeze_order_payment_time ON payment_unfreeze_orders (payment_order_id,
    created_at, id)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_unfreeze_order_inflight ON payment_unfreeze_orders (payment_order_id)
    WHERE status IN ('pending','unknown','processing')
""")
    op.execute("""
CREATE TABLE profit_sharing_allocations (
    id UUID NOT NULL,
    payment_order_id UUID NOT NULL,
    rule_version_item_id UUID NOT NULL,
    amount_cents BIGINT NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_sharing_allocation_receiver UNIQUE (payment_order_id, rule_version_item_id),
    CONSTRAINT uq_sharing_allocation_payment_id UNIQUE (payment_order_id, id),
    CONSTRAINT fk_sharing_allocation_payment FOREIGN KEY(payment_order_id) REFERENCES
        payment_orders (id),
    CONSTRAINT fk_sharing_allocation_rule_item FOREIGN KEY(rule_version_item_id) REFERENCES
        profit_sharing_rule_version_items (id),
    CONSTRAINT ck_sharing_allocation_amount CHECK (amount_cents BETWEEN 1 AND 9007199254740991)
)
""")
    op.execute("""
CREATE INDEX ix_sharing_allocation_rule_item ON profit_sharing_allocations (rule_version_item_id)
""")
    op.execute("""
CREATE TABLE profit_sharing_orders (
    id UUID NOT NULL,
    payment_order_id UUID NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    channel_order_no VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_sharing_order_number UNIQUE (order_no),
    CONSTRAINT uq_sharing_order_payment_id UNIQUE (payment_order_id, id),
    CONSTRAINT fk_sharing_order_payment FOREIGN KEY(payment_order_id) REFERENCES
        payment_orders (id),
    CONSTRAINT ck_sharing_order_number CHECK (order_no ~ '^ps_[A-Za-z0-9_-]+$'),
    CONSTRAINT ck_sharing_order_status CHECK (status IN
        ('pending','unknown','processing','finished','rejected'))
)
""")
    op.execute("""
CREATE INDEX ix_sharing_order_payment_time ON profit_sharing_orders (payment_order_id,
    created_at, id)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_sharing_order_inflight ON profit_sharing_orders (payment_order_id)
    WHERE status IN ('pending','unknown','processing')
""")
    op.execute("""
CREATE TABLE payment_channel_requests (
    id UUID NOT NULL,
    operation VARCHAR(64) NOT NULL,
    payment_order_id UUID,
    profit_sharing_order_id UUID,
    unfreeze_order_id UUID,
    merchant_binding_id UUID,
    reconciliation_run_id UUID,
    request_snapshot JSONB NOT NULL,
    outcome VARCHAR(32) NOT NULL,
    http_status SMALLINT,
    channel_request_id VARCHAR(128),
    response_snapshot JSONB,
    error_code VARCHAR(128),
    request_id VARCHAR(64) NOT NULL,
    finished_at TIMESTAMP(6) WITH TIME ZONE,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_payment_request_order FOREIGN KEY(payment_order_id) REFERENCES
        payment_orders (id),
    CONSTRAINT fk_payment_request_sharing FOREIGN KEY(profit_sharing_order_id) REFERENCES
        profit_sharing_orders (id),
    CONSTRAINT fk_payment_request_unfreeze FOREIGN KEY(unfreeze_order_id) REFERENCES
        payment_unfreeze_orders (id),
    CONSTRAINT fk_payment_request_binding FOREIGN KEY(merchant_binding_id) REFERENCES
        property_merchant_bindings (id),
    CONSTRAINT fk_payment_request_reconciliation FOREIGN KEY(reconciliation_run_id) REFERENCES
        payment_reconciliation_runs (id),
    CONSTRAINT ck_payment_request_target CHECK (num_nonnulls(payment_order_id,
        profit_sharing_order_id, unfreeze_order_id, merchant_binding_id, reconciliation_run_id) =
        1 AND ((operation IN ('payment_submit','payment_query','payment_close','remaining_amount')
        AND payment_order_id IS NOT NULL) OR (operation IN
        ('profit_sharing_submit','profit_sharing_query') AND profit_sharing_order_id IS NOT NULL)
        OR (operation IN ('unfreeze_submit','unfreeze_query') AND unfreeze_order_id IS NOT NULL)
        OR (operation IN ('receiver_add','receiver_delete','maximum_ratio') AND
        merchant_binding_id IS NOT NULL) OR (operation IN
        ('trade_statement','profit_sharing_statement','platform_fundflow_statement','statement_download')
        AND reconciliation_run_id IS NOT NULL))),
    CONSTRAINT ck_payment_request_outcome CHECK (outcome IN
        ('started','verified_response','transport_unknown','invalid_response') AND (outcome <>
        'started' OR finished_at IS NULL)),
    CONSTRAINT ck_payment_request_http_status CHECK (http_status IS NULL OR http_status
        BETWEEN 100 AND 599),
    CONSTRAINT ck_payment_request_snapshot CHECK (request_id ~ '^[A-Za-z0-9_-]{1,64}$' AND
        jsonb_typeof(request_snapshot) = 'object' AND (response_snapshot IS NULL OR
        jsonb_typeof(response_snapshot) = 'object'))
)
""")
    op.execute("""
CREATE INDEX ix_payment_request_merchant_binding_id ON payment_channel_requests
    (merchant_binding_id, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_payment_request_payment_order_id ON payment_channel_requests
    (payment_order_id, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_payment_request_profit_sharing_order_id ON payment_channel_requests
    (profit_sharing_order_id, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_payment_request_reconciliation_run_id ON payment_channel_requests
    (reconciliation_run_id, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_payment_request_unfreeze_order_id ON payment_channel_requests
    (unfreeze_order_id, created_at, id)
""")
    op.execute("""
CREATE TABLE payment_tasks (
    id UUID NOT NULL,
    task_type VARCHAR(32) NOT NULL,
    payment_order_id UUID,
    profit_sharing_order_id UUID,
    unfreeze_order_id UUID,
    notification_id UUID,
    reconciliation_run_id UUID,
    status VARCHAR(16) NOT NULL,
    next_run_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    attempt_count BIGINT NOT NULL,
    lease_expires_at TIMESTAMP(6) WITH TIME ZONE,
    last_error VARCHAR(1000),
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_payment_task_order FOREIGN KEY(payment_order_id) REFERENCES payment_orders (id),
    CONSTRAINT fk_payment_task_sharing FOREIGN KEY(profit_sharing_order_id) REFERENCES
        profit_sharing_orders (id),
    CONSTRAINT fk_payment_task_unfreeze FOREIGN KEY(unfreeze_order_id) REFERENCES
        payment_unfreeze_orders (id),
    CONSTRAINT fk_payment_task_notification FOREIGN KEY(notification_id) REFERENCES
        payment_channel_notifications (id),
    CONSTRAINT fk_payment_task_reconciliation FOREIGN KEY(reconciliation_run_id) REFERENCES
        payment_reconciliation_runs (id),
    CONSTRAINT ck_payment_task_target CHECK (num_nonnulls(payment_order_id,
        profit_sharing_order_id, unfreeze_order_id, notification_id, reconciliation_run_id) = 1
        AND ((task_type IN ('payment_submit','payment_query','payment_close') AND payment_order_id
        IS NOT NULL) OR (task_type IN ('profit_sharing_submit','profit_sharing_query') AND
        profit_sharing_order_id IS NOT NULL) OR (task_type IN ('unfreeze_submit','unfreeze_query')
        AND unfreeze_order_id IS NOT NULL) OR (task_type = 'notification_process' AND
        notification_id IS NOT NULL) OR (task_type = 'reconciliation' AND reconciliation_run_id IS
        NOT NULL))),
    CONSTRAINT ck_payment_task_lease CHECK (attempt_count >= 0 AND ((status = 'running' AND
        lease_expires_at IS NOT NULL) OR (status IN ('ready','completed','paused') AND
        lease_expires_at IS NULL)))
)
""")
    op.execute("""
CREATE INDEX ix_payment_task_lease ON payment_tasks (lease_expires_at, id) WHERE status = 'running'
""")
    op.execute("""
CREATE INDEX ix_payment_task_ready ON payment_tasks (next_run_at, id) WHERE status = 'ready'
""")
    op.execute("""
CREATE UNIQUE INDEX uq_payment_task_notification_id ON payment_tasks (task_type,
    notification_id) WHERE notification_id IS NOT NULL
""")
    op.execute("""
CREATE UNIQUE INDEX uq_payment_task_payment_order_id ON payment_tasks (task_type,
    payment_order_id) WHERE payment_order_id IS NOT NULL
""")
    op.execute("""
CREATE UNIQUE INDEX uq_payment_task_profit_sharing_order_id ON payment_tasks (task_type,
    profit_sharing_order_id) WHERE profit_sharing_order_id IS NOT NULL
""")
    op.execute("""
CREATE UNIQUE INDEX uq_payment_task_reconciliation_run_id ON payment_tasks (task_type,
    reconciliation_run_id) WHERE reconciliation_run_id IS NOT NULL
""")
    op.execute("""
CREATE UNIQUE INDEX uq_payment_task_unfreeze_order_id ON payment_tasks (task_type,
    unfreeze_order_id) WHERE unfreeze_order_id IS NOT NULL
""")
    op.execute("""
CREATE TABLE profit_sharing_order_items (
    id UUID NOT NULL,
    payment_order_id UUID NOT NULL,
    profit_sharing_order_id UUID NOT NULL,
    allocation_id UUID NOT NULL,
    amount_cents BIGINT NOT NULL,
    result VARCHAR(32),
    channel_detail_no VARCHAR(64),
    fail_reason VARCHAR(1000),
    finished_at TIMESTAMP(6) WITH TIME ZONE,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_sharing_order_allocation UNIQUE (profit_sharing_order_id, allocation_id),
    CONSTRAINT uq_sharing_order_item_payment_id UNIQUE (payment_order_id, id),
    CONSTRAINT fk_sharing_order_item_order FOREIGN KEY(payment_order_id,
        profit_sharing_order_id) REFERENCES profit_sharing_orders (payment_order_id, id),
    CONSTRAINT fk_sharing_order_item_allocation FOREIGN KEY(payment_order_id, allocation_id)
        REFERENCES profit_sharing_allocations (payment_order_id, id),
    CONSTRAINT ck_sharing_order_item_amount CHECK (amount_cents BETWEEN 1 AND 9007199254740991),
    CONSTRAINT ck_sharing_order_item_result CHECK (result IS NULL OR result IN
        ('success','failed')),
    CONSTRAINT ck_sharing_order_item_finished CHECK ((result IS NULL AND finished_at IS NULL)
        OR (result IS NOT NULL AND finished_at IS NOT NULL))
)
""")
    op.execute("""
CREATE INDEX ix_sharing_order_item_allocation ON profit_sharing_order_items (payment_order_id,
    allocation_id)
""")
    op.execute("""
CREATE INDEX ix_sharing_order_item_parent ON profit_sharing_order_items (payment_order_id,
    profit_sharing_order_id)
""")
    op.execute("""
CREATE TABLE payment_order_items (
    id UUID NOT NULL,
    property_company_id UUID NOT NULL,
    payment_order_id UUID NOT NULL,
    bill_id UUID NOT NULL,
    amount_cents BIGINT NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_payment_item_order_bill UNIQUE (payment_order_id, bill_id),
    CONSTRAINT uq_payment_item_bill_id UNIQUE (bill_id, id),
    CONSTRAINT fk_payment_item_order FOREIGN KEY(property_company_id, payment_order_id)
        REFERENCES payment_orders (property_company_id, id),
    CONSTRAINT fk_payment_item_bill FOREIGN KEY(property_company_id, bill_id) REFERENCES bills
        (property_company_id, id),
    CONSTRAINT ck_payment_item_amount CHECK (amount_cents BETWEEN 1 AND 9007199254740991)
)
""")
    op.execute("""
CREATE INDEX ix_payment_item_company_bill ON payment_order_items (property_company_id, bill_id)
""")
    op.execute("""
CREATE INDEX ix_payment_item_company_order ON payment_order_items (property_company_id,
    payment_order_id)
""")
    op.execute("""
CREATE TABLE payment_reconciliation_discrepancies (
    id UUID NOT NULL,
    reconciliation_run_id UUID NOT NULL,
    difference_type VARCHAR(32) NOT NULL,
    reference_key VARCHAR(256) NOT NULL,
    payment_order_id UUID,
    profit_sharing_order_item_id UUID,
    expected_cents BIGINT,
    actual_cents BIGINT,
    evidence JSONB NOT NULL,
    status VARCHAR(16) NOT NULL,
    resolved_at TIMESTAMP(6) WITH TIME ZONE,
    resolved_by UUID,
    resolution_note VARCHAR(1000),
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_payment_reconciliation_difference UNIQUE (reconciliation_run_id,
        difference_type, reference_key),
    CONSTRAINT fk_payment_difference_run FOREIGN KEY(reconciliation_run_id) REFERENCES
        payment_reconciliation_runs (id),
    CONSTRAINT fk_payment_difference_order FOREIGN KEY(payment_order_id) REFERENCES
        payment_orders (id),
    CONSTRAINT fk_payment_difference_sharing_item FOREIGN KEY(payment_order_id,
        profit_sharing_order_item_id) REFERENCES profit_sharing_order_items (payment_order_id,
        id),
    CONSTRAINT fk_payment_difference_resolver FOREIGN KEY(resolved_by) REFERENCES
        admin_accounts (id),
    CONSTRAINT ck_payment_difference_identity CHECK (difference_type IN
        ('channel_only','local_only','amount_mismatch','status_mismatch','unclassified') AND
        btrim(reference_key) <> ''),
    CONSTRAINT ck_payment_difference_association CHECK (profit_sharing_order_item_id IS NULL
        OR payment_order_id IS NOT NULL),
    CONSTRAINT ck_payment_difference_status CHECK (status IN ('open','observing','resolved')
        AND (status <> 'resolved' OR resolved_at IS NOT NULL) AND jsonb_typeof(evidence) =
        'object')
)
""")
    op.execute("""
CREATE INDEX ix_payment_difference_order ON payment_reconciliation_discrepancies
    (payment_order_id, id)
""")
    op.execute("""
CREATE INDEX ix_payment_difference_resolver ON payment_reconciliation_discrepancies (resolved_by)
""")
    op.execute("""
CREATE INDEX ix_payment_difference_run_status ON payment_reconciliation_discrepancies
    (reconciliation_run_id, status, id)
""")
    op.execute("""
CREATE INDEX ix_payment_difference_sharing_item ON payment_reconciliation_discrepancies
    (payment_order_id, profit_sharing_order_item_id)
""")
    op.execute("""
CREATE TABLE bill_payment_reservations (
    bill_id UUID NOT NULL,
    payment_order_id UUID NOT NULL,
    created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    PRIMARY KEY (bill_id),
    CONSTRAINT fk_payment_reservation_bill FOREIGN KEY(bill_id) REFERENCES bills (id),
    CONSTRAINT fk_payment_reservation_item FOREIGN KEY(payment_order_id, bill_id) REFERENCES
        payment_order_items (payment_order_id, bill_id)
)
""")
    op.execute("""
CREATE INDEX ix_payment_reservation_order ON bill_payment_reservations (payment_order_id)
""")
    op.add_column(
        "bill_operations",
        sa.Column("actor_type", sa.String(16), nullable=False, server_default="admin"),
    )
    op.alter_column("bill_operations", "actor_type", server_default=None)
    op.alter_column("bill_operations", "actor_id", nullable=True)
    op.alter_column("bill_operations", "response_status", nullable=True)
    op.drop_constraint("ck_bill_operation_action", "bill_operations")
    op.create_check_constraint(
        "ck_bill_operation_action",
        "bill_operations",
        "action IN "
        "('create','update','receipt','online_receipt','correct_receipt','reverse_rec"
        "eipt','void')",
    )
    op.create_check_constraint(
        "ck_bill_operation_actor",
        "bill_operations",
        "(actor_type = 'admin' AND actor_id IS NOT NULL AND response_status IS NOT "
        "NULL AND action <> 'online_receipt') OR (actor_type = 'system' AND actor_id "
        "IS NULL AND response_status IS NULL AND action = 'online_receipt')",
    )
    op.add_column(
        "bill_settlement_entries", sa.Column("payment_order_item_id", sa.UUID(), nullable=True)
    )
    op.drop_constraint("ck_bill_entry_source", "bill_settlement_entries")
    op.create_check_constraint(
        "ck_bill_entry_source",
        "bill_settlement_entries",
        "(source_type = 'offline' AND payment_order_item_id IS NULL) OR (source_type "
        "= 'online_payment' AND payment_order_item_id IS NOT NULL AND entry_type = "
        "'receipt' AND received_on IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_bill_entry_payment_item",
        "bill_settlement_entries",
        "payment_order_items",
        ["bill_id", "payment_order_item_id"],
        ["bill_id", "id"],
    )
    op.create_index(
        "uq_bill_entry_payment_item",
        "bill_settlement_entries",
        ["payment_order_item_id"],
        unique=True,
        postgresql_where=sa.text("payment_order_item_id IS NOT NULL"),
    )
    op.create_index(
        "ix_bill_entry_payment_item_fk",
        "bill_settlement_entries",
        ["bill_id", "payment_order_item_id"],
    )
    _install_guards()


def _install_guards() -> None:
    op.execute("""
CREATE FUNCTION payment_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'payment history is immutable' USING ERRCODE = '23514',
        CONSTRAINT = 'ck_payment_immutable';
END $$;
CREATE FUNCTION payment_guard_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    allowed text[] := string_to_array(TG_ARGV[0], ',');
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'payment history cannot be deleted' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_immutable';
    END IF;
    IF (to_jsonb(NEW) - allowed) IS DISTINCT FROM (to_jsonb(OLD) - allowed) THEN
        RAISE EXCEPTION 'payment identity is immutable' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_immutable';
    END IF;
    IF TG_TABLE_NAME = 'property_merchant_bindings' THEN
        IF (NEW.enabled IS DISTINCT FROM OLD.enabled AND
            NEW.row_version <> OLD.row_version + 1) OR
           (NEW.enabled IS NOT DISTINCT FROM OLD.enabled AND
            NEW.row_version <> OLD.row_version) THEN
            RAISE EXCEPTION 'invalid merchant configuration version' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_merchant_binding_version_change';
        END IF;
    ELSIF TG_TABLE_NAME IN ('payment_orders','profit_sharing_orders','payment_unfreeze_orders')
       AND (to_jsonb(OLD)->>'status') IN
           ('succeeded','closed','finished','rejected','no_remaining') THEN
        IF (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'confirmed payment result cannot regress' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_payment_terminal_result';
        END IF;
    ELSIF TG_TABLE_NAME = 'profit_sharing_order_items' AND (to_jsonb(OLD)->>'result') IS NOT
        NULL THEN
        IF (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
           (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'confirmed receiver result cannot regress' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_payment_terminal_result';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE FUNCTION payment_guard_configuration() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    parent_xid text;
    latest bigint;
BEGIN
    IF TG_TABLE_NAME = 'property_merchant_bindings' THEN
        PERFORM 1 FROM property_companies WHERE id = NEW.property_company_id FOR UPDATE;
        IF NEW.enabled THEN
            RAISE EXCEPTION 'new merchant binding must be disabled' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_merchant_binding_initial';
        END IF;
    ELSIF TG_TABLE_NAME = 'profit_sharing_rule_versions' THEN
        PERFORM 1 FROM property_companies WHERE id = NEW.property_company_id FOR UPDATE;
        SELECT COALESCE(MAX(version_no),0) INTO latest FROM profit_sharing_rule_versions
        WHERE property_company_id = NEW.property_company_id;
        IF NEW.version_no <> latest + 1 THEN
            RAISE EXCEPTION 'invalid next rule version' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_sharing_rule_next_version';
        END IF;
    ELSE
        SELECT xmin::text INTO parent_xid FROM profit_sharing_rule_versions
        WHERE id = NEW.rule_version_id;
        IF parent_xid IS NULL OR
           pg_xact_status(parent_xid::xid8) IS DISTINCT FROM 'in progress' THEN
            RAISE EXCEPTION 'committed rule cannot gain items' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_sharing_rule_complete';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE FUNCTION payment_check_rule() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target uuid;
    item_count bigint;
    ratio bigint;
BEGIN
    IF TG_TABLE_NAME = 'profit_sharing_rule_versions' THEN
        target := NEW.id;
    ELSE target := NEW.rule_version_id;
    END IF;
    SELECT COUNT(*), COALESCE(SUM(rate_bps),0) INTO item_count, ratio
    FROM profit_sharing_rule_version_items WHERE rule_version_id = target;
    IF item_count = 0 OR ratio > 10000 THEN
        RAISE EXCEPTION 'invalid complete sharing rule' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_sharing_rule_complete';
    END IF;
    RETURN NULL;
END $$;
""")
    for table in (
        "profit_sharing_rule_versions",
        "profit_sharing_rule_version_items",
        "payment_order_items",
        "profit_sharing_allocations",
    ):
        op.execute(
            f"CREATE TRIGGER payment_history_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION payment_history_immutable()"
        )
    for table, allowed in {
        "property_merchant_bindings": (
            "enabled,max_ratio_bps,ratio_checked_at,row_version,updated_at"
        ),
        "payment_orders": (
            "status,prepay_token,channel_transaction_no,payer_total_cents,paid_at,"
            "closed_at,updated_at"
        ),
        "profit_sharing_orders": "status,channel_order_no,updated_at",
        "profit_sharing_order_items": "result,channel_detail_no,fail_reason,finished_at,updated_at",
        "payment_unfreeze_orders": (
            "status,channel_order_no,unfrozen_cents,channel_detail_no,fail_reason,finished_at,updated_at"
        ),
        "payment_tasks": "status,next_run_at,attempt_count,lease_expires_at,last_error,updated_at",
        "payment_reconciliation_runs": (
            "status,statement_hash_type,statement_hash,summary,finished_at,updated_at"
        ),
        "payment_reconciliation_discrepancies": (
            "payment_order_id,profit_sharing_order_item_id,expected_cents,actual_cents,evidence,"
            "status,resolved_at,resolved_by,resolution_note,updated_at"
        ),
    }.items():
        op.execute(
            f"CREATE TRIGGER payment_guard_identity BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION payment_guard_identity('{allowed}')"
        )
    for table in (
        "property_merchant_bindings",
        "profit_sharing_rule_versions",
        "profit_sharing_rule_version_items",
    ):
        op.execute(
            f"CREATE TRIGGER payment_guard_configuration BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION payment_guard_configuration()"
        )
    for table in ("profit_sharing_rule_versions", "profit_sharing_rule_version_items"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER payment_check_rule AFTER INSERT ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "payment_check_rule()"
        )
    _install_accounting_guards()
    _install_funds_guards()
    _install_evidence_guards()


def _install_accounting_guards() -> None:
    op.execute("""
CREATE FUNCTION payment_guard_order_item() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    current_bill bills%ROWTYPE;
    parent_status text;
    parent_xid text;
BEGIN
    SELECT * INTO current_bill FROM bills WHERE id = NEW.bill_id FOR UPDATE;
    SELECT status, xmin::text INTO parent_status, parent_xid FROM payment_orders
    WHERE id = NEW.payment_order_id FOR UPDATE;
    IF parent_status IS NULL OR parent_status <> 'pending' OR
       pg_xact_status(parent_xid::xid8) IS DISTINCT FROM 'in progress' OR EXISTS (
           SELECT 1 FROM payment_order_items WHERE payment_order_id = NEW.payment_order_id
           AND pg_xact_status(xmin::text::xid8) IS DISTINCT FROM 'in progress') THEN
        RAISE EXCEPTION 'payment items are frozen with creation' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_item_frozen';
    END IF;
    IF current_bill.id IS NOT NULL AND (current_bill.lifecycle_status <> 'active' OR
       NEW.amount_cents <> current_bill.outstanding_cents OR EXISTS
       (SELECT 1 FROM bill_payment_reservations WHERE bill_id = NEW.bill_id)) THEN
        RAISE EXCEPTION 'payment must cover current unreserved balance' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_item_balance';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER payment_guard_order_item BEFORE INSERT ON payment_order_items
FOR EACH ROW EXECUTE FUNCTION payment_guard_order_item();
CREATE FUNCTION payment_guard_reservation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target uuid;
    current_payment payment_orders%ROWTYPE;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'reservation identity is immutable' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_reservation_identity';
    END IF;
    IF TG_OP = 'DELETE' THEN target := OLD.bill_id; ELSE target := NEW.bill_id; END IF;
    PERFORM 1 FROM bills WHERE id = target FOR UPDATE;
    IF TG_OP = 'DELETE' THEN
        SELECT * INTO current_payment FROM payment_orders
        WHERE id = OLD.payment_order_id FOR UPDATE;
        IF current_payment.status NOT IN ('succeeded','closed') THEN
            RAISE EXCEPTION 'unconfirmed payment reservation cannot be released'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_reservation_release';
        END IF;
        RETURN OLD;
    END IF;
    SELECT * INTO current_payment FROM payment_orders
    WHERE id = NEW.payment_order_id FOR UPDATE;
    IF current_payment.status IN ('succeeded','closed') THEN
        RAISE EXCEPTION 'terminal payment cannot reserve bills' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_reservation_active';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER payment_guard_reservation BEFORE INSERT OR UPDATE OR DELETE
ON bill_payment_reservations FOR EACH ROW EXECUTE FUNCTION payment_guard_reservation();
CREATE FUNCTION payment_guard_bill() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    reserved_status text;
BEGIN
    IF TG_TABLE_NAME = 'bill_operations' THEN
        PERFORM 1 FROM bills WHERE id = NEW.bill_id FOR UPDATE;
        IF NEW.action IN ('receipt','correct_receipt','reverse_receipt','void') AND EXISTS
           (SELECT 1 FROM bill_payment_reservations WHERE bill_id = NEW.bill_id) THEN
            RAISE EXCEPTION 'bill has an active payment' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_bill_payment_in_progress';
        END IF;
    ELSE
        SELECT payment.status INTO reserved_status FROM bill_payment_reservations reservation
        JOIN payment_orders payment ON payment.id = reservation.payment_order_id
        WHERE reservation.bill_id = OLD.id;
        IF reserved_status IS NOT NULL AND
           ((NEW.lifecycle_status IS DISTINCT FROM OLD.lifecycle_status) OR
            (NEW.settled_cents IS DISTINCT FROM OLD.settled_cents AND
             reserved_status <> 'succeeded')) THEN
            RAISE EXCEPTION 'bill has an active payment' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_bill_payment_in_progress';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER payment_guard_bill BEFORE UPDATE ON bills
FOR EACH ROW EXECUTE FUNCTION payment_guard_bill();
CREATE TRIGGER payment_guard_bill BEFORE INSERT ON bill_operations
FOR EACH ROW EXECUTE FUNCTION payment_guard_bill();
CREATE FUNCTION payment_guard_entry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    current_operation bill_operations%ROWTYPE;
    current_item payment_order_items%ROWTYPE;
    current_payment payment_orders%ROWTYPE;
    original_source text;
BEGIN
    PERFORM 1 FROM bills WHERE id = NEW.bill_id FOR UPDATE;
    SELECT * INTO current_operation FROM bill_operations WHERE id = NEW.operation_id;
    IF NEW.source_type = 'offline' THEN
        IF current_operation.actor_type IS DISTINCT FROM 'admin' OR EXISTS
           (SELECT 1 FROM bill_payment_reservations WHERE bill_id = NEW.bill_id) THEN
            RAISE EXCEPTION 'offline receipt conflicts with payment or actor'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_bill_payment_in_progress';
        END IF;
        IF NEW.entry_type = 'reversal' THEN
            SELECT source_type INTO original_source FROM bill_settlement_entries
            WHERE id = NEW.reverses_entry_id;
            IF original_source IS DISTINCT FROM 'offline' THEN
                RAISE EXCEPTION 'online receipt cannot be reversed offline'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_bill_online_reversal';
            END IF;
        END IF;
    ELSE
        SELECT * INTO current_item FROM payment_order_items
        WHERE id = NEW.payment_order_item_id;
        SELECT * INTO current_payment FROM payment_orders
        WHERE id = current_item.payment_order_id;
        IF current_operation.actor_type IS DISTINCT FROM 'system' OR
           current_operation.action IS DISTINCT FROM 'online_receipt' OR
           current_payment.status IS DISTINCT FROM 'succeeded' OR
           NEW.amount_cents IS DISTINCT FROM current_item.amount_cents OR
           NEW.received_on IS DISTINCT FROM
               (current_payment.paid_at AT TIME ZONE 'Asia/Shanghai')::date OR
           NOT EXISTS (SELECT 1 FROM bill_payment_reservations
                       WHERE bill_id = NEW.bill_id AND
                             payment_order_id = current_payment.id) THEN
            RAISE EXCEPTION 'online receipt does not match confirmed original payment'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_bill_online_receipt';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER payment_guard_entry BEFORE INSERT ON bill_settlement_entries
FOR EACH ROW EXECUTE FUNCTION payment_guard_entry();
CREATE FUNCTION payment_check_aggregate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target uuid;
    payment payment_orders%ROWTYPE;
    expected_total numeric;
BEGIN
    IF TG_TABLE_NAME = 'payment_orders' THEN target := NEW.id;
    ELSE target := NEW.payment_order_id;
    END IF;
    SELECT * INTO payment FROM payment_orders WHERE id = target;
    IF payment.id IS NULL THEN RETURN NULL; END IF;
    SELECT COALESCE(SUM(amount_cents),0) INTO expected_total
    FROM payment_order_items WHERE payment_order_id = target;
    IF expected_total <> payment.amount_cents THEN
        RAISE EXCEPTION 'payment amount does not equal item total' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_aggregate';
    END IF;
    IF payment.status NOT IN ('succeeded','closed') THEN
        IF EXISTS (SELECT 1 FROM payment_order_items item WHERE item.payment_order_id = target
                   AND NOT EXISTS (SELECT 1 FROM bill_payment_reservations reservation
                                   WHERE reservation.bill_id = item.bill_id AND
                                         reservation.payment_order_id = target)) OR
           NOT EXISTS (SELECT 1 FROM payment_tasks WHERE payment_order_id = target) THEN
            RAISE EXCEPTION 'active payment needs all reservations and recovery task'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_aggregate';
        END IF;
    ELSE
        IF EXISTS (SELECT 1 FROM bill_payment_reservations WHERE payment_order_id = target) THEN
            RAISE EXCEPTION 'terminal payment still holds reservations' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_payment_aggregate';
        END IF;
    END IF;
    IF payment.status = 'succeeded' THEN
        IF (SELECT COALESCE(SUM(amount_cents),0) FROM profit_sharing_allocations
            WHERE payment_order_id = target) > payment.amount_cents THEN
            RAISE EXCEPTION 'rounded allocation sum exceeds payment amount'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_aggregate';
        END IF;
        IF EXISTS (SELECT 1 FROM payment_order_items item WHERE item.payment_order_id = target
                   AND NOT EXISTS (SELECT 1 FROM bill_settlement_entries entry
                                   WHERE entry.payment_order_item_id = item.id AND
                                         entry.amount_cents = item.amount_cents)) OR
           EXISTS (SELECT 1 FROM profit_sharing_rule_version_items rule_item
                   WHERE rule_item.rule_version_id = payment.rule_version_id AND
                     round(payment.amount_cents::numeric * rule_item.rate_bps / 10000) > 0 AND
                     NOT EXISTS (SELECT 1 FROM profit_sharing_allocations allocation
                                 WHERE allocation.payment_order_id = target AND
                                       allocation.rule_version_item_id = rule_item.id AND
                                       allocation.amount_cents = round(
                                           payment.amount_cents::numeric * rule_item.rate_bps
                                               / 10000)))
        THEN
            RAISE EXCEPTION 'successful payment has incomplete posting or allocations'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_aggregate';
        END IF;
        IF EXISTS (SELECT 1 FROM profit_sharing_allocations WHERE payment_order_id = target) THEN
            IF NOT EXISTS (SELECT 1 FROM profit_sharing_orders sharing
                           JOIN payment_tasks task ON task.profit_sharing_order_id = sharing.id
                           WHERE sharing.payment_order_id = target) THEN
                RAISE EXCEPTION 'payment needs first sharing execution and recovery task'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_aggregate';
            END IF;
        ELSIF NOT EXISTS (SELECT 1 FROM payment_unfreeze_orders unfreeze
                         JOIN payment_tasks task ON task.unfreeze_order_id = unfreeze.id
                         WHERE unfreeze.payment_order_id = target) THEN
            RAISE EXCEPTION 'zero allocation payment needs unfreeze and task'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_aggregate';
        END IF;
    END IF;
    RETURN NULL;
END $$;
""")
    for table in ("payment_orders", "payment_order_items", "bill_payment_reservations"):
        event = "INSERT OR UPDATE" if table == "payment_orders" else "INSERT"
        op.execute(
            f"CREATE CONSTRAINT TRIGGER payment_check_aggregate AFTER {event} ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "payment_check_aggregate()"
        )


def _install_funds_guards() -> None:
    op.execute("""
CREATE FUNCTION payment_guard_allocation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    payment payment_orders%ROWTYPE;
    rule_item profit_sharing_rule_version_items%ROWTYPE;
BEGIN
    SELECT * INTO payment FROM payment_orders WHERE id = NEW.payment_order_id FOR UPDATE;
    SELECT * INTO rule_item FROM profit_sharing_rule_version_items
    WHERE id = NEW.rule_version_item_id;
    IF payment.status IS DISTINCT FROM 'succeeded' OR
       rule_item.rule_version_id IS DISTINCT FROM payment.rule_version_id OR
       NEW.amount_cents IS DISTINCT FROM
           round(payment.amount_cents::numeric * rule_item.rate_bps / 10000) THEN
        RAISE EXCEPTION 'allocation does not match frozen successful payment'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_sharing_allocation_fact';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER payment_guard_allocation BEFORE INSERT ON profit_sharing_allocations
FOR EACH ROW EXECUTE FUNCTION payment_guard_allocation();
CREATE FUNCTION payment_guard_funds() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    payment payment_orders%ROWTYPE;
    allocation_amount bigint;
    already_succeeded numeric;
    parent_xid text;
    parent_status text;
BEGIN
    SELECT * INTO payment FROM payment_orders WHERE id = NEW.payment_order_id FOR UPDATE;
    IF payment.status IS DISTINCT FROM 'succeeded' THEN
        RAISE EXCEPTION 'fund execution needs successful payment' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_funds_prerequisite';
    END IF;
    IF TG_TABLE_NAME = 'profit_sharing_order_items' THEN
        IF TG_OP = 'INSERT' THEN
            SELECT xmin::text, status INTO parent_xid, parent_status FROM profit_sharing_orders
            WHERE id = NEW.profit_sharing_order_id;
            IF parent_status IS NULL OR parent_status <> 'pending' OR
               pg_xact_status(parent_xid::xid8) IS DISTINCT FROM 'in progress' OR EXISTS (
                   SELECT 1 FROM profit_sharing_order_items
                   WHERE profit_sharing_order_id = NEW.profit_sharing_order_id
                   AND pg_xact_status(xmin::text::xid8) IS DISTINCT FROM 'in progress') THEN
                RAISE EXCEPTION 'sharing execution cannot gain items' USING ERRCODE = '23514',
                    CONSTRAINT = 'ck_sharing_execution_frozen';
            END IF;
        END IF;
        SELECT amount_cents INTO allocation_amount FROM profit_sharing_allocations
        WHERE id = NEW.allocation_id AND payment_order_id = NEW.payment_order_id;
        SELECT COALESCE(SUM(amount_cents),0) INTO already_succeeded
        FROM profit_sharing_order_items WHERE allocation_id = NEW.allocation_id AND
            result = 'success' AND id <> NEW.id;
        IF NEW.amount_cents + already_succeeded > allocation_amount THEN
            RAISE EXCEPTION 'sharing exceeds remaining allocation' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_sharing_fulfillment';
        END IF;
    ELSIF TG_TABLE_NAME = 'profit_sharing_orders' AND TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM payment_unfreeze_orders WHERE payment_order_id = payment.id) THEN
            RAISE EXCEPTION 'unfreeze permanently prohibits new sharing' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_payment_unfreeze_barrier';
        END IF;
    ELSIF TG_TABLE_NAME = 'payment_unfreeze_orders' AND TG_OP = 'INSERT' THEN
        IF EXISTS (SELECT 1 FROM profit_sharing_orders WHERE payment_order_id = payment.id
                   AND status IN ('pending','unknown','processing')) OR
           EXISTS (SELECT 1 FROM profit_sharing_allocations allocation
                   WHERE allocation.payment_order_id = payment.id AND
                     allocation.amount_cents <> COALESCE((
                         SELECT SUM(item.amount_cents) FROM profit_sharing_order_items item
                         WHERE item.allocation_id = allocation.id AND item.result =
                             'success'),0)) OR
           EXISTS (SELECT 1 FROM payment_unfreeze_orders WHERE payment_order_id = payment.id
                   AND status IN ('succeeded','no_remaining')) THEN
            RAISE EXCEPTION 'unfreeze needs complete fulfillment and no inflight sharing'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_unfreeze_prerequisite';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE FUNCTION payment_check_funds() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target uuid;
    parent_status text;
    payment_target uuid;
BEGIN
    IF TG_TABLE_NAME = 'profit_sharing_orders' THEN target := NEW.id;
    ELSIF TG_TABLE_NAME = 'profit_sharing_order_items' THEN target := NEW.profit_sharing_order_id;
    ELSE
        IF NOT EXISTS (SELECT 1 FROM payment_tasks WHERE unfreeze_order_id = NEW.id) THEN
            RAISE EXCEPTION 'unfreeze needs durable recovery task' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_payment_funds_aggregate';
        END IF;
        RETURN NULL;
    END IF;
    SELECT status, payment_order_id INTO parent_status, payment_target
    FROM profit_sharing_orders WHERE id = target;
    IF NOT EXISTS (SELECT 1 FROM profit_sharing_order_items
                   WHERE profit_sharing_order_id = target) OR
       NOT EXISTS (SELECT 1 FROM payment_tasks WHERE profit_sharing_order_id = target) OR
       (parent_status = 'finished' AND EXISTS
         (SELECT 1 FROM profit_sharing_order_items
          WHERE profit_sharing_order_id = target AND result IS NULL)) OR
       (parent_status = 'rejected' AND EXISTS
         (SELECT 1 FROM profit_sharing_order_items
          WHERE profit_sharing_order_id = target AND result IS NOT NULL)) OR
       EXISTS (SELECT 1 FROM profit_sharing_allocations allocation
               WHERE allocation.payment_order_id = payment_target AND
                 allocation.amount_cents < COALESCE((
                     SELECT SUM(item.amount_cents) FROM profit_sharing_order_items item
                     WHERE item.allocation_id = allocation.id AND item.result = 'success'),0))
    THEN
        RAISE EXCEPTION 'incomplete or overfulfilled sharing aggregate' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_funds_aggregate';
    END IF;
    RETURN NULL;
END $$;
""")
    for table in ("profit_sharing_orders", "profit_sharing_order_items", "payment_unfreeze_orders"):
        op.execute(
            f"CREATE TRIGGER payment_guard_funds BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION payment_guard_funds()"
        )
        op.execute(
            f"CREATE CONSTRAINT TRIGGER payment_check_funds AFTER INSERT OR UPDATE ON "
            f"{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "payment_check_funds()"
        )


def _install_evidence_guards() -> None:
    op.execute("""
CREATE FUNCTION payment_guard_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    identity_fields text[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'channel evidence cannot be deleted' USING ERRCODE = '23514',
            CONSTRAINT = 'ck_payment_evidence_immutable';
    END IF;
    IF TG_TABLE_NAME = 'payment_channel_notifications' THEN
        identity_fields := ARRAY['payment_order_id','status','processed_at','updated_at'];
        IF (OLD.payment_order_id IS NOT NULL AND
            NEW.payment_order_id IS DISTINCT FROM OLD.payment_order_id) OR
           (OLD.status IN ('processed','ignored') AND
            (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at')) THEN
            RAISE EXCEPTION 'notification association or result cannot change'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_evidence_immutable';
        END IF;
    ELSE
        identity_fields := ARRAY['outcome','http_status','channel_request_id',
                                 'response_snapshot','error_code','finished_at'];
        IF OLD.finished_at IS NOT NULL AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
            RAISE EXCEPTION 'finished channel attempt is immutable' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_payment_evidence_immutable';
        END IF;
        IF OLD.outcome = 'verified_response' AND (
           NEW.outcome <> OLD.outcome OR NEW.http_status IS DISTINCT FROM OLD.http_status OR
           NEW.channel_request_id IS DISTINCT FROM OLD.channel_request_id OR
           NEW.error_code IS DISTINCT FROM OLD.error_code OR
           NEW.response_snapshot IS NULL OR NOT NEW.response_snapshot @> OLD.response_snapshot) THEN
            RAISE EXCEPTION 'verified channel source is immutable' USING ERRCODE = '23514',
                CONSTRAINT = 'ck_payment_evidence_immutable';
        END IF;
    END IF;
    IF (to_jsonb(NEW) - identity_fields) IS DISTINCT FROM
       (to_jsonb(OLD) - identity_fields) THEN
        RAISE EXCEPTION 'channel identity and original parameters are immutable'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_payment_evidence_immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER payment_guard_evidence BEFORE UPDATE OR DELETE ON payment_channel_requests
FOR EACH ROW EXECUTE FUNCTION payment_guard_evidence();
CREATE TRIGGER payment_guard_evidence BEFORE UPDATE OR DELETE ON payment_channel_notifications
FOR EACH ROW EXECUTE FUNCTION payment_guard_evidence();
""")


def downgrade() -> None:
    connection = op.get_bind()
    for table in TABLES:
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot downgrade while payment data exists")
    op.execute("DROP TRIGGER payment_guard_bill ON bills")
    op.execute("DROP TRIGGER payment_guard_bill ON bill_operations")
    op.execute("DROP TRIGGER payment_guard_entry ON bill_settlement_entries")
    op.drop_index("ix_bill_entry_payment_item_fk", "bill_settlement_entries")
    op.drop_index("uq_bill_entry_payment_item", "bill_settlement_entries")
    op.drop_constraint("fk_bill_entry_payment_item", "bill_settlement_entries")
    op.drop_constraint("ck_bill_entry_source", "bill_settlement_entries")
    op.drop_column("bill_settlement_entries", "payment_order_item_id")
    op.create_check_constraint(
        "ck_bill_entry_source", "bill_settlement_entries", "source_type = 'offline'"
    )
    op.drop_constraint("ck_bill_operation_actor", "bill_operations")
    op.drop_constraint("ck_bill_operation_action", "bill_operations")
    op.create_check_constraint(
        "ck_bill_operation_action",
        "bill_operations",
        "action IN ('create','update','receipt','correct_receipt','reverse_receipt','void')",
    )
    op.drop_column("bill_operations", "actor_type")
    op.alter_column("bill_operations", "actor_id", nullable=False)
    op.alter_column("bill_operations", "response_status", nullable=False)
    for table in reversed(TABLES):
        op.drop_table(table)
    for function in (
        "payment_guard_evidence",
        "payment_check_funds",
        "payment_guard_funds",
        "payment_guard_allocation",
        "payment_check_aggregate",
        "payment_guard_entry",
        "payment_guard_bill",
        "payment_guard_reservation",
        "payment_guard_order_item",
        "payment_check_rule",
        "payment_guard_configuration",
        "payment_guard_identity",
        "payment_history_immutable",
    ):
        op.execute(f"DROP FUNCTION {function}()")
