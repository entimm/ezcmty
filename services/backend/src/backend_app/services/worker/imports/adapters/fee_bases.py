"""Translate complete fee-basis file rows into shared version-append operations."""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.billing import MAX_CENTS
from backend_app.domain.billing.basis import FeeBasisCreationCommand
from backend_app.domain.housing import (
    HouseLocation,
    house_location_snapshot,
    resolve_house_location,
)
from backend_app.domain.imports.errors import ImportExecutionFailure
from backend_app.domain.imports.operation_keys import operation_key
from backend_app.domain.imports.types import (
    ImportContext,
    ImportPlan,
    ImportPreparation,
    ImportProblem,
)
from backend_app.repositories.housing import HousingRepository
from backend_app.repositories.imports.operations import get_operation_by_key
from backend_app.services.fee_basis_creation import (
    create_fee_basis,
    prepare_fee_basis_creation,
    verify_fee_basis_result,
)

_FIELDS = (
    "phase_name",
    "building_name",
    "unit_name",
    "room_no",
    "house_external_code",
    "effective_from_month",
    "house_usage",
    "area_sqm",
    "unit_price_amount",
    "fixed_amount",
    "change_reason",
)
_USAGE = {"住宅": "residential", "商业": "commercial", "办公": "office", "其他": "other"}
_USAGE_LABELS = {value: key for key, value in _USAGE.items()}
_BASIS_LABELS = {
    "house_usage": "房屋用途",
    "area_sqm": "计费面积",
    "unit_price_cents": "月单价",
    "fixed_amount_cents": "固定月费",
}
_TEMPLATE_KEY = "property_fee_basis_versions"
_OPERATION_TYPE = "property_fee_basis.create"
_TARGET_TYPE = "fee_basis_version"


class _CellFormatError(ValueError):
    def __init__(self, field_key: str, message: str) -> None:
        self.field_key = field_key
        self.message = message


def _cents(value: Any, field_key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", str(value)):
        raise _CellFormatError(field_key, "金额须为非负数字，最多两位小数且不带货币符号")
    amount = Decimal(str(value)) * 100
    if amount > MAX_CENTS:
        raise _CellFormatError(field_key, "金额超过允许范围")
    return int(amount)


def _command(row: Mapping[str, Any], house_id: str) -> FeeBasisCreationCommand:
    usage = row.get("house_usage")
    if not isinstance(usage, str) or usage not in _USAGE:
        raise _CellFormatError("house_usage", "房屋用途须填写住宅、商业、办公或其他")
    return FeeBasisCreationCommand.from_input(
        {
            "house_id": house_id,
            "effective_from_month": row.get("effective_from_month"),
            "house_usage": _USAGE[usage],
            "area_sqm": str(row["area_sqm"]) if row.get("area_sqm") is not None else None,
            "unit_price_cents": _cents(row.get("unit_price_amount"), "unit_price_amount"),
            "fixed_amount_cents": _cents(row.get("fixed_amount"), "fixed_amount"),
            "change_reason": row.get("change_reason"),
        }
    )


def _problem(error: AppError) -> ImportProblem:
    if error.code.startswith("auth."):
        raise error
    field = {
        "property.house_location_invalid": "room_no",
        "property.house_location_changed": "room_no",
        "property.house_external_code_mismatch": "house_external_code",
    }.get(error.code)
    code = (
        "import." + error.code.split(".", 1)[1]
        if field is not None
        else "import.validation_failed"
        if error.code == "VALIDATION_ERROR"
        else "import.conflict"
    )
    return ImportProblem(
        code,
        error.public_detail or str(error),
        field_key=field,
        suggestion="核对既有房屋、完整依据及生效月；版本或位置变化后须新建批次重新预览确认",
    )


def _field_text(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key == "house_usage":
        return _USAGE_LABELS.get(str(value), str(value))
    if key in {"unit_price_cents", "fixed_amount_cents"}:
        cents = int(value)
        return f"{cents // 100}.{cents % 100:02d} 元" + ("/㎡" if key == "unit_price_cents" else "")
    return f"{value} ㎡"


def _basis_text(basis: Mapping[str, Any] | None) -> str:
    if basis is None:
        return "该月无版本"
    return "；".join(
        f"{label}：{_field_text(key, basis.get(key))}" for key, label in _BASIS_LABELS.items()
    )


class FeeBasisImportAdapter:
    def normalize(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: (value.strip() or None) if isinstance(value, str) else value
            for key in _FIELDS
            for value in (row.get(key),)
        }

    def required_permissions(
        self, normalized_input: Mapping[str, Any], prepared: Mapping[str, Any] | None = None
    ) -> frozenset[str]:
        return frozenset({"property.fee_basis.manage"})

    def prepare(
        self,
        normalized_input: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        fixed_prepared: Mapping[str, Any] | None = None,
    ) -> ImportPreparation:
        if fixed_prepared is not None:
            stable_key = operation_key(
                context.scope.property_company_id,
                _TEMPLATE_KEY,
                _OPERATION_TYPE,
                dict(fixed_prepared["natural_key"]),
                str(fixed_prepared["input_fingerprint"]),
            )
            operation = get_operation_by_key(
                db,
                company_id=context.scope.property_company_id,
                operation_key=stable_key,
                lock=True,
            )
            if (
                operation is None
                or operation.operation_type != _OPERATION_TYPE
                or operation.input_fingerprint != fixed_prepared["input_fingerprint"]
                or operation.natural_key != fixed_prepared["natural_key"]
            ):
                raise ValueError("import.operation_identity_mismatch")
            # A shared success can postdate the source failure. Verify it before the
            # pending baseline check, which would otherwise reject its own appended version.
            target = (
                {
                    "target_type": operation.target_type or "",
                    "target_id": operation.target_id or "",
                }
                if operation.status in {"succeeded", "skipped"}
                else None
            )
            return ImportPreparation(
                dict(fixed_prepared),
                tuple(self.revalidate(fixed_prepared, context, db, target=target)),
                identity={
                    "operation_type": _OPERATION_TYPE,
                    "natural_key": dict(fixed_prepared["natural_key"]),
                },
            )
        identity = None
        try:
            community_id = context.scope.community_id
            if community_id is None:
                raise AppError("auth.forbidden")
            repo = HousingRepository(db, context.scope.property_company_id)
            snapshot = resolve_house_location(
                repo,
                community_id,
                HouseLocation(
                    phase_name=normalized_input.get("phase_name"),
                    building_name=cast(str, normalized_input.get("building_name")),
                    unit_name=normalized_input.get("unit_name"),
                    room_no=cast(str, normalized_input.get("room_no")),
                ),
            )
            # Identify duplicates even when another field or the optional code is invalid.
            identity = {
                "operation_type": _OPERATION_TYPE,
                "natural_key": {"house_id": snapshot["house_id"]},
            }
            if normalized_input.get("house_external_code") is not None:
                snapshot = house_location_snapshot(
                    repo,
                    community_id,
                    snapshot["house_id"],
                    house_external_code=normalized_input["house_external_code"],
                )
            return ImportPreparation(
                prepare_fee_basis_creation(
                    db,
                    company_id=context.scope.property_company_id,
                    community_id=community_id,
                    command=_command(normalized_input, snapshot["house_id"]),
                    house_snapshot=snapshot,
                ),
                identity=identity,
            )
        except _CellFormatError as error:
            return ImportPreparation(
                None,
                (
                    ImportProblem(
                        "import.validation_failed", error.message, field_key=error.field_key
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
            operation_type=_OPERATION_TYPE,
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
            if context.scope.community_id is None or (
                target is not None and target["target_type"] != _TARGET_TYPE
            ):
                raise AppError("auth.forbidden")
            command = FeeBasisCreationCommand.from_input(prepared["command"])
            if target is not None:
                # The immutable original result remains valid after later normal price changes.
                verify_fee_basis_result(
                    db,
                    company_id=context.scope.property_company_id,
                    community_id=context.scope.community_id,
                    command=command,
                    house_snapshot=prepared["house_snapshot"],
                    target_id=target["target_id"],
                    original_status="created" if prepared["action"] == "create" else "skipped",
                    actor_id=context.actor_id if context.phase == "apply" else None,
                    lock=context.phase == "apply",
                    expected_latest_version_no=prepared["expected_latest_version_no"],
                    expected_target_id=prepared.get("target_id"),
                )
            else:
                prepare_fee_basis_creation(
                    db,
                    company_id=context.scope.property_company_id,
                    community_id=context.scope.community_id,
                    command=command,
                    house_snapshot=prepared["house_snapshot"],
                    expected_latest_version_no=prepared["expected_latest_version_no"],
                    expected_action=prepared["action"],
                    expected_target_id=prepared.get("target_id"),
                )
            return ()
        except AppError as error:
            return (_problem(error),)

    def execute(
        self, operation: ImportPlan, context: ImportContext, db: Session
    ) -> Mapping[str, Any]:
        try:
            if context.scope.community_id is None:
                raise AppError("auth.forbidden")
            result = create_fee_basis(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                actor_id=context.actor_id,
                command=FeeBasisCreationCommand.from_input(operation.values["command"]),
                expected_latest_version_no=operation.values["expected_latest_version_no"],
                request_id=context.request_id,
                house_snapshot=operation.values["house_snapshot"],
                allow_existing=True,
                expected_action=operation.action,
                expected_target_id=operation.values.get("target_id"),
            )
            return {
                "status": result.status,
                "target_type": _TARGET_TYPE,
                "target_id": result.basis.id,
            }
        except AppError as error:
            problem = _problem(error)
            raise ImportExecutionFailure(
                "import.system_error" if error.status_code == 503 else problem.code,
                retryable=error.status_code == 503,
            ) from None

    def resolve_operation(
        self, operation_key: str, prepared: Mapping[str, Any], context: ImportContext, db: Session
    ) -> Mapping[str, Any] | None:
        # Existing equal content cannot prove that this logical operation appended it.
        if prepared["action"] != "skip" or not prepared.get("target_id"):
            return None
        if context.scope.community_id is None:
            return None
        try:
            # This guarded operation must remain a skip; it never refreshes the baseline.
            result = create_fee_basis(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                actor_id=context.actor_id,
                command=FeeBasisCreationCommand.from_input(prepared["command"]),
                expected_latest_version_no=prepared["expected_latest_version_no"],
                request_id=context.request_id,
                house_snapshot=prepared["house_snapshot"],
                allow_existing=True,
                expected_action="skip",
                expected_target_id=prepared["target_id"],
            )
        except AppError as error:
            if error.code.startswith("auth."):
                raise
            return None
        if result.status != "skipped" or result.basis.id != prepared["target_id"]:
            return None
        return {
            "status": "skipped",
            "target_type": _TARGET_TYPE,
            "target_id": result.basis.id,
        }

    def presentation_fields(self) -> Sequence[dict[str, str]]:
        return (
            {"key": "house_label", "label": "完整房屋位置", "format": "text"},
            {"key": "effective_from_month", "label": "生效月", "format": "text"},
            {"key": "comparison_version", "label": "同月比较版本", "format": "text"},
            {"key": "old_basis", "label": "旧标准", "format": "text"},
            {"key": "new_basis", "label": "输入标准", "format": "text"},
            {"key": "changes", "label": "具体变化", "format": "text"},
            {
                "key": "calculated_amount_cents",
                "label": "输入月费试算",
                "format": "money_cents",
            },
            {"key": "effective_period", "label": "适用区间", "format": "text"},
            {"key": "action_reason", "label": "动作说明", "format": "text"},
            {"key": "change_reason", "label": "变更原因", "format": "text"},
            {"key": "result_version", "label": "原目标版本", "format": "text"},
            {"key": "result_source", "label": "执行结果说明", "format": "text"},
        )

    def summary_fields(self) -> Sequence[dict[str, str]]:
        return ()

    def presentation(self, prepared: Mapping[str, Any]) -> Mapping[str, Any]:
        old = prepared["old_basis"]
        new = prepared["new_basis"]
        month = prepared["command"]["effective_from_month"]
        following = prepared["next_effective_month"]
        return {
            "house_label": prepared["house_label"],
            "effective_from_month": month,
            "comparison_version": f"v{prepared['comparison_version_no']}"
            if prepared["comparison_version_no"] is not None
            else "该月无版本",
            "old_basis": _basis_text(old),
            "new_basis": _basis_text(new),
            "changes": "该月无版本，新增完整依据"
            if old is None
            else "；".join(
                f"{_BASIS_LABELS[key]}：{_field_text(key, old.get(key))} → "
                f"{_field_text(key, new.get(key))}"
                for key in prepared["changed_fields"]
            )
            or "同月业务内容相同",
            "calculated_amount_cents": prepared["calculated_amount_cents"],
            "effective_period": f"从 {month} 起，至 {following} 之前"
            if following is not None
            else f"从 {month} 起持续适用",
            "action_reason": "同月最新内容相同，跳过"
            if prepared["action"] == "skip"
            else "该月无版本，新增依据"
            if old is None
            else "同月内容变化，新增更正版本",
            "change_reason": prepared["command"]["change_reason"],
        }

    def result_presentation(
        self,
        prepared: Mapping[str, Any],
        *,
        execution_status: str,
        target: Mapping[str, str] | None,
    ) -> Mapping[str, Any]:
        if (
            execution_status not in {"created", "skipped"}
            or target is None
            or target.get("target_type") != _TARGET_TYPE
            or target.get("status") not in {"succeeded", "skipped"}
        ):
            return {}
        number = (
            prepared["expected_latest_version_no"] + 1
            if prepared["action"] == "create"
            else prepared["comparison_version_no"]
        )
        return {
            "result_version": f"v{number}（{target['target_id']}）",
            "result_source": "新增版本"
            if execution_status == "created"
            else "复用原成功"
            if target["status"] == "succeeded"
            else "业务跳过",
        }
