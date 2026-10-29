from unittest.mock import Mock

from sqlalchemy import func, select
from tests.support.billing_services import BillingSetup

from backend_app.domain.billing.creation import BillCreationCommand
from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry
from backend_app.services.property_account_access import property_business_context
from backend_app.services.property_admin.billing import PropertyBillingService
from backend_app.services.property_business.bill_creation import create_bill
from backend_app.services.property_business.billing import BillingUseCases
from backend_app.services.property_business.commands import ReceiptCreate
from backend_app.services.property_business.context import (
    BusinessActor,
    BusinessAuthority,
    PropertyBusinessContext,
)


def test_shared_receipt_and_audit_roll_back_in_the_callers_transaction(
    billing_setup: BillingSetup,
) -> None:
    setup = billing_setup
    bill_id = setup.create().bill.id
    with setup.factory() as db:
        context = property_business_context(db, setup.housing.context)
        result = BillingUseCases(db).write(
            context,
            setup.housing.community_id,
            "receipt",
            ReceiptCreate(1, 100, None, "线下凭据", frozenset({"amount_cents"})),
            "shared-receipt",
            "shared-receipt",
            "a" * 64,
            bill_id=bill_id,
        )
        assert result.bill.settled_cents == 100
        with setup.factory() as observer:
            original = observer.get(Bill, bill_id)
            assert original and original.settled_cents == 0
            assert observer.scalar(select(func.count()).select_from(BillOperation)) == 1
        db.rollback()
    with setup.factory() as db:
        bill = db.get(Bill, bill_id)
        assert bill and bill.settled_cents == 0 and bill.row_version == 1
        assert db.scalar(select(func.count()).select_from(BillSettlementEntry)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AdminAuditLog)
                .where(AdminAuditLog.request_id == "shared-receipt")
            )
            == 0
        )


def test_shared_creation_accepts_trusted_actor_source_and_projects_linked_name(
    billing_setup: BillingSetup,
) -> None:
    setup = billing_setup
    with setup.factory() as db:
        account = db.scalar(select(AdminAccount).where(AdminAccount.scope == "platform_admin"))
        assert account and account.property_company_id is None
        actor = BusinessActor(
            account.id, account.display_name, frozenset({"bill.manage", "bill_receipt.create"})
        )
        # Test-only authority proves the business boundary without adding any runtime adapter.
        authority = Mock(spec=BusinessAuthority)
        authority.authorize.return_value = actor
        context = PropertyBusinessContext(
            setup.housing.company_id, account.id, account.scope, authority
        )
        result = create_bill(
            db,
            company_id=setup.housing.company_id,
            community_id=setup.housing.community_id,
            actor_id=actor.id,
            context=context,
            command=BillCreationCommand.from_input(
                {
                    "house_id": setup.house_id,
                    "billing_month": "2026-01",
                    "amount_source": "manual",
                    "receivable_cents": 10000,
                    "manual_amount_reason": "历史",
                    "initial_receipt": {"amount_cents": 100},
                }
            ),
            key="linked-actor",
            fingerprint="b" * 64,
            request_id="linked-actor",
            input_fields=frozenset(),
        )
        db.commit()
        authority.authorize.assert_called_once_with(
            context, actor.permissions, lock=True, shared=True
        )
        with setup.factory() as reader:
            service = PropertyBillingService(reader)
            operations = service.list_operations(
                setup.housing.context,
                setup.housing.community_id,
                result.bill_id,
                page=1,
                page_size=20,
            )
            entries = service.list_entries(
                setup.housing.context,
                setup.housing.community_id,
                result.bill_id,
                page=1,
                page_size=20,
            )
            assert operations.items[0].actor_id == actor.id
            assert operations.items[0].actor_name == actor.display_name
            assert entries.items[0].actor_name == actor.display_name
