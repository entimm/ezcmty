from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.payments.configuration import configuration_token
from backend_app.models.payments import (
    PaymentChannelRequest,
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.models.property import PropertyCompany
from backend_app.repositories.pagination import read_page
from backend_app.repositories.property import PropertyRepository


class ConfigurationRepository:
    def __init__(self, db: Session):
        self.db = db

    def company(self, company_id: str, *, lock: bool = False) -> PropertyCompany:
        company = PropertyRepository(self.db).company(company_id, lock=lock)
        if company is None:
            raise AppError("resource.not_found")
        return company

    def binding(self, company_id: str, binding_id: str) -> PropertyMerchantBinding:
        result = self.db.scalar(
            select(PropertyMerchantBinding)
            .where(
                PropertyMerchantBinding.property_company_id == company_id,
                PropertyMerchantBinding.id == binding_id,
            )
            .execution_options(populate_existing=True)
        )
        if result is None:
            raise AppError("resource.not_found")
        return result

    def bindings(self, company_id: str) -> list[PropertyMerchantBinding]:
        return list(
            self.db.scalars(
                select(PropertyMerchantBinding)
                .where(PropertyMerchantBinding.property_company_id == company_id)
                .order_by(PropertyMerchantBinding.id)
                .execution_options(populate_existing=True)
            )
        )

    def rule(self, company_id: str, rule_id: str) -> ProfitSharingRuleVersion:
        result = self.db.scalar(
            select(ProfitSharingRuleVersion).where(
                ProfitSharingRuleVersion.property_company_id == company_id,
                ProfitSharingRuleVersion.id == rule_id,
            )
        )
        if result is None:
            raise AppError("resource.not_found")
        return result

    def items(self, rule_id: str) -> list[ProfitSharingRuleVersionItem]:
        return list(
            self.db.scalars(
                select(ProfitSharingRuleVersionItem)
                .where(ProfitSharingRuleVersionItem.rule_version_id == rule_id)
                .order_by(ProfitSharingRuleVersionItem.id)
            )
        )

    def latest_rule(self, company_id: str) -> ProfitSharingRuleVersion | None:
        return self.db.scalar(
            select(ProfitSharingRuleVersion)
            .where(ProfitSharingRuleVersion.property_company_id == company_id)
            .order_by(ProfitSharingRuleVersion.version_no.desc())
            .limit(1)
        )

    def current(
        self, company_id: str
    ) -> tuple[
        PropertyMerchantBinding | None,
        ProfitSharingRuleVersion | None,
        list[ProfitSharingRuleVersionItem],
    ]:
        binding = next((b for b in self.bindings(company_id) if b.enabled), None)
        rule = self.latest_rule(company_id)
        return binding, rule, self.items(rule.id) if rule else []

    def configuration_token(self, company_id: str) -> str:
        rule = self.latest_rule(company_id)
        return configuration_token(
            [(b.id, b.row_version) for b in self.bindings(company_id)], rule.id if rule else None
        )

    def receiver_ready(self, binding_id: str, receiver_account: str) -> bool:
        binding = self.db.get(PropertyMerchantBinding, binding_id)
        if binding is None:
            return False
        evidence = self.db.scalar(
            select(PaymentChannelRequest)
            .where(
                PaymentChannelRequest.merchant_binding_id == binding_id,
                PaymentChannelRequest.operation.in_(("receiver_add", "receiver_delete")),
                PaymentChannelRequest.outcome == "verified_response",
                PaymentChannelRequest.finished_at.is_not(None),
                PaymentChannelRequest.response_snapshot["receiver_account"].as_string()
                == receiver_account,
                PaymentChannelRequest.response_snapshot["merchant_no"].as_string()
                == binding.merchant_no,
            )
            .order_by(PaymentChannelRequest.created_at.desc(), PaymentChannelRequest.id.desc())
            .limit(1)
        )
        return (
            evidence is not None
            and evidence.operation == "receiver_add"
            and evidence.error_code is None
        )

    def previous_binding(self, company_id: str, key: str) -> PropertyMerchantBinding | None:
        return self.db.scalar(
            select(PropertyMerchantBinding).where(
                PropertyMerchantBinding.property_company_id == company_id,
                PropertyMerchantBinding.idempotency_key == key,
            )
        )

    def previous_rule(self, company_id: str, key: str) -> ProfitSharingRuleVersion | None:
        return self.db.scalar(
            select(ProfitSharingRuleVersion).where(
                ProfitSharingRuleVersion.property_company_id == company_id,
                ProfitSharingRuleVersion.idempotency_key == key,
            )
        )

    def binding_page(
        self, company_id: str, *, page: int, page_size: int, sort: str, enabled: bool | None
    ) -> tuple[list[PropertyMerchantBinding], int]:
        query = select(PropertyMerchantBinding).where(
            PropertyMerchantBinding.property_company_id == company_id
        )
        if enabled is not None:
            query = query.where(PropertyMerchantBinding.enabled == enabled)
        return read_page(
            self.db,
            PropertyMerchantBinding,
            query,
            page=page,
            page_size=page_size,
            order=(("created_at", sort.startswith("-")), ("id", sort.startswith("-"))),
        )

    def rule_page(
        self, company_id: str, *, page: int, page_size: int, sort: str
    ) -> tuple[list[ProfitSharingRuleVersion], int]:
        return read_page(
            self.db,
            ProfitSharingRuleVersion,
            select(ProfitSharingRuleVersion).where(
                ProfitSharingRuleVersion.property_company_id == company_id
            ),
            page=page,
            page_size=page_size,
            order=(("version_no", sort.startswith("-")), ("id", sort.startswith("-"))),
        )
