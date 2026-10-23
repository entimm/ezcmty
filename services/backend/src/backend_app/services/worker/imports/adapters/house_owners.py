"""Translate owner registration file inputs and shared business results."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.housing import (
    HouseLocation,
    HouseOwnerCreationCommand,
    house_location_snapshot,
    house_owner_creation_permissions,
    resolve_house_location,
)
from backend_app.domain.imports.errors import ImportExecutionFailure
from backend_app.domain.imports.types import (
    ImportContext,
    ImportPlan,
    ImportPreparation,
    ImportProblem,
)
from backend_app.repositories.housing import HousingRepository
from backend_app.services.house_owner_creation import (
    create_house_owner,
    prepare_house_owner_creation,
    revalidate_house_owner_creation,
)

_FIELDS = (
    "phase_name",
    "building_name",
    "unit_name",
    "room_no",
    "house_external_code",
    "name",
    "phone",
)


def _problem(error: AppError) -> ImportProblem:
    if error.code.startswith("auth."):
        raise error
    code = {
        "property.house_location_invalid": "import.house_location_invalid",
        "property.house_location_changed": "import.house_location_changed",
        "property.house_external_code_mismatch": "import.house_external_code_mismatch",
        "VALIDATION_ERROR": "import.validation_failed",
    }.get(error.code, "import.conflict")
    return ImportProblem(
        code,
        error.public_detail or str(error),
        field_key="building_name" if error.code == "property.house_location_invalid" else None,
        suggestion="核对既有房屋完整位置、辅助编号及业主姓名和手机号后重新预检或上传",
    )


class HouseOwnerImportAdapter:
    def normalize(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: (value.strip() or None) if isinstance(value, str) else value
            for key in _FIELDS
            for value in (row.get(key),)
        }

    def required_permissions(
        self, normalized_input: Mapping[str, Any], prepared: Mapping[str, Any] | None = None
    ) -> frozenset[str]:
        return house_owner_creation_permissions()

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
                tuple(self.revalidate(fixed_prepared, context, db)),
                identity={
                    "operation_type": "house_owner.create",
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
            command = HouseOwnerCreationCommand.from_input(
                {
                    "house_id": snapshot["house_id"],
                    "name": normalized_input.get("name"),
                    "phone": normalized_input.get("phone"),
                }
            )
            identity = {
                "operation_type": "house_owner.create",
                "natural_key": command.to_dict(),
            }
            if normalized_input.get("house_external_code") is not None:
                snapshot = house_location_snapshot(
                    repo,
                    community_id,
                    snapshot["house_id"],
                    house_external_code=normalized_input["house_external_code"],
                )
            return ImportPreparation(
                prepare_house_owner_creation(
                    db,
                    company_id=context.scope.property_company_id,
                    community_id=community_id,
                    command=command,
                    house_snapshot=snapshot,
                ),
                identity=identity,
            )
        except AppError as error:
            return ImportPreparation(None, (_problem(error),), identity=identity)

    def plan(self, prepared: Mapping[str, Any]) -> ImportPlan:
        return ImportPlan(
            action=str(prepared["action"]),
            values=dict(prepared),
            operation_type="house_owner.create",
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
            if (
                context.scope.community_id is None
                or target
                and target["target_type"] != "house_owner"
            ):
                raise AppError("auth.forbidden")
            if target is not None and context.phase == "apply":
                return self._revalidate_target(prepared, context, db, target["target_id"])
            else:
                prepare_house_owner_creation(
                    db,
                    company_id=context.scope.property_company_id,
                    community_id=context.scope.community_id,
                    command=HouseOwnerCreationCommand.from_input(prepared["command"]),
                    house_snapshot=prepared["house_snapshot"],
                    target_id=target["target_id"] if target else prepared.get("target_id"),
                )
            return ()
        except AppError as error:
            return (_problem(error),)

    def _revalidate_target(
        self,
        prepared: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        target_id: str,
    ) -> Sequence[ImportProblem]:
        try:
            if context.scope.community_id is None:
                raise AppError("auth.forbidden")
            revalidate_house_owner_creation(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                actor_id=context.actor_id,
                command=HouseOwnerCreationCommand.from_input(prepared["command"]),
                house_snapshot=prepared["house_snapshot"],
                target_id=target_id,
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
            result = create_house_owner(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                actor_id=context.actor_id,
                command=HouseOwnerCreationCommand.from_input(operation.values["command"]),
                request_id=context.request_id,
                house_snapshot=operation.values["house_snapshot"],
                allow_existing=True,
                expected_target_id=operation.values.get("target_id")
                if operation.action == "skip"
                else None,
            )
            return {
                "status": result.status,
                "target_type": "house_owner",
                "target_id": result.owner.id,
            }
        except AppError as error:
            problem = _problem(error)
            raise ImportExecutionFailure(problem.code) from None

    def resolve_operation(
        self, operation_key: str, prepared: Mapping[str, Any], context: ImportContext, db: Session
    ) -> Mapping[str, Any] | None:
        # A matching registration does not prove that this logical operation created it.
        if prepared["action"] != "skip" or not prepared.get("target_id"):
            return None
        if self._revalidate_target(prepared, context, db, prepared["target_id"]):
            return None
        return {
            "status": "skipped",
            "target_type": "house_owner",
            "target_id": prepared["target_id"],
        }

    def presentation_fields(self) -> Sequence[dict[str, str]]:
        return (
            {"key": "house_label", "label": "完整位置", "format": "text"},
            {"key": "name", "label": "业主姓名", "format": "text"},
            {"key": "phone", "label": "手机号", "format": "text"},
            {"key": "owner_status", "label": "已有登记状态", "format": "text"},
        )

    def summary_fields(self) -> Sequence[dict[str, str]]:
        return ()

    def presentation(self, prepared: Mapping[str, Any]) -> Mapping[str, Any]:
        enabled = prepared["owner_enabled"]
        return {
            "house_label": prepared["house_label"],
            "name": prepared["command"]["name"],
            "phone": prepared["command"]["phone"],
            "owner_status": "新增登记" if enabled is None else "启用" if enabled else "停用",
        }
