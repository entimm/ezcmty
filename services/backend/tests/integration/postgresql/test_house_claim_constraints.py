from dataclasses import replace

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from tests.support.house_claims import ClaimSetup

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.schemas.house_claims import ClaimReview
from backend_app.services.property_admin.house_claims import PropertyHouseClaimService


@pytest.mark.parametrize(
    "change",
    [
        "applicant_phone='bad'",
        "status='rejected'",
        "applicant_name='其他人'",
    ],
)
def test_application_has_only_independent_phone_snapshot_and_frozen_facts(
    claim_setup: ClaimSetup, change: str
) -> None:
    with claim_setup.factory() as db:
        columns = {
            c["name"] for c in inspect(db.connection()).get_columns("house_claim_applications")
        }
        assert "applicant_phone" in columns
        assert not columns & {
            "phone_binding_id",
            "phone_verification_id",
            "phone_verified_at",
            "phone_snapshot",
            "wechat_appid",
        }
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    f"UPDATE house_claim_applications SET {change},row_version=row_version+1 "
                    "WHERE id=:id"
                ),
                {"id": claim_setup.claim.id},
            )
            db.commit()


def test_partial_unique_pending_claim_and_binding_origin_scope_are_native_constraints(
    claim_setup: ClaimSetup,
) -> None:
    s = claim_setup
    with s.factory() as db:
        with pytest.raises(IntegrityError) as duplicate:
            db.execute(
                text("""INSERT INTO house_claim_applications
                SELECT :new_id,user_id,property_company_id,community_id,house_id,
                    house_label_snapshot,applicant_name,applicant_phone,applicant_remark,
                    match_status,matched_owner_id,status,reviewed_by_admin_id,reviewed_at,
                    review_reason,cancelled_at,row_version,'another-key',request_fingerprint,
                    created_at,updated_at FROM house_claim_applications WHERE id=:id"""),
                {"new_id": new_id(), "id": s.claim.id},
            )
            db.commit()
        assert getattr(duplicate.value.orig, "sqlstate", None) == "23505"
        db.rollback()
        with pytest.raises(IntegrityError) as scope:
            db.execute(
                text("""INSERT INTO resident_house_bindings
                (id,user_id,property_company_id,community_id,house_id,claim_application_id,
                 status,granted_at,row_version,created_at,updated_at)
                SELECT :new_id,:other_user,property_company_id,community_id,house_id,id,
                    'active',now(),1,now(),now() FROM house_claim_applications WHERE id=:id"""),
                {"new_id": new_id(), "other_user": new_id(), "id": s.claim.id},
            )
            db.commit()
        assert getattr(scope.value.orig, "sqlstate", None) == "23503"


@pytest.mark.parametrize(
    "permissions",
    [
        ["property.house_claim.read"],
        ["property.house_claim.review"],
        [],
    ],
)
def test_review_requires_both_read_and_review_permissions(
    claim_setup: ClaimSetup, permissions: list[str]
) -> None:
    s = claim_setup
    ctx = replace(s.housing.context, permissions=permissions)
    with s.factory() as db, pytest.raises(AppError) as caught:
        PropertyHouseClaimService(db).review(
            ctx, s.claim.id, ClaimReview(expected_row_version=1, decision="approved"), "permission"
        )
    assert caught.value.code == "auth.forbidden"
