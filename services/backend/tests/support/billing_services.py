from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend_app.schemas import billing as schema
from backend_app.services.property_admin.billing import PropertyBillingService
from tests.support.housing_services import HousingSetup


@dataclass
class BillingSetup:
    factory: sessionmaker[Session]
    housing: HousingSetup
    house_id: str

    def create(
        self, *, month: str = "2026-01", key: str = "create", paid: int = 0
    ) -> schema.BillWriteResult:
        with self.factory() as db:
            return PropertyBillingService(db).write(
                self.housing.context,
                self.housing.community_id,
                "create",
                schema.BillCreate(
                    house_id=self.house_id,
                    billing_month=month,
                    amount_source="manual",
                    receivable_cents=10000,
                    manual_amount_reason="历史",
                    initial_receipt=schema.InitialReceipt(amount_cents=paid) if paid else None,
                ),
                key,
                "request",
            )
