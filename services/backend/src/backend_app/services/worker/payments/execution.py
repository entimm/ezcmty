from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend_app.integrations.wechatpay.client import ChannelResponse, WechatPayError
from backend_app.models.admin import utc_now
from backend_app.repositories.payments.channel_records import save_response, start_request
from backend_app.repositories.payments.tasks import TaskLease, require_current_lease


@dataclass(frozen=True)
class RecordedResponse[T]:
    request_record_id: str
    response: ChannelResponse[T] = field(repr=False)


class RecordedChannelError(WechatPayError):
    def __init__(self, error: WechatPayError, request_record_id: str) -> None:
        self.request_record_id = request_record_id
        super().__init__(
            error.code,
            outcome=error.outcome,
            http_status=error.http_status,
            channel_request_id=error.channel_request_id,
            retry_after_seconds=error.retry_after_seconds,
        )


def perform_channel_call[T](
    factory: sessionmaker[Session],
    *,
    operation: str,
    target_id: str,
    request_snapshot: Mapping[str, Any],
    diagnostic_request_id: str,
    call: Callable[[], ChannelResponse[T]],
    snapshot: Callable[[T], Mapping[str, Any]],
    lease: TaskLease | None = None,
    clock: Callable[[], datetime] = utc_now,
    seal: bool = True,
) -> RecordedResponse[T]:
    """Commit attempt, call with no open Session, then commit evidence independently.

    The owning use case applies business results in a fourth transaction, after its business
    locks and current lease check. Late evidence remains valid even after this worker loses lease.
    """
    with factory() as db:
        if lease is not None:
            require_current_lease(db, lease, now=clock())
        record = start_request(
            db,
            operation=operation,
            target_id=target_id,
            request_snapshot=request_snapshot,
            request_id=diagnostic_request_id,
            now=clock(),
        )
        record_id = record.id
        db.commit()
    try:
        response = call()
    except WechatPayError as error:
        with factory() as db:
            save_response(
                db,
                record_id,
                outcome=error.outcome,
                now=clock(),
                http_status=error.http_status,
                channel_request_id=error.channel_request_id,
                error_code=error.code,
            )
            db.commit()
        raise RecordedChannelError(error, record_id) from None
    with factory() as db:
        save_response(
            db,
            record_id,
            outcome="verified_response",
            now=clock(),
            http_status=response.http_status,
            channel_request_id=response.channel_request_id,
            response_snapshot=snapshot(response.value),
            seal=seal,
        )
        db.commit()
    return RecordedResponse(record_id, response)
