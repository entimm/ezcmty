from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.models.admin import AdminAccount
from backend_app.schemas import housing as schema
from backend_app.schemas import property as property_schema
from backend_app.services.contracts.admin import AdminContext
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.platform_admin.property import PropertyOnboardingService
from backend_app.services.property_admin.admin import PropertyAdminService
from backend_app.services.property_admin.housing import PropertyHousingService
from tests.support.admin_data import create_super_admin
from tests.support.admin_services import PASSWORD, platform_token


@dataclass
class HousingSetup:
    platform_token: str
    token: str
    context: AdminContext
    company_id: str
    community_id: str
    node_id: str


def provision_housing(
    factory: sessionmaker[Session],
    store: AdminSessionStore,
    *,
    business_accounts: bool = False,
) -> HousingSetup:
    if business_accounts:
        with factory() as db:
            actor = create_super_admin(
                db,
                scope="platform_admin",
                login_name="root",
                display_name="平台",
                password=PASSWORD,
            )
            db.commit()
            platform, _ = store.create("platform_admin", actor.id, actor.session_version)
    else:
        platform = platform_token(factory, store)
    with factory() as db:
        context = PlatformAdminService(db).authenticate(store, platform)
        service = PropertyOnboardingService(db)
        company = service.create_company(
            context, property_schema.CompanyCreate(code="HOUSING", name="公司"), "company"
        )
        community = service.create_community(
            context,
            property_schema.CommunityCreate(
                property_company_id=company.id, code="HOUSING", name="小区", address="地址"
            ),
            "community",
        )
        if business_accounts:
            model = create_super_admin(
                db,
                scope="property_admin",
                property_company_id=company.id,
                login_name="housing",
                display_name="管理员",
                password=PASSWORD,
            )
        else:
            account = service.create_admin(
                context,
                company.id,
                property_schema.PropertyAdminCreate(
                    login_name="housing", display_name="管理员", password=PASSWORD
                ),
                "account",
            )
            service.create_admin(
                context,
                company.id,
                property_schema.PropertyAdminCreate(
                    login_name="backup", display_name="另一管理员", password=PASSWORD
                ),
                "backup",
            )
            existing = db.get(AdminAccount, account.id)
            assert existing
            model = existing
        service.update_company(
            context, company.id, property_schema.CompanyUpdate(enabled=True), "enable"
        )
        model.must_change_password = False
        db.commit()
        token, _ = store.create("property_admin", model.id, model.session_version)
        property_context = PropertyAdminService(db).authenticate(store, token)
        node = PropertyHousingService(db).create_node(
            property_context,
            community.id,
            schema.SpaceNodeCreate(node_type="building", name="楼栋"),
            "node",
        )
        return HousingSetup(platform, token, property_context, company.id, community.id, node.id)
