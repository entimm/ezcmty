from dataclasses import replace

import pytest
from sqlalchemy import func, select
from tests.support.billing_services import BillingSetup
from tests.support.house_claims import ClaimSetup
from tests.support.payments import complete_payment, provision_payment

from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.models.house_claims import ResidentHouseBinding
from backend_app.models.housing import SpaceNode
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import PaymentChannelRequest, PaymentTask
from backend_app.schemas.house_claims import ClaimReview, HouseRelease
from backend_app.services.property_admin.house_claims import PropertyHouseClaimService
from backend_app.services.resident.billing import ResidentBillingService
from backend_app.services.resident.house_claims import ResidentHouseClaimService


def approved(setup: ClaimSetup) -> tuple[BillingSetup, str]:
    with setup.factory() as db:
        PropertyHouseClaimService(db).review(
            setup.housing.context,
            setup.claim.id,
            ClaimReview(expected_row_version=1, decision="approved"),
            "review",
        )
        binding = db.scalar(
            select(ResidentHouseBinding).where(
                ResidentHouseBinding.user_id == setup.context.user_id
            )
        )
        assert binding
        return BillingSetup(setup.factory, setup.housing, setup.claim.house_id), binding.id


def test_pagination_before_claim_dates_and_strict_projection(claim_setup: ClaimSetup) -> None:
    setup, binding_id = approved(claim_setup)
    first = setup.create(month="2024-01", key="one", paid=3000).bill
    setup.create(month="2024-02", key="two", paid=10000)
    setup.create(month="2024-03", key="three")
    with setup.factory() as db:
        svc = ResidentBillingService(db, get_settings())
        filters = {
            "scope": "outstanding",
            "billing_month_from": None,
            "billing_month_to": None,
            "page": 1,
            "page_size": 1,
            "sort": "billing_month,id",
        }
        page = svc.list(claim_setup.context, binding_id, **filters)
        assert page.total == 2 and page.items[0].id == first.id
        assert page.items[0].payment_availability == "collection_unavailable"
        all_items = svc.list(
            claim_setup.context, binding_id, **{**filters, "scope": "all", "page_size": 100}
        )
        assert all_items.total == 3
        empty = svc.list(claim_setup.context, binding_id, **{**filters, "page": 10})
        assert empty.total == 2 and empty.items == []
        entries = svc.entries(
            claim_setup.context, first.id, page=1, page_size=1, sort="created_at,id"
        )
        assert entries.total == 1 and entries.items[0].display_type == "offline_receipt"
        assert set(entries.items[0].model_dump()) == {
            "id",
            "bill_id",
            "entry_type",
            "source_type",
            "amount_cents",
            "received_on",
            "display_type",
            "own_payment_order_id",
            "created_at",
        }
        assert page.items[0].model_dump(mode="json")["created_at"].endswith("Z")
        with pytest.raises(AppError) as invalid:
            svc.list(
                claim_setup.context,
                binding_id,
                **{**filters, "billing_month_from": "2026-02", "billing_month_to": "2026-01"},
            )
        assert invalid.value.code == "VALIDATION_ERROR"
        assert db.scalar(select(func.count()).select_from(PaymentChannelRequest)) == 0
        assert db.scalar(select(func.count()).select_from(PaymentTask)) == 0


def test_own_and_other_reservations_and_online_entries(claim_setup: ClaimSetup) -> None:
    setup, _ = approved(claim_setup)
    own_bill = setup.create(month="2024-01", key="own").bill
    other_bill = setup.create(month="2024-02", key="other").bill
    with setup.factory() as db:
        own = provision_payment(
            db, setup, bill_id=own_bill.id, key="own", payer_user_id=claim_setup.context.user_id
        )
        other = provision_payment(db, setup, bill_id=other_bill.id, key="other")
        db.commit()
        svc = ResidentBillingService(db, get_settings())
        own_view = svc.get(claim_setup.context, own_bill.id)
        other_view = svc.get(claim_setup.context, other_bill.id)
        assert (
            own_view.own_payment_order_id == own.order_id
            and own_view.payment_availability == "own_payment_in_progress"
        )
        assert (
            other_view.own_payment_order_id is None
            and other_view.payment_availability == "other_payment_in_progress"
        )
        complete_payment(db, own)
        complete_payment(db, other)
        db.commit()
        own_entry = svc.entries(
            claim_setup.context, own_bill.id, page=1, page_size=20, sort="created_at,id"
        ).items[0]
        other_entry = svc.entries(
            claim_setup.context, other_bill.id, page=1, page_size=20, sort="created_at,id"
        ).items[0]
        assert (
            own_entry.display_type == "own_payment"
            and own_entry.own_payment_order_id == own.order_id
        )
        assert (
            other_entry.display_type == "other_payment" and other_entry.own_payment_order_id is None
        )


def test_current_authorization_filters_records_counts_and_entries(claim_setup: ClaimSetup) -> None:
    setup, binding_id = approved(claim_setup)
    bill = setup.create().bill
    with setup.factory() as db:
        stranger = MiniappUser(wechat_openid="unrelated_resident")
        db.add(stranger)
        db.commit()
        svc = ResidentBillingService(db, get_settings())
        with pytest.raises(AppError) as denied:
            svc.get(replace(claim_setup.context, user_id=stranger.id), bill.id)
        assert denied.value.code == "resource.not_found"
        node = db.get(SpaceNode, setup.housing.node_id)
        assert node
        node.enabled = False
        db.commit()
        with pytest.raises(AppError) as disabled:
            svc.get(claim_setup.context, bill.id)
        assert disabled.value.code == "resource.not_found"
        node.enabled = True
        db.commit()
        ResidentHouseClaimService(db).release(
            claim_setup.context, binding_id, HouseRelease(expected_row_version=1)
        )
        with pytest.raises(AppError) as released:
            svc.entries(claim_setup.context, bill.id, page=1, page_size=20, sort="created_at,id")
        assert released.value.code == "resource.not_found"
