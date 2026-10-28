from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.imports.types import ImportContext, ImportScope
from backend_app.import_definitions.catalog import get_import_registry
from backend_app.services.imports import presentation
from backend_app.services.worker.imports.adapters import fee_bases
from backend_app.services.worker.imports.adapters.fee_bases import FeeBasisImportAdapter

HOUSE_ID = "019a1234-1234-7123-8123-123456789abc"
TARGET_ID = "019a1234-1234-7123-8123-123456789abd"
COMPANY_ID = "019a1234-1234-7123-8123-123456789abe"
COMMUNITY_ID = "019a1234-1234-7123-8123-123456789abf"
DB = cast(Session, object())
CONTEXT = ImportContext(
    "property_admin", "actor", ImportScope(COMPANY_ID, "community", COMMUNITY_ID), "request"
)


def _row(**changes: Any) -> dict[str, Any]:
    return {
        "phase_name": "",
        "building_name": "01栋",
        "unit_name": "",
        "room_no": "0001",
        "house_external_code": "",
        "effective_from_month": "2026-10",
        "house_usage": "住宅",
        "area_sqm": "100.0000",
        "unit_price_amount": "2.50",
        "fixed_amount": "",
        "change_reason": "批量调价",
        **changes,
    }


def _prepared(action: str = "create") -> dict[str, Any]:
    new = fee_bases._command(FeeBasisImportAdapter().normalize(_row()), HOUSE_ID).to_dict()
    old = {**new, "unit_price_cents": 200, "change_reason": "原标准"}
    if action == "skip":
        old["unit_price_cents"] = new["unit_price_cents"]
    return {
        "command": new,
        "house_snapshot": {"house_id": HOUSE_ID, "private": "not-an-api-field"},
        "natural_key": {"house_id": HOUSE_ID},
        "input_fingerprint": "a" * 64,
        "expected_latest_version_no": 4,
        "comparison_version_id": TARGET_ID,
        "comparison_version_no": 3,
        "old_basis": old,
        "new_basis": new,
        "changed_fields": ["unit_price_cents"] if action == "create" else [],
        "calculated_amount_cents": 25000,
        "next_effective_month": "2027-01",
        "house_label": "示例小区／01栋／0001",
        "action": action,
        "target_id": TARGET_ID if action == "skip" else None,
    }


def test_fee_basis_template_uses_its_own_business_permissions_and_fixed_complete_columns() -> None:
    definition = get_import_registry().get("property_fee_basis_versions", 1)
    assert definition.required_permissions == ("property.fee_basis.manage",)
    assert definition.read_permissions == ("property.bill.read",)
    assert definition.allowed_actor_scopes == ("property_admin",)
    assert definition.allowed_scope_types == ("community",)
    assert tuple(field.key for field in definition.fields) == tuple(_row())
    assert definition.headers == (
        "分区",
        "楼栋",
        "单元",
        "房号",
        "房屋外部编号",
        "生效月份",
        "房屋用途",
        "计费面积（㎡）",
        "月单价（元/㎡）",
        "固定月费（元）",
        "变更原因",
    )
    adapter = FeeBasisImportAdapter()
    assert adapter.required_permissions({}, None) == {"property.fee_basis.manage"}
    assert adapter.summary_fields() == ()


def test_file_conversion_is_exact_preserves_zero_and_canonicalizes_area() -> None:
    adapter = FeeBasisImportAdapter()
    normalized = adapter.normalize(_row(room_no=" 0001 ", change_reason=" 原因 ", secret="private"))
    assert normalized["room_no"] == "0001"
    assert normalized["house_external_code"] is None
    assert "secret" not in normalized
    command = fee_bases._command(normalized, HOUSE_ID)
    assert command.area_sqm == "100"
    assert command.house_usage == "residential"
    assert command.unit_price_cents == 250
    assert command.fixed_amount_cents is None
    assert command.change_reason == "原因"
    zero = fee_bases._command(
        adapter.normalize(_row(area_sqm="", unit_price_amount="", fixed_amount="0")), HOUSE_ID
    )
    assert zero.area_sqm is None and zero.unit_price_cents is None
    assert zero.fixed_amount_cents == 0


@pytest.mark.parametrize(
    "amount",
    ["-1", "0.001", "￥1", "1e2", "NaN", "Infinity", True, "90071992547409.92", "9" * 5000],
)
def test_amount_conversion_rejects_rounding_symbols_nonfinite_and_out_of_range(amount: Any) -> None:
    with pytest.raises(fee_bases._CellFormatError):
        fee_bases._command(
            FeeBasisImportAdapter().normalize(_row(unit_price_amount=amount)), HOUSE_ID
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"house_usage": "residential"},
        {"effective_from_month": "2026-13"},
        {"area_sqm": "1.00001"},
        {"area_sqm": "0"},
        {"area_sqm": "100000000"},
        {"area_sqm": ""},
        {"change_reason": " "},
        {"fixed_amount": "0", "area_sqm": "-1"},
        {"fixed_amount": "0", "unit_price_amount": "0.001"},
    ],
)
def test_invalid_basis_keeps_house_identity_for_same_file_duplicate_detection(
    changes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fee_bases, "resolve_house_location", lambda *args: {"house_id": HOUSE_ID})
    result = FeeBasisImportAdapter().prepare(
        FeeBasisImportAdapter().normalize(_row(**changes)), CONTEXT, DB
    )
    assert result.prepared is None
    assert result.identity == {
        "operation_type": "property_fee_basis.create",
        "natural_key": {"house_id": HOUSE_ID},
    }
    assert {problem.code for problem in result.problems} == {"import.validation_failed"}


def test_optional_code_failure_still_marks_the_identified_house_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fee_bases, "resolve_house_location", lambda *args: {"house_id": HOUSE_ID})
    monkeypatch.setattr(
        fee_bases,
        "house_location_snapshot",
        Mock(side_effect=AppError("property.house_external_code_mismatch")),
    )
    adapter = FeeBasisImportAdapter()
    result = adapter.prepare(adapter.normalize(_row(house_external_code="OTHER")), CONTEXT, DB)
    assert result.identity is not None and result.identity["natural_key"] == {"house_id": HOUSE_ID}
    assert result.problems[0].code == "import.house_external_code_mismatch"


@pytest.mark.parametrize("action", ["create", "skip"])
def test_pending_revalidation_keeps_the_confirmed_baseline_and_action(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepared(action)
    prepare = Mock(side_effect=AppError("billing.basis_version_conflict"))
    monkeypatch.setattr(fee_bases, "prepare_fee_basis_creation", prepare)
    problems = FeeBasisImportAdapter().revalidate(prepared, CONTEXT, DB)
    assert [problem.code for problem in problems] == ["import.conflict"]
    assert prepare.call_args.kwargs["expected_latest_version_no"] == 4
    assert prepare.call_args.kwargs["expected_action"] == action
    assert prepare.call_args.kwargs["expected_target_id"] == prepared["target_id"]


@pytest.mark.parametrize("action,original_status", [("create", "created"), ("skip", "skipped")])
def test_success_revalidation_checks_its_original_target_without_reading_latest(
    action: str, original_status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    verify = Mock()
    prepare = Mock(side_effect=AssertionError("success must not check latest baseline"))
    monkeypatch.setattr(fee_bases, "verify_fee_basis_result", verify)
    monkeypatch.setattr(fee_bases, "prepare_fee_basis_creation", prepare)
    assert (
        FeeBasisImportAdapter().revalidate(
            _prepared(action),
            replace(CONTEXT, phase="apply"),
            DB,
            target={"target_type": "fee_basis_version", "target_id": TARGET_ID},
        )
        == ()
    )
    assert verify.call_args.kwargs["original_status"] == original_status
    assert verify.call_args.kwargs["expected_latest_version_no"] == 4
    assert verify.call_args.kwargs["target_id"] == TARGET_ID
    assert verify.call_args.kwargs["actor_id"] == CONTEXT.actor_id
    assert verify.call_args.kwargs["lock"] is True
    prepare.assert_not_called()


def test_unknown_append_never_infers_success_from_matching_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare = Mock(side_effect=AssertionError("a matching version cannot prove original success"))
    monkeypatch.setattr(fee_bases, "prepare_fee_basis_creation", prepare)
    assert FeeBasisImportAdapter().resolve_operation("key", _prepared(), CONTEXT, DB) is None
    prepare.assert_not_called()


def test_unknown_skip_requires_its_original_fixed_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    create = Mock(side_effect=AppError("billing.basis_version_conflict"))
    monkeypatch.setattr(fee_bases, "create_fee_basis", create)
    adapter = FeeBasisImportAdapter()
    assert adapter.resolve_operation("key", _prepared("skip"), CONTEXT, DB) is None
    create.side_effect = None
    create.return_value = SimpleNamespace(status="skipped", basis=SimpleNamespace(id=TARGET_ID))
    assert adapter.resolve_operation("key", _prepared("skip"), CONTEXT, DB) == {
        "status": "skipped",
        "target_type": "fee_basis_version",
        "target_id": TARGET_ID,
    }
    assert create.call_args.kwargs["expected_latest_version_no"] == 4
    assert create.call_args.kwargs["expected_action"] == "skip"
    assert create.call_args.kwargs["expected_target_id"] == TARGET_ID
    assert create.call_args.kwargs["actor_id"] == CONTEXT.actor_id
    assert create.call_args.kwargs["allow_existing"] is True


def test_safe_preview_shows_changes_and_period_without_internal_snapshots_or_fee_totals() -> None:
    adapter = FeeBasisImportAdapter()
    prepared = _prepared()
    original = deepcopy(prepared)
    values = presentation.values(adapter, prepared)
    assert values is not None
    assert values["comparison_version"] == "v3"
    assert values["changes"] == "月单价：2.00 元/㎡ → 2.50 元/㎡"
    assert values["calculated_amount_cents"] == 25000
    assert values["effective_period"] == "从 2026-10 起，至 2027-01 之前"
    assert values["result_version"] is None
    assert "house_snapshot" not in values and "command" not in values
    assert "private" not in str(values)
    assert prepared == original
    assert adapter.summary_fields() == ()
    prepared.update(old_basis=None, comparison_version_no=None, next_effective_month=None)
    values = presentation.values(adapter, prepared)
    assert values is not None and values["comparison_version"] == "该月无版本"
    assert values["old_basis"] == "该月无版本"
    assert values["effective_period"] == "从 2026-10 起持续适用"


@pytest.mark.parametrize(
    "action,status,operation_status,expected_version,source",
    [
        ("create", "created", "succeeded", 5, "新增版本"),
        ("create", "skipped", "succeeded", 5, "复用原成功"),
        ("skip", "skipped", "skipped", 3, "业务跳过"),
    ],
)
def test_result_projection_exposes_the_original_version_and_preserves_row_history(
    action: str, status: str, operation_status: str, expected_version: int, source: str
) -> None:
    target = {
        "status": operation_status,
        "target_type": "fee_basis_version",
        "target_id": TARGET_ID,
    }
    adapter = FeeBasisImportAdapter()
    values = presentation.values(adapter, _prepared(action), execution_status=status, target=target)
    assert values is not None
    assert values["result_version"] == f"v{expected_version}（{TARGET_ID}）"
    assert values["result_source"] == source
    failed = presentation.values(
        adapter, _prepared(action), execution_status="failed", target=target
    )
    assert failed is not None and failed["result_version"] is None
    assert failed["result_source"] is None


def test_result_projection_keeps_the_same_white_list_and_scalar_validation() -> None:
    class Adapter:
        def presentation_fields(self) -> tuple[dict[str, str], ...]:
            return ({"key": "allowed", "label": "业务值", "format": "text"},)

        def presentation(self, prepared: Any) -> dict[str, Any]:
            return {"allowed": "原值", "private": {"secret": True}}

        def result_presentation(self, prepared: Any, **kwargs: Any) -> dict[str, Any]:
            return {"allowed": "结果", "private": {"secret": True}}

    assert presentation.values(Adapter(), {}) == {"allowed": "结果"}

    class InvalidAdapter(Adapter):
        def result_presentation(self, prepared: Any, **kwargs: Any) -> dict[str, Any]:
            return {"allowed": {"secret": True}}

    with pytest.raises(ValueError, match="import.adapter_result_invalid"):
        presentation.values(InvalidAdapter(), {})


@pytest.mark.parametrize("action,status", [("create", "succeeded"), ("skip", "skipped")])
def test_fixed_retry_reuses_a_shared_success_before_checking_its_old_baseline(
    action: str, status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepared(action)
    operation = SimpleNamespace(
        operation_type="property_fee_basis.create",
        input_fingerprint=prepared["input_fingerprint"],
        natural_key=prepared["natural_key"],
        status=status,
        target_type="fee_basis_version",
        target_id=TARGET_ID,
    )
    lookup = Mock(return_value=operation)
    verify = Mock()
    pending = Mock(side_effect=AssertionError("original success must precede pending baseline"))
    monkeypatch.setattr(fee_bases, "get_operation_by_key", lookup)
    monkeypatch.setattr(fee_bases, "verify_fee_basis_result", verify)
    monkeypatch.setattr(fee_bases, "prepare_fee_basis_creation", pending)
    result = FeeBasisImportAdapter().prepare({}, CONTEXT, DB, fixed_prepared=prepared)
    assert result.prepared == prepared and result.problems == ()
    assert lookup.call_args.kwargs["lock"] is True
    assert lookup.call_args.kwargs["company_id"] == COMPANY_ID
    assert verify.call_args.kwargs["target_id"] == TARGET_ID
    pending.assert_not_called()


def test_fixed_retry_without_success_keeps_its_original_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    operation = SimpleNamespace(
        operation_type="property_fee_basis.create",
        input_fingerprint=prepared["input_fingerprint"],
        natural_key=prepared["natural_key"],
        status="failed",
        target_type=None,
        target_id=None,
    )
    pending = Mock(side_effect=AppError("billing.basis_version_conflict"))
    monkeypatch.setattr(fee_bases, "get_operation_by_key", Mock(return_value=operation))
    monkeypatch.setattr(fee_bases, "prepare_fee_basis_creation", pending)
    result = FeeBasisImportAdapter().prepare({}, CONTEXT, DB, fixed_prepared=prepared)
    assert result.prepared == prepared
    assert [problem.code for problem in result.problems] == ["import.conflict"]
    assert pending.call_args.kwargs["expected_latest_version_no"] == 4


def test_fixed_retry_rejects_a_mismatched_original_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    operation = SimpleNamespace(
        operation_type="property_fee_basis.create",
        input_fingerprint="b" * 64,
        natural_key=prepared["natural_key"],
        status="succeeded",
        target_type="fee_basis_version",
        target_id=TARGET_ID,
    )
    monkeypatch.setattr(fee_bases, "get_operation_by_key", Mock(return_value=operation))
    with pytest.raises(ValueError, match="import.operation_identity_mismatch"):
        FeeBasisImportAdapter().prepare({}, CONTEXT, DB, fixed_prepared=prepared)
