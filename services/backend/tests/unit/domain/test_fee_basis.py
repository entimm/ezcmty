from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any, cast
from unittest.mock import Mock

import pytest
from pytest import MonkeyPatch
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.domain.billing import MAX_CENTS
from backend_app.domain.billing.basis import (
    FeeBasisCreationCommand,
    fee_basis_fingerprint,
    matches_fee_basis,
)
from backend_app.models.billing import FeeBasisVersion
from backend_app.repositories.billing import BillingRepository
from backend_app.services import fee_basis_creation as service


def command(**changes: Any) -> FeeBasisCreationCommand:
    return FeeBasisCreationCommand.from_input(
        {
            "house_id": "house",
            "effective_from_month": "2026-04",
            "house_usage": "residential",
            "area_sqm": "100.0000",
            "unit_price_cents": 200,
            "fixed_amount_cents": None,
            "change_reason": " 调整 ",
            **changes,
        }
    )


def basis(**changes: Any) -> FeeBasisVersion:
    values = command().to_dict()
    values["area_sqm"] = Decimal(values["area_sqm"])
    values["effective_from_month"] = date(2026, 4, 1)
    return FeeBasisVersion(id="basis", version_no=2, **{**values, **changes})


@pytest.fixture
def snapshot() -> dict[str, Any]:
    return {
        "house_id": "house",
        "community_id": "community",
        "community_name": "小区",
        "space_node_id": "building",
        "path": [{"id": "building", "node_type": "building", "name": "01栋", "enabled": True}],
        "room_no": "0001",
        "house_external_code": None,
        "external_code": "unsubmitted-code",
        "effective_enabled": True,
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"area_sqm": "1.005", "unit_price_cents": 100}, 101),
        ({"area_sqm": None, "unit_price_cents": None, "fixed_amount_cents": 0}, 0),
        ({"unit_price_cents": 0}, 0),
        ({"area_sqm": "99999999.9999", "fixed_amount_cents": 1}, 1),
    ],
)
def test_validated_basis_preserves_exact_calculation(
    changes: dict[str, Any], expected: int
) -> None:
    assert command(**changes).calculated_amount() == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"change_reason": " \n "},
        {"change_reason": "原" * 1001},
        {"house_usage": "unknown"},
        {"effective_from_month": "2026-13"},
        {"effective_from_month": "0000-01"},
        {"area_sqm": "0", "fixed_amount_cents": 100},
        {"area_sqm": "100000000"},
        {"area_sqm": "1.00001"},
        {"area_sqm": "-1"},
        {"area_sqm": "1e2"},
        {"unit_price_cents": True, "fixed_amount_cents": 100},
        {"unit_price_cents": MAX_CENTS + 1, "fixed_amount_cents": 100},
        {"fixed_amount_cents": -1},
        {"area_sqm": None},
        {"unit_price_cents": None},
        {"unit_price_cents": MAX_CENTS},
    ],
)
def test_complete_input_is_validated_even_with_fixed_precedence(changes: dict[str, Any]) -> None:
    with pytest.raises(AppError) as caught:
        command(**changes)
    assert caught.value.code == "VALIDATION_ERROR"


def test_same_basis_uses_decimal_equality_and_excludes_reason() -> None:
    existing = basis(area_sqm=Decimal("100.0000"), change_reason="旧原因")
    assert matches_fee_basis(command(area_sqm="100"), existing)
    assert not matches_fee_basis(command(), existing, include_reason=True)
    assert command().area_sqm == "100" and command().change_reason == "调整"


@pytest.mark.parametrize(
    "changes",
    [
        {"area_sqm": "50", "unit_price_cents": 400},
        {"house_usage": "commercial"},
        {"effective_from_month": "2026-05"},
        {"house_id": "another-house"},
    ],
)
def test_same_amount_does_not_make_basis_equal(changes: dict[str, Any]) -> None:
    assert not matches_fee_basis(command(**changes), basis())


@pytest.mark.parametrize("changes", [{"area_sqm": "101"}, {"unit_price_cents": None}])
def test_fixed_basis_still_compares_idle_parameters(changes: dict[str, Any]) -> None:
    existing = basis(fixed_amount_cents=30000)
    proposed = command(fixed_amount_cents=30000, **changes)
    assert proposed.calculated_amount() == 30000
    assert not matches_fee_basis(proposed, existing)


def test_null_fixed_amount_and_zero_fixed_amount_are_distinct() -> None:
    assert not matches_fee_basis(command(fixed_amount_cents=0), basis(unit_price_cents=0))


def test_fingerprint_tracks_intent_and_baseline_but_not_derived_state(
    snapshot: dict[str, Any],
) -> None:
    original = fee_basis_fingerprint(command(), snapshot, 1)
    changed = deepcopy(snapshot)
    changed["effective_enabled"] = False
    changed["path"][0]["enabled"] = False
    changed["external_code"] = "another-unsubmitted-code"
    changed["preview_text"] = "changed"
    assert fee_basis_fingerprint(command(area_sqm="100.0000"), changed, 1) == original
    assert fee_basis_fingerprint(command(), snapshot, 2) != original
    assert fee_basis_fingerprint(command(change_reason="新原因"), snapshot, 1) != original
    changed["path"][0]["name"] = "02栋"
    assert fee_basis_fingerprint(command(), changed, 1) != original


@pytest.fixture
def repo(monkeypatch: MonkeyPatch, snapshot: dict[str, Any]) -> Mock:
    result = Mock(spec=BillingRepository)
    result.housing = Mock()
    result.latest_basis_number.return_value = 2
    result.latest_basis_for_month.return_value = basis()
    result.next_basis_month.return_value = date(2026, 7, 1)
    monkeypatch.setattr(service, "BillingRepository", lambda *_: result)
    monkeypatch.setattr(service, "house_location_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(service, "revalidate_house_location", lambda *_args, **_kwargs: snapshot)
    return result


def test_prepare_compares_same_month_and_preserves_next_boundary(repo: Mock) -> None:
    repo.latest_basis_for_month.return_value = None
    prepared = service.prepare_fee_basis_creation(
        Mock(spec=Session), company_id="company", community_id="community", command=command()
    )
    assert prepared["action"] == "create" and prepared["old_basis"] is None
    assert prepared["next_effective_month"] == "2026-07"
    assert prepared["expected_latest_version_no"] == 2
    repo.latest_basis_for_month.assert_called_once_with("house", date(2026, 4, 1))
    repo.effective_basis.assert_not_called()


@pytest.mark.parametrize("action", ["create", "skip"])
def test_new_operations_reject_stale_baseline_even_if_contents_now_match(
    repo: Mock, action: str
) -> None:
    with pytest.raises(AppError) as caught:
        service.prepare_fee_basis_creation(
            Mock(spec=Session),
            company_id="company",
            community_id="community",
            command=command(),
            expected_latest_version_no=1,
            expected_action=action,
            expected_target_id="basis" if action == "skip" else None,
        )
    assert caught.value.code == "billing.basis_version_conflict"


def test_skip_cannot_silently_upgrade_to_create(repo: Mock) -> None:
    repo.latest_basis_for_month.return_value = basis(unit_price_cents=300)
    with pytest.raises(AppError) as caught:
        service.prepare_fee_basis_creation(
            Mock(spec=Session),
            company_id="company",
            community_id="community",
            command=command(),
            expected_latest_version_no=2,
            expected_action="skip",
            expected_target_id="basis",
        )
    assert caught.value.code == "billing.basis_version_conflict"


def test_a_to_b_to_a_uses_latest_month_comparison(repo: Mock) -> None:
    repo.latest_basis_for_month.return_value = basis(unit_price_cents=300)
    prepared = service.prepare_fee_basis_creation(
        Mock(spec=Session), company_id="company", community_id="community", command=command()
    )
    assert prepared["action"] == "create" and prepared["comparison_version_no"] == 2
    assert prepared["changed_fields"] == ["unit_price_cents"]


@pytest.mark.parametrize("original_status", ["created", "skipped"])
def test_original_success_is_verified_without_requiring_latest(
    repo: Mock, original_status: str
) -> None:
    target = basis(change_reason="调整" if original_status == "created" else "另一原因")
    repo.basis.return_value = target
    result = service.verify_fee_basis_result(
        Mock(spec=Session),
        company_id="company",
        community_id="community",
        command=command(),
        target_id="basis",
        original_status=original_status,
        expected_latest_version_no=1,
        expected_target_id="basis" if original_status == "skipped" else None,
    )
    assert result is target
    repo.latest_basis_number.assert_not_called()
    repo.latest_basis_for_month.assert_not_called()


def test_original_created_result_requires_original_reason(repo: Mock) -> None:
    repo.basis.return_value = basis(change_reason="另一原因")
    with pytest.raises(AppError) as caught:
        service.verify_fee_basis_result(
            Mock(spec=Session),
            company_id="company",
            community_id="community",
            command=command(),
            target_id="basis",
            original_status="created",
            expected_latest_version_no=1,
        )
    assert caught.value.code == "billing.basis_version_conflict"


def test_apply_reuse_protects_parent_resources_before_house_and_does_not_check_latest(
    repo: Mock, monkeypatch: MonkeyPatch, snapshot: dict[str, Any]
) -> None:
    events: list[str] = []
    actor = Mock(id="actor", enabled=True, must_change_password=False)

    def protect(*_args: Any) -> tuple[Mock, Mock, Mock]:
        events.append("company/account/community")
        return Mock(enabled=True), actor, Mock()

    def house(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        events.append("house")
        assert kwargs["lock"] is True and kwargs["exclusive"] is False
        return snapshot

    repo.protect.side_effect = protect
    repo.basis.return_value = basis()
    identity = Mock()
    identity.effective_permissions.return_value = {"property.fee_basis.manage"}
    monkeypatch.setattr(service, "AdminIdentity", lambda *_: identity)
    monkeypatch.setattr(service, "house_location_snapshot", house)
    service.verify_fee_basis_result(
        Mock(spec=Session),
        company_id="company",
        community_id="community",
        command=command(),
        target_id="basis",
        original_status="created",
        expected_latest_version_no=1,
        actor_id="actor",
        lock=True,
    )
    assert events == ["company/account/community", "house"]
    repo.latest_basis_number.assert_not_called()


def test_apply_reuse_requires_current_maintenance_permission_before_house_read(
    repo: Mock, monkeypatch: MonkeyPatch
) -> None:
    repo.protect.return_value = (
        Mock(enabled=True),
        Mock(id="actor", enabled=True, must_change_password=False),
        Mock(),
    )
    identity = Mock()
    identity.effective_permissions.return_value = {"property.bill.read"}
    monkeypatch.setattr(service, "AdminIdentity", lambda *_: identity)
    house = Mock()
    monkeypatch.setattr(service, "house_location_snapshot", house)
    with pytest.raises(AppError) as caught:
        service.verify_fee_basis_result(
            Mock(spec=Session),
            company_id="company",
            community_id="community",
            command=command(),
            target_id="basis",
            original_status="created",
            actor_id="actor",
            lock=True,
        )
    assert caught.value.code == "auth.forbidden"
    house.assert_not_called()


@pytest.mark.parametrize("verify_success", [False, True])
def test_disabled_path_blocks_new_skip_and_success_reuse(
    repo: Mock, snapshot: dict[str, Any], verify_success: bool
) -> None:
    snapshot["effective_enabled"] = False
    with pytest.raises(AppError) as caught:
        if verify_success:
            service.verify_fee_basis_result(
                Mock(spec=Session),
                company_id="company",
                community_id="community",
                command=command(),
                target_id="basis",
                original_status="skipped",
            )
        else:
            service.prepare_fee_basis_creation(
                Mock(spec=Session),
                company_id="company",
                community_id="community",
                command=command(),
            )
    assert caught.value.code == "property.housing_disabled"


@pytest.mark.parametrize("allow_existing", [False, True])
def test_manual_appends_same_content_and_import_skip_has_no_audit_or_commit(
    repo: Mock, monkeypatch: MonkeyPatch, allow_existing: bool
) -> None:
    repo.protect.return_value = (
        Mock(enabled=True),
        Mock(id="actor", enabled=True, must_change_password=False),
        Mock(),
    )
    identity = Mock()
    identity.effective_permissions.return_value = {"property.fee_basis.manage"}
    monkeypatch.setattr(service, "AdminIdentity", lambda *_: identity)
    original = basis()
    repo.basis.return_value = original
    db = Mock(spec=Session)
    result = service.create_fee_basis(
        cast(Session, db),
        company_id="company",
        community_id="community",
        actor_id="actor",
        command=command(),
        expected_latest_version_no=2,
        request_id="request",
        allow_existing=allow_existing,
        expected_action="skip" if allow_existing else None,
        expected_target_id="basis" if allow_existing else None,
    )
    if allow_existing:
        assert result.status == "skipped" and result.basis is original
        identity.audit.record.assert_not_called()
        db.add.assert_not_called()
    else:
        assert result.status == "created" and result.basis.version_no == 3
        identity.audit.record.assert_called_once()
        db.add.assert_called_once_with(result.basis)
    db.commit.assert_not_called()
