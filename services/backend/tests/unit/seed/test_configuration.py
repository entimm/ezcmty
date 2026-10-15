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
