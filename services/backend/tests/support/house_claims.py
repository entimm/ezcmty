from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.resident_sessions import ResidentContext, ResidentSessionStore
from backend_app.schemas import house_claims as schema
from backend_app.schemas.housing import HouseCreate, HouseOwnerCreate
from backend_app.schemas.miniapp import MiniappLogin, PhoneBindingCreate
from backend_app.services.property_admin.housing import PropertyHousingService
from backend_app.services.resident.house_claims import ResidentHouseClaimService
from backend_app.services.resident.identity import ResidentIdentityService
from tests.support.housing_services import HousingSetup, provision_housing
from tests.support.resident import FakeWechat


@dataclass
class ClaimSetup:
    factory: sessionmaker[Session]
    housing: HousingSetup
    context: ResidentContext
    claim: schema.ResidentHouseClaim
    phone_id: str


def provision_claim(
    factory: sessionmaker[Session],
    admin_store: AdminSessionStore,
    *,
    business_accounts: bool = False,
) -> ClaimSetup:
    housing = provision_housing(factory, admin_store, business_accounts=business_accounts)
    store = ResidentSessionStore(admin_store.client, admin_store.settings)
    wechat = FakeWechat()
    wechat.phones["phone"] = "13800138000"
    with factory() as db:
        house = PropertyHousingService(db).create_house(
            housing.context,
            housing.community_id,
            HouseCreate(
                space_node_id=housing.node_id,
                room_no="101",
                owners=[HouseOwnerCreate(name="张三", phone="13800138000")],
            ),
            "house",
        )
        svc = ResidentIdentityService(db)
        login = svc.login(MiniappLogin(code="resident"), store, wechat, "test")
        ctx = store.authenticate(login.token)
        phone = svc.bind_phone(
            ctx, PhoneBindingCreate(code="phone"), "phone", "phone", store, wechat
        )
        claim, _ = ResidentHouseClaimService(db).create(
            ctx,
            schema.HouseClaimCreate(
                house_id=house.id, applicant_name="张三", phone_binding_id=phone.id
            ),
            "claim",
        )
    return ClaimSetup(factory, housing, ctx, claim, phone.id)
