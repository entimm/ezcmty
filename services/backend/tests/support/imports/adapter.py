"""A test-only business table and adapter for end-to-end import acceptance."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend_app.core.identifiers import new_id
from backend_app.domain.imports.errors import ImportExecutionFailure, ImportOutcomeUnknown
from backend_app.domain.imports.fingerprints import fingerprint
from backend_app.domain.imports.registry import ImportDefinition, ImportField
from backend_app.domain.imports.types import (
    ImportContext,
    ImportPlan,
    ImportPreparation,
    ImportProblem,
)
from backend_app.import_definitions.catalog import JsonImportRegistry


class TestRecordAdapter:
    __test__ = False
    allow_retry = False
    unknown = False

    def normalize(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "code": str(row.get("code") or "").strip().upper(),
            "name": str(row.get("name") or "").strip(),
        }

    def prepare(
        self,
        row: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        fixed_prepared: Mapping[str, Any] | None = None,
    ) -> ImportPreparation:
        prepared = dict(fixed_prepared if fixed_prepared is not None else row)
        return ImportPreparation(
            prepared,
            tuple(self.revalidate(prepared, context, db)),
            identity={"operation_type": "test_record.create", "natural_key": {"code": row["code"]}}
            if row.get("code")
            else None,
        )

    def required_permissions(
        self, normalized_input: Mapping[str, Any], prepared: Mapping[str, Any] | None = None
    ) -> frozenset[str]:
        return frozenset()

    def revalidate(
        self,
        row: Mapping[str, Any],
        context: ImportContext,
        db: Session,
        *,
        target: Mapping[str, str] | None = None,
    ) -> Sequence[ImportProblem]:
        if row["name"] == "INVALID":
            return [ImportProblem("import.validation_failed", "名称不符合规则", field_key="name")]
        existing = db.execute(
            text(
                "SELECT name FROM import_test_records "
                "WHERE property_company_id=:company AND code=:code"
            ),
            {"company": context.scope.property_company_id, "code": row["code"]},
        ).scalar_one_or_none()
        if existing is not None and existing != row["name"]:
            return [ImportProblem("import.conflict", "已有记录内容不同", field_key="code")]
        if row["name"] == "WARNING":
            return [
                ImportProblem(
                    "import.value_warning", "请核对名称", severity="warning", field_key="name"
                )
            ]
        return []

    def plan(self, row: Mapping[str, Any]) -> ImportPlan:
        return ImportPlan(
            "create", dict(row), "test_record.create", {"code": row["code"]}, fingerprint(dict(row))
        )

    def execute(self, plan: ImportPlan, context: ImportContext, db: Session) -> Mapping[str, Any]:
        row = plan.values
        existing = (
            db.execute(
                text(
                    "SELECT id,name FROM import_test_records "
                    "WHERE property_company_id=:company AND code=:code FOR UPDATE"
                ),
                {"company": context.scope.property_company_id, "code": row["code"]},
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if existing["name"] != row["name"]:
                raise ValueError("import.conflict")
            return {
                "status": "skipped",
                "target_type": "test_record",
                "target_id": str(existing["id"]),
            }
        if row["name"] == "RETRY" and not self.allow_retry:
            raise ImportExecutionFailure("import.system_error", retryable=True)
        if row["name"] == "UNKNOWN" and self.unknown:
            raise ImportOutcomeUnknown
        record_id = new_id()
        db.execute(
            text(
                "INSERT INTO import_test_records "
                "(id,property_company_id,code,name,operation_key) "
                "VALUES (:id,:company,:code,:name,:operation_key)"
            ),
            {
                "id": record_id,
                "company": context.scope.property_company_id,
                "code": row["code"],
                "name": row["name"],
                "operation_key": row.get("_operation_key"),
            },
        )
        return {"status": "created", "target_type": "test_record", "target_id": record_id}

    def resolve_operation(
        self, operation_key: str, prepared: Mapping[str, Any], context: ImportContext, db: Session
    ) -> Mapping[str, Any] | None:
        row = db.execute(
            text(
                "SELECT id FROM import_test_records "
                "WHERE property_company_id=:company AND operation_key=:operation_key"
            ),
            {"company": context.scope.property_company_id, "operation_key": operation_key},
        ).scalar_one_or_none()
        return (
            {"status": "created", "target_type": "test_record", "target_id": str(row)}
            if row is not None
            else None
        )


def test_definition(version_no: int = 1) -> ImportDefinition:
    return ImportDefinition(
        released_at="2026-10-23T00:00:00Z",
        key="test_records",
        name="测试记录",
        version_no=version_no,
        adapter_key="test_records",
        fields=(
            ImportField(
                "code",
                "编码",
                1,
                required=True,
                max_length=30,
                normalization_rules=("trim", "uppercase"),
            ),
            ImportField(
                "name", "名称", 2, required=True, max_length=80, normalization_rules=("trim",)
            ),
        ),
    )


def test_registry(adapter: TestRecordAdapter | None = None) -> JsonImportRegistry:
    return JsonImportRegistry(
        (test_definition(),), {"test_records": adapter or TestRecordAdapter()}
    )


def install_test_records(db: Session) -> None:
    db.execute(
        text(
            "CREATE TABLE import_test_records (id uuid PRIMARY KEY, "
            "property_company_id uuid NOT NULL REFERENCES property_companies(id), "
            "code varchar(30) NOT NULL,name varchar(80) NOT NULL,operation_key char(64), "
            "UNIQUE(property_company_id,code),UNIQUE(property_company_id,operation_key))"
        )
    )
