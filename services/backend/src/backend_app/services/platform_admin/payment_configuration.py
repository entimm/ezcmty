from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import Settings
from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.domain.payments.configuration import channel_configured, fingerprint
from backend_app.integrations.wechatpay.client import (
    ChannelResponse,
    WechatPayClient,
    WechatPayError,
)
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.models.admin import AdminAccount, utc_now
from backend_app.models.payments import (
    ProfitSharingRuleVersion,
    ProfitSharingRuleVersionItem,
    PropertyMerchantBinding,
)
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.payments.channel_records import save_response, start_request
from backend_app.repositories.payments.configuration import ConfigurationRepository
from backend_app.schemas.mappers.payment_configuration import configuration_view, rule_view
from backend_app.schemas.payments import configuration as schema
from backend_app.services.contracts.admin import AdminContext


class PaymentConfigurationService:
    def __init__(self, db: Session, settings: Settings, channel: ProfitSharing | None = None):
        self.db = db
        self.settings = settings
        self.repo = ConfigurationRepository(db)
        self.identity = AdminIdentity(AdminRepository(db, "platform_admin"))
        self.channel = channel

    def _read(self, ctx: AdminContext, company_id: str) -> None:
        self.identity.require_permission(ctx, "platform.payment_config.read")
        self.repo.company(company_id)

    def _writer(self, ctx: AdminContext, company_id: str, *, lock: bool = True) -> AdminAccount:
        self.identity.require_permission(ctx, "platform.payment_config.manage")
        candidate = self.identity.account(ctx.account_id)
        self.db.refresh(candidate)
        if not candidate.enabled or candidate.session_version != ctx.version:
            raise AppError("auth.unauthenticated")
        if candidate.must_change_password:
            raise AppError("auth.password_change_required")
        if "platform.payment_config.manage" not in self.identity.effective_permissions(
            candidate.id
        ):
            raise AppError("auth.forbidden")
        self.repo.company(company_id, lock=lock)
        actor = self.identity.actor(ctx)
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if "platform.payment_config.manage" not in self.identity.effective_permissions(actor.id):
            raise AppError("auth.forbidden")
        return actor

    def _token(self, company_id: str, expected: str) -> None:
        if self.repo.configuration_token(company_id) != expected:
            raise AppError("payment.configuration_changed")

    def get(self, ctx: AdminContext, company_id: str) -> schema.PaymentConfiguration:
        self._read(ctx, company_id)
        return configuration_view(self.repo, company_id, self.settings)

    def bindings(
        self, ctx: AdminContext, company_id: str, **filters: Any
    ) -> schema.MerchantBindingPage:
        self._read(ctx, company_id)
        items, total = self.repo.binding_page(company_id, **filters)
        return schema.MerchantBindingPage(
            items=[schema.MerchantBinding.model_validate(i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def rules(
        self, ctx: AdminContext, company_id: str, **filters: Any
    ) -> schema.ProfitSharingRuleVersionPage:
        self._read(ctx, company_id)
        items, total = self.repo.rule_page(company_id, **filters)
        return schema.ProfitSharingRuleVersionPage(
            items=[rule_view(self.repo, i) for i in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def rule(
        self, ctx: AdminContext, company_id: str, rule_id: str
    ) -> schema.ProfitSharingRuleVersion:
        self._read(ctx, company_id)
        return rule_view(self.repo, self.repo.rule(company_id, rule_id))

    def _audit(
        self, actor: AdminAccount, action: str, target: str, company_id: str, request_id: str
    ) -> None:
        self.identity.audit.record(
            actor=actor,
            action=action,
            target_type="payment_configuration",
            target_id=target,
            property_company_id=company_id,
            request_id=request_id,
        )

    def create_binding(
        self,
        ctx: AdminContext,
        company_id: str,
        data: schema.MerchantBindingCreate,
        key: str,
        request_id: str,
    ) -> schema.MerchantBinding:
        actor = self._writer(ctx, company_id)
        digest = fingerprint(data.model_dump())
        previous = self.repo.previous_binding(company_id, key)
        if previous:
            if previous.request_fingerprint != digest:
                raise AppError("payment.idempotency_conflict")
            return schema.MerchantBinding.model_validate(previous)
        self._token(company_id, data.expected_configuration_token)
        if (
            not self.settings.wechatpay_service_provider_merchant_no
            or not data.merchant_no.strip()
            or not data.merchant_name.strip()
        ):
            raise AppError("payment.configuration_unavailable")
        now = utc_now()
        binding = PropertyMerchantBinding(
            property_company_id=company_id,
            service_provider_merchant_no=self.settings.wechatpay_service_provider_merchant_no,
            merchant_no=data.merchant_no,
            merchant_name=data.merchant_name,
            enabled=False,
            created_by=actor.id,
            idempotency_key=key,
            request_fingerprint=digest,
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        self.db.add(binding)
        self.db.flush()
        self._audit(actor, "payment.merchant_binding.create", binding.id, company_id, request_id)
        self.db.commit()
        return schema.MerchantBinding.model_validate(binding)

    def _verify(self, company_id: str, binding_id: str, request_id: str) -> int:
        binding = self.repo.binding(company_id, binding_id)
        merchant_no = binding.merchant_no
        if (
            binding.service_provider_merchant_no
            != self.settings.wechatpay_service_provider_merchant_no
        ):
            raise AppError("payment.configuration_unavailable")
        if self.channel is None and not channel_configured(self.settings):
            raise AppError("payment.configuration_unavailable")
        try:
            channel = self.channel or ProfitSharing(WechatPayClient.from_settings(self.settings))
        except WechatPayError:
            raise AppError("payment.configuration_unavailable") from None
        factory = sessionmaker(bind=self.db.get_bind(), autoflush=False)
        self.db.rollback()  # Release actor/company locks before any network request.

        def record_call(
            operation: str, call: Callable[[], ChannelResponse[dict[str, Any]]]
        ) -> dict[str, Any]:
            with factory() as evidence_db:
                record = start_request(
                    evidence_db,
                    operation=operation,
                    target_id=binding_id,
                    request_snapshot={"merchant_no": merchant_no},
                    request_id=request_id,
                    now=utc_now(),
                )
                record_id = record.id
                evidence_db.commit()
            try:
                response = call()
            except WechatPayError as error:
                with factory() as evidence_db:
                    save_response(
                        evidence_db,
                        record_id,
                        outcome=error.outcome,
                        now=utc_now(),
                        http_status=error.http_status,
                        channel_request_id=error.channel_request_id,
                        error_code=error.code,
                    )
                    evidence_db.commit()
                raise AppError("system.dependency_unavailable") from None
            with factory() as evidence_db:
                save_response(
                    evidence_db,
                    record_id,
                    outcome="verified_response",
                    now=utc_now(),
                    http_status=response.http_status,
                    channel_request_id=response.channel_request_id,
                    response_snapshot=response.value,
                )
                evidence_db.commit()
            return response.value

        receiver = record_call(
            "receiver_add",
            lambda: channel.add_receiver(
                merchant_no=merchant_no,
                receiver_account=self.settings.wechatpay_service_provider_merchant_no,
                receiver_name=self.settings.wechatpay_platform_receiver_name.get_secret_value(),
            ),
        )
        ratio = record_call("maximum_ratio", lambda: channel.maximum_ratio(merchant_no=merchant_no))
        if (
            receiver.get("merchant_no") != merchant_no
            or receiver.get("receiver_account")
            != self.settings.wechatpay_service_provider_merchant_no
            or ratio.get("merchant_no") != merchant_no
        ):
            raise AppError("payment.configuration_unavailable")
        return int(ratio["maximum_ratio_bps"])

    def activate(
        self,
        ctx: AdminContext,
        company_id: str,
        data: schema.ActiveMerchantBindingUpdate,
        request_id: str,
    ) -> schema.PaymentConfiguration:
        self._writer(ctx, company_id)
        self._token(company_id, data.expected_configuration_token)
        ratio = self._verify(company_id, data.binding_id, request_id) if data.binding_id else None
        actor = self._writer(ctx, company_id)
        self._token(company_id, data.expected_configuration_token)
        now = utc_now()
        for binding in self.repo.bindings(company_id):
            if binding.enabled and binding.id != data.binding_id:
                binding.enabled = False
                binding.row_version += 1
                binding.updated_at = now
        self.db.flush()  # Release the partial unique index before activating its replacement.
        if data.binding_id:
            target = self.repo.binding(company_id, data.binding_id)
            if not target.enabled:
                target.enabled = True
                target.row_version += 1
                target.updated_at = now
            target.max_ratio_bps = ratio
            target.ratio_checked_at = now
        self.db.flush()
        self._audit(
            actor,
            "payment.merchant_binding.activate",
            data.binding_id or company_id,
            company_id,
            request_id,
        )
        self.db.commit()
        return configuration_view(self.repo, company_id, self.settings)

    def create_rule(
        self,
        ctx: AdminContext,
        company_id: str,
        data: schema.ProfitSharingRuleCreate,
        key: str,
        request_id: str,
    ) -> schema.ProfitSharingRuleVersion:
        self._writer(ctx, company_id)
        digest = fingerprint(data.model_dump())
        previous = self.repo.previous_rule(company_id, key)
        if previous:
            if previous.request_fingerprint != digest:
                raise AppError("payment.idempotency_conflict")
            return rule_view(self.repo, previous)
        self._token(company_id, data.expected_configuration_token)
        binding, _, _ = self.repo.current(company_id)
        if binding is None:
            raise AppError("payment.configuration_unavailable")
        binding_id = binding.id
        ratio = self._verify(company_id, binding_id, request_id)
        actor = self._writer(ctx, company_id)
        # A concurrent successful replay wins even when its original token is now stale.
        previous = self.repo.previous_rule(company_id, key)
        if previous:
            if previous.request_fingerprint != digest:
                raise AppError("payment.idempotency_conflict")
            return rule_view(self.repo, previous)
        self._token(company_id, data.expected_configuration_token)
        binding, latest, _ = self.repo.current(company_id)
        if binding is None or binding.id != binding_id:
            raise AppError("payment.configuration_changed")
        if sum(i.rate_bps for i in data.items) > ratio:
            raise AppError("payment.rate_exceeds_channel_limit")
        now = utc_now()
        binding.max_ratio_bps = ratio
        binding.ratio_checked_at = now
        version = ProfitSharingRuleVersion(
            property_company_id=company_id,
            version_no=latest.version_no + 1 if latest else 1,
            calculation_version=1,
            created_by=actor.id,
            idempotency_key=key,
            request_fingerprint=digest,
            created_at=now,
        )
        self.db.add(version)
        self.db.flush()
        for item in data.items:
            self.db.add(
                ProfitSharingRuleVersionItem(
                    rule_version_id=version.id,
                    receiver_type="merchant",
                    receiver_account=self.settings.wechatpay_service_provider_merchant_no,
                    receiver_name=self.settings.wechatpay_platform_receiver_name.get_secret_value(),
                    relation_type="service_provider",
                    rate_bps=item.rate_bps,
                )
            )
        self.db.flush()
        self._audit(actor, "payment.profit_sharing_rule.create", version.id, company_id, request_id)
        self.db.commit()
        return rule_view(self.repo, version)
