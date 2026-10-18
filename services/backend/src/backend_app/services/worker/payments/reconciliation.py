from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.identifiers import new_id
from backend_app.domain.payments.funds import retry_seconds
from backend_app.domain.payments.reconciliation import (
    ReconciliationResult,
    business_date,
    compare_fundflow,
    compare_sharing,
    compare_trade,
)
from backend_app.integrations.wechatpay.client import ChannelResponse
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing, SharingFact
from backend_app.integrations.wechatpay.statements import (
    ParsedStatement,
    Statements,
    StatementSource,
    StatementType,
)
from backend_app.models.admin import utc_now
from backend_app.models.payments import (
    PaymentOrder,
    PaymentReconciliationRun,
    PropertyMerchantBinding,
)
from backend_app.repositories.payments.channel_records import finish_statement
from backend_app.repositories.payments.reconciliation import (
    ReconciliationRepository,
    day_bounds,
    ensure_run,
    lock_run,
)
from backend_app.repositories.payments.tasks import (
    TaskLease,
    complete_task,
    require_current_lease,
    reschedule_task,
)
from backend_app.services.worker.payments.execution import (
    RecordedChannelError,
    perform_channel_call,
)
from backend_app.services.worker.payments.funds_support import NOT_FOUND


class ReconciliationService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        statements: Statements,
        *,
        service_provider_merchant_no: str,
        app_id: str,
        platform_receiver_account: str | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.factory = factory
        self.statements = statements
        self.provider = service_provider_merchant_no
        self.app_id = app_id
        self.platform_receiver_account = platform_receiver_account or service_provider_merchant_no
        self.clock = clock

    def scan(self, *, limit: int = 100) -> int:
        """Find missing persistent scopes, rather than remembering a process-local last date."""
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid reconciliation production bound")
        now = self.clock()
        available = business_date(now) - timedelta(days=1)
        created = 0
        with self.factory() as db:
            bindings = db.execute(
                select(
                    PropertyMerchantBinding.service_provider_merchant_no,
                    PropertyMerchantBinding.merchant_no,
                    func.min(PropertyMerchantBinding.created_at),
                ).group_by(
                    PropertyMerchantBinding.service_provider_merchant_no,
                    PropertyMerchantBinding.merchant_no,
                )
            ).all()
            scopes: dict[tuple[str, str | None], datetime] = {}
            first_platform_day = db.scalar(
                select(func.min(PaymentReconciliationRun.business_date)).where(
                    PaymentReconciliationRun.service_provider_merchant_no == self.provider,
                    PaymentReconciliationRun.statement_type == "platform_fundflow",
                )
            )
            for binding_provider, binding_merchant, first_binding in bindings:
                earliest_payment = db.scalar(
                    select(
                        func.min(
                            func.least(
                                PaymentOrder.created_at,
                                func.coalesce(PaymentOrder.paid_at, PaymentOrder.created_at),
                            )
                        )
                    )
                    .join(
                        PropertyMerchantBinding,
                        PaymentOrder.merchant_binding_id == PropertyMerchantBinding.id,
                    )
                    .where(
                        PropertyMerchantBinding.service_provider_merchant_no == binding_provider,
                        PropertyMerchantBinding.merchant_no == binding_merchant,
                    )
                )
                first = min(first_binding, earliest_payment) if earliest_payment else first_binding
                scopes[(binding_provider, binding_merchant)] = first
                key = binding_provider, None
                scopes[key] = min(scopes.get(key, first), first)
            platform_key = self.provider, None
            if self.provider and platform_key not in scopes:
                scopes[platform_key] = day_bounds(first_platform_day or available)[0]
            elif self.provider and first_platform_day is not None:
                scopes[platform_key] = min(scopes[platform_key], day_bounds(first_platform_day)[0])
            for (provider, merchant), first in sorted(
                scopes.items(), key=lambda pair: (pair[0][0], pair[0][1] or "")
            ):
                for kind in (
                    ["platform_fundflow"] if merchant is None else ["trade", "profit_sharing"]
                ):
                    missing = db.scalars(
                        text("""
                        SELECT candidate::date FROM generate_series(CAST(:first AS date),
                            CAST(:last AS date), INTERVAL '1 day') candidate
                        WHERE NOT EXISTS (SELECT 1 FROM payment_reconciliation_runs run
                            WHERE run.business_date = candidate::date AND run.statement_type = :kind
                            AND run.service_provider_merchant_no = :provider
                            AND run.merchant_no IS NOT DISTINCT FROM CAST(:merchant AS varchar))
                        ORDER BY candidate LIMIT :remaining
                    """),
                        {
                            "first": business_date(first),
                            "last": available,
                            "kind": kind,
                            "provider": provider,
                            "merchant": merchant,
                            "remaining": limit - created,
                        },
                    ).all()
                    for day in missing:
                        _, inserted = ensure_run(
                            db,
                            day=day,
                            statement_type=kind,
                            provider=provider,
                            merchant=merchant,
                            now=now,
                        )
                        created += inserted
                    if created >= limit:
                        db.commit()
                        return created
            db.commit()
        return created

    def handle(self, lease: TaskLease) -> None:
        with self.factory() as db:
            run = lock_run(db, lease.target_id)
            require_current_lease(db, lease, now=self.clock())
            run.status, run.finished_at, run.updated_at = "running", None, self.clock()
            kind = cast(StatementType, run.statement_type)
            day, merchant, provider = (
                run.business_date,
                run.merchant_no,
                run.service_provider_merchant_no,
            )
            db.commit()
        if provider != self.provider:
            self._failed(lease, "HISTORICAL_PROVIDER_CONFIGURATION_REQUIRED")
            return
        try:
            if kind == "trade":
                assert merchant is not None

                def get_source() -> ChannelResponse[StatementSource]:
                    return self.statements.request_trade(merchant_no=merchant, business_date=day)
            elif kind == "profit_sharing":
                assert merchant is not None

                def get_source() -> ChannelResponse[StatementSource]:
                    return self.statements.request_profit_sharing(
                        merchant_no=merchant, business_date=day
                    )
            else:

                def get_source() -> ChannelResponse[StatementSource]:
                    return self.statements.request_platform_fundflow(business_date=day)

            source = perform_channel_call(
                self.factory,
                operation={
                    "trade": "trade_statement",
                    "profit_sharing": "profit_sharing_statement",
                    "platform_fundflow": "platform_fundflow_statement",
                }[kind],
                target_id=lease.target_id,
                request_snapshot={
                    "business_date": day.isoformat(),
                    "merchant_no": merchant,
                    "service_provider_merchant_no": provider,
                    "statement_type": kind,
                },
                diagnostic_request_id=new_id(),
                lease=lease,
                clock=self.clock,
                call=get_source,
                snapshot=lambda value: value.snapshot(),
            )
            downloaded = perform_channel_call(
                self.factory,
                operation="statement_download",
                target_id=lease.target_id,
                request_snapshot={
                    "hash_type": source.response.value.hash_type,
                    "source_digest": source.response.value.source_digest,
                },
                diagnostic_request_id=new_id(),
                lease=lease,
                clock=self.clock,
                call=lambda: self.statements.download(source.response.value, statement_type=kind),
                snapshot=lambda value: {
                    "hash_type": source.response.value.hash_type,
                    "source_digest": source.response.value.source_digest,
                    "source_row_count": len(value.rows),
                    "summary": value.summary,
                },
                seal=False,
            )
            observations = self._observe_unfreezes(lease) if kind == "trade" else []
        except RecordedChannelError as error:
            self._failed(lease, error.code, error.retry_after_seconds)
            return
        try:
            self._publish(
                lease,
                downloaded.request_record_id,
                source.response.value.hash_type,
                source.response.value.source_digest,
                downloaded.response.value,
                observations,
            )
        except ValueError:
            self._failed(lease, "RECONCILIATION_INVALID_SCOPE")

    def _publish(
        self,
        lease: TaskLease,
        source_id: str,
        hash_type: str,
        digest: str,
        parsed: ParsedStatement,
        observations: list[dict[str, Any]],
    ) -> None:
        with self.factory() as db:
            run = db.get(PaymentReconciliationRun, lease.target_id)
            assert run is not None
            repository = ReconciliationRepository(db)
            payments = (
                repository.payment_facts(run, parsed.rows) if run.statement_type == "trade" else []
            )
            run = lock_run(db, lease.target_id)
            require_current_lease(db, lease, now=self.clock())
            if parsed.statement_type != run.statement_type:
                raise ValueError("Statement scope mismatch")
            now = self.clock()
            args: dict[str, Any] = {
                "now": now,
                "source_digest": hash_type + ":" + digest,
                "source_request_id": source_id,
            }
            if run.statement_type == "trade":
                payments = repository.payment_facts(run, parsed.rows)
                assert run.merchant_no is not None
                result = compare_trade(
                    parsed.rows,
                    payments,
                    day=run.business_date,
                    provider=run.service_provider_merchant_no,
                    merchant=run.merchant_no,
                    app_id=self.app_id,
                    **args,
                )
                repository.internal_checks(run, result, payments, now=now)
                self._compare_unfreezes(result, observations, now=now)
            elif run.statement_type == "profit_sharing":
                assert run.merchant_no is not None
                result = compare_sharing(
                    parsed.rows,
                    repository.sharing_facts(run, parsed.rows),
                    day=run.business_date,
                    provider=run.service_provider_merchant_no,
                    merchant=run.merchant_no,
                    **args,
                )
            else:
                if any(business_date(row["booked_at"]) != run.business_date for row in parsed.rows):
                    raise ValueError("Fundflow statement date mismatch")
                result = compare_fundflow(
                    parsed.rows,
                    repository.sharing_facts(run, parsed.rows),
                    receiver_account=self.platform_receiver_account,
                    **args,
                )
            self._commit_result(db, lease, run, source_id, hash_type, digest, result, now=now)
            db.commit()

    def _commit_result(
        self,
        db: Session,
        lease: TaskLease,
        run: PaymentReconciliationRun,
        source_id: str,
        hash_type: str,
        digest: str,
        result: ReconciliationResult,
        *,
        now: datetime,
    ) -> None:
        decisions = ReconciliationRepository(db).apply_result(run, result, now=now)
        finish_statement(
            db,
            source_id,
            lease,
            now=now,
            decision_snapshot={
                "detected_at": now.isoformat(),
                "decisions": decisions,
                "company_summaries": result.company_summaries,
            },
        )
        run.statement_hash_type, run.statement_hash = hash_type, digest
        run.status, run.finished_at, run.updated_at = "completed", now, now
        complete_task(db, lease, now=now)

    def _observe_unfreezes(self, lease: TaskLease) -> list[dict[str, Any]]:
        with self.factory() as db:
            run = db.get(PaymentReconciliationRun, lease.target_id)
            assert run is not None
            targets = ReconciliationRepository(db).unfreeze_facts(run)
        channel = ProfitSharing(self.statements.client)
        observations: list[dict[str, Any]] = []
        for target in targets:

            def query_unfreeze(target: dict[str, Any] = target) -> ChannelResponse[SharingFact]:
                return channel.query_order(
                    merchant_no=target["merchant"],
                    channel_transaction_no=target["channel_transaction_no"],
                    order_no=target["order_no"],
                )

            def query_remaining(target: dict[str, Any] = target) -> ChannelResponse[dict[str, Any]]:
                return channel.remaining_amount(
                    channel_transaction_no=target["channel_transaction_no"]
                )

            try:
                recorded = perform_channel_call(
                    self.factory,
                    operation="unfreeze_query",
                    target_id=target["execution_id"],
                    request_snapshot={
                        "merchant_no": target["merchant"],
                        "order_no": target["order_no"],
                        "channel_transaction_no": target["channel_transaction_no"],
                    },
                    diagnostic_request_id=new_id(),
                    lease=lease,
                    clock=self.clock,
                    call=query_unfreeze,
                    snapshot=lambda fact: fact.snapshot(),
                )
            except RecordedChannelError as error:
                if error.outcome != "verified_response" or error.code not in NOT_FOUND:
                    raise
                remaining = perform_channel_call(
                    self.factory,
                    operation="remaining_amount",
                    target_id=target["payment_id"],
                    request_snapshot={"channel_transaction_no": target["channel_transaction_no"]},
                    diagnostic_request_id=new_id(),
                    lease=lease,
                    clock=self.clock,
                    call=query_remaining,
                    snapshot=lambda value: value,
                )
                if (
                    remaining.response.value["channel_transaction_no"]
                    != target["channel_transaction_no"]
                ):
                    raise ValueError("Unfreeze remaining amount identity mismatch") from None
                observations.append(
                    {
                        "local": target,
                        "source_id": remaining.request_record_id,
                        "remaining_cents": remaining.response.value["remaining_cents"],
                    }
                )
            else:
                observations.append(
                    {
                        "local": target,
                        "source_id": recorded.request_record_id,
                        "fact": recorded.response.value,
                    }
                )
        return observations

    def _compare_unfreezes(
        self, result: ReconciliationResult, observations: list[dict[str, Any]], *, now: datetime
    ) -> None:
        for observation in observations:
            local = observation["local"]
            args: dict[str, Any] = {
                "source": "unfreeze_query",
                "now": now,
                "source_request_id": observation["source_id"],
                "local": local,
            }
            identity = (local["order_no"],)
            if "remaining_cents" in observation:
                actual = "no_remaining" if observation["remaining_cents"] == 0 else "not_found"
                if local["status"] == "failed":
                    actual = "failed"
                result.check(
                    "unfreeze_status",
                    identity,
                    expected_status=local["status"],
                    actual_status=actual,
                    difference=None if local["status"] == actual else "status_mismatch",
                    **args,
                )
                continue
            fact = observation["fact"]
            valid = (
                fact.merchant_no == local["merchant"]
                and fact.order_no == local["order_no"]
                and fact.channel_transaction_no == local["channel_transaction_no"]
                and local["channel_order_no"] in {None, fact.channel_order_no}
                and len(fact.receivers) == 1
                and fact.receivers[0].receiver_type == "merchant"
                and fact.receivers[0].receiver_account == local["merchant"]
            )
            result.check(
                "business_identity",
                identity,
                difference=None if valid else "status_mismatch",
                **args,
            )
            if not valid:
                continue
            receiver = fact.receivers[0]
            actual_status = (
                ("succeeded" if receiver.channel_status == "SUCCESS" else "failed")
                if fact.channel_status == "FINISHED"
                else "processing"
            )
            result.check(
                "unfreeze_status",
                identity,
                expected_status=local["status"],
                actual_status=actual_status,
                difference=None if local["status"] == actual_status else "status_mismatch",
                **args,
            )
            result.check(
                "unfreeze_amount",
                identity,
                expected=local["amount_cents"],
                actual=receiver.amount_cents if receiver.channel_status == "SUCCESS" else None,
                difference="amount_mismatch"
                if local["status"] == "succeeded"
                and receiver.channel_status == "SUCCESS"
                and local["amount_cents"] != receiver.amount_cents
                else None,
                **args,
            )

    def _failed(self, lease: TaskLease, code: str, retry_after: int | None = None) -> None:
        with self.factory() as db:
            run = lock_run(db, lease.target_id)
            require_current_lease(db, lease, now=self.clock())
            now = self.clock()
            run.status, run.finished_at, run.updated_at = "failed", now, now
            reschedule_task(
                db,
                lease,
                now=now,
                next_run_at=now
                + timedelta(seconds=retry_seconds(lease.attempt_count, retry_after)),
                error_code=code,
            )
            db.commit()
