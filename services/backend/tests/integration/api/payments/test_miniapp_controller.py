import json
import socket
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Any, cast

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import func, select
from tests.support.paths import REPOSITORY_ROOT
from tests.support.payment_api import PaymentHouse, configure_payment_api

from backend_app.integrations.wechatpay.payments import Payments
from backend_app.integrations.wechatpay.profit_sharing import ProfitSharing
from backend_app.models.admin import utc_now
from backend_app.models.billing import Bill, BillSettlementEntry
from backend_app.models.payments import BillPaymentReservation, PaymentOrder
from backend_app.repositories.payments.tasks import claim_tasks, ensure_task
from backend_app.services.worker.payments.orders import OrderService


@contextmanager
def resident_listener(house: PaymentHouse) -> Iterator[str]:
    app = FastAPI()
    app.mount("/api/resident", cast(FastAPI, house.resident.client.app))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, log_config=None, access_log=False, lifespan="off")
        )
        thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 10
            interval = Event()
            while not server.started:
                assert thread.is_alive(), "Resident HTTP server stopped before readiness"
                assert monotonic() < deadline, "Resident HTTP server startup timed out"
                interval.wait(0.01)
            yield f"http://127.0.0.1:{port}/api/resident"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Resident HTTP server did not stop"


def compile_miniapp(directory: Path, base: str) -> Path:
    miniapp = REPOSITORY_ROOT / "apps/miniapp"
    compiled = directory / "dist"
    subprocess.run(
        ["pnpm", "exec", "tsc", "--outDir", str(compiled)],
        cwd=miniapp,
        check=True,
        capture_output=True,
        timeout=45,
    )
    # Only this fixture's compiled output targets its isolated HTTP listener.
    # The source app and ordinary production build configuration stay untouched.
    config = compiled / "config.js"
    config.write_text(config.read_text() + f"\nexports.API_BASE_URL = {json.dumps(base)};\n")
    return compiled


def run_controller(
    house: PaymentHouse,
    *,
    compiled: Path,
    base: str,
    state: Path,
    phase: str,
    order_id: str | None = None,
) -> dict[str, Any]:
    process = subprocess.run(
        [
            "node",
            str(Path(__file__).parents[3] / "support/miniapp_payment.cjs"),
            str(compiled),
            str(state),
            phase,
        ],
        input=json.dumps(
            {
                "base": base,
                "token": house.resident.token,
                "userId": house.resident.user_id,
                "billId": house.bill_id,
                "bindingId": house.binding_id,
                "orderId": order_id,
            }
        ),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    return cast(dict[str, Any], json.loads(process.stdout))


@pytest.mark.slow
def test_compiled_miniapp_recovers_original_payment_over_http_and_isolated_postgresql(
    payment_house: PaymentHouse, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    house = payment_house
    peer, settings = configure_payment_api(house, monkeypatch)
    monkeypatch.setattr("backend_app.api.resident.billing.get_settings", lambda: settings)
    peer.now = utc_now().timestamp()
    factory = house.workspace.platform.factory
    calls: list[tuple[str, str]] = []

    def channel(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/merchant-configs/1900000002"):
            return peer.response({"sub_mchid": "1900000002", "max_ratio": 3000})
        if request.url.path == "/v3/pay/partner/transactions/jsapi":
            return peer.response({"prepay_id": "private-prepay-integration"})
        if request.url.path.endswith("/close"):
            return peer.response(None, 204)
        assert request.method == "GET"
        with factory() as db:
            order = db.scalars(select(PaymentOrder)).one()
            assert request.url.path.endswith("/" + order.order_no)
            return peer.response(
                {
                    "sp_mchid": "1900000001",
                    "sub_mchid": "1900000002",
                    "sp_appid": peer.config.app_id,
                    "out_trade_no": order.order_no,
                    "trade_state": "NOTPAY",
                }
            )

    client = peer.client(channel)
    worker = OrderService(factory, settings, Payments(client), ProfitSharing(client))

    def execute(task_type: str, order_id: str) -> None:
        with factory() as db:
            ensure_task(db, task_type, order_id, now=utc_now(), reactivate=True)
            leases = claim_tasks(db, now=utc_now(), task_types={task_type})
            assert len(leases) == 1
            db.commit()
        worker.handle(leases[0])

    with resident_listener(house) as base:
        compiled = compile_miniapp(tmp_path, base)
        state = tmp_path / "miniapp-storage.json"
        created = run_controller(house, compiled=compiled, base=base, state=state, phase="create")
        order_id = created["orderId"]
        assert created["creates"] == 1
        assert created["recoveredByKey"] is True
        with factory() as db:
            order = db.scalars(select(PaymentOrder)).one()
            assert order.id == order_id and order.idempotency_key == created["key"]
            assert order.status == "pending" and order.amount_cents == 7000
            assert db.get(BillPaymentReservation, house.bill_id) is not None
        execute("payment_submit", order_id)
        cancelled = run_controller(
            house,
            compiled=compiled,
            base=base,
            state=state,
            phase="cancel_close",
            order_id=order_id,
        )
        assert cancelled == {
            "orderId": order_id,
            "panels": ["cancelled", "unknown"],
            "status": "closing",
        }
        with factory() as db:
            assert db.get(BillPaymentReservation, house.bill_id) is not None
        execute("payment_close", order_id)
        released = run_controller(
            house,
            compiled=compiled,
            base=base,
            state=state,
            phase="release",
            order_id=order_id,
        )
        assert released == {"orderId": order_id, "status": "closed", "billHidden": True}
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        assert db.get(BillPaymentReservation, house.bill_id) is None
        bill = db.get(Bill, house.bill_id)
        assert bill is not None and bill.outstanding_cents == 7000
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillSettlementEntry)
                .where(BillSettlementEntry.source_type == "online_payment")
            )
            == 0
        )
    assert len(calls) == 4  # Fresh ratio, original submit, original query, reliable close.
