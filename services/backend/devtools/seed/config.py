from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend_app.domain.billing import MAX_CENTS, business_today
from backend_app.schemas.billing import Month


class SeedError(Exception):
    """A safe, non-secret diagnostic suitable for CLI output."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class AdminParameters(Parameters):
    accounts: int = Field(default=3, ge=0, le=100_000)
    roles: int = Field(default=2, ge=1, le=10_000)


class PropertyParameters(Parameters):
    companies: int = Field(default=2, ge=1, le=10_000)
    communities_per_company: int = Field(default=2, ge=1, le=10_000)
    admins_per_company: int = Field(default=3, ge=1, le=10_000)


class HousingParameters(Parameters):
    phases_per_community: int = Field(default=1, ge=0, le=100)
    buildings_per_community: int = Field(default=2, ge=1, le=10_000)
    units_per_building: int = Field(default=2, ge=0, le=100)
    houses_per_unit: int = Field(default=3, ge=0, le=100_000)
    houses_per_building: int = Field(default=1, ge=0, le=100_000)
    owners_per_house: int = Field(default=2, ge=0, le=100)


def shifted_month(offset: int) -> str:
    today = business_today()
    number = today.year * 12 + today.month - 1 + offset
    return f"{number // 12:04d}-{number % 12 + 1:02d}"


class BillingParameters(Parameters):
    start_month: Month = Field(default_factory=lambda: shifted_month(-2))
    end_month: Month = Field(default_factory=lambda: shifted_month(2))
    basis_versions_per_house: int = Field(default=4, ge=0, le=100)
    bill_months_per_house: int | None = Field(default=None, ge=0, le=120)
    min_receivable_cents: int = Field(default=10_000, ge=2, le=MAX_CENTS)
    max_receivable_cents: int = Field(default=50_000, ge=2, le=MAX_CENTS)
    unpaid_weight: int = Field(default=4, ge=0, le=100)
    partially_settled_weight: int = Field(default=2, ge=0, le=100)
    settled_weight: int = Field(default=3, ge=0, le=100)
    voided_weight: int = Field(default=1, ge=0, le=100)
    additional_receipts_per_bill: int = Field(default=2, ge=0, le=20)
    amount_corrections_per_bill: int = Field(default=1, ge=0, le=20)
    date_corrections_per_bill: int = Field(default=1, ge=0, le=20)
    reversals_per_bill: int = Field(default=1, ge=0, le=20)
    rebuilds_per_bill: int = Field(default=1, ge=0, le=10)

    def months(self) -> list[str]:
        start = date.fromisoformat(self.start_month + "-01")
        end = date.fromisoformat(self.end_month + "-01")
        first = start.year * 12 + start.month - 1
        last = end.year * 12 + end.month - 1
        return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(first, last + 1)]

    @model_validator(mode="after")
    def valid_distribution(self) -> Self:
        months = self.months()
        if not 1 <= len(months) <= 120:
            raise ValueError("账单月份范围必须按先后顺序包含 1–120 个月")
        if self.bill_months_per_house is not None and self.bill_months_per_house > len(months):
            raise ValueError("每房账单月份数不能超过月份范围")
        if self.min_receivable_cents > self.max_receivable_cents:
            raise ValueError("最小金额不能超过最大金额")
        if self.min_receivable_cents < 4 * (self.additional_receipts_per_bill + 1):
            raise ValueError("最小正金额不足以分配指定次数的收款与金额纠错")
        if not sum(
            (
                self.unpaid_weight,
                self.partially_settled_weight,
                self.settled_weight,
                self.voided_weight,
            )
        ):
            raise ValueError("账单状态权重不能全部为零")
        return self


@dataclass(frozen=True)
class Scenario:
    parameters: type[Parameters]
    tables: frozenset[str]
    dependencies: tuple[str, ...] = ()
    version: int = 1


REGISTRY = {
    "admin": Scenario(
        AdminParameters,
        frozenset(
            {
                "admin_accounts",
                "admin_roles",
                "admin_account_roles",
                "admin_role_permissions",
                "admin_audit_logs",
            }
        ),
        version=2,
    ),
    "property": Scenario(
        PropertyParameters,
        frozenset(
            {
                "property_companies",
                "communities",
                "admin_accounts",
                "admin_roles",
                "admin_account_roles",
                "admin_audit_logs",
            }
        ),
    ),
    "housing": Scenario(
        HousingParameters,
        frozenset(
            {
                "community_space_nodes",
                "houses",
                "house_owners",
                "admin_audit_logs",
            }
        ),
        ("property",),
    ),
    "billing": Scenario(
        BillingParameters,
        frozenset(
            {
                "property_fee_basis_versions",
                "bills",
                "bill_operations",
                "bill_settlement_entries",
                "admin_audit_logs",
            }
        ),
        ("housing",),
    ),
}
EXCLUDED_TABLES = {
    "import_batches": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "import_requests": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "import_artifacts": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "import_operations": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "import_rows": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "import_issues": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "import_tasks": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "import_batch_events": "通用导入运行事实仅由导入流程生成，不填充生产测试类型",
    "alembic_version": "Alembic migration bookkeeping",
    "house_claim_applications": "认领与审核需由授权用户发起，不在后台开发数据场景中伪造",
    "resident_house_bindings": "房屋授权来源于认领审批，不在后台开发数据场景中伪造",
    "miniapp_users": "微信账号必须经真实授权创建，不在后台开发数据场景中伪造",
    "miniapp_user_identities": "额外身份须由可信业务授予，不在普通开发数据场景中伪造",
    "miniapp_phone_bindings": "手机号授权事实不由开发数据填充生成",
    "miniapp_phone_verifications": "微信成功验证凭据不由开发数据填充生成",
    "property_merchant_bindings": "收款身份由平台核实后配置，普通填充不建立商户绑定",
    "profit_sharing_rule_versions": "真实资金规则只通过平台支付配置发布",
    "profit_sharing_rule_version_items": "接收账号及比例属于完整资金规则，不伪造接收关系",
    "payment_orders": "居民付款事实及原业务单不由普通后台填充创建",
    "payment_order_items": "支付明细必须随真实支付聚合创建",
    "bill_payment_reservations": "占用只能由支付用例建立，不阻塞开发账单",
    "profit_sharing_allocations": "应分事实只能在可信收款入账事务生成",
    "profit_sharing_orders": "普通填充不得触发真实资金分账任务",
    "profit_sharing_order_items": "接收结果由可信渠道查询确认，不伪造到账",
    "payment_unfreeze_orders": "普通填充不得触发真实资金解冻任务",
    "payment_tasks": "资金恢复任务由支付用例创建，不由普通填充生成",
    "payment_channel_requests": "渠道调用证据只能来自实际协议尝试",
    "payment_channel_notifications": "通知证据必须验签，不伪造渠道通知",
    "payment_reconciliation_runs": "资金批次由实际账户与业务日期周期生产",
    "payment_reconciliation_discrepancies": "差异必须有可靠核对依据，不伪造资金异常",
}


class Plan(Parameters):
    scenarios: list[str]
    parameters: dict[str, dict[str, Any]]
    versions: dict[str, int]
    workers: int = Field(default=1, ge=1, le=8)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        if "admin" in self.scenarios:
            a = self.parameters["admin"]
            result.update(platform_accounts=a["accounts"], custom_roles=a["roles"])
        if "property" in self.parameters:
            p = self.parameters["property"]
            companies = p["companies"]
            communities = companies * p["communities_per_company"]
            result.update(
                companies=companies,
                communities=communities,
                property_accounts=companies * p["admins_per_company"],
            )
            if "housing" in self.parameters:
                h = self.parameters["housing"]
                buildings = communities * h["buildings_per_community"]
                units = buildings * h["units_per_building"]
                houses = units * h["houses_per_unit"] + buildings * h["houses_per_building"]
                result.update(
                    phases=communities * h["phases_per_community"],
                    buildings=buildings,
                    units=units,
                    houses=houses,
                    owners=houses * h["owners_per_house"],
                )
                if "billing" in self.parameters:
                    from devtools.seed.billing_plan import estimate

                    result.update(estimate(BillingParameters(**self.parameters["billing"]), houses))
        return result


def resolve_plan(
    scenarios: list[str],
    *,
    config: Path | None = None,
    overrides: list[str] | None = None,
    workers: int = 1,
) -> Plan:
    if not scenarios or any(name not in REGISTRY for name in scenarios):
        raise SeedError("请选择已注册场景，或使用 --all")
    selected = list(dict.fromkeys(scenarios))
    needed: set[str] = set()

    def visit(name: str, path: set[str]) -> None:
        if name in path:
            raise SeedError("场景依赖存在循环")
        if name in needed:
            return
        for dependency in REGISTRY[name].dependencies:
            if dependency not in REGISTRY:
                raise SeedError("场景依赖未注册")
            visit(dependency, path | {name})
        needed.add(name)

    for name in selected:
        visit(name, set())
    raw: dict[str, Any] = {}
    if config:
        with config.open("rb") as stream:
            raw = tomllib.load(stream)
    if set(raw) - needed:
        raise SeedError("配置包含未选择或未知场景")
    # An implicit dependency supplies only the minimal usable prerequisites.
    if "property" in needed and "property" not in selected:
        raw["property"] = {
            "companies": 1,
            "communities_per_company": 1,
            "admins_per_company": 1,
            **raw.get("property", {}),
        }
    for assignment in overrides or []:
        try:
            qualified, value = assignment.split("=", 1)
            name, key = qualified.split(".", 1)
            if name not in needed or key not in REGISTRY[name].parameters.model_fields:
                raise ValueError
            if name == "billing" and key in {"start_month", "end_month"}:
                parsed: Any = value
            elif name == "billing" and key == "bill_months_per_house" and value == "all":
                parsed = None
            else:
                parsed = int(value)
            raw.setdefault(name, {})[key] = parsed
        except ValueError, TypeError:
            raise SeedError(
                "--set 必须为 scene.parameter=整数；月份用 YYYY-MM，月份数量可用 all"
            ) from None
    parameters = {
        name: REGISTRY[name].parameters.model_validate(raw.get(name, {})).model_dump()
        for name in REGISTRY
        if name in needed
    }
    return Plan(
        scenarios=selected,
        parameters=parameters,
        versions={name: REGISTRY[name].version for name in parameters},
        workers=workers,
    )


def validate_plan(plan: Plan) -> None:
    if not plan.scenarios or any(name not in REGISTRY for name in plan.scenarios):
        raise SeedError("保存的场景不可用")
    if plan.versions != {
        name: REGISTRY[name].version for name in plan.parameters if name in REGISTRY
    }:
        raise SeedError("场景版本已变化，请使用原版本续跑或创建新批次")
    for name, values in plan.parameters.items():
        if name not in REGISTRY:
            raise SeedError("保存的场景不可用")
        REGISTRY[name].parameters.model_validate(values)

    resolved = resolve_plan(
        plan.scenarios,
        overrides=[
            f"{name}.{key}={'all' if value is None else value}"
            for name, values in plan.parameters.items()
            for key, value in values.items()
        ],
        workers=plan.workers,
    )
    if resolved.parameters != plan.parameters or resolved.versions != plan.versions:
        raise SeedError("保存的场景参数或依赖不完整")
