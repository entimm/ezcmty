import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from devtools.seed import runner
from devtools.seed.config import SeedError, resolve_plan
from devtools.seed.runtime import Actor
from devtools.seed.state import State
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.support.seed import SeedRun, totals

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.core.errors import AppError
from backend_app.models.billing import Bill, BillOperation, FeeBasisVersion
from backend_app.schemas.billing import BillUpdate
from backend_app.services.property_admin.billing import PropertyBillingService


def test_billing_default_data_covers_required_cases_and_resume_adds_nothing(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    factory, _ = real_admin
    plan = resolve_plan(["billing"])
    directory = seed_run(plan)
    report = json.loads((directory / "report.json").read_text())
    assert report["billing"]["missing_coverage"] == []
    assert set(report["billing"]["states"]) == {"unpaid", "partially_settled", "settled", "voided"}
    assert all(value == 0 for value in report["billing"]["checks"].values())
    first = totals(factory)
    assert {name: first[name] for name in report["billing"]["tables"]} == report["billing"][
        "tables"
    ]
    with factory() as db:
        snapshot = {
            b.id: (b.row_version, b.basis_version_id, b.receivable_cents, b.settled_cents)
            for b in db.scalars(select(Bill))
        }
    seed_run(resume=directory.name)
    assert totals(factory) == first
    assert json.loads((directory / "report.json").read_text())["steps_this_execution"] == 0
    seed_run(plan)
    second = totals(factory)
    for table in report["billing"]["tables"]:
        assert second[table] == 2 * first[table]
    with factory() as db:
        for identifier, expected in snapshot.items():
            bill = db.get(Bill, identifier)
            assert bill is not None
            assert (
                bill.row_version,
                bill.basis_version_id,
                bill.receivable_cents,
                bill.settled_cents,
            ) == expected


def test_billing_custom_counts_match_estimate_across_parallel_companies(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    plan = resolve_plan(
        ["billing"],
        workers=2,
        overrides=[
            "property.companies=2",
            "housing.phases_per_community=0",
            "housing.buildings_per_community=1",
            "housing.units_per_building=0",
            "housing.houses_per_building=2",
            "housing.owners_per_house=1",
            "billing.basis_versions_per_house=2",
            "billing.bill_months_per_house=3",
            "billing.additional_receipts_per_bill=3",
            "billing.amount_corrections_per_bill=2",
            "billing.date_corrections_per_bill=3",
            "billing.reversals_per_bill=2",
            "billing.rebuilds_per_bill=2",
            "billing.min_receivable_cents=13000",
            "billing.max_receivable_cents=13017",
        ],
    )
    directory = seed_run(plan)
    factory, _ = real_admin
    counts = totals(factory)
    assert counts["houses"] == counts["house_owners"] == 4
    assert counts["property_fee_basis_versions"] == 8
    report = json.loads((directory / "report.json").read_text())
    assert all(counts[table] == plan.counts()[table] for table in report["billing"]["tables"])
    with factory() as db:
        assert set(
            db.scalars(
                select(func.count()).select_from(FeeBasisVersion).group_by(FeeBasisVersion.house_id)
            )
        ) == {2}
        assert set(
            db.scalars(select(func.count(func.distinct(Bill.period_start))).group_by(Bill.house_id))
        ) == {3}
        assert not db.scalar(
            select(Bill.id).where(
                Bill.receivable_cents > 0,
                (Bill.receivable_cents < 13000) | (Bill.receivable_cents > 13017),
            )
        )
    seed_run(resume=directory.name)
    assert totals(factory) == counts


@pytest.mark.parametrize(
    "suffix",
    [
        "basis/1",
        "month/0/write/0",
        "month/0/write/1",
        "month/0/write/2",
        "month/0/write/3",
        "month/0/write/4",
        "month/4/write/3",
        "month/4/write/4",
    ],
)
def test_billing_resume_recovers_each_committed_operation_without_duplicates(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    original = State.complete
    fired = False
    committed_operation: str | None = None
    key_to_interrupt = "billing/0/0/building/0/house/0/" + suffix

    def fail_once(
        self: State, key: str, result: dict[str, Any], account: dict[str, str] | None = None
    ) -> None:
        nonlocal fired, committed_operation
        if key == key_to_interrupt and not fired:
            fired = True
            if result["model"] == "bill":
                committed_operation = result["payload"]["operation"]["id"]
            raise RuntimeError("billing service committed before local completion")
        original(self, key, result, account)

    monkeypatch.setattr(State, "complete", fail_once)
    plan = resolve_plan(
        ["billing"],
        overrides=[
            "housing.phases_per_community=0",
            "housing.buildings_per_community=1",
            "housing.units_per_building=0",
            "housing.houses_per_building=1",
            "housing.owners_per_house=0",
        ],
    )
    with pytest.raises(RuntimeError, match="before local"):
        seed_run(plan)
    assert fired
    directory = next((tmp_path / "seed").glob("*/state.json")).parent
    saved_date = json.loads((directory / "state.json").read_text())["business_date"]
    monkeypatch.setattr(runner, "business_today", lambda: date(2030, 1, 1))
    seed_run(resume=directory.name)
    factory, _ = real_admin
    report = json.loads((directory / "report.json").read_text())
    assert report["billing"]["business_date"] == saved_date
    assert all(
        report["billing"]["tables"][name] == plan.counts()[name]
        for name in report["billing"]["tables"]
    )
    with factory() as db:
        if committed_operation:
            assert db.get(BillOperation, committed_operation) is not None
        duplicates = db.execute(
            select(BillOperation.idempotency_key, func.count())
            .group_by(BillOperation.idempotency_key)
            .having(func.count() > 1)
        ).all()
        assert not duplicates
    before = totals(factory)
    seed_run(resume=directory.name)
    assert totals(factory) == before


def test_billing_resume_retries_intent_that_did_not_reach_service(
    seed_run: SeedRun,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = PropertyBillingService.write
    fired = False

    def fail_once(self: PropertyBillingService, *args: Any, **kwargs: Any) -> Any:
        nonlocal fired
        if not fired:
            fired = True
            raise RuntimeError("before billing commit")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PropertyBillingService, "write", fail_once)
    plan = resolve_plan(["billing"], overrides=["housing.owners_per_house=0"])
    with pytest.raises(RuntimeError, match="before billing commit"):
        seed_run(plan)
    directory = next((tmp_path / "seed").glob("*/state.json")).parent
    seed_run(resume=directory.name)
    report = json.loads((directory / "report.json").read_text())
    assert report["billing"]["missing_coverage"] == []


@pytest.mark.parametrize(
    "overrides",
    [
        ["billing.bill_months_per_house=0"],
        ["billing.basis_versions_per_house=0"],
        [
            "billing.basis_versions_per_house=1",
            "billing.additional_receipts_per_bill=0",
            "billing.amount_corrections_per_bill=0",
            "billing.date_corrections_per_bill=0",
            "billing.reversals_per_bill=0",
            "billing.rebuilds_per_bill=0",
        ],
    ],
)
def test_billing_zero_counts_omit_objects_and_report_missing_coverage(
    seed_run: SeedRun, overrides: list[str]
) -> None:
    plan = resolve_plan(["billing"], overrides=overrides)
    directory = seed_run(plan)
    report = json.loads((directory / "report.json").read_text())
    assert report["billing"]["missing_coverage"]
    assert all(value == 0 for value in report["billing"]["checks"].values())


def test_billing_scale_estimate_matches_actual_counts_beyond_recipe_cycle(
    seed_run: SeedRun,
) -> None:
    plan = resolve_plan(
        ["billing"],
        overrides=[
            "housing.phases_per_community=0",
            "housing.buildings_per_community=1",
            "housing.units_per_building=0",
            "housing.houses_per_building=65",
            "housing.owners_per_house=0",
            "billing.basis_versions_per_house=1",
            "billing.bill_months_per_house=1",
        ],
    )
    directory = seed_run(plan)
    report = json.loads((directory / "report.json").read_text())
    assert report["tables"]["houses"] == 65
    assert report["billing"]["tables"] == {
        name: plan.counts()[name] for name in report["billing"]["tables"]
    }


def test_billing_queries_keep_seed_companies_isolated_and_resume_rejects_external_edits(
    seed_run: SeedRun,
    real_admin: tuple[sessionmaker[Session], AdminSessionStore],
) -> None:
    directory = seed_run(
        resolve_plan(
            ["billing"],
            overrides=[
                "property.companies=2",
                "housing.buildings_per_community=1",
                "housing.units_per_building=0",
                "housing.houses_per_building=1",
                "housing.owners_per_house=0",
            ],
        )
    )
    accounts = json.loads((directory / "accounts.json").read_text())
    account = next(
        a for a in accounts if a["登录端"] == "property_admin" and a["登录名"].endswith("c0_a0")
    )
    factory, store = real_admin
    actor = Actor("property_admin", account["登录名"], account["密码"], directory.name)
    try:
        with factory() as db:
            context = actor.get(db, store)
            own = db.scalar(
                select(Bill).where(
                    Bill.property_company_id == context.property_company_id,
                    Bill.lifecycle_status == "active",
                )
            )
            other = db.scalar(
                select(Bill).where(Bill.property_company_id != context.property_company_id)
            )
            assert own is not None and other is not None
            service = PropertyBillingService(db)
            with pytest.raises(AppError) as error:
                service.get_bill(context, other.community_id, other.id)
            assert error.value.code == "resource.not_found"
            service.write(
                context,
                own.community_id,
                "update",
                BillUpdate(expected_row_version=own.row_version, external_bill_no="外部修正"),
                "external_edit",
                "external_edit",
                bill_id=own.id,
            )
    finally:
        actor.close(store)
    before = totals(factory)
    with pytest.raises(SeedError, match="外部变化"):
        seed_run(resume=directory.name)
    assert totals(factory) == before
