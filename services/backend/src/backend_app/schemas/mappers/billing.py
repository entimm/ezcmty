from datetime import date
from typing import Any, Literal, cast

from backend_app.domain.billing import HouseUsage
from backend_app.models.billing import Bill, BillOperation, BillSettlementEntry, FeeBasisVersion
from backend_app.schemas import billing as schema


def basis_view(item: FeeBasisVersion) -> schema.FeeBasisVersion:
    return schema.FeeBasisVersion(
        id=item.id,
        house_id=item.house_id,
        version_no=item.version_no,
        effective_from_month=item.effective_from_month.isoformat()[:7],
        house_usage=cast(HouseUsage, item.house_usage),
        area_sqm=format(item.area_sqm, "f") if item.area_sqm is not None else None,
        unit_price_cents=item.unit_price_cents,
        fixed_amount_cents=item.fixed_amount_cents,
        change_reason=item.change_reason,
        created_by=item.created_by,
        created_at=item.created_at,
    )


def bill_view(item: Bill, basis: FeeBasisVersion | None, enabled: bool, today: date) -> schema.Bill:
    data: dict[str, Any] = {
        column.name: getattr(item, column.name) for column in Bill.__table__.columns
    }
    data.update(
        billing_month=item.period_start.isoformat()[:7],
        basis=basis_view(basis) if basis else None,
        house_effective_enabled=enabled,
        is_overdue=bool(
            item.lifecycle_status == "active"
            and item.outstanding_cents > 0
            and item.due_date
            and item.due_date < today
        ),
    )
    return schema.Bill.model_validate(data)


def operation_view(item: BillOperation, actor_name: str) -> schema.BillOperation:
    return schema.BillOperation.model_validate(
        {
            **{
                name: getattr(item, name)
                for name in schema.BillOperation.model_fields
                if name != "actor_name"
            },
            "actor_name": actor_name,
        }
    )


def entry_view(
    item: BillSettlementEntry,
    operation: BillOperation,
    actor_name: str,
    reversed_by: str | None = None,
) -> schema.SettlementEntry:
    return schema.SettlementEntry(
        id=item.id,
        bill_id=item.bill_id,
        operation_id=item.operation_id,
        entry_type=cast(Literal["receipt", "reversal"], item.entry_type),
        source_type="offline",
        amount_cents=item.amount_cents,
        reverses_entry_id=item.reverses_entry_id,
        reversed_by_entry_id=reversed_by,
        received_on=item.received_on,
        created_at=item.created_at,
        actor_id=operation.actor_id,
        actor_name=actor_name,
        reason=operation.reason,
    )
