from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker
from tests.support.admin_services import PASSWORD
from tests.support.billing_services import BillingSetup

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.models.admin import AdminAccount
from backend_app.models.property import PropertyCompany
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import property as property_schema
from backend_app.schemas.payments import configuration as schema
from backend_app.services.platform_admin.admin import PlatformAdminService
from backend_app.services.platform_admin.payment_configuration import PaymentConfigurationService
from backend_app.services.platform_admin.property import PropertyOnboardingService


@pytest.mark.parametrize(
    "operation",
    [
        "payment_configuration",
        "company_update",
        "community_create",
        "community_update",
        "admin_create",
        "admin_update",
        "admin_password_reset",
    ],
)
def test_company_writers_wait_without_holding_platform_actor(
    billing_setup: BillingSetup,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    operation: str,
) -> None:
    setup = billing_setup

    def write() -> None:
        with setup.factory() as db:
            ctx = PlatformAdminService(db).authenticate(real_admin[1], setup.housing.platform_token)
            service = PropertyOnboardingService(db)
            if operation == "payment_configuration":
                settings = get_settings().model_copy(
                    update={"wechatpay_service_provider_merchant_no": "isolated_platform"}
                )
                config = PaymentConfigurationService(db, settings)
                token = config.get(ctx, setup.housing.company_id).configuration_token
                config.create_binding(
                    ctx,
                    setup.housing.company_id,
                    schema.MerchantBindingCreate(
                        merchant_no="isolated_property",
                        merchant_name="隔离商户",
                        expected_configuration_token=token,
                    ),
                    "lock-order",
                    "lock-order",
                )
            elif operation == "company_update":
                service.update_company(
                    ctx,
                    setup.housing.company_id,
                    property_schema.CompanyUpdate(name="已协调公司"),
                    "lock-order",
                )
            elif operation == "community_create":
                service.create_community(
                    ctx,
                    property_schema.CommunityCreate(
                        property_company_id=setup.housing.company_id,
                        code="LOCK_ORDER",
                        name="小区",
                        address="地址",
                    ),
                    "lock-order",
                )
            elif operation == "community_update":
                service.update_community(
                    ctx,
                    setup.housing.community_id,
                    property_schema.CommunityUpdate(name="已协调小区"),
                    "lock-order",
                )
            elif operation == "admin_create":
                service.create_admin(
                    ctx,
                    setup.housing.company_id,
                    property_schema.PropertyAdminCreate(
                        login_name="lock_order", display_name="管理员", password=PASSWORD
                    ),
                    "lock-order",
                )
            elif operation == "admin_update":
                service.update_admin(
                    ctx,
                    setup.housing.company_id,
                    setup.housing.context.account_id,
                    admin_schema.AccountUpdate(display_name="已协调管理员"),
                    "lock-order",
                )
            else:
                service.reset_admin_password(
                    ctx,
                    setup.housing.company_id,
                    setup.housing.context.account_id,
                    admin_schema.PasswordReset(password=PASSWORD),
                    "lock-order",
                )

    with setup.factory() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        with setup.factory() as db:
            actor_id = (
                PlatformAdminService(db)
                .authenticate(real_admin[1], setup.housing.platform_token)
                .account_id
            )
        assert blocker.scalar(
            select(PropertyCompany)
            .where(PropertyCompany.id == setup.housing.company_id)
            .with_for_update()
        )
        blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(write)
        try:
            with setup.factory() as observer:
                deadline = monotonic() + 5
                while not observer.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"pid": blocker_pid},
                ):
                    assert monotonic() < deadline, "Writer never waited for the company lock"
                    if future.done():
                        future.result()
                # A competing company-first writer can still acquire its actor next;
                # the waiting writer must not create actor -> company inversion.
                assert observer.scalar(
                    select(AdminAccount)
                    .where(AdminAccount.id == actor_id)
                    .with_for_update(nowait=True)
                )
        finally:
            blocker.rollback()
        future.result(timeout=10)


def test_configuration_rechecks_actor_after_company_wait(
    billing_setup: BillingSetup,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    setup = billing_setup

    def write() -> None:
        with setup.factory() as db:
            ctx = PlatformAdminService(db).authenticate(real_admin[1], setup.housing.platform_token)
            svc = PaymentConfigurationService(db, get_settings())
            token = svc.get(ctx, setup.housing.company_id).configuration_token
            svc.activate(
                ctx,
                setup.housing.company_id,
                schema.ActiveMerchantBindingUpdate(
                    binding_id=None, expected_configuration_token=token
                ),
                "actor-revoked",
            )

    with setup.factory() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        assert blocker.scalar(
            select(PropertyCompany)
            .where(PropertyCompany.id == setup.housing.company_id)
            .with_for_update()
        )
        blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(write)
        try:
            with setup.factory() as observer:
                deadline = monotonic() + 5
                while not observer.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"pid": blocker_pid},
                ):
                    assert monotonic() < deadline, "Configuration never waited for company"
                    if future.done():
                        future.result()
                ctx = PlatformAdminService(observer).authenticate(
                    real_admin[1], setup.housing.platform_token
                )
                actor = observer.get(AdminAccount, ctx.account_id)
                assert actor
                actor.session_version += 1
                observer.commit()
        finally:
            blocker.rollback()
        with pytest.raises(AppError) as error:
            future.result(timeout=10)
        assert error.value.code == "auth.unauthenticated"
