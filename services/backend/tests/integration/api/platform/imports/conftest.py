import pytest
from tests.support.admin import Harness


@pytest.fixture
def harness(business_harness: Harness) -> Harness:
    return business_harness
