from backend_app.core.config import Settings
from backend_app.domain.payments.configuration import configuration_reasons
from backend_app.models.payments import ProfitSharingRuleVersion
from backend_app.repositories.payments.configuration import ConfigurationRepository
from backend_app.schemas.payments import configuration as schema


def rule_view(
    repo: ConfigurationRepository, rule: ProfitSharingRuleVersion
) -> schema.ProfitSharingRuleVersion:
    return schema.ProfitSharingRuleVersion(
        id=rule.id,
        property_company_id=rule.property_company_id,
        version_no=rule.version_no,
        calculation_version=1,
        items=[schema.ProfitSharingRuleItem.model_validate(i) for i in repo.items(rule.id)],
        created_at=rule.created_at,
    )


def configuration_view(
    repo: ConfigurationRepository, company_id: str, settings: Settings
) -> schema.PaymentConfiguration:
    company = repo.company(company_id)
    binding, rule, items = repo.current(company_id)
    ready = binding is not None and repo.receiver_ready(
        binding.id, settings.wechatpay_service_provider_merchant_no
    )
    reasons = configuration_reasons(
        company, binding, rule, items, settings=settings, receiver_ready=ready
    )
    return schema.PaymentConfiguration(
        property_company_id=company_id,
        configuration_token=repo.configuration_token(company_id),
        ready=not reasons,
        reasons=reasons,
        current_binding=schema.MerchantBinding.model_validate(binding) if binding else None,
        current_rule=rule_view(repo, rule) if rule else None,
    )
