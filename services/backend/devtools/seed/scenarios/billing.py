from datetime import date

from backend_app.schemas.billing import BillWriteResult
from devtools.seed.billing_plan import bases, recipes, writes
from devtools.seed.config import BillingParameters, SeedError
from devtools.seed.runtime import Actor, Executor


def populate_house(
    executor: Executor,
    actor: Actor,
    company_id: str,
    community_id: str,
    house_id: str,
    house_key: str,
    house_index: int,
    parameters: BillingParameters,
    today: date,
) -> None:
    key = house_key.replace("housing/", "billing/", 1)
    if executor.state.marked(key):
        return
    versions = bases(parameters, house_index)
    bills = recipes(parameters, house_index)
    identifiers: dict[int, str] = {}

    def basis(number: int) -> None:
        version = versions[number - 1]
        values = version.values
        identifiers[number] = executor.step(
            key + f"/basis/{number}",
            actor,
            "property.fee_basis.create",
            "basis",
            values,
            refs={"community_id": community_id, "house_id": house_id},
            unique={"house_id": house_id, "version_no": number},
            expected={
                "house_id": house_id,
                "version_no": number,
                "effective_from_month": values["effective_from_month"] + "-01",
                **{
                    field: values[field]
                    for field in (
                        "house_usage",
                        "area_sqm",
                        "unit_price_cents",
                        "fixed_amount_cents",
                        "change_reason",
                    )
                },
            },
        )

    for index, _ in enumerate(parameters.months()):
        for item in versions:
            if item.month_index == index and not item.after_bill:
                basis(item.number)
        if index < len(bills):
            recipe = bills[index]
            results: list[BillWriteResult] = []
            for step, write in enumerate(writes(recipe, today)):
                values = dict(write.values)
                if write.action == "create":
                    values["house_id"] = house_id
                    if recipe.automatic:
                        if recipe.basis is None:
                            raise SeedError("自动账单缺少计划依据")
                        values["basis_version_id"] = identifiers[recipe.basis.number]
                entry_id = None
                if write.receipt_from is not None:
                    entry_id = next(
                        entry.id
                        for entry in results[write.receipt_from].settlement_entries
                        if entry.entry_type == "receipt"
                    )
                results.append(
                    executor.bill(
                        key + f"/month/{index}/write/{step}",
                        actor,
                        company_id,
                        community_id,
                        write.action,
                        values,
                        bill_id=results[-1].bill.id if write.action != "create" else None,
                        entry_id=entry_id,
                    )
                )
        for item in versions:
            if item.month_index == index and item.after_bill:
                basis(item.number)
    executor.state.mark(key)
