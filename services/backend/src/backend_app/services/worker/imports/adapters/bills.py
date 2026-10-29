"""Translate bill import input and results; business rules belong to shared billing."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.billing.creation import (
    BillCreationCommand,
    creation_identity,
    creation_permissions,
)
from backend_app.domain.housing import (
    HouseLocation,
    house_location_snapshot,
    resolve_house_location,
)
from backend_app.domain.imports.errors import ImportExecutionFailure
from backend_app.domain.imports.types import (
    ImportContext,
    ImportPlan,
    ImportPreparation,
    ImportProblem,
)
from backend_app.repositories.billing import BillingRepository
from backend_app.repositories.housing import HousingRepository
from backend_app.services.property_account_access import property_task_context
from backend_app.services.property_business.bill_creation import create_bill, prepare_bill_creation

_FIELDS = (
    "phase_name",
    "building_name",
    "unit_name",
    "room_no",
    "house_external_code",
    "billing_month",
    "receivable_amount",
    "manual_amount_reason",
    "initial_paid_amount",
    "initial_received_on",
    "initial_receipt_reason",
    "external_bill_no",
    "due_date",
)
_INPUT_FIELDS = frozenset(
    {
        "house_id",
        "billing_month",
        "receivable_cents",
        "manual_amount_reason",
        "external_bill_no",
        "due_date",
        "initial_receipt",
    }
)


class _CellFormatError(ValueError):
    def __init__(self, field_key: str) -> None:
        self.field_key = field_key


def _cents(value: Any, field_key: str) -> int:
    """Decode the file's yuan protocol without rounding or binary arithmetic."""
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", str(value)):
        raise _CellFormatError(field_key)
    return int(Decimal(str(value)) * 100)


def _command(row: Mapping[str, Any], house_id: str) -> BillCreationCommand:
    paid = _cents(row.get("initial_paid_amount"), "initial_paid_amount")
    return BillCreationCommand.from_input(
        {
            "house_id": house_id,
            "bill_type": "property_fee",
            "billing_month": row.get("billing_month"),
            "amount_source": "manual",
            "receivable_cents": _cents(row.get("receivable_amount"), "receivable_amount"),
            "manual_amount_reason": row.get("manual_amount_reason"),
            "external_bill_no": row.get("external_bill_no"),
            "due_date": row.get("due_date"),
            "initial_receipt": {
                "amount_cents": paid,
                "received_on": row.get("initial_received_on"),
                "reason": row.get("initial_receipt_reason"),
            }
            if paid
            else None,
        }
    )


def _problem(error: AppError) -> ImportProblem:
    if error.code.startswith("auth."):
        raise error
    fields = {
        "property.house_location_invalid": "room_no",
        "property.house_external_code_mismatch": "house_external_code",
        "property.house_location_changed": "room_no",
        "billing.overpayment": "initial_paid_amount",
        "billing.bill_exists": "billing_month",
        "billing.bill_voided": "billing_month",
        "billing.amount_out_of_range": "receivable_amount",
    }
    if error.code in {
        "property.house_location_invalid",
        "property.house_external_code_mismatch",
        "property.house_location_changed",
    }:
        code = "import." + error.code.split(".", 1)[1]
    else:
        code = "import.validation_failed" if error.code == "VALIDATION_ERROR" else "import.conflict"
    return ImportProblem(
        code,
        str(error),
        field_key=fields.get(error.code),
        suggestion="核对该行的房屋位置、月份及建账资料后重新上传",
    )


class BillImportAdapter:
    def normalize(self, row: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in _FIELDS:
            value = row.get(key)
            if isinstance(value, str):
                value = value.strip() or None
                # Native Excel dates are decoded by the parser as midnight datetimes.
                if key in {"initial_received_on", "due_date"} and value is not None:
                    value = re.sub(r"T00:00:00(?:\.0+)?$", "", value)
            result[key] = value
        return result

    def required_permissions(
        self, normalized_input: Mapping[str, Any], prepared: Mapping[str, Any] | None = None
    ) -> frozenset[str]:
        try:
            paid = _cents(normalized_input.get("initial_paid_amount"), "initial_paid_amount")
        except _CellFormatError:
            paid = None
        return creation_permissions(initial_paid_cents=paid)

    def prepare(
        self,
        normalized_input: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        fixed_prepared: Mapping[str, Any] | None = None,
    ) -> ImportPreparation:
        if fixed_prepared is not None:
            return ImportPreparation(
                dict(fixed_prepared),
                tuple(
                    self.revalidate(
                        fixed_prepared,
                        context,
                        db,
                    )
                ),
                identity={
                    "operation_type": "property_fee_bill.create",
                    "natural_key": dict(fixed_prepared["natural_key"]),
                },
            )
        identity = None
        try:
            community_id = context.scope.community_id
            if community_id is None:
                raise AppError("auth.forbidden")
            repo = HousingRepository(db, context.scope.property_company_id)
            location = HouseLocation(
                phase_name=normalized_input.get("phase_name"),
                building_name=cast(str, normalized_input.get("building_name")),
                unit_name=normalized_input.get("unit_name"),
                room_no=cast(str, normalized_input.get("room_no")),
            )
            snapshot = resolve_house_location(repo, community_id, location)
            identity = {
                "operation_type": "property_fee_bill.create",
                "natural_key": creation_identity(
                    snapshot["house_id"],
                    cast(str, normalized_input.get("billing_month")),
                ),
            }
            if normalized_input.get("house_external_code") is not None:
                checked_location = replace(
                    location, house_external_code=normalized_input["house_external_code"]
                )
                snapshot = house_location_snapshot(
                    repo,
                    community_id,
                    snapshot["house_id"],
                    house_external_code=checked_location.house_external_code,
                )
            command = _command(normalized_input, snapshot["house_id"])
            result = prepare_bill_creation(
                db,
                company_id=context.scope.property_company_id,
                community_id=community_id,
                command=command,
                house_snapshot=snapshot,
            )
            return ImportPreparation(
                {**result, "command": command.to_dict(), "house_snapshot": snapshot},
                identity=identity,
            )
        except _CellFormatError as error:
            return ImportPreparation(
                None,
                (
                    ImportProblem(
                        "import.validation_failed",
                        "金额须为非负数字，最多两位小数且不能留空",
                        field_key=error.field_key,
                        suggestion="未缴明确填写 0，金额使用元且不带货币符号",
                    ),
                ),
                identity=identity,
            )
        except AppError as error:
            return ImportPreparation(None, (_problem(error),), identity=identity)

    def plan(self, prepared: Mapping[str, Any]) -> ImportPlan:
        return ImportPlan(
            action=str(prepared["action"]),
            values=dict(prepared),
            operation_type="property_fee_bill.create",
            natural_key=dict(prepared["natural_key"]),
            input_fingerprint=str(prepared["input_fingerprint"]),
        )

    def revalidate(
        self,
        prepared: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        target: Mapping[str, str] | None = None,
    ) -> Sequence[ImportProblem]:
        try:
            if context.scope.community_id is None or target and target["target_type"] != "bill":
                raise AppError("auth.forbidden")
            prepare_bill_creation(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                command=BillCreationCommand.from_input(prepared["command"]),
                house_snapshot=prepared["house_snapshot"],
                target_id=target["target_id"] if target else prepared.get("target_id"),
            )
            return ()
        except AppError as error:
            return (_problem(error),)

    def execute(
        self,
        operation: ImportPlan,
        context: ImportContext,
        db: Session,
    ) -> Mapping[str, Any]:
        try:
            assert context.scope.community_id is not None
            assert operation.input_fingerprint is not None
            result = create_bill(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                actor_id=context.actor_id,
                context=property_task_context(
                    db, context.scope.property_company_id, context.actor_id
                ),
                command=BillCreationCommand.from_input(operation.values["command"]),
                key="import_" + str(operation.values["_operation_key"]),
                fingerprint=operation.input_fingerprint,
                request_id=context.request_id,
                input_fields=_INPUT_FIELDS,
                house_snapshot=operation.values["house_snapshot"],
                allow_existing=True,
                expected_target_id=operation.values.get("target_id")
                if operation.action == "skip"
                else None,
            )
            return {"status": result.status, "target_type": "bill", "target_id": result.bill_id}
        except AppError as error:
            problem = _problem(error)
            raise ImportExecutionFailure(
                "import.system_error" if error.status_code == 503 else problem.code,
                retryable=error.status_code == 503,
            ) from None

    def resolve_operation(
        self,
        operation_key: str,
        prepared: Mapping[str, Any],
        context: ImportContext,
        db: Session,
    ) -> Mapping[str, Any] | None:
        repo = BillingRepository(db, context.scope.property_company_id)
        operation = repo.operation_by_key("import_" + operation_key)
        if operation is None:
            if context.scope.community_id is None:
                return None
            try:
                existing = prepare_bill_creation(
                    db,
                    company_id=context.scope.property_company_id,
                    community_id=context.scope.community_id,
                    command=BillCreationCommand.from_input(prepared["command"]),
                    house_snapshot=prepared["house_snapshot"],
                    target_id=prepared.get("target_id"),
                )
            except AppError:
                return None
            if existing["action"] == "skip" and existing["target_id"]:
                return {
                    "status": "skipped",
                    "target_type": "bill",
                    "target_id": existing["target_id"],
                }
            return None
        if (
            operation.action != "create"
            or operation.request_fingerprint != prepared["input_fingerprint"]
        ):
            raise ImportExecutionFailure("import.conflict")
        return {"status": "created", "target_type": "bill", "target_id": operation.bill_id}

    def presentation_fields(self) -> Sequence[dict[str, str]]:
        return (
            {"key": "matched_house_label", "label": "匹配房屋位置", "format": "text"},
            {"key": "billing_month", "label": "账单月份", "format": "text"},
            {"key": "receivable_cents", "label": "应收金额", "format": "money_cents"},
            {"key": "initial_paid_cents", "label": "初始已缴", "format": "money_cents"},
            {"key": "outstanding_cents", "label": "待缴金额", "format": "money_cents"},
        )

    def summary_fields(self) -> Sequence[dict[str, str]]:
        return (
            {"key": "receivable_cents", "label": "预计新增应收", "format": "money_cents"},
            {"key": "initial_paid_cents", "label": "初始已缴", "format": "money_cents"},
            {"key": "outstanding_cents", "label": "预计待缴", "format": "money_cents"},
        )

    def presentation(self, prepared: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "matched_house_label": prepared["house_label_snapshot"],
            "billing_month": prepared["command"]["billing_month"],
            "receivable_cents": prepared["receivable_cents"],
            "initial_paid_cents": prepared["initial_paid_cents"],
            "outstanding_cents": prepared["outstanding_cents"],
        }
