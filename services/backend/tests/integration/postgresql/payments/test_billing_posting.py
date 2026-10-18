from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from tests.support.billing_services import BillingSetup
from tests.support.payments import complete_payment, provision_payment

from backend_app.core.errors import AppError
from backend_app.domain.billing import Action
from backend_app.domain.billing.posting import post_online_receipt
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.models.payments import BillPaymentReservation, PaymentOrder, PaymentOrderItem
from backend_app.repositories.billing import BillingRepository
from backend_app.schemas import billing as schema
from backend_app.services.property_admin.billing import PropertyBillingService


def test_shared_posting_rolls_back_with_its_caller_and_keeps_original_reservation(
    billing_setup: BillingSetup,
) -> None:
    setup = billing_setup
    created = setup.create(paid=3000)
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=created.bill.id)
        db.commit()
    with setup.factory() as db:
        repo = BillingRepository(db, setup.housing.company_id)
        assert repo.protect_company() is not None
        assert repo.community(setup.housing.community_id, lock=True) is not None
        repo.house(setup.housing.community_id, setup.house_id, lock=True)
        bill = repo.bill(setup.housing.community_id, created.bill.id, lock=True)
        order = db.scalar(
            select(PaymentOrder)
            .where(PaymentOrder.id == payment.order_id)
            .with_for_update(of=PaymentOrder)
        )
        item = db.get(PaymentOrderItem, payment.item_id)
        assert bill and order and item
        order.status = "succeeded"
        order.channel_transaction_no = "isolated_transaction"
        order.paid_at = datetime(2026, 10, 18, 16, 5, tzinfo=UTC)
        db.flush()
        post_online_receipt(repo, bill, item, order.paid_at, "posting-rollback")
        db.flush()
        assert bill.settled_cents == 10000 and bill.row_version == 2
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 2
        db.rollback()
    with setup.factory() as db:
        bill = db.get(Bill, created.bill.id)
        order = db.get(PaymentOrder, payment.order_id)
        assert bill and (bill.settled_cents, bill.row_version) == (3000, 1)
        assert order and order.status == "pending" and order.paid_at is None
        assert db.get(BillPaymentReservation, created.bill.id) is not None
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 1


def test_property_history_reads_system_receipt_without_an_administrator_actor(
    billing_setup: BillingSetup,
) -> None:
    setup = billing_setup
    created = setup.create()
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=created.bill.id)
        db.commit()
    with setup.factory() as db:
        complete_payment(db, payment, paid_at=datetime(2026, 10, 18, 16, 5, tzinfo=UTC))
        db.commit()
    with setup.factory() as db:
        service = PropertyBillingService(db)
        bill = service.get_bill(setup.housing.context, setup.housing.community_id, created.bill.id)
        entries = service.list_entries(
            setup.housing.context,
            setup.housing.community_id,
            bill.id,
            page=1,
            page_size=20,
        )
        operations = service.list_operations(
            setup.housing.context,
            setup.housing.community_id,
            bill.id,
            page=1,
            page_size=20,
        )
    assert bill.settled_cents == 10000 and bill.row_version == 2
    assert bill.payment_in_progress is False
    assert entries.total == 1
    entry = entries.items[0]
    assert entry.source_type == "online_payment" and entry.payment_order_item_id == payment.item_id
    assert entry.actor_type == "system" and entry.actor_id is None and entry.actor_name == "系统"
    assert entry.received_on and entry.received_on.isoformat() == "2026-10-19"
    operation = next(item for item in operations.items if item.action == "online_receipt")
    assert operation.actor_type == "system" and operation.actor_id is None
    assert operation.actor_name == "系统"


@pytest.mark.parametrize("action", ["correct_receipt", "reverse_receipt"])
def test_property_cannot_correct_or_reverse_a_confirmed_online_receipt(
    billing_setup: BillingSetup, action: Action
) -> None:
    setup = billing_setup
    created = setup.create()
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=created.bill.id)
        db.commit()
    with setup.factory() as db:
        complete_payment(db, payment)
        db.commit()
        entry_id = db.scalar(
            select(BillSettlementEntry.id).where(
                BillSettlementEntry.payment_order_item_id == payment.item_id
            )
        )
    assert entry_id
    data = (
        schema.ReceiptCorrection(
            expected_row_version=2,
            corrected_amount_cents=5000,
            corrected_received_on=None,
            reason="误选线上流水",
        )
        if action == "correct_receipt"
        else schema.BillReasonAction(expected_row_version=2, reason="误选线上流水")
    )
    with setup.factory() as db:
        with pytest.raises(AppError) as error:
            PropertyBillingService(db).write(
                setup.housing.context,
                setup.housing.community_id,
                action,
                data,
                "reject-online",
                "request",
                bill_id=created.bill.id,
                entry_id=entry_id,
            )
        assert error.value.code == "billing.invalid_receipt"
    with setup.factory() as db:
        bill = db.get(Bill, created.bill.id)
        assert bill and (bill.settled_cents, bill.row_version) == (10000, 2)
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 1
        assert db.scalar(select(func.count()).select_from(BillOperation)) == 2


@pytest.mark.parametrize("action", ["receipt", "correct_receipt", "reverse_receipt", "void"])
def test_current_payment_reservation_blocks_offline_writes_at_the_original_bill_version(
    billing_setup: BillingSetup, action: Action
) -> None:
    setup = billing_setup
    created = setup.create(paid=0 if action == "void" else 3000)
    with setup.factory() as db:
        provision_payment(db, setup, bill_id=created.bill.id)
        db.commit()
    data: schema.ReceiptCreate | schema.ReceiptCorrection | schema.BillReasonAction
    if action == "receipt":
        data = schema.ReceiptCreate(expected_row_version=1, amount_cents=1)
    elif action == "correct_receipt":
        data = schema.ReceiptCorrection(
            expected_row_version=1,
            corrected_amount_cents=2000,
            corrected_received_on=None,
            reason="误录",
        )
    else:
        data = schema.BillReasonAction(expected_row_version=1, reason="误录")
    with setup.factory() as db:
        service = PropertyBillingService(db)
        view = service.get_bill(setup.housing.context, setup.housing.community_id, created.bill.id)
        assert view.payment_in_progress is True and view.row_version == 1
        with pytest.raises(AppError) as error:
            service.write(
                setup.housing.context,
                setup.housing.community_id,
                action,
                data,
                "reject-reserved",
                "request",
                bill_id=created.bill.id,
                entry_id=created.settlement_entries[0].id if created.settlement_entries else None,
            )
        assert error.value.code == "payment.bill_reserved"
    with setup.factory() as db:
        bill = db.get(Bill, created.bill.id)
        assert bill and bill.row_version == 1 and bill.settled_cents == created.bill.settled_cents
        assert db.get(BillPaymentReservation, created.bill.id) is not None


def test_payment_occupation_allows_nonfinancial_metadata_update(
    billing_setup: BillingSetup,
) -> None:
    setup = billing_setup
    created = setup.create()
    with setup.factory() as db:
        provision_payment(db, setup, bill_id=created.bill.id)
        db.commit()
    with setup.factory() as db:
        result = PropertyBillingService(db).write(
            setup.housing.context,
            setup.housing.community_id,
            "update",
            schema.BillUpdate(expected_row_version=1, external_bill_no="external-reference"),
            "metadata-only",
            "request",
            bill_id=created.bill.id,
        )
    assert result.bill.payment_in_progress is True
    assert result.bill.row_version == 2 and result.bill.external_bill_no == "external-reference"
    assert result.bill.settled_cents == 0 and result.bill.outstanding_cents == 10000
