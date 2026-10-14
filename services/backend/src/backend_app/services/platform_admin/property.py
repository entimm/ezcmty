from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend_app.core.admin_security import hash_password
from backend_app.core.errors import AppError
from backend_app.domain.admin.identity import AdminIdentity
from backend_app.models.admin import AdminAccount, AdminRole, utc_now
from backend_app.models.property import Community, PropertyCompany
from backend_app.repositories.admin import AdminRepository
from backend_app.repositories.property import PropertyRepository
from backend_app.schemas import admin as admin_schema
from backend_app.schemas import property as schema
from backend_app.schemas.mappers.property import community_view, property_admin_view
from backend_app.services.contracts.admin import AdminContext


class PropertyOnboardingService:
    """Platform operations retain their platform actor while provisioning company identities."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = PropertyRepository(db)
        self.identity = AdminIdentity(AdminRepository(db, "platform_admin"))

    def _business_writer(self, context: AdminContext, permission: str) -> AdminAccount:
        actor = self.identity.actor(context)
        if actor.must_change_password:
            raise AppError("auth.password_change_required")
        if permission not in self.identity.effective_permissions(actor.id):
            raise AppError("auth.forbidden")
        return actor

    def _company(self, company_id: str, *, lock: bool = False) -> PropertyCompany:
        company = self.repo.company(company_id, lock=lock)
        if company is None:
            raise AppError("resource.not_found")
        return company

    def _community(self, community_id: str, *, lock: bool = False) -> Community:
        community = self.repo.community(community_id, lock=lock)
        if community is None:
            raise AppError("resource.not_found")
        return community

    def _audit(
        self,
        actor: AdminAccount,
        action: str,
        target_type: str,
        target_id: str,
        company_id: str,
        request_id: str,
        changed_fields: list[str] | None = None,
    ) -> None:
        self.identity.audit.record(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            property_company_id=company_id,
            metadata={"changed_fields": changed_fields or []},
        )

    def get_company(self, context: AdminContext, company_id: str) -> schema.PropertyCompany:
        self.identity.require_permission(context, "property.company.read")
        return schema.PropertyCompany.model_validate(self._company(company_id))

    def list_companies(self, context: AdminContext, **filters: Any) -> schema.CompanyPage:
        self.identity.require_permission(context, "property.company.read")
        items, total = self.repo.companies(**filters)
        return schema.CompanyPage(
            items=[schema.PropertyCompany.model_validate(item) for item in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def create_company(
        self,
        context: AdminContext,
        data: schema.CompanyCreate,
        request_id: str,
    ) -> schema.PropertyCompany:
        actor = self._business_writer(context, "property.company.create")
        if self.repo.company_by_code(data.code):
            raise AppError("property.duplicate_company_code")
        now = utc_now()
        company = PropertyCompany(
            **data.model_dump(), enabled=False, created_at=now, updated_at=now
        )
        self.db.add(company)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if self.repo.company_by_code(data.code):
                raise AppError("property.duplicate_company_code") from exc
            raise
        self._audit(
            actor, "property.company.create", "property_company", company.id, company.id, request_id
        )
        self.db.commit()
        return schema.PropertyCompany.model_validate(company)

    def update_company(
        self,
        context: AdminContext,
        company_id: str,
        data: schema.CompanyUpdate,
        request_id: str,
    ) -> schema.PropertyCompany:
        actor = self._business_writer(context, "property.company.update")
        company = self._company(company_id, lock=True)
        changes: list[str] = []
        if data.enabled is not None and data.enabled != company.enabled:
            company_admins = AdminRepository(self.db, "property_admin", company_id)
            system = company_admins.role_by_code("super_admin", lock=True)
            if data.enabled and (
                system is None
                or not system.enabled
                or not system.is_system
                or not company_admins.active_super_accounts(system.id)
            ):
                raise AppError("property.company_admin_required")
            company.enabled = data.enabled
            if not data.enabled:
                self.repo.invalidate_company_accounts(company_id)
            changes.append("enabled")
        for field in ("name", "contact_name", "contact_phone"):
            if field not in data.model_fields_set:
                continue
            value = getattr(data, field)
            if field == "name" and value is None:
                continue
            if value != getattr(company, field):
                setattr(company, field, value)
                changes.append(field)
        if changes:
            company.updated_at = utc_now()
        self._audit(
            actor,
            "property.company.update",
            "property_company",
            company.id,
            company.id,
            request_id,
            changes,
        )
        self.db.commit()
        return schema.PropertyCompany.model_validate(company)

    def community_view(
        self, community: Community, company_name: str | None = None
    ) -> schema.Community:
        name = (
            company_name
            if company_name is not None
            else self._company(community.property_company_id).name
        )
        return community_view(community, name)

    def get_community(self, context: AdminContext, community_id: str) -> schema.Community:
        self.identity.require_permission(context, "property.community.read")
        return self.community_view(self._community(community_id))

    def list_communities(self, context: AdminContext, **filters: Any) -> schema.CommunityPage:
        self.identity.require_permission(context, "property.community.read")
        items, total = self.repo.communities(**filters)
        return schema.CommunityPage(
            items=[self.community_view(item, company_name) for item, company_name in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def create_community(
        self,
        context: AdminContext,
        data: schema.CommunityCreate,
        request_id: str,
    ) -> schema.Community:
        actor = self._business_writer(context, "property.community.create")
        company = self._company(data.property_company_id, lock=True)
        if self.repo.community_by_code(data.code):
            raise AppError("property.duplicate_community_code")
        now = utc_now()
        community = Community(**data.model_dump(), enabled=True, created_at=now, updated_at=now)
        self.db.add(community)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if self.repo.community_by_code(data.code):
                raise AppError("property.duplicate_community_code") from exc
            raise
        self._audit(
            actor, "property.community.create", "community", community.id, company.id, request_id
        )
        self.db.commit()
        return self.community_view(community)

    def update_community(
        self,
        context: AdminContext,
        community_id: str,
        data: schema.CommunityUpdate,
        request_id: str,
    ) -> schema.Community:
        actor = self._business_writer(context, "property.community.update")
        community = self._community(community_id, lock=True)
        changes: list[str] = []
        for field, value in data.model_dump(exclude_none=True).items():
            if value != getattr(community, field):
                setattr(community, field, value)
                changes.append(field)
        if changes:
            community.updated_at = utc_now()
        self._audit(
            actor,
            "property.community.update",
            "community",
            community.id,
            community.property_company_id,
            request_id,
            changes,
        )
        self.db.commit()
        return self.community_view(community)

    def _admin_view(
        self, repo: AdminRepository, account: AdminAccount
    ) -> schema.PropertyAdminAccount:
        return property_admin_view(account, repo.account_roles(account.id))

    def get_admin(
        self, context: AdminContext, company_id: str, account_id: str
    ) -> schema.PropertyAdminAccount:
        self.identity.require_permission(context, "property.admin.read")
        self._company(company_id)
        repo = AdminRepository(self.db, "property_admin", company_id)
        account = repo.account(account_id)
        if account is None:
            raise AppError("resource.not_found")
        return self._admin_view(repo, account)

    def list_admins(
        self, context: AdminContext, company_id: str, **filters: Any
    ) -> schema.PropertyAdminPage:
        self.identity.require_permission(context, "property.admin.read")
        self._company(company_id)
        repo = AdminRepository(self.db, "property_admin", company_id)
        items, total = repo.accounts(**filters)
        return schema.PropertyAdminPage(
            items=[self._admin_view(repo, account) for account in items],
            total=total,
            page=filters["page"],
            page_size=filters["page_size"],
        )

    def create_admin(
        self,
        context: AdminContext,
        company_id: str,
        data: schema.PropertyAdminCreate,
        request_id: str,
    ) -> schema.PropertyAdminAccount:
        actor, _ = self.identity.management_writer(context)
        self._company(company_id, lock=True)
        repo = AdminRepository(self.db, "property_admin", company_id)
        if repo.identity_by_login(data.login_name):
            raise AppError("admin.duplicate_login")
        # The company row serializes initial provisioning before a system role exists.
        role = repo.role_by_code("super_admin", lock=True)
        if role is None:
            role = AdminRole(
                scope="property_admin",
                property_company_id=company_id,
                code="super_admin",
                name="公司超级管理员",
                enabled=True,
                is_system=True,
            )
            self.db.add(role)
            self.db.flush()
        elif not role.enabled or not role.is_system:
            raise AppError("resource.conflict", public_detail="公司系统角色不可用")
        account = AdminAccount(
            scope="property_admin",
            property_company_id=company_id,
            login_name=data.login_name,
            display_name=data.display_name,
            password_hash=hash_password(data.password),
        )
        self.db.add(account)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            if repo.identity_by_login(data.login_name):
                raise AppError("admin.duplicate_login") from exc
            raise
        repo.replace_roles(account.id, {role.id})
        self._audit(actor, "property.admin.create", "account", account.id, company_id, request_id)
        self.db.commit()
        return self._admin_view(repo, account)

    def update_admin(
        self,
        context: AdminContext,
        company_id: str,
        account_id: str,
        data: admin_schema.AccountUpdate,
        request_id: str,
    ) -> schema.PropertyAdminAccount:
        actor, _ = self.identity.management_writer(context)
        self._company(company_id, lock=True)
        repo = AdminRepository(self.db, "property_admin", company_id)
        system = repo.role_by_code("super_admin", lock=True)
        account = repo.account(account_id, lock=True)
        if account is None:
            raise AppError("resource.not_found")
        changes: list[str] = []
        if data.enabled is not None and data.enabled != account.enabled:
            if not data.enabled and system and system.enabled:
                supers = repo.active_super_accounts(system.id)
                if any(item.id == account.id for item in supers) and len(supers) <= 1:
                    raise AppError("admin.last_super_admin")
            account.enabled = data.enabled
            account.session_version += 1
            changes.append("enabled")
        if data.display_name is not None and data.display_name != account.display_name:
            account.display_name = data.display_name
            changes.append("display_name")
        self._audit(
            actor, "property.admin.update", "account", account.id, company_id, request_id, changes
        )
        self.db.commit()
        return self._admin_view(repo, account)

    def reset_admin_password(
        self,
        context: AdminContext,
        company_id: str,
        account_id: str,
        data: admin_schema.PasswordReset,
        request_id: str,
    ) -> None:
        actor, _ = self.identity.management_writer(context)
        self._company(company_id, lock=True)
        repo = AdminRepository(self.db, "property_admin", company_id)
        account = repo.account(account_id, lock=True)
        if account is None:
            raise AppError("resource.not_found")
        account.password_hash = hash_password(data.password)
        account.must_change_password = True
        account.session_version += 1
        self._audit(
            actor, "property.admin.password_reset", "account", account.id, company_id, request_id
        )
        self.db.commit()
