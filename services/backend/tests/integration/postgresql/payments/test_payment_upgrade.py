from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from tests.support.billing_services import BillingSetup
from tests.support.paths import BACKEND_ROOT

from backend_app.models.billing import BillOperation, BillSettlementEntry
from backend_app.services.property_admin.billing import PropertyBillingService


def test_payment_upgrade_preserves_existing_offline_billing(billing_setup: BillingSetup) -> None:
    s = billing_setup
    original = s.create(paid=3500)
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    # Offline rows also fit the preceding revision. Exercise upgrade with real pre-payment columns.
    command.downgrade(cfg, "20261017_house_claims")
    with s.factory() as db:
        old_bill = db.execute(
            text("SELECT settled_cents, row_version FROM bills WHERE id = :id"),
            {"id": original.bill.id},
        ).one()
        assert tuple(old_bill) == (3500, 1)
    command.upgrade(cfg, "head")
    with s.factory() as db:
        service = PropertyBillingService(db)
        bill = service.get_bill(s.housing.context, s.housing.community_id, original.bill.id)
        assert bill.settled_cents == 3500 and bill.outstanding_cents == 6500
        assert bill.row_version == 1 and not bill.payment_in_progress
        operation = db.scalar(select(BillOperation).where(BillOperation.bill_id == bill.id))
        assert operation is not None and operation.actor_type == "admin"
        assert operation.actor_id == s.housing.context.account_id
        entry = db.scalar(select(BillSettlementEntry).where(BillSettlementEntry.bill_id == bill.id))
        assert entry is not None and entry.source_type == "offline"
        assert entry.payment_order_item_id is None and entry.amount_cents == 3500
        replay = service.operation_result(s.housing.context, "create")
        assert replay.response_status == 201 and replay.result.bill.id == bill.id
