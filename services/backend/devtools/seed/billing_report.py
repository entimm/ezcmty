"""Read-only, batch-scoped verification of the generated billing data."""

import re
from collections import Counter
from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from backend_app.models.admin import AdminAccount, AdminAuditLog
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry, FeeBasisVersion
from backend_app.models.housing import House
from backend_app.models.property import Community, PropertyCompany
from backend_app.schemas.billing import BillWriteResult
from devtools.seed.config import Plan, SeedError
from devtools.seed.state import State

FEATURES = {
    "area_rate",
    "fixed_positive",
    "fixed_zero",
    "different_effective_months",
    "same_month_correction",
    "historical_basis_preserved",
    "corrected_basis_used",
    "historical_month",
    "current_month",
    "future_month",
    "automatic",
    "manual_unbound",
    "zero_bill",
    "unpaid",
    "partially_settled",
    "settled",
    "voided",
    "rebuilt",
    "initial_partial",
    "initial_full",
    "additional_receipt",
    "amount_correction",
    "date_correction",
    "reversal",
    "external_number",
    "no_external_number",
    "expired_due_date",
    "future_due_date",
    "no_due_date",
}


def billing_report(db: Session, state: State, plan: Plan, today: date) -> dict[str, Any]:
    houses = (
        select(House.id)
        .join(Community, Community.id == House.community_id)
        .join(
            PropertyCompany,
            PropertyCompany.id == Community.property_company_id,
        )
        .where(
            PropertyCompany.code.startswith(("SEED_" + state.run_id + "_").upper(), autoescape=True)
        )
    )
    bill_ids = select(Bill.id).where(Bill.house_id.in_(houses))
    counts: dict[str, int] = {}
    for model, condition in (
        (FeeBasisVersion, FeeBasisVersion.house_id.in_(houses)),
        (Bill, Bill.id.in_(bill_ids)),
        (BillOperation, BillOperation.bill_id.in_(bill_ids)),
        (BillSettlementEntry, BillSettlementEntry.bill_id.in_(bill_ids)),
    ):
        counts[model.__tablename__] = (
            db.scalar(select(func.count()).select_from(model).where(condition)) or 0
        )
    violations: Counter[str] = Counter(
        {
            name: 0
            for name in (
                "expected_counts",
                "active_house_month_unique",
                "settlement_totals",
                "amount_bounds",
                "zero_without_entries",
                "company_isolation",
                "operation_versions",
                "immutable_bill_facts",
                "operation_results",
                "idempotency",
                "audit",
                "reversal_matches",
                "receipt_dates",
            )
        }
    )
    features: set[str] = set()
    states: Counter[str] = Counter()
    months: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    entries: Counter[str] = Counter()
    money: Counter[str] = Counter()
    due_dates: Counter[str] = Counter()
    overdue_bills = 0
    expected_counts = plan.counts()
    violations["expected_counts"] = sum(
        count != expected_counts[name] for name, count in counts.items()
    )
    method: ColumnElement[str] = case(
        (FeeBasisVersion.fixed_amount_cents.is_(None), "area_rate"),
        (FeeBasisVersion.fixed_amount_cents == 0, "fixed_zero"),
        else_="fixed_positive",
    )
    basis_methods: dict[str, int] = {
        name: count
        for name, count in db.execute(
            select(method, func.count())
            .where(
                FeeBasisVersion.house_id.in_(houses),
            )
            .group_by(method)
        )
    }
    features.update(basis_methods)
    same_month = (
        select(FeeBasisVersion.house_id)
        .where(FeeBasisVersion.house_id.in_(houses))
        .group_by(
            FeeBasisVersion.house_id,
            FeeBasisVersion.effective_from_month,
        )
        .having(func.count() > 1)
    )
    if db.scalar(select(same_month.exists())):
        features.add("same_month_correction")
    different_months = (
        select(FeeBasisVersion.house_id)
        .where(FeeBasisVersion.house_id.in_(houses))
        .group_by(
            FeeBasisVersion.house_id,
        )
        .having(func.count(func.distinct(FeeBasisVersion.effective_from_month)) > 1)
    )
    if db.scalar(select(different_months.exists())):
        features.add("different_effective_months")

    basis_audits = (
        select(func.count())
        .select_from(AdminAuditLog)
        .where(
            AdminAuditLog.scope == "property_admin",
            AdminAuditLog.property_company_id == Community.property_company_id,
            AdminAuditLog.actor_id == FeeBasisVersion.created_by,
            AdminAuditLog.target_id == FeeBasisVersion.id,
            AdminAuditLog.action == "property.fee_basis.create",
            AdminAuditLog.request_id.startswith("seed_" + state.run_id + "_", autoescape=True),
            AdminAuditLog.result == "success",
        )
        .correlate(Community, FeeBasisVersion)
        .scalar_subquery()
    )
    for creator_company, company, audits in db.execute(
        select(
            AdminAccount.property_company_id,
            Community.property_company_id,
            basis_audits,
        )
        .select_from(FeeBasisVersion)
        .join(House, House.id == FeeBasisVersion.house_id)
        .join(Community, Community.id == House.community_id)
        .join(AdminAccount, AdminAccount.id == FeeBasisVersion.created_by)
        .where(FeeBasisVersion.house_id.in_(houses))
        .execution_options(yield_per=256)
    ):
        violations["company_isolation"] += creator_company != company
        violations["audit"] += audits != 1

    entry_totals = (
        select(
            BillSettlementEntry.bill_id.label("bill_id"),
            func.sum(BillSettlementEntry.amount_cents).label("settled"),
            func.count().label("entries"),
        )
        .where(BillSettlementEntry.bill_id.in_(bill_ids))
        .group_by(BillSettlementEntry.bill_id)
        .subquery()
    )
    op_totals = (
        select(
            BillOperation.bill_id.label("bill_id"),
            func.count().label("operations"),
            func.min(BillOperation.bill_version).label("first"),
            func.max(BillOperation.bill_version).label("last"),
        )
        .where(BillOperation.bill_id.in_(bill_ids))
        .group_by(BillOperation.bill_id)
        .subquery()
    )
    later_basis = aliased(FeeBasisVersion)
    has_newer = (
        select(later_basis.id)
        .where(
            later_basis.house_id == FeeBasisVersion.house_id,
            later_basis.effective_from_month == FeeBasisVersion.effective_from_month,
            later_basis.version_no > FeeBasisVersion.version_no,
        )
        .correlate(FeeBasisVersion)
        .exists()
    )
    rows = db.execute(
        select(
            Bill,
            Community.property_company_id,
            House.community_id,
            AdminAccount.property_company_id,
            func.coalesce(entry_totals.c.settled, 0),
            func.coalesce(entry_totals.c.entries, 0),
            op_totals.c.operations,
            op_totals.c.first,
            op_totals.c.last,
            FeeBasisVersion.version_no,
            has_newer,
        )
        .join(House, House.id == Bill.house_id)
        .join(Community, Community.id == House.community_id)
        .join(AdminAccount, AdminAccount.id == Bill.created_by)
        .outerjoin(entry_totals, entry_totals.c.bill_id == Bill.id)
        .outerjoin(op_totals, op_totals.c.bill_id == Bill.id)
        .outerjoin(FeeBasisVersion, FeeBasisVersion.id == Bill.basis_version_id)
        .where(Bill.id.in_(bill_ids))
        .execution_options(yield_per=256)
    )
    for (
        bill,
        company,
        community,
        creator_company,
        settled,
        entry_count,
        op_count,
        first,
        last,
        basis_number,
        has_later_basis,
    ) in rows:
        assert isinstance(bill, Bill)
        label = "voided" if bill.lifecycle_status == "voided" else bill.settlement_status
        assert label is not None
        states[label] += 1
        features.add(label)
        months[bill.period_start.strftime("%Y-%m")] += 1
        sources[bill.amount_source] += 1
        money.update(
            receivable_cents=bill.receivable_cents,
            settled_cents=bill.settled_cents,
            outstanding_cents=bill.outstanding_cents,
        )
        features.add(
            "historical_month"
            if bill.period_start < today.replace(day=1)
            else "current_month"
            if bill.period_start == today.replace(day=1)
            else "future_month"
        )
        features.add(
            "external_number" if bill.external_bill_no is not None else "no_external_number"
        )
        due_kind = (
            "no_due_date"
            if bill.due_date is None
            else "expired_due_date"
            if bill.due_date < today
            else "future_due_date"
        )
        features.add(due_kind)
        due_dates[due_kind] += 1
        overdue_bills += (
            bill.lifecycle_status == "active"
            and bill.outstanding_cents > 0
            and bill.due_date is not None
            and bill.due_date < today
        )
        if bill.amount_source == "basis":
            features.add("automatic")
        elif bill.basis_version_id is None:
            features.add("manual_unbound")
        if bill.receivable_cents == 0:
            features.add("zero_bill")
        violations["settlement_totals"] += bill.settled_cents != settled
        violations["amount_bounds"] += not 0 <= bill.settled_cents <= bill.receivable_cents
        violations["amount_bounds"] += bill.receivable_cents != 0 and not (
            plan.parameters["billing"]["min_receivable_cents"]
            <= bill.receivable_cents
            <= plan.parameters["billing"]["max_receivable_cents"]
        )
        violations["zero_without_entries"] += bill.receivable_cents == 0 and entry_count != 0
        violations["company_isolation"] += not (
            company == bill.property_company_id == creator_company
            and community == bill.community_id
        )
        violations["operation_versions"] += not (
            op_count == bill.row_version == last and first == 1
        )
        if has_later_basis:
            features.add("historical_basis_preserved")
        if basis_number == 3:
            features.add("corrected_basis_used")
    groups = (
        select(
            func.count().filter(Bill.lifecycle_status == "active").label("active"),
            func.count().filter(Bill.lifecycle_status == "voided").label("voided"),
        )
        .where(Bill.id.in_(bill_ids))
        .group_by(Bill.house_id, Bill.period_start)
        .subquery()
    )
    violations["active_house_month_unique"] = (
        db.scalar(select(func.count()).select_from(groups).where(groups.c.active > 1)) or 0
    )
    rebuilt_months = (
        db.scalar(
            select(func.count())
            .select_from(groups)
            .where(groups.c.active == 1, groups.c.voided > 0)
        )
        or 0
    )
    if rebuilt_months:
        features.add("rebuilt")

    audit_count = (
        select(func.count())
        .select_from(AdminAuditLog)
        .where(
            AdminAuditLog.scope == "property_admin",
            AdminAuditLog.property_company_id == BillOperation.property_company_id,
            AdminAuditLog.actor_id == BillOperation.actor_id,
            AdminAuditLog.request_id == BillOperation.request_id,
            AdminAuditLog.action == "property.bill." + BillOperation.action,
            AdminAuditLog.target_id == BillOperation.bill_id,
            AdminAuditLog.result == "success",
        )
        .correlate(BillOperation)
        .scalar_subquery()
    )
    for operation, bill, actor_company, audit in db.execute(
        select(
            BillOperation,
            Bill,
            AdminAccount.property_company_id,
            audit_count,
        )
        .join(Bill, Bill.id == BillOperation.bill_id)
        .join(AdminAccount, AdminAccount.id == BillOperation.actor_id)
        .where(BillOperation.bill_id.in_(bill_ids))
        .execution_options(yield_per=256)
    ):
        assert isinstance(operation, BillOperation)
        assert isinstance(bill, Bill)
        actions[operation.action] += 1
        payload = BillWriteResult.model_validate(operation.result)
        violations["company_isolation"] += (
            operation.property_company_id != bill.property_company_id
            or actor_company != bill.property_company_id
        )
        violations["audit"] += audit != 1
        violations["idempotency"] += not (
            operation.idempotency_key.startswith("seed_" + state.run_id + "_")
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation.request_id)
            and re.fullmatch(r"[0-9a-f]{64}", operation.request_fingerprint)
        )
        violations["operation_results"] += not (
            payload.bill.id == operation.bill_id
            and payload.bill.row_version == operation.bill_version
            and payload.operation.id == operation.id
            and payload.operation.action == operation.action
            and payload.operation.actor_id == operation.actor_id
            and payload.operation.request_id == operation.request_id
        )
        violations["immutable_bill_facts"] += any(
            getattr(bill, field) != getattr(payload.bill, field)
            for field in (
                "house_id",
                "community_id",
                "property_company_id",
                "basis_version_id",
                "receivable_cents",
                "amount_source",
                "calculation_rule_version",
                "period_start",
                "period_end",
                "house_label_snapshot",
            )
        )
        if operation.action == "create" and payload.settlement_entries:
            features.add(
                "initial_full"
                if payload.bill.settled_cents == payload.bill.receivable_cents
                else "initial_partial"
            )
        if operation.action == "receipt" and "误登记" not in (operation.reason or ""):
            features.add("additional_receipt")
        if operation.action == "reverse_receipt":
            features.add("reversal")
    original = aliased(BillSettlementEntry)
    for entry, old, operation in db.execute(
        select(BillSettlementEntry, original, BillOperation)
        .join(BillOperation, BillOperation.id == BillSettlementEntry.operation_id)
        .outerjoin(original, original.id == BillSettlementEntry.reverses_entry_id)
        .where(BillSettlementEntry.bill_id.in_(bill_ids))
        .execution_options(yield_per=256)
    ):
        entries[entry.entry_type] += 1
        violations["receipt_dates"] += entry.received_on is not None and entry.received_on > today
        if entry.entry_type == "reversal":
            violations["reversal_matches"] += (
                old is None
                or old.bill_id != entry.bill_id
                or old.entry_type != "receipt"
                or old.amount_cents != -entry.amount_cents
            )
            if old is not None and operation.action == "correct_receipt":
                replacement = next(
                    i
                    for i in operation.result["settlement_entries"]
                    if i["entry_type"] == "receipt"
                )
                if replacement["amount_cents"] != old.amount_cents:
                    features.add("amount_correction")
                if replacement["received_on"] != (
                    old.received_on.isoformat() if old.received_on else None
                ):
                    features.add("date_correction")
    if any(violations.values()):
        raise SeedError("账单一致性核验失败：" + str(dict(violations)))
    return {
        "tables": counts,
        "states": dict(states),
        "months": dict(sorted(months.items())),
        "amount_sources": dict(sources),
        "basis_methods": basis_methods,
        "due_dates": dict(due_dates),
        "overdue_bills": overdue_bills,
        "rebuilt_house_months": rebuilt_months,
        "actions": dict(actions),
        "entries": dict(entries),
        "amounts": dict(money),
        "coverage": sorted(features),
        "missing_coverage": sorted(FEATURES - features),
        "checks": dict(violations),
        "business_date": today.isoformat(),
    }
