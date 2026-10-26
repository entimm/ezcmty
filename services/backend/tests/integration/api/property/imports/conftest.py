import pytest
from tests.support.workspace import WorkspaceHarness


@pytest.fixture
def workspace(business_workspace: WorkspaceHarness) -> WorkspaceHarness:
    return business_workspace
