"""Business permissions, their fixed read dependencies and role presets."""

from collections.abc import Iterable
from dataclasses import dataclass

from backend_app.core.errors import AppError
from backend_app.domain.admin.types import AdminScope


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    name: str
    group: str
    assignable: bool
    level: str = "查看"
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoleTemplateDefinition:
    code: str
    name: str
    permissions: tuple[str, ...]


def permission_prefix(scope: AdminScope) -> str:
    return "platform" if scope == "platform_admin" else "property"


def permission_catalog(scope: AdminScope) -> list[PermissionDefinition]:
    prefix = permission_prefix(scope)
    common = [
        ("system.read", "查看系统资料", "系统资料", "查看", ()),
        ("system.manage", "管理账号、角色与授权", "系统管理", "系统管理", ("system.read",)),
        ("audit.read", "查看操作日志", "操作日志", "查看", ()),
    ]
    if scope == "platform_admin":
        definitions = [
            ("onboarding.read", "查看物业接入资料", "物业接入", "查看", ()),
            ("onboarding.manage", "维护物业接入资料", "物业接入", "维护", ("onboarding.read",)),
            ("onboarding.toggle", "启停物业公司", "关键操作", "关键操作", ("onboarding.read",)),
            ("payment.read", "查看支付资金", "支付资金", "查看", ()),
            ("payment_reconciliation.read", "查看资金核对", "资金核对", "查看", ()),
            (
                "payment_reconciliation.manage",
                "重新核对资金",
                "资金核对",
                "经办",
                ("payment_reconciliation.read",),
            ),
            ("payment_config.read", "查看收款配置", "收款配置", "查看", ()),
            ("payment_config.manage", "维护收款配置", "收款配置", "维护", ("payment_config.read",)),
            (
                "payment.recover",
                "处理资金异常",
                "关键操作",
                "关键操作",
                ("payment.read", "payment_reconciliation.read"),
            ),
        ]
    else:
        definitions = [
            ("housing.read", "查看房产资料", "房产资料", "查看", ()),
            ("housing.manage", "维护房产资料", "房产资料", "维护", ("housing.read",)),
            ("bill.read", "查看账单及计费依据", "物业费账单", "查看", ()),
            ("bill.manage", "经办账单", "物业费账单", "经办", ("bill.read",)),
            ("fee_basis.manage", "维护计费依据", "计费依据", "维护", ("bill.read",)),
            ("bill_receipt.create", "登记线下收款", "线下收款", "登记", ("bill.read",)),
            ("bill.void", "作废账单", "关键操作", "关键操作", ("bill.read",)),
            ("bill_receipt.correct", "纠正或撤销收款", "关键操作", "关键操作", ("bill.read",)),
            ("resident_access.read", "查看居民房屋授权", "居民房屋授权", "查看", ()),
            (
                "resident_access.review",
                "审核房屋认领",
                "居民房屋授权",
                "审核",
                ("resident_access.read",),
            ),
            (
                "resident_access.revoke",
                "撤销居民房屋授权",
                "关键操作",
                "关键操作",
                ("resident_access.read",),
            ),
            ("payment.read", "查看线上收款", "线上收款", "查看", ()),
        ]
    return [
        PermissionDefinition(
            code=f"{prefix}.{code}",
            name=name,
            group=group,
            assignable=code != "system.manage",
            level=level,
            requires=tuple(f"{prefix}.{dependency}" for dependency in required),
        )
        for code, name, group, level, required in definitions + common
    ]


def normalize_permissions(scope: AdminScope, permissions: Iterable[str]) -> list[str]:
    """Validate assignable input and include only the fixed required read abilities."""
    catalog = {item.code: item for item in permission_catalog(scope) if item.assignable}
    codes = set(permissions)
    if not codes <= catalog.keys():
        raise AppError("admin.invalid_permission")
    pending = list(codes)
    while pending:
        for dependency in catalog[pending.pop()].requires:
            if dependency not in codes:
                codes.add(dependency)
                pending.append(dependency)
    return sorted(codes)


def role_templates(scope: AdminScope) -> list[RoleTemplateDefinition]:
    prefix = permission_prefix(scope)
    if scope == "platform_admin":
        financial = (
            "onboarding.read",
            "payment.read",
            "payment_reconciliation.read",
            "payment_config.read",
        )
        definitions = [
            ("onboarding_operator", "接入运营", ("onboarding.manage",)),
            ("financial_reader", "财务查询", financial),
            ("financial_operator", "财务经办", (*financial, "payment_reconciliation.manage")),
        ]
    else:
        definitions = [
            ("housing_operator", "资料专员", ("housing.manage",)),
            ("cashier", "收费员", ("bill.manage", "bill_receipt.create", "payment.read")),
            (
                "resident_reviewer",
                "客服审核员",
                ("housing.read", "bill.read", "resident_access.review"),
            ),
        ]
    return [
        RoleTemplateDefinition(
            code=code,
            name=name,
            permissions=tuple(
                normalize_permissions(scope, (f"{prefix}.{item}" for item in permissions))
            ),
        )
        for code, name, permissions in definitions
    ]
