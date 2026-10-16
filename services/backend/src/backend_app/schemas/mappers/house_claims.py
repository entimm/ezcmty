from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.schemas import house_claims as schema


def resident_claim_view(item: HouseClaim) -> schema.ResidentHouseClaim:
    return schema.ResidentHouseClaim.model_validate(item)


def property_claim_view(item: HouseClaim) -> schema.PropertyHouseClaim:
    return schema.PropertyHouseClaim.model_validate(item)


def resident_binding_view(
    item: ResidentHouseBinding, claim: HouseClaim, effective_enabled: bool
) -> schema.ResidentHouseBinding:
    data = {
        name: getattr(item, name)
        for name in schema.ResidentHouseBinding.model_fields
        if name not in {"house_label_snapshot", "effective_enabled"}
    }
    return schema.ResidentHouseBinding(
        **data, house_label_snapshot=claim.house_label_snapshot, effective_enabled=effective_enabled
    )


def property_binding_view(
    item: ResidentHouseBinding, claim: HouseClaim, effective_enabled: bool
) -> schema.PropertyHouseBinding:
    return schema.PropertyHouseBinding(
        **resident_binding_view(item, claim, effective_enabled).model_dump(),
        property_company_id=item.property_company_id,
        user_id=item.user_id,
        applicant_name=claim.applicant_name,
        applicant_phone=claim.applicant_phone,
    )
