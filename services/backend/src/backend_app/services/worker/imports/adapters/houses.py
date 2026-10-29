"""Convert housing file inputs and shared business results to the import protocol."""

import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.housing import (
    HouseCreationCommand,
    SpaceLocation,
    house_creation_identity,
    house_creation_permissions,
    resolve_space_location,
)
from backend_app.domain.imports.errors import ImportExecutionFailure
from backend_app.domain.imports.types import (
    ImportContext,
    ImportPlan,
    ImportPreparation,
    ImportProblem,
)
from backend_app.repositories.housing import HousingRepository
from backend_app.services.property_account_access import property_task_context
from backend_app.services.property_business.house_creation import (
    create_house,
    prepare_house_creation,
)

_FIELDS = ("phase_name", "building_name", "unit_name", "room_no", "floor_no", "external_code")
_INPUT_FIELDS = frozenset({"space_node_id", "room_no", "floor_no", "external_code"})


def _problem(error: AppError) -> ImportProblem:
    if error.code.startswith("auth."):
        raise error
    code = {
        "property.house_location_invalid": "import.house_location_invalid",
        "property.house_location_changed": "import.house_location_changed",
        "VALIDATION_ERROR": "import.validation_failed",
    }.get(error.code, "import.conflict")
    return ImportProblem(
        code,
        error.public_detail or str(error),
        field_key="building_name" if error.code == "property.house_location_invalid" else None,
        suggestion="先维护完整空间层级，再核对房号、楼层及外部编号后重新预检或上传",
    )


class HouseImportAdapter:
    def normalize(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: (value.strip() or None) if isinstance(value, str) else value
            for key in _FIELDS
            for value in (row.get(key),)
        }

    def required_permissions(
        self, normalized_input: Mapping[str, Any], prepared: Mapping[str, Any] | None = None
    ) -> frozenset[str]:
        return house_creation_permissions()

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
                    "operation_type": "house.create",
                    "natural_key": dict(fixed_prepared["natural_key"]),
                },
            )
        identity = None
        try:
            if context.scope.community_id is None:
                raise AppError("auth.forbidden")
            snapshot = resolve_space_location(
                HousingRepository(db, context.scope.property_company_id),
                context.scope.community_id,
                SpaceLocation(
                    phase_name=normalized_input.get("phase_name"),
                    building_name=cast(str, normalized_input.get("building_name")),
                    unit_name=normalized_input.get("unit_name"),
                ),
            )
            identity = {
                "operation_type": "house.create",
                "natural_key": house_creation_identity(
                    snapshot["space_node_id"], cast(str, normalized_input.get("room_no"))
                ),
            }
            floor = normalized_input.get("floor_no")
            if isinstance(floor, str) and re.fullmatch(r"[+-]?[0-9]+", floor):
                try:
                    floor = int(floor)
                except ValueError:
                    # Oversized integer text is invalid row input, not a task failure.
                    pass
            if floor is not None and type(floor) is not int:
                return ImportPreparation(
                    None,
                    (
                        ImportProblem(
                            "import.validation_failed", "楼层须为整数或留空", field_key="floor_no"
                        ),
                    ),
                    identity=identity,
                )
            command = HouseCreationCommand.from_input(
                {
                    "space_node_id": snapshot["space_node_id"],
                    "room_no": normalized_input.get("room_no"),
                    "floor_no": floor,
                    "external_code": normalized_input.get("external_code"),
                }
            )
            return ImportPreparation(
                prepare_house_creation(
                    db,
                    company_id=context.scope.property_company_id,
                    community_id=context.scope.community_id,
                    command=command,
                    space_snapshot=snapshot,
                ),
                identity=identity,
            )
        except AppError as error:
            return ImportPreparation(None, (_problem(error),), identity=identity)

    def plan(self, prepared: Mapping[str, Any]) -> ImportPlan:
        return ImportPlan(
            action=str(prepared["action"]),
            values=dict(prepared),
            operation_type="house.create",
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
            if context.scope.community_id is None or target and target["target_type"] != "house":
                raise AppError("auth.forbidden")
            prepare_house_creation(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                command=HouseCreationCommand.from_input(prepared["command"]),
                space_snapshot=prepared["space_snapshot"],
                target_id=target["target_id"] if target else prepared.get("target_id"),
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
            result = create_house(
                db,
                company_id=context.scope.property_company_id,
                community_id=context.scope.community_id,
                actor_id=context.actor_id,
                context=property_task_context(
                    db, context.scope.property_company_id, context.actor_id
                ),
                command=HouseCreationCommand.from_input(operation.values["command"]),
                request_id=context.request_id,
                input_fields=_INPUT_FIELDS,
                space_snapshot=operation.values["space_snapshot"],
                allow_existing=True,
                expected_target_id=operation.values.get("target_id")
                if operation.action == "skip"
                else None,
            )
            return {"status": result.status, "target_type": "house", "target_id": result.house.id}
        except AppError as error:
            problem = _problem(error)
            raise ImportExecutionFailure(problem.code) from None

    def resolve_operation(
        self, operation_key: str, prepared: Mapping[str, Any], context: ImportContext, db: Session
    ) -> Mapping[str, Any] | None:
        # Creation evidence lives in the framework's atomic operation ledger. A house
        # matching a natural key cannot prove which operation created it.
        if prepared["action"] != "skip" or not prepared.get("target_id"):
            return None
        if self.revalidate(prepared, context, db):
            return None
        return {"status": "skipped", "target_type": "house", "target_id": prepared["target_id"]}

    def presentation_fields(self) -> Sequence[dict[str, str]]:
        return (
            {"key": "house_label", "label": "完整位置", "format": "text"},
            {"key": "room_no", "label": "房号", "format": "text"},
            {"key": "floor_no", "label": "楼层", "format": "text"},
            {"key": "external_code", "label": "房屋外部编号", "format": "text"},
        )

    def summary_fields(self) -> Sequence[dict[str, str]]:
        return ()

    def presentation(self, prepared: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "house_label": prepared["house_label"],
            **{key: prepared["command"][key] for key in ("room_no", "floor_no", "external_code")},
        }
