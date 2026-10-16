from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
}
EXCLUDED_TABLES = {
    "alembic_version": "Alembic migration bookkeeping",
    "property_fee_basis_versions": "Billing versions are maintained through the billing workflow",
    "bills": "Billing scenarios are entered through the billing workflow",
    "bill_operations": "Immutable results are created atomically by billing operations",
    "bill_settlement_entries": "Immutable entries are created atomically by billing operations",
}


class Plan(Parameters):
    scenarios: list[str]
    parameters: dict[str, dict[str, int]]
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
            if "housing" in self.scenarios:
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
            raw.setdefault(name, {})[key] = int(value)
        except ValueError, TypeError:
            raise SeedError("--set 必须为已选择场景的 scene.parameter=整数") from None
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
            f"{name}.{key}={value}"
            for name, values in plan.parameters.items()
            for key, value in values.items()
        ],
        workers=plan.workers,
    )
    if resolved.parameters != plan.parameters or resolved.versions != plan.versions:
        raise SeedError("保存的场景参数或依赖不完整")
