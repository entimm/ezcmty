import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from tests.support.billing_services import BillingSetup
from tests.support.payments import PaymentSetup, complete_payment, provision_payment
from tests.support.wechatpay import WechatPayHarness

from backend_app.domain.payments.reconciliation import business_date
from backend_app.integrations.wechatpay.statements import Statements
from backend_app.models.admin import utc_now
from backend_app.models.miniapp import MiniappUser
from backend_app.models.payments import (
    PaymentChannelRequest,
    PaymentOrder,
    PaymentReconciliationDiscrepancy,
    PaymentReconciliationRun,
    PaymentTask,
    ProfitSharingAllocation,
)
from backend_app.repositories.payments.reconciliation import (
    ReconciliationRepository,
    ensure_run,
    lock_run,
    schedule_reconciliation,
)
from backend_app.repositories.payments.tasks import TaskLease, claim_tasks
from backend_app.services.worker.payments.reconciliation import ReconciliationService


def _required[T](value: T | None) -> T:
    assert value is not None
    return value


def scenario(setup: BillingSetup, *, paid_at: datetime, rate: int = 300) -> PaymentSetup:
    bill_id = setup.create().bill.id
    with setup.factory() as db:
        payment = provision_payment(db, setup, bill_id=bill_id, rate_bps=rate)
        complete_payment(db, payment, paid_at=paid_at)
        db.commit()
        return payment


def trade_file(
    setup: BillingSetup,
    payment: PaymentSetup,
    *,
    amount: int = 10000,
    fee: int = 60,
    wrong_identity: bool = False,
    extra: bool = False,
) -> bytes:
    with setup.factory() as db:
        order = _required(db.get(PaymentOrder, payment.order_id))
        payer = db.get(MiniappUser, payment.payer_user_id)
        assert order is not None and payer is not None and order.paid_at is not None
        timestamp = order.paid_at.isoformat()
        number, transaction = order.order_no, order.channel_transaction_no
        openid = payer.wechat_openid
    header = (
        "交易时间,公众账号ID,商户号,特约商户号,商户订单号,微信订单号,"
        "交易状态,订单金额,手续费,货币种类,用户标识"
    )
    row = (
        f"{timestamp},{'wrong' if wrong_identity else 'wx_test_app'},1900000001,1900000002,"
        f"{number},{transaction},SUCCESS,{amount / 100:.2f},{fee / 100:.2f},CNY,{openid}"
    )
    rows = [row]
    if extra:
        rows.append(
            f"{timestamp},wx_test_app,1900000001,1900000002,external_order,external_transaction,SUCCESS,1.23,0.01,CNY,external_payer"
        )
    return (
        header + "\n" + "\n".join(rows) + f"\n总交易单数,总交易额\n{len(rows)},100.00\n"
    ).encode()


def peer_statements(
    peer: WechatPayHarness, content: bytes, *, unavailable: bool = False
) -> Statements:
    digest = hashlib.sha1(content, usedforsecurity=False).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if unavailable:
            return peer.response({"code": "NO_BILL_EXIST", "message": "not yet generated"}, 404)
        if request.url.path == "/v3/billdownload/file":
            return httpx.Response(200, content=content)
        return peer.response(
            {
                "hash_type": "SHA1",
                "hash_value": digest,
                "download_url": "https://api.mch.weixin.qq.com/v3/billdownload/file?token=private",
            }
        )

    return Statements(peer.client(handler))


def service(setup: BillingSetup, statements: Statements, now: datetime) -> ReconciliationService:
    return ReconciliationService(
        setup.factory,
        statements,
        service_provider_merchant_no="1900000001",
        app_id="wx_test_app",
        clock=lambda: now,
    )


def create_run(setup: BillingSetup, day: Any, now: datetime, *, kind: str = "trade") -> str:
    with setup.factory() as db:
        run, _ = ensure_run(
            db,
            day=day,
            statement_type=kind,
            provider="1900000001",
            merchant="1900000002" if kind != "platform_fundflow" else None,
            now=now,
        )
        db.commit()
        return run.id


def run_once(setup: BillingSetup, worker: ReconciliationService, now: datetime) -> None:
    with setup.factory() as db:
        leases = claim_tasks(db, now=now, task_types={"reconciliation"})
        assert len(leases) == 1
        db.commit()
    worker.handle(leases[0])


def rerun(setup: BillingSetup, run_id: str, now: datetime) -> None:
    with setup.factory() as db:
        schedule_reconciliation(db, lock_run(db, run_id), now=now)
        db.commit()


def test_trade_statement_scoped_summary_fee_source_and_unknown_rows(
    billing_setup: BillingSetup,
) -> None:
    now = utc_now()
    payment = scenario(billing_setup, paid_at=now - timedelta(days=1))
    peer = WechatPayHarness()
    content = trade_file(billing_setup, payment, extra=True)
    run_id = create_run(billing_setup, business_date(now - timedelta(days=1)), now)
    run_once(billing_setup, service(billing_setup, peer_statements(peer, content), now), now)
    with billing_setup.factory() as db:
        run = _required(db.get(PaymentReconciliationRun, run_id))
        assert run is not None and run.status == "completed"
        assert run.summary["channel_count"] == 2 and run.summary["channel_amount_cents"] == 10123
        company = run.summary["company_summaries"][billing_setup.housing.company_id]
        assert company["channel_count"] == 1 and company["channel_amount_cents"] == 10000
        assert company["channel_fee_cents"] == 60
        assert _required(db.get(PaymentOrder, payment.order_id)).status == "succeeded"
        records = list(db.scalars(select(PaymentChannelRequest)))
        assert len(records) == 2 and all(record.finished_at is not None for record in records)
        downloaded = next(record for record in records if record.operation == "statement_download")
        assert (
            downloaded.response_snapshot is not None and downloaded.response_snapshot["decisions"]
        )
        assert "private" not in str([record.response_snapshot for record in records])
        differences = list(db.scalars(select(PaymentReconciliationDiscrepancy)))
        external = next(d for d in differences if d.difference_type == "channel_only")
        assert external.payment_order_id is None
        assert external.evidence["source_request_id"] == downloaded.id
        assert external.evidence["source_digest"] == "SHA1:" + _required(run.statement_hash)
        assert db.scalar(select(func.count()).select_from(ProfitSharingAllocation)) == 1


def test_same_payment_amount_and_fee_differences_keep_keys_and_reopen_resolution(
    billing_setup: BillingSetup,
) -> None:
    now = utc_now()
    payment = scenario(billing_setup, paid_at=now - timedelta(days=1))
    peer = WechatPayHarness()
    run_id = create_run(billing_setup, business_date(now - timedelta(days=1)), now)
    run_once(
        billing_setup,
        service(billing_setup, peer_statements(peer, trade_file(billing_setup, payment)), now),
        now,
    )
    now += timedelta(minutes=1)
    rerun(billing_setup, run_id, now)
    mismatch = trade_file(billing_setup, payment, amount=9999, fee=61)
    run_once(billing_setup, service(billing_setup, peer_statements(peer, mismatch), now), now)
    with billing_setup.factory() as db:
        differences = {
            d.evidence["check_code"]: d
            for d in db.scalars(select(PaymentReconciliationDiscrepancy))
        }
        assert differences["payment_amount"].expected_cents == 10000
        assert differences["channel_fee"].expected_cents == 60
        keys = {code: d.reference_key for code, d in differences.items()}
        amount = differences["payment_amount"]
        amount.status, amount.resolved_at = "resolved", now
        amount.resolved_by = billing_setup.housing.context.account_id
        amount.resolution_note = "external case 123"
        db.commit()
    now += timedelta(minutes=1)
    rerun(billing_setup, run_id, now)
    run_once(billing_setup, service(billing_setup, peer_statements(peer, mismatch), now), now)
    with billing_setup.factory() as db:
        differences = {
            d.evidence["check_code"]: d
            for d in db.scalars(select(PaymentReconciliationDiscrepancy))
        }
        assert {code: d.reference_key for code, d in differences.items()} == keys
        assert differences["payment_amount"].status == "open"
        assert differences["payment_amount"].resolution_note == "external case 123"
        assert differences["payment_amount"].resolved_by == billing_setup.housing.context.account_id
    now += timedelta(minutes=1)
    rerun(billing_setup, run_id, now)
    run_once(
        billing_setup,
        service(billing_setup, peer_statements(peer, trade_file(billing_setup, payment)), now),
        now,
    )
    with billing_setup.factory() as db:
        assert all(
            d.status == "resolved"
            for d in db.scalars(
                select(PaymentReconciliationDiscrepancy).where(
                    PaymentReconciliationDiscrepancy.reference_key.in_(
                        [keys["payment_amount"], keys["channel_fee"]]
                    )
                )
            )
        )
        records = list(
            db.scalars(
                select(PaymentChannelRequest).where(
                    PaymentChannelRequest.operation == "statement_download"
                )
            )
        )
        assert len(records) == 4 and all(r.finished_at is not None for r in records)


def test_missing_file_does_not_zero_or_resolve_previous_results(
    billing_setup: BillingSetup,
) -> None:
    now = utc_now()
    payment = scenario(billing_setup, paid_at=now - timedelta(days=1))
    peer = WechatPayHarness()
    run_id = create_run(billing_setup, business_date(now - timedelta(days=1)), now)
    run_once(
        billing_setup,
        service(
            billing_setup,
            peer_statements(peer, trade_file(billing_setup, payment, amount=9999)),
            now,
        ),
        now,
    )
    with billing_setup.factory() as db:
        previous_summary = _required(db.get(PaymentReconciliationRun, run_id)).summary
        previous_differences = [
            (d.id, d.status, d.evidence)
            for d in db.scalars(select(PaymentReconciliationDiscrepancy))
        ]
    now += timedelta(minutes=1)
    rerun(billing_setup, run_id, now)
    run_once(
        billing_setup,
        service(billing_setup, peer_statements(peer, b"", unavailable=True), now),
        now,
    )
    with billing_setup.factory() as db:
        run = _required(db.get(PaymentReconciliationRun, run_id))
        assert run is not None and run.status == "failed" and run.summary == previous_summary
        assert [
            (d.id, d.status, d.evidence)
            for d in db.scalars(select(PaymentReconciliationDiscrepancy))
        ] == previous_differences
        task = db.scalar(select(PaymentTask).where(PaymentTask.reconciliation_run_id == run_id))
        assert task is not None and task.status == "ready" and task.last_error == "NO_BILL_EXIST"


def test_decision_rollback_keeps_unsealed_trusted_source_and_no_partial_business_result(
    billing_setup: BillingSetup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utc_now()
    payment = scenario(billing_setup, paid_at=now - timedelta(days=1))
    peer = WechatPayHarness()
    run_id = create_run(billing_setup, business_date(now - timedelta(days=1)), now)
    original = ReconciliationRepository.apply_result

    def fail(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise RuntimeError("injected decision failure")

    monkeypatch.setattr(ReconciliationRepository, "apply_result", fail)
    with pytest.raises(RuntimeError, match="injected decision failure"):
        run_once(
            billing_setup,
            service(billing_setup, peer_statements(peer, trade_file(billing_setup, payment)), now),
            now,
        )
    with billing_setup.factory() as db:
        source = _required(
            db.scalar(
                select(PaymentChannelRequest).where(
                    PaymentChannelRequest.operation == "statement_download"
                )
            )
        )
        assert (
            source is not None
            and source.outcome == "verified_response"
            and source.finished_at is None
        )
        assert source.response_snapshot is not None and "decisions" not in source.response_snapshot
        assert db.scalar(select(func.count()).select_from(PaymentReconciliationDiscrepancy)) == 0
        run = _required(db.get(PaymentReconciliationRun, run_id))
        assert run is not None and run.status == "running" and run.statement_hash is None


def test_bounded_multi_worker_producer_fills_downtime_and_includes_disabled_history(
    billing_setup: BillingSetup,
) -> None:
    now = utc_now()
    scenario(billing_setup, paid_at=now - timedelta(minutes=2))
    peer = WechatPayHarness()
    worker = service(billing_setup, peer_statements(peer, b""), now + timedelta(days=5))
    with ThreadPoolExecutor(max_workers=2) as pool:
        produced = list(pool.map(lambda _: worker.scan(limit=4), range(2)))
    assert sum(produced) <= 8
    for _ in range(10):
        if worker.scan(limit=4) == 0:
            break
    with billing_setup.factory() as db:
        runs = list(db.scalars(select(PaymentReconciliationRun)))
        assert len(runs) == 15
        assert (
            len(
                {
                    (
                        r.business_date,
                        r.statement_type,
                        r.service_provider_merchant_no,
                        r.merchant_no,
                    )
                    for r in runs
                }
            )
            == 15
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentTask)
                .where(PaymentTask.task_type == "reconciliation")
            )
            == 15
        )
    assert worker.scan(limit=4) == 0


def test_cross_day_sharing_and_platform_booking_match_by_original_execution(
    billing_setup: BillingSetup,
) -> None:
    from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
    from backend_app.models.payments import ProfitSharingOrder, ProfitSharingRuleVersionItem
    from backend_app.repositories.payments.tasks import claim_tasks
    from backend_app.services.worker.payments.profit_sharing import ProfitSharingService

    now = utc_now()
    paid = now - timedelta(days=3)
    shared = now - timedelta(days=2)
    booked = now - timedelta(days=1)
    payment = scenario(billing_setup, paid_at=paid)
    peer = WechatPayHarness()
    with billing_setup.factory() as db:
        sharing = _required(db.scalar(select(ProfitSharingOrder)))
        receiver = _required(
            db.get(ProfitSharingRuleVersionItem, payment.rule_item_ids[0])
        ).receiver_account
        transaction = _required(db.get(PaymentOrder, payment.order_id)).channel_transaction_no
        number, sharing_id = sharing.order_no, sharing.id
        lease = claim_tasks(db, now=now, task_types={"profit_sharing_submit"})[0]
        db.commit()
    channel_order = "channel_" + sharing_id
    detail = "detail_" + sharing_id
    fact = {
        "sub_mchid": "1900000002",
        "transaction_id": transaction,
        "out_order_no": number,
        "order_id": channel_order,
        "state": "FINISHED",
        "receivers": [
            {
                "type": "MERCHANT_ID",
                "account": receiver,
                "amount": 300,
                "result": "SUCCESS",
                "detail_id": detail,
                "finish_time": shared.isoformat(),
            }
        ],
    }
    ProfitSharingService(
        billing_setup.factory,
        ProfitSharing(peer.client(lambda request: peer.response(fact))),
        clock=lambda: now,
    ).handle(lease)
    sharing_csv = (
        "分账发起方,分账方,微信订单号,微信分账/回退单号,商户分账/回退单号,分账明细单号,"
        "分账接收方,金额,订单金额,处理状态,业务类型,分账时间\n"
        f"1900000001,1900000002,{transaction},{channel_order},{number},{detail},"
        f"{receiver},3.00,100.00,SUCCESS,分账,{shared.isoformat()}\n总条数,总金额\n1,3.00\n"
    ).encode()
    share_run = create_run(billing_setup, business_date(shared), now, kind="profit_sharing")
    run_once(billing_setup, service(billing_setup, peer_statements(peer, sharing_csv), now), now)
    with billing_setup.factory() as db:
        run = _required(db.get(PaymentReconciliationRun, share_run))
        assert run.status == "completed" and run.summary["matched_count"] == 1
        assert run.summary["discrepancy_count"] == 0 and run.summary["local_amount_cents"] == 300
    fund_csv = (
        "资金流水单号,微信支付业务单号,业务凭证号,业务类型,业务名称,收支类型,收支金额(元),记账时间\n"
        f"flow_1,{channel_order},{detail},分账,分账入账,收入,3.00,{booked.isoformat()}\n"
        "资金流水总笔数,总金额\n1,3.00\n"
    ).encode()
    fund_run = create_run(billing_setup, business_date(booked), now, kind="platform_fundflow")
    worker = ReconciliationService(
        billing_setup.factory,
        peer_statements(peer, fund_csv),
        service_provider_merchant_no="1900000001",
        app_id="wx_test_app",
        platform_receiver_account=receiver,
        clock=lambda: now,
    )
    run_once(billing_setup, worker, now)
    with billing_setup.factory() as db:
        run = _required(db.get(PaymentReconciliationRun, fund_run))
        assert run.status == "completed" and run.summary["matched_count"] == 1
        assert run.summary["discrepancy_count"] == 0
        assert (
            run.summary["company_summaries"][billing_setup.housing.company_id][
                "channel_amount_cents"
            ]
            == 300
        )
        assert _required(db.get(PaymentOrder, payment.order_id)).paid_at == paid


def test_lost_reconciliation_lease_preserves_source_without_publishing_partial_decisions(
    billing_setup: BillingSetup,
) -> None:
    from backend_app.repositories.payments.tasks import LeaseLost

    clock = [utc_now()]
    payment = scenario(billing_setup, paid_at=clock[0] - timedelta(days=1))
    content = trade_file(billing_setup, payment)
    peer = WechatPayHarness()
    digest = hashlib.sha1(content, usedforsecurity=False).hexdigest()
    run_id = create_run(billing_setup, business_date(clock[0] - timedelta(days=1)), clock[0])
    takeovers: list[TaskLease] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/billdownload/file":
            clock[0] += timedelta(seconds=31)
            with billing_setup.factory() as db:
                takeovers.extend(claim_tasks(db, now=clock[0], task_types={"reconciliation"}))
                db.commit()
            return httpx.Response(200, content=content)
        return peer.response(
            {
                "hash_type": "SHA1",
                "hash_value": digest,
                "download_url": "https://api.mch.weixin.qq.com/v3/billdownload/file?token=private",
            }
        )

    worker = ReconciliationService(
        billing_setup.factory,
        Statements(peer.client(handler)),
        service_provider_merchant_no="1900000001",
        app_id="wx_test_app",
        clock=lambda: clock[0],
    )
    with pytest.raises(LeaseLost):
        run_once(billing_setup, worker, clock[0])
    with billing_setup.factory() as db:
        source = _required(
            db.scalar(
                select(PaymentChannelRequest).where(
                    PaymentChannelRequest.operation == "statement_download"
                )
            )
        )
        assert source.outcome == "verified_response" and source.finished_at is None
        assert "decisions" not in _required(source.response_snapshot)
        assert db.scalar(select(func.count()).select_from(PaymentReconciliationDiscrepancy)) == 0
        assert _required(db.get(PaymentReconciliationRun, run_id)).statement_hash is None
    assert len(takeovers) == 1
    worker.statements = peer_statements(peer, content)
    worker.handle(takeovers[0])
    with billing_setup.factory() as db:
        assert _required(db.get(PaymentReconciliationRun, run_id)).status == "completed"
        sources = list(
            db.scalars(
                select(PaymentChannelRequest).where(
                    PaymentChannelRequest.operation == "statement_download"
                )
            )
        )
        assert sum(source.finished_at is not None for source in sources) == 1


def test_business_identity_mismatch_never_assigns_wrong_fee_or_exposes_other_identity(
    billing_setup: BillingSetup,
) -> None:
    now = utc_now()
    payment = scenario(billing_setup, paid_at=now - timedelta(days=1))
    run_id = create_run(billing_setup, business_date(now - timedelta(days=1)), now)
    peer = WechatPayHarness()
    run_once(
        billing_setup,
        service(
            billing_setup,
            peer_statements(peer, trade_file(billing_setup, payment, wrong_identity=True)),
            now,
        ),
        now,
    )
    with billing_setup.factory() as db:
        run = _required(db.get(PaymentReconciliationRun, run_id))
        assert run.status == "completed"
        assert run.summary["channel_fee_cents"] == 60
        grouped = run.summary["company_summaries"][billing_setup.housing.company_id]
        assert grouped["channel_fee_cents"] is None
        difference = _required(
            db.scalar(
                select(PaymentReconciliationDiscrepancy).where(
                    PaymentReconciliationDiscrepancy.reference_key.like("business_identity:%")
                )
            )
        )
        assert difference is not None and difference.evidence["actual_status"] is None
        assert "wrong" not in str(difference.evidence)


def test_independent_unfreeze_query_compares_actual_amount_without_changing_funds(
    billing_setup: BillingSetup,
) -> None:
    from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
    from backend_app.models.payments import PaymentUnfreezeOrder
    from backend_app.services.worker.payments.unfreezing import UnfreezingService

    now = utc_now()
    payment = scenario(billing_setup, paid_at=now - timedelta(days=1), rate=0)
    now = utc_now()
    peer = WechatPayHarness()
    with billing_setup.factory() as db:
        order = _required(db.scalar(select(PaymentUnfreezeOrder)))
        payment_order = _required(db.get(PaymentOrder, payment.order_id))
        fact: dict[str, Any] = {
            "sub_mchid": "1900000002",
            "transaction_id": payment_order.channel_transaction_no,
            "out_order_no": order.order_no,
            "order_id": "channel_" + order.id,
            "state": "FINISHED",
            "receivers": [
                {
                    "type": "MERCHANT_ID",
                    "account": "1900000002",
                    "amount": 9940,
                    "result": "SUCCESS",
                    "detail_id": "unfreeze_detail",
                    "finish_time": now.isoformat(),
                }
            ],
        }
        lease = claim_tasks(db, now=now, task_types={"unfreeze_submit"})[0]
        unfreeze_id = order.id
        db.commit()
    unfreezer = UnfreezingService(
        billing_setup.factory,
        ProfitSharing(peer.client(lambda request: peer.response(fact))),
        clock=lambda: now,
    )
    unfreezer.handle(lease)
    now += timedelta(seconds=10)
    with billing_setup.factory() as db:
        lease = claim_tasks(db, now=now, task_types={"unfreeze_query"})[0]
        db.commit()
    unfreezer.handle(lease)
    content = trade_file(billing_setup, payment)
    digest = hashlib.sha1(content, usedforsecurity=False).hexdigest()
    fact["receivers"][0]["amount"] = 9939

    def handler(request: httpx.Request) -> httpx.Response:
        if "/v3/profitsharing/orders/" in request.url.path:
            return peer.response(fact)
        if request.url.path == "/v3/billdownload/file":
            return httpx.Response(200, content=content)
        return peer.response(
            {
                "hash_type": "SHA1",
                "hash_value": digest,
                "download_url": "https://api.mch.weixin.qq.com/v3/billdownload/file?token=private",
            }
        )

    run_id = create_run(billing_setup, business_date(now - timedelta(days=1)), now)
    run_once(billing_setup, service(billing_setup, Statements(peer.client(handler)), now), now)
    with billing_setup.factory() as db:
        run = _required(db.get(PaymentReconciliationRun, run_id))
        assert run.status == "completed"
        difference = _required(
            db.scalar(
                select(PaymentReconciliationDiscrepancy).where(
                    PaymentReconciliationDiscrepancy.reference_key.like("unfreeze_amount:%")
                )
            )
        )
        assert difference.expected_cents == 9940 and difference.actual_cents == 9939
        assert (
            difference.evidence["source"] == "unfreeze_query"
            and difference.evidence["source_digest"] is None
        )
        source = _required(db.get(PaymentChannelRequest, difference.evidence["source_request_id"]))
        assert source.operation == "unfreeze_query" and source.finished_at is not None
        assert _required(db.get(PaymentUnfreezeOrder, unfreeze_id)).unfrozen_cents == 9940
        assert _required(db.get(PaymentOrder, payment.order_id)).status == "succeeded"


def test_platform_account_first_batch_and_downtime_exist_without_merchant_bindings(
    billing_setup: BillingSetup,
) -> None:
    now = utc_now()
    peer = WechatPayHarness()
    unconfigured = ReconciliationService(
        billing_setup.factory,
        peer_statements(peer, b""),
        service_provider_merchant_no="",
        app_id="",
        clock=lambda: now,
    )
    assert unconfigured.scan(limit=2) == 0
    worker = service(billing_setup, peer_statements(peer, b""), now)
    assert worker.scan(limit=2) == 1
    worker = service(billing_setup, peer_statements(peer, b""), now + timedelta(days=5))
    assert worker.scan(limit=2) == 2
    assert worker.scan(limit=2) == 2
    assert worker.scan(limit=2) == 1
    assert worker.scan(limit=2) == 0
    with billing_setup.factory() as db:
        runs = list(db.scalars(select(PaymentReconciliationRun)))
        assert len(runs) == 6 and all(
            run.statement_type == "platform_fundflow" and run.merchant_no is None for run in runs
        )
