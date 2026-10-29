from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend_app.core.identifiers import normalize_login_name
from backend_app.domain.admin.types import AdminScope
from backend_app.models.admin import (
    AdminAccount,
    AdminAccountRole,
    AdminAuditLog,
    AdminRole,
    AdminRolePermission,
)
from backend_app.repositories.pagination import read_page


class AdminRepository:
    def __init__(self, db: Session, scope: AdminScope, property_company_id: str | None = None):
        self.db = db
        self.scope = scope
        self.property_company_id = property_company_id

    def identity(self, account_id: str) -> AdminAccount | None:
        """Resolve an identity for authentication before its trusted company is known."""
        return self.db.scalar(
            select(AdminAccount).where(
                AdminAccount.scope == self.scope, AdminAccount.id == account_id
            )
        )

    def identity_by_login(self, login_name: str) -> AdminAccount | None:
        return self.db.scalar(
            select(AdminAccount).where(
                AdminAccount.scope == self.scope,
                AdminAccount.login_name == normalize_login_name(login_name),
            )
        )

    def account(
        self, account_id: str, *, lock: bool = False, shared: bool = False
    ) -> AdminAccount | None:
        query = select(AdminAccount).where(
            AdminAccount.scope == self.scope,
            AdminAccount.id == account_id,
            AdminAccount.property_company_id == self.property_company_id,
        )
        if lock:
            query = query.with_for_update(read=shared, of=AdminAccount).execution_options(
                populate_existing=True
            )
        return self.db.scalar(query)

    def account_by_login(self, login_name: str) -> AdminAccount | None:
        return self.db.scalar(
            select(AdminAccount).where(
                AdminAccount.scope == self.scope,
                AdminAccount.login_name == normalize_login_name(login_name),
                AdminAccount.property_company_id == self.property_company_id,
            )
        )

    def role(self, role_id: str, *, lock: bool = False) -> AdminRole | None:
        query = select(AdminRole).where(
            AdminRole.scope == self.scope,
            AdminRole.id == role_id,
            AdminRole.property_company_id == self.property_company_id,
        )
        if lock:
            query = query.with_for_update(of=AdminRole).execution_options(populate_existing=True)
        return self.db.scalar(query)

    def role_by_code(self, code: str, *, lock: bool = False) -> AdminRole | None:
        query = select(AdminRole).where(
            AdminRole.scope == self.scope,
            AdminRole.code == code,
            AdminRole.property_company_id == self.property_company_id,
        )
        if lock:
            query = query.with_for_update(of=AdminRole).execution_options(populate_existing=True)
        return self.db.scalar(query)

    def account_roles(self, account_id: str, *, lock: bool = False) -> list[AdminRole]:
        query = (
            select(AdminRole)
            .join(
                AdminAccountRole,
                (AdminAccountRole.scope == AdminRole.scope)
                & (AdminAccountRole.role_id == AdminRole.id),
            )
            .where(
                AdminRole.scope == self.scope,
                AdminAccountRole.account_id == account_id,
                AdminRole.property_company_id == self.property_company_id,
                AdminAccountRole.property_company_id == self.property_company_id,
            )
            .order_by(AdminRole.code)
        )
        if lock:
            query = query.with_for_update(of=AdminRole).execution_options(populate_existing=True)
        return list(self.db.scalars(query))

    def permissions(self, role_id: str, *, lock: bool = False) -> list[str]:
        query = (
            select(AdminRolePermission.permission)
            .join(AdminRole, AdminRole.id == AdminRolePermission.role_id)
            .where(
                AdminRolePermission.scope == self.scope,
                AdminRolePermission.role_id == role_id,
                AdminRole.property_company_id == self.property_company_id,
            )
            .order_by(AdminRolePermission.permission)
        )
        if lock:
            query = query.with_for_update(of=AdminRolePermission)
        return list(self.db.scalars(query))

    def replace_roles(self, account_id: str, role_ids: set[str]) -> None:
        self.db.execute(
            delete(AdminAccountRole).where(
                AdminAccountRole.scope == self.scope, AdminAccountRole.account_id == account_id
            )
        )
        self.db.add_all(
            [
                AdminAccountRole(
                    scope=self.scope,
                    account_id=account_id,
                    role_id=rid,
                    property_company_id=self.property_company_id,
                )
                for rid in sorted(role_ids)
            ]
        )
        self.db.flush()

    def replace_permissions(self, role_id: str, permissions: set[str]) -> None:
        self.db.execute(
            delete(AdminRolePermission).where(
                AdminRolePermission.scope == self.scope, AdminRolePermission.role_id == role_id
            )
        )
        self.db.add_all(
            [
                AdminRolePermission(scope=self.scope, role_id=role_id, permission=code)
                for code in sorted(permissions)
            ]
        )
        self.db.flush()

    def active_super_accounts(self, role_id: str) -> list[AdminAccount]:
        query = (
            select(AdminAccount)
            .join(
                AdminAccountRole,
                (AdminAccountRole.scope == AdminAccount.scope)
                & (AdminAccountRole.account_id == AdminAccount.id),
            )
            .where(
                AdminAccount.scope == self.scope,
                AdminAccount.enabled.is_(True),
                AdminAccount.property_company_id == self.property_company_id,
                AdminAccountRole.role_id == role_id,
            )
            .with_for_update(of=AdminAccount)
            .execution_options(populate_existing=True)
        )
        return list(self.db.scalars(query))

    def role_account_count(self, role_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(AdminAccountRole)
                .where(
                    AdminAccountRole.scope == self.scope,
                    AdminAccountRole.role_id == role_id,
                    AdminAccountRole.property_company_id == self.property_company_id,
                )
            )
            or 0
        )

    def invalidate_role_accounts(self, role_id: str) -> None:
        ids = select(AdminAccountRole.account_id).where(
            AdminAccountRole.scope == self.scope, AdminAccountRole.role_id == role_id
        )
        self.db.execute(
            update(AdminAccount)
            .where(
                AdminAccount.scope == self.scope,
                AdminAccount.id.in_(ids),
                AdminAccount.property_company_id == self.property_company_id,
            )
            .values(session_version=AdminAccount.session_version + 1)
        )

    def accounts(
        self, *, page: int, page_size: int, login_name: str | None, enabled: bool | None, sort: str
    ) -> tuple[list[AdminAccount], int]:
        query = select(AdminAccount).where(
            AdminAccount.scope == self.scope,
            AdminAccount.property_company_id == self.property_company_id,
        )
        if login_name:
            query = query.where(
                AdminAccount.login_name.contains(normalize_login_name(login_name), autoescape=True)
            )
        if enabled is not None:
            query = query.where(AdminAccount.enabled == enabled)
        key = "login_name" if sort.lstrip("-") == "login_name" else "created_at"
        return read_page(
            self.db,
            AdminAccount,
            query,
            page=page,
            page_size=page_size,
            order=((key, sort.startswith("-")), ("id", False)),
        )

    def roles(
        self, *, page: int, page_size: int, name: str | None, enabled: bool | None, sort: str
    ) -> tuple[list[AdminRole], int]:
        query = select(AdminRole).where(
            AdminRole.scope == self.scope,
            AdminRole.property_company_id == self.property_company_id,
        )
        if name:
            query = query.where(AdminRole.name.icontains(name, autoescape=True))
        if enabled is not None:
            query = query.where(AdminRole.enabled == enabled)
        key = "name" if sort.lstrip("-") == "name" else "code"
        return read_page(
            self.db,
            AdminRole,
            query,
            page=page,
            page_size=page_size,
            order=((key, sort.startswith("-")), ("id", False)),
        )

    def audit(
        self,
        *,
        actor: AdminAccount | None,
        action: str,
        target_type: str,
        target_id: str | None,
        request_id: str,
        result: str = "success",
        property_company_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Only these non-secret fields may enter the audit JSON.
        allowed = {"changed_fields", "role_ids", "permissions"}
        if action in {"property.house_claim.review", "property.resident_house_binding.revoke"}:
            allowed |= {"status", "match_status", "house_id"}
        if action in {
            "payment.payment_order.recover",
            "payment.reconciliation_run.recover",
            "payment.reconciliation_discrepancy.recover",
        }:
            allowed |= {"reason", "task_id", "evidence"}
        if action == "payment.reconciliation_discrepancy.external_resolution":
            allowed |= {
                "reason",
                "evidence_reference",
                "before",
                "after",
                "source_request_id",
                "source_digest",
            }
        safe = {key: value for key, value in (metadata or {}).items() if key in allowed}
        self.db.add(
            AdminAuditLog(
                scope=self.scope,
                property_company_id=property_company_id,
                actor_id=actor.id if actor else None,
                actor_name=actor.display_name if actor else None,
                action=action,
                target_type=target_type,
                target_id=target_id,
                result=result,
                request_id=request_id,
                safe_metadata=safe,
            )
        )

    def audit_logs(
        self,
        *,
        page: int,
        page_size: int,
        from_time: datetime | None,
        to_time: datetime | None,
        action: str | None,
        result: str | None,
        request_id: str | None,
        sort: str,
    ) -> tuple[list[AdminAuditLog], int]:
        query = select(AdminAuditLog).where(AdminAuditLog.scope == self.scope)
        if self.scope == "property_admin":
            if self.property_company_id is None:
                raise ValueError("Property audit queries require a company context")
            query = query.where(AdminAuditLog.property_company_id == self.property_company_id)
        for column, value in (
            (AdminAuditLog.action, action),
            (AdminAuditLog.result, result),
            (AdminAuditLog.request_id, request_id),
        ):
            if value is not None:
                query = query.where(column == value)
        if from_time is not None:
            query = query.where(AdminAuditLog.created_at >= from_time)
        if to_time is not None:
            query = query.where(AdminAuditLog.created_at <= to_time)
        descending = sort.startswith("-")
        return read_page(
            self.db,
            AdminAuditLog,
            query,
            page=page,
            page_size=page_size,
            order=(("created_at", descending), ("id", descending)),
        )
