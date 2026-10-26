import pytest


@pytest.fixture
def migrated_database_url(fresh_migrated_database_url: str) -> str:
    return fresh_migrated_database_url
