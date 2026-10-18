import hashlib
import json
from datetime import date

import httpx
import pytest
from tests.support.wechatpay import WechatPayHarness

from backend_app.integrations.wechatpay.client import WechatPayError
from backend_app.integrations.wechatpay.statements import (
    Statements,
    StatementSource,
    StatementType,
    parse_statement,
)

TRADE = (
    "交易时间,公众账号ID,商户号,特约商户号,微信订单号,商户订单号,用户标识,交易状态,"
    "货币种类,应结订单金额,订单金额,手续费,商品名称\n"
    "`2026-10-19 12:00:00,`wx_test_app,`1900000001,`1900000002,`tx1,`PAY1,`private-openid,"
    "`SUCCESS,`CNY,`99.00,`100.00,`0.06,`private-product-description\n"
    "总交易单数,订单总金额,手续费总金额\n`1,`100.00,`0.06\n"
).encode()


def test_trade_parser_uses_order_amount_and_discards_personal_data() -> None:
    statement = parse_statement("trade", TRADE)
    assert statement.summary == {
        "source_row_count": 1,
        "amount_cents": 10000,
        "channel_fee_cents": 6,
    }
    assert statement.rows[0]["amount_cents"] == 10000
    assert statement.rows[0]["channel_fee_cents"] == 6
    assert "private-openid" not in json.dumps(statement.rows)
    assert "private-product" not in json.dumps(statement.rows)
    assert "private" not in repr(statement)


def test_profit_sharing_parser_keeps_receiver_and_business_kinds_separate() -> None:
    data = (
        "分账时间,分账发起方,分账方,微信订单号,微信分账/回退单号,商户分账/回退单号,"
        "订单金额,分账接收方,金额,业务类型,处理状态,分账描述,分账明细单号,备注\n"
        "`2026-10-19 12:01:00,`1900000001,`1900000002,`tx1,`sharing1,`PS1,`100.00,"
        "`1900000001,`3.00,`分出,`成功,`private-description,`detail1,`private-remark\n"
        "总条数,分账成功出资金\n`1,`3.00\n"
    ).encode()
    result = parse_statement("profit_sharing", data)
    assert result.rows[0]["receiver_account"] == "1900000001"
    assert result.rows[0]["channel_business_type"] == "分出"
    assert result.rows[0]["amount_cents"] == 300
    assert "private" not in json.dumps(result.rows)


def test_platform_fundflow_parser_uses_signed_amount_and_stable_record() -> None:
    data = (
        "记账时间,微信支付业务单号,资金流水单号,业务名称,业务类型,收支类型,收支金额(元),"
        "账户结余(元),资金变更提交申请人,备注,业务凭证号\n"
        "`2026-10-19 12:01:00,`sharing1,`fundflow1,`分账,`分账,`收入,`3.00,`100.00,"
        "`private-name,`private-remark,`detail1\n"
        "`2026-10-19 12:02:00,`fee1,`fundflow2,`交易,`扣除交易手续费,`支出,`0.06,`99.94,"
        "`private-name,`private-remark,`fee-detail1\n"
        "资金流水总笔数,收入笔数,收入金额,支出笔数,支出金额\n`2,`1,`3.00,`1,`0.06\n"
    ).encode()
    result = parse_statement("platform_fundflow", data)
    assert result.rows[0]["channel_record_no"] == "fundflow1"
    assert result.rows[0]["channel_detail_no"] == "detail1"
    assert result.rows[0]["amount_cents"] == 300
    assert result.rows[1]["amount_cents"] == -6
    assert "private" not in json.dumps(result.rows)


@pytest.mark.parametrize("change", ["count", "precision", "truncated", "missing_order_amount"])
def test_incomplete_or_ambiguous_statement_is_not_a_zero_transaction_result(change: str) -> None:
    data = TRADE
    if change == "count":
        data = data.replace(b"`1,`100.00,`0.06", b"`2,`100.00,`0.06")
    elif change == "precision":
        data = data.replace(b"`0.06", b"`0.061")
    elif change == "truncated":
        data = data[: data.index("总交易单数".encode())]
    else:
        data = data.replace("订单金额,".encode(), "旧版字段,".encode())
    with pytest.raises(WechatPayError):
        parse_statement("trade", data)


@pytest.mark.parametrize("statement_type", ["trade", "profit_sharing", "platform_fundflow"])
def test_statement_application_uses_exact_scope_and_verified_digest(
    peer: WechatPayHarness,
    statement_type: StatementType,
) -> None:
    digest = hashlib.sha1(TRADE, usedforsecurity=False).hexdigest()

    def handle(request: httpx.Request) -> httpx.Response:
        expected_path = {
            "trade": "/v3/bill/tradebill",
            "profit_sharing": "/v3/profitsharing/bills",
            "platform_fundflow": "/v3/bill/fundflowbill",
        }[statement_type]
        assert request.url.path == expected_path
        assert request.url.params["bill_date"] == "2026-10-19"
        if statement_type == "platform_fundflow":
            assert request.url.params["account_type"] == "BASIC"
            assert "sub_mchid" not in request.url.params
        else:
            assert request.url.params["sub_mchid"] == "1900000002"
        return peer.response(
            {
                "hash_type": "SHA1",
                "hash_value": digest,
                "download_url": "https://api.mch.weixin.qq.com/v3/billdownload/file?token=private",
            }
        )

    adapter = Statements(peer.client(handle))
    if statement_type == "trade":
        source = adapter.request_trade(merchant_no="1900000002", business_date=date(2026, 10, 19))
    elif statement_type == "profit_sharing":
        source = adapter.request_profit_sharing(
            merchant_no="1900000002", business_date=date(2026, 10, 19)
        )
    else:
        source = adapter.request_platform_fundflow(business_date=date(2026, 10, 19))
    assert source.value.source_digest == digest
    assert "private" not in repr(source.value)
    assert "download_url" not in source.value.snapshot()


def test_unsigned_statement_download_uses_previously_authenticated_digest(
    peer: WechatPayHarness,
) -> None:
    digest = hashlib.sha1(TRADE, usedforsecurity=False).hexdigest()

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/billdownload/file"
        assert "Authorization" in request.headers
        return httpx.Response(200, content=TRADE)

    result = Statements(peer.client(handle)).download(
        StatementSource(
            "SHA1", digest, "https://api.mch.weixin.qq.com/v3/billdownload/file?token=private"
        ),
        statement_type="trade",
    )
    assert result.value.summary["source_row_count"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.test/v3/billdownload/file?token=private",
        "http://api.mch.weixin.qq.com/v3/billdownload/file",
        "https://api.mch.weixin.qq.com@attacker.test/v3/billdownload/file",
        "https://api.mch.weixin.qq.com/unrelated",
    ],
)
def test_download_does_not_leak_authorization_to_untrusted_target(
    peer: WechatPayHarness, url: str
) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Untrusted download must not make a network request")

    with pytest.raises(WechatPayError, match="INVALID_DOWNLOAD_SOURCE"):
        peer.client(unexpected).download(url, "0" * 40)


def test_download_checksum_mismatch_is_not_trusted_evidence(peer: WechatPayHarness) -> None:
    with pytest.raises(WechatPayError, match="STATEMENT_DIGEST_MISMATCH"):
        peer.client(lambda _: httpx.Response(200, content=TRADE)).download(
            "https://api.mch.weixin.qq.com/v3/billdownload/file?token=private", "0" * 40
        )
