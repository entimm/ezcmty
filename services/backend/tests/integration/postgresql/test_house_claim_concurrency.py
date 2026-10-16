from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from typing import Any, Literal

import pytest
from sqlalchemy import func, select, text
from tests.support.house_claims import ClaimSetup

from backend_app.core.errors import AppError
from backend_app.models.admin import AdminAuditLog
from backend_app.models.house_claims import HouseClaim, ResidentHouseBinding
from backend_app.repositories.house_claims import HouseClaimRepository
from backend_app.schemas.house_claims import ClaimCancellation, ClaimReview
from backend_app.services.property_admin.house_claims import PropertyHouseClaimService
from backend_app.services.resident.house_claims import ResidentHouseClaimService


@pytest.mark.parametrize("decision", ["approved", "rejected"])
@pytest.mark.parametrize("winner", ["cancelled", "review"])
def test_withdrawal_and_review_compete_on_database_atomic_update(
    claim_setup: ClaimSetup,
    monkeypatch: pytest.MonkeyPatch,
    decision: Literal["approved", "rejected"],
    winner: str,
) -> None:
    setup = claim_setup
    held, attempted, release = Event(), Event(), Event()
    original = HouseClaimRepository.transition_claim
    winner_status = "cancelled" if winner == "cancelled" else decision
    pids: dict[str, int] = {}

    def transition(
        repo: HouseClaimRepository, claim: HouseClaim, version: int, status: str, **kwargs: Any
    ) -> HouseClaim:
        pids[status] = repo.db.scalar(text("SELECT pg_backend_pid()"))
        if status == winner_status:
            result = original(repo, claim, version, status, **kwargs)
            held.set()
            assert release.wait(10), "Winner was not released"
            return result
        assert held.wait(10)
        attempted.set()
        return original(repo, claim, version, status, **kwargs)

    monkeypatch.setattr(HouseClaimRepository, "transition_claim", transition)

    def operate(status: str) -> str:
        with setup.factory() as db:
            try:
                if status == "cancelled":
                    result = ResidentHouseClaimService(db).cancel(
                        setup.context, setup.claim.id, ClaimCancellation(expected_row_version=1)
                    )
                else:
                    result = PropertyHouseClaimService(db).review(
                        setup.housing.context,
                        setup.claim.id,
                        ClaimReview(expected_row_version=1, decision=decision, reason="人工核实"),
                        "review-race",
                    )
                return result.status
            except AppError as exc:
                assert exc.code == "resident.state_changed" and exc.status_code == 409
                return "conflict"

    loser_status = decision if winner_status == "cancelled" else "cancelled"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(operate, winner_status)
        try:
            assert held.wait(10)
            second = pool.submit(operate, loser_status)
            assert attempted.wait(10)
            with setup.factory() as observer:
                deadline = monotonic() + 5
                while True:
                    blockers = observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[loser_status]}
                    )
                    if pids[winner_status] in blockers:
                        break
                    assert monotonic() < deadline, "Loser did not wait on the actual PostgreSQL row"
        finally:
            release.set()
        assert first.result(timeout=10) == winner_status
        assert second.result(timeout=10) == "conflict"
    with setup.factory() as db:
        claim = db.get(HouseClaim, setup.claim.id)
        assert claim and claim.status == winner_status and claim.row_version == 2
        assert db.scalar(select(func.count()).select_from(ResidentHouseBinding)) == int(
            winner_status == "approved"
        )
        assert db.scalar(
            select(func.count())
            .select_from(AdminAuditLog)
            .where(AdminAuditLog.action == "property.house_claim.review")
        ) == int(winner_status != "cancelled")


def test_repeated_review_returns_conflict_and_keeps_one_binding(claim_setup: ClaimSetup) -> None:
    s = claim_setup
    with s.factory() as db:
        service = PropertyHouseClaimService(db)
        service.review(
            s.housing.context,
            s.claim.id,
            ClaimReview(expected_row_version=1, decision="approved"),
            "first",
        )
        with pytest.raises(AppError) as caught:
            service.review(
                s.housing.context,
                s.claim.id,
                ClaimReview(expected_row_version=1, decision="approved"),
                "again",
            )
        assert caught.value.code == "resident.state_changed"
        assert db.scalar(select(func.count()).select_from(ResidentHouseBinding)) == 1
