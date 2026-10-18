from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from threading import Barrier

import pytest
from psycopg import Error
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tests.support.billing_services import BillingSetup
from tests.support.payments import PaymentSetup, complete_payment, provision_payment

from backend_app.models.admin import utc_now
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.payments import (
    BillPaymentReservation,
    PaymentOrder,
    PaymentOrderItem,
    PaymentReconciliationRun,
    PaymentTask,
    PaymentUnfreezeOrder,
    ProfitSharingAllocation,
    ProfitSharingOrder,
    ProfitSharingOrderItem,
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.models.property import PropertyCompany


@contextmanager
def rejects(constraint: str) -> Iterator[None]:
    with pytest.raises(IntegrityError) as caught:
        yield
    error = caught.value.orig
    assert isinstance(error, Error)
    assert error.diag.constraint_name == constraint


def pending(setup: BillingSetup, *, rates: tuple[int, ...] = (300,)) -> PaymentSetup:
    bill_id = setup.create().bill.id
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=bill_id, rates=rates)
        db.commit()
    return payment


def succeeded(setup: BillingSetup, *, rates: tuple[int, ...] = (300,)) -> PaymentSetup:
    payment = pending(setup, rates=rates)
    with setup.factory() as db:
        complete_payment(db, payment)
        db.commit()
    return payment


def test_reservation_preserves_bill_version_and_cannot_release_unknown_payment(
    billing_setup: BillingSetup,
) -> None:
    payment = pending(billing_setup)
    with billing_setup.factory() as db:
        item = db.get(PaymentOrderItem, payment.item_id)
        assert item is not None
        bill = db.get(Bill, item.bill_id)
        assert bill is not None and bill.row_version == 1 and bill.settled_cents == 0
        with rejects("ck_payment_reservation_release"):
            db.execute(
                delete(BillPaymentReservation).where(
                    BillPaymentReservation.payment_order_id == payment.order_id
                )
            )
        db.rollback()
        assert db.get(BillPaymentReservation, item.bill_id) is not None


@pytest.mark.parametrize("resource", ["binding", "rule", "order", "item", "task"])
def test_database_freezes_payment_identity_and_history(
    billing_setup: BillingSetup, resource: str
) -> None:
    payment = pending(billing_setup)
    commands = {
        "binding": (
            "UPDATE property_merchant_bindings SET merchant_no='other' WHERE id=:id",
            payment.binding_id,
        ),
        "rule": (
            "UPDATE profit_sharing_rule_version_items SET rate_bps=0 WHERE id=:id",
            payment.rule_item_ids[0],
        ),
        "order": (
            "UPDATE payment_orders SET amount_cents=amount_cents+1 WHERE id=:id",
            payment.order_id,
        ),
        "item": ("DELETE FROM payment_order_items WHERE id=:id", payment.item_id),
        "task": ("DELETE FROM payment_tasks WHERE payment_order_id=:id", payment.order_id),
    }
    sql, target = commands[resource]
    with billing_setup.factory() as db:
        with rejects("ck_payment_immutable"):
            db.execute(text(sql), {"id": target})
        db.rollback()


def test_committed_rule_cannot_gain_new_receiver(billing_setup: BillingSetup) -> None:
    payment = pending(billing_setup)
    with billing_setup.factory() as db:
        db.add(
            ProfitSharingRuleVersionItem(
                rule_version_id=payment.rule_id,
                receiver_account="other",
                receiver_name="另一接收方",
                rate_bps=0,
            )
        )
        with rejects("ck_sharing_rule_complete"):
            db.flush()
        db.rollback()


def test_touching_payment_parent_cannot_append_to_frozen_items(billing_setup: BillingSetup) -> None:
    payment = pending(billing_setup)
    second = billing_setup.create(month="2026-02", key="second")
    with billing_setup.factory() as db:
        db.execute(
            text("UPDATE payment_orders SET updated_at=:now WHERE id=:id"),
            {"now": utc_now(), "id": payment.order_id},
        )
        db.add(
            PaymentOrderItem(
                property_company_id=billing_setup.housing.company_id,
                payment_order_id=payment.order_id,
                bill_id=second.bill.id,
                amount_cents=10000,
            )
        )
        with rejects("ck_payment_item_frozen"):
            db.flush()
        db.rollback()


@pytest.mark.parametrize("missing", ["reservation", "task", "amount"])
def test_incomplete_payment_creation_is_rejected_at_commit(
    billing_setup: BillingSetup, missing: str
) -> None:
    bill_id = billing_setup.create().bill.id
    with billing_setup.factory() as db:
        payment = provision_payment(
            db,
            billing_setup,
            bill_id=bill_id,
            reserve=missing != "reservation",
            schedule=missing != "task",
            order_amount_cents=9999 if missing == "amount" else None,
        )
        with rejects("ck_payment_aggregate"):
            db.commit()
        db.rollback()
        assert db.get(PaymentOrder, payment.order_id) is None


@pytest.mark.parametrize("rates", [(300,), (0,), (300, 200)])
def test_success_commits_receipt_allocations_recovery_and_release_atomically(
    billing_setup: BillingSetup, rates: tuple[int, ...]
) -> None:
    payment = succeeded(billing_setup, rates=rates)
    with billing_setup.factory() as db:
        order = db.get(PaymentOrder, payment.order_id)
        item = db.get(PaymentOrderItem, payment.item_id)
        assert order is not None and order.status == "succeeded" and item is not None
        bill = db.get(Bill, item.bill_id)
        assert bill is not None and bill.row_version == 2 and bill.settled_cents == 10000
        assert db.get(BillPaymentReservation, item.bill_id) is None
        operation = db.scalar(select(BillOperation).where(BillOperation.action == "online_receipt"))
        entry = db.scalar(
            select(BillSettlementEntry).where(BillSettlementEntry.payment_order_item_id == item.id)
        )
        assert operation is not None and operation.actor_type == "system"
        assert operation.actor_id is None and operation.response_status is None
        assert entry is not None and entry.source_type == "online_payment"
        assert list(
            db.scalars(
                select(ProfitSharingAllocation.amount_cents)
                .where(ProfitSharingAllocation.payment_order_id == order.id)
                .order_by(ProfitSharingAllocation.amount_cents)
            )
        ) == sorted(r for r in rates if r)
        target = ProfitSharingOrder if any(rates) else PaymentUnfreezeOrder
        assert db.scalar(select(func.count()).select_from(target)) == 1


def test_successful_payment_cannot_regress(billing_setup: BillingSetup) -> None:
    payment = succeeded(billing_setup)
    with billing_setup.factory() as db:
        with rejects("ck_payment_terminal_result"):
            db.execute(
                text(
                    "UPDATE payment_orders SET status='unknown', paid_at=NULL, "
                    "channel_transaction_no=NULL WHERE id=:id"
                ),
                {"id": payment.order_id},
            )
        db.rollback()


def test_unfreeze_requires_full_fulfillment(billing_setup: BillingSetup) -> None:
    payment = succeeded(billing_setup)
    with billing_setup.factory() as db:
        db.add(PaymentUnfreezeOrder(payment_order_id=payment.order_id, order_no="uf_early"))
        with rejects("ck_payment_unfreeze_prerequisite"):
            db.flush()
        db.rollback()


def fulfill(db: Session, payment_id: str) -> None:
    sharing = db.scalar(
        select(ProfitSharingOrder).where(ProfitSharingOrder.payment_order_id == payment_id)
    )
    assert sharing is not None
    sharing.status = "finished"
    for item in db.scalars(
        select(ProfitSharingOrderItem).where(
            ProfitSharingOrderItem.profit_sharing_order_id == sharing.id
        )
    ):
        item.result = "success"
        item.finished_at = utc_now()
    db.flush()


def test_any_unfreeze_permanently_blocks_new_sharing(billing_setup: BillingSetup) -> None:
    payment = succeeded(billing_setup)
    with billing_setup.factory() as db:
        fulfill(db, payment.order_id)
        unfreeze = PaymentUnfreezeOrder(payment_order_id=payment.order_id, order_no="uf_release")
        db.add(unfreeze)
        db.flush()
        db.add(PaymentTask(task_type="unfreeze_submit", unfreeze_order_id=unfreeze.id))
        db.commit()
    with billing_setup.factory() as db:
        db.add(ProfitSharingOrder(payment_order_id=payment.order_id, order_no="ps_after_release"))
        with rejects("ck_payment_unfreeze_barrier"):
            db.flush()
        db.rollback()


def test_touching_sharing_parent_cannot_append_to_frozen_execution(
    billing_setup: BillingSetup,
) -> None:
    payment = succeeded(billing_setup, rates=(300, 200))
    with billing_setup.factory() as db:
        sharing = db.scalar(
            select(ProfitSharingOrder).where(
                ProfitSharingOrder.payment_order_id == payment.order_id
            )
        )
        allocation = db.scalar(
            select(ProfitSharingAllocation).where(
                ProfitSharingAllocation.payment_order_id == payment.order_id
            )
        )
        assert sharing is not None and allocation is not None
        sharing.updated_at = utc_now()
        db.flush()
        db.add(
            ProfitSharingOrderItem(
                payment_order_id=payment.order_id,
                profit_sharing_order_id=sharing.id,
                allocation_id=allocation.id,
                amount_cents=1,
            )
        )
        with rejects("ck_sharing_execution_frozen"):
            db.flush()
        db.rollback()


def test_competing_new_payments_leave_exactly_one_reservation(billing_setup: BillingSetup) -> None:
    bill_id = billing_setup.create().bill.id
    barrier = Barrier(2)

    def create(index: int) -> str:
        barrier.wait(timeout=10)
        with billing_setup.factory() as db:
            try:
                payment = provision_payment(db, billing_setup, bill_id=bill_id, key=f"race{index}")
                db.commit()
                return payment.order_id
            except IntegrityError:
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert results.count("conflict") == 1
    with billing_setup.factory() as db:
        assert db.scalar(select(func.count()).select_from(BillPaymentReservation)) == 1
        assert db.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        bill = db.get(Bill, bill_id)
        assert bill is not None and bill.row_version == 1


def test_platform_fundflow_null_merchant_scope_is_unique(billing_setup: BillingSetup) -> None:
    with billing_setup.factory() as db:
        values = {
            "business_date": date(2026, 10, 18),
            "statement_type": "platform_fundflow",
            "service_provider_merchant_no": "1900000001",
        }
        db.add(PaymentReconciliationRun(**values))
        db.commit()
        db.add(PaymentReconciliationRun(**values))
        with rejects("uq_payment_reconciliation_scope"):
            db.flush()
        db.rollback()


@pytest.mark.parametrize("foreign", ["binding", "rule"])
def test_payment_cannot_reference_another_company_configuration(
    billing_setup: BillingSetup, foreign: str
) -> None:
    payment = pending(billing_setup)
    with billing_setup.factory() as db:
        company = PropertyCompany(code="OTHER", name="另一公司")
        db.add(company)
        db.flush()
        binding = PropertyMerchantBinding(
            property_company_id=company.id,
            service_provider_merchant_no="1900000001",
            merchant_no="1900000003",
            merchant_name="另一商户",
            created_by=billing_setup.housing.context.account_id,
            idempotency_key="other_binding",
            request_fingerprint="4" * 64,
        )
        rule = ProfitSharingRuleVersion(
            property_company_id=company.id,
            version_no=1,
            created_by=billing_setup.housing.context.account_id,
            idempotency_key="other_rule",
            request_fingerprint="5" * 64,
        )
        db.add_all([binding, rule])
        db.flush()
        db.add(
            ProfitSharingRuleVersionItem(
                rule_version_id=rule.id,
                receiver_account="platform",
                receiver_name="平台",
                rate_bps=0,
            )
        )
        original = db.get(PaymentOrder, payment.order_id)
        assert original is not None
        db.add(
            PaymentOrder(
                property_company_id=company.id,
                payer_user_id=payment.payer_user_id,
                merchant_binding_id=payment.binding_id if foreign == "binding" else binding.id,
                rule_version_id=payment.rule_id if foreign == "rule" else rule.id,
                order_no="p_cross_company",
                amount_cents=10000,
                expires_at=original.expires_at,
                idempotency_key="cross",
                request_fingerprint="6" * 64,
            )
        )
        with rejects(f"fk_payment_order_{foreign}"):
            db.flush()
        db.rollback()


def test_failed_attempt_can_only_retry_remaining_allocation(billing_setup: BillingSetup) -> None:
    payment = succeeded(billing_setup)
    with billing_setup.factory() as db:
        original = db.scalar(
            select(ProfitSharingOrder).where(
                ProfitSharingOrder.payment_order_id == payment.order_id
            )
        )
        allocation = db.scalar(
            select(ProfitSharingAllocation).where(
                ProfitSharingAllocation.payment_order_id == payment.order_id
            )
        )
        assert original is not None and allocation is not None
        original.status = "rejected"
        db.flush()
        retry = ProfitSharingOrder(payment_order_id=payment.order_id, order_no="ps_retry")
        db.add(retry)
        db.flush()
        db.add(
            ProfitSharingOrderItem(
                payment_order_id=payment.order_id,
                profit_sharing_order_id=retry.id,
                allocation_id=allocation.id,
                amount_cents=allocation.amount_cents + 1,
            )
        )
        with rejects("ck_sharing_fulfillment"):
            db.flush()
        db.rollback()


def test_confirmed_receiver_success_cannot_be_changed_to_failure(
    billing_setup: BillingSetup,
) -> None:
    payment = succeeded(billing_setup)
    with billing_setup.factory() as db:
        fulfill(db, payment.order_id)
        db.commit()
    with billing_setup.factory() as db:
        with rejects("ck_payment_terminal_result"):
            db.execute(
                text(
                    "UPDATE profit_sharing_order_items SET result='failed' "
                    "WHERE payment_order_id=:id"
                ),
                {"id": payment.order_id},
            )
        db.rollback()


def test_channel_transaction_is_globally_unique_across_bindings(
    billing_setup: BillingSetup,
) -> None:
    first = succeeded(billing_setup)
    second_bill = billing_setup.create(month="2026-02", key="second")
    with billing_setup.factory() as db:
        second = provision_payment(db, billing_setup, bill_id=second_bill.bill.id, key="second")
        db.commit()
    with billing_setup.factory() as db:
        original = db.get(PaymentOrder, first.order_id)
        other = db.get(PaymentOrder, second.order_id)
        assert original is not None and other is not None
        other.status = "succeeded"
        other.channel_transaction_no = original.channel_transaction_no
        other.paid_at = utc_now()
        with rejects("uq_payment_order_transaction"):
            db.flush()
        db.rollback()
