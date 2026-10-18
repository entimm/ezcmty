import pytest
from tests.support.wechatpay import WechatPayHarness


@pytest.fixture
def peer() -> WechatPayHarness:
    return WechatPayHarness()
