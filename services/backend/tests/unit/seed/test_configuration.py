from pathlib import Path

import pytest
from devtools.seed.bootstrap import SeedSettings
from devtools.seed.config import SeedError, resolve_plan
from devtools.seed.runner import guard
from pydantic import ValidationError

from backend_app.core.config import Settings


def test_housing_supplies_minimal_prerequisites_and_exact_counts() -> None:
    plan = resolve_plan(["housing"], overrides=["housing.houses_per_unit=20"])
    assert plan.parameters["property"] == {
        "companies": 1,
        "communities_per_company": 1,
        "admins_per_company": 1,
    }
    assert plan.counts()["houses"] == 82
    assert plan.counts()["owners"] == 164


def test_command_parameters_override_toml(tmp_path: Path) -> None:
    config = tmp_path / "seed.toml"
    config.write_text("[admin]\naccounts=5\nroles=3\n")
    plan = resolve_plan(["admin"], config=config, overrides=["admin.accounts=8"])
    assert plan.parameters["admin"] == {"accounts": 8, "roles": 3}


@pytest.mark.parametrize(
    "override", ["admin.unknown=1", "other.accounts=1", "admin.accounts=x", "accounts=1"]
)
def test_rejects_invalid_overrides(override: str) -> None:
    with pytest.raises(SeedError):
        resolve_plan(["admin"], overrides=[override])


@pytest.mark.parametrize(
    "override", ["admin.accounts=-1", "admin.roles=0", "admin.accounts=100001"]
)
def test_rejects_out_of_range_counts(override: str) -> None:
    with pytest.raises(ValidationError):
        resolve_plan(["admin"], overrides=[override])


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_non_development_environment_is_rejected(environment: str) -> None:
    settings = Settings().model_copy(update={"env": environment})
    with pytest.raises(SeedError, match="APP_ENV"):
        guard(settings, SeedSettings(enabled=True))


def test_default_environment_and_missing_opt_in_are_rejected() -> None:
    settings = Settings()
    settings.__pydantic_fields_set__.discard("env")
    with pytest.raises(SeedError, match="显式"):
        guard(settings, SeedSettings(enabled=True))
    settings = settings.model_copy(update={"env": "test"})
    with pytest.raises(SeedError, match="SEED_ENABLED"):
        guard(settings, SeedSettings(enabled=False))


def test_every_mapped_business_table_has_a_declared_scenario() -> None:
    from devtools.seed.config import EXCLUDED_TABLES, REGISTRY

    from backend_app.db.base import Base
    from backend_app.models import admin, housing, property  # noqa: F401

    declared = set().union(*(scenario.tables for scenario in REGISTRY.values()))
    assert set(Base.metadata.tables) - EXCLUDED_TABLES.keys() <= declared


def test_invalid_saved_dependencies_are_rejected_before_execution() -> None:
    from devtools.seed.config import validate_plan

    plan = resolve_plan(["housing"])
    del plan.parameters["property"]
    del plan.versions["property"]
    with pytest.raises(SeedError, match="依赖不完整"):
        validate_plan(plan)


def test_billing_uses_dependencies_and_accepts_per_object_counts(tmp_path: Path) -> None:
    config = tmp_path / "billing.toml"
    config.write_text(
        '[billing]\nstart_month="2026-01"\nend_month="2026-06"\nbasis_versions_per_house=5\n'
    )
    plan = resolve_plan(
        ["billing"],
        config=config,
        overrides=[
            "property.companies=2",
            "housing.houses_per_unit=4",
            "housing.owners_per_house=1",
            "billing.bill_months_per_house=3",
            "billing.additional_receipts_per_bill=3",
            "billing.amount_corrections_per_bill=2",
            "billing.date_corrections_per_bill=3",
            "billing.reversals_per_bill=2",
            "billing.rebuilds_per_bill=2",
        ],
    )
    assert list(plan.parameters) == ["property", "housing", "billing"]
    assert plan.counts()["houses"] == 36
    assert plan.counts()["owners"] == 36
    assert plan.counts()["property_fee_basis_versions"] == 180
    from devtools.seed.config import validate_plan

    validate_plan(plan)


@pytest.mark.parametrize(
    "override",
    [
        "billing.start_month=2026-13",
        "billing.end_month=2026-07",
        "billing.bill_months_per_house=6",
        "billing.basis_versions_per_house=-1",
        "billing.min_receivable_cents=60000",
        "billing.additional_receipts_per_bill=21",
        "billing.max_receivable_cents=2",
    ],
)
def test_invalid_billing_ranges_and_counts_are_rejected(override: str) -> None:
    with pytest.raises(ValidationError):
        resolve_plan(
            ["billing"],
            overrides=[
                "billing.start_month=2026-08",
                "billing.end_month=2026-12",
                override,
            ],
        )


def test_billing_rejects_an_empty_status_distribution() -> None:
    with pytest.raises(ValidationError):
        resolve_plan(
            ["billing"],
            overrides=[
                "billing.unpaid_weight=0",
                "billing.partially_settled_weight=0",
                "billing.settled_weight=0",
                "billing.voided_weight=0",
            ],
        )


def test_saved_billing_months_do_not_drift_on_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    from devtools.seed import config

    monkeypatch.setattr(config, "business_today", lambda: date(2026, 10, 16))
    plan = resolve_plan(["billing"])
    assert plan.parameters["billing"]["start_month"] == "2026-08"
    monkeypatch.setattr(config, "business_today", lambda: date(2027, 1, 1))
    config.validate_plan(plan)
    assert plan.parameters["billing"]["end_month"] == "2026-12"


def test_billing_can_generate_only_bases_or_only_manual_bills() -> None:
    from devtools.seed.config import validate_plan

    bases_only = resolve_plan(["billing"], overrides=["billing.bill_months_per_house=0"])
    assert bases_only.counts()["bills"] == 0
    assert bases_only.counts()["property_fee_basis_versions"] == 56
    manual_only = resolve_plan(["billing"], overrides=["billing.basis_versions_per_house=0"])
    assert manual_only.counts()["property_fee_basis_versions"] == 0
    assert manual_only.counts()["bills"] > 0
    validate_plan(manual_only)
