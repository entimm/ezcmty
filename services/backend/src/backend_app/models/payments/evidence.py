from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend_app.core.identifiers import new_id
from backend_app.db.base import Base
from backend_app.db.types import UTC_TIMESTAMP
from backend_app.models.admin import utc_now


class PaymentChannelNotification(Base):
    __tablename__ = "payment_channel_notifications"
    __table_args__ = (
        UniqueConstraint("channel_notification_id", name="uq_payment_notification_number"),
        ForeignKeyConstraint(
            ["payment_order_id"], ["payment_orders.id"], name="fk_payment_notification_order"
        ),
        CheckConstraint(
            "btrim(channel_notification_id) <> '' AND btrim(notification_type) <> ''",
            name="ck_payment_notification_identity",
        ),
        CheckConstraint(
            "(status = 'pending' AND processed_at IS NULL) OR (status IN "
            "('processed','ignored','quarantined') AND processed_at IS NOT NULL)",
            name="ck_payment_notification_status",
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_payment_notification_payload"),
        Index("ix_payment_notification_order", "payment_order_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    channel_notification_id: Mapped[str] = mapped_column(String(64), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payment_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    processed_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class PaymentTask(Base):
    __tablename__ = "payment_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payment_order_id"], ["payment_orders.id"], name="fk_payment_task_order"
        ),
        ForeignKeyConstraint(
            ["profit_sharing_order_id"],
            ["profit_sharing_orders.id"],
            name="fk_payment_task_sharing",
        ),
        ForeignKeyConstraint(
            ["unfreeze_order_id"], ["payment_unfreeze_orders.id"], name="fk_payment_task_unfreeze"
        ),
        ForeignKeyConstraint(
            ["notification_id"],
            ["payment_channel_notifications.id"],
            name="fk_payment_task_notification",
        ),
        ForeignKeyConstraint(
            ["reconciliation_run_id"],
            ["payment_reconciliation_runs.id"],
            name="fk_payment_task_reconciliation",
        ),
        CheckConstraint(
            "num_nonnulls(payment_order_id, profit_sharing_order_id, unfreeze_order_id, "
            "notification_id, reconciliation_run_id) = 1 AND ((task_type IN "
            "('payment_submit','payment_query','payment_close') AND payment_order_id IS "
            "NOT NULL) OR (task_type IN ('profit_sharing_submit','profit_sharing_query') "
            "AND profit_sharing_order_id IS NOT NULL) OR (task_type IN "
            "('unfreeze_submit','unfreeze_query') AND unfreeze_order_id IS NOT NULL) OR "
            "(task_type = 'notification_process' AND notification_id IS NOT NULL) OR "
            "(task_type = 'reconciliation' AND reconciliation_run_id IS NOT NULL))",
            name="ck_payment_task_target",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND ((status = 'running' AND lease_expires_at IS NOT NULL) "
            "OR (status IN ('ready','completed','paused') AND lease_expires_at IS NULL))",
            name="ck_payment_task_lease",
        ),
        Index(
            "ix_payment_task_ready", "next_run_at", "id", postgresql_where=text("status = 'ready'")
        ),
        Index(
            "ix_payment_task_lease",
            "lease_expires_at",
            "id",
            postgresql_where=text("status = 'running'"),
        ),
        *(
            Index(
                f"uq_payment_task_{target}",
                "task_type",
                target,
                unique=True,
                postgresql_where=text(f"{target} IS NOT NULL"),
            )
            for target in (
                "payment_order_id",
                "profit_sharing_order_id",
                "unfreeze_order_id",
                "notification_id",
                "reconciliation_run_id",
            )
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    profit_sharing_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    unfreeze_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    notification_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    reconciliation_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    next_run_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    attempt_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)


class PaymentChannelRequest(Base):
    __tablename__ = "payment_channel_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payment_order_id"], ["payment_orders.id"], name="fk_payment_request_order"
        ),
        ForeignKeyConstraint(
            ["profit_sharing_order_id"],
            ["profit_sharing_orders.id"],
            name="fk_payment_request_sharing",
        ),
        ForeignKeyConstraint(
            ["unfreeze_order_id"],
            ["payment_unfreeze_orders.id"],
            name="fk_payment_request_unfreeze",
        ),
        ForeignKeyConstraint(
            ["merchant_binding_id"],
            ["property_merchant_bindings.id"],
            name="fk_payment_request_binding",
        ),
        ForeignKeyConstraint(
            ["reconciliation_run_id"],
            ["payment_reconciliation_runs.id"],
            name="fk_payment_request_reconciliation",
        ),
        CheckConstraint(
            "num_nonnulls(payment_order_id, profit_sharing_order_id, unfreeze_order_id, "
            "merchant_binding_id, reconciliation_run_id) = 1 AND ((operation IN "
            "('payment_submit','payment_query','payment_close','remaining_amount') AND "
            "payment_order_id IS NOT NULL) OR (operation IN "
            "('profit_sharing_submit','profit_sharing_query') AND profit_sharing_order_id "
            "IS NOT NULL) OR (operation IN ('unfreeze_submit','unfreeze_query') AND "
            "unfreeze_order_id IS NOT NULL) OR (operation IN "
            "('receiver_add','receiver_delete','maximum_ratio') AND merchant_binding_id IS "
            "NOT NULL) OR (operation IN "
            "('trade_statement','profit_sharing_statement','platform_fundflow_statement','s"
            "tatement_download') AND reconciliation_run_id IS NOT NULL))",
            name="ck_payment_request_target",
        ),
        CheckConstraint(
            "outcome IN "
            "('started','verified_response','transport_unknown','invalid_response') AND "
            "(outcome <> 'started' OR finished_at IS NULL)",
            name="ck_payment_request_outcome",
        ),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="ck_payment_request_http_status",
        ),
        CheckConstraint(
            "request_id ~ '^[A-Za-z0-9_-]{1,64}$' AND jsonb_typeof(request_snapshot) = "
            "'object' AND (response_snapshot IS NULL OR jsonb_typeof(response_snapshot) = "
            "'object')",
            name="ck_payment_request_snapshot",
        ),
        *(
            Index(f"ix_payment_request_{target}", target, "created_at", "id")
            for target in (
                "payment_order_id",
                "profit_sharing_order_id",
                "unfreeze_order_id",
                "merchant_binding_id",
                "reconciliation_run_id",
            )
        ),
    )
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    profit_sharing_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    unfreeze_order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    merchant_binding_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    reconciliation_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    channel_request_id: Mapped[str | None] = mapped_column(String(128))
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False, default=utc_now)
