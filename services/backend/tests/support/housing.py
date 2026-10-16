from typing import Any

from sqlalchemy import select

from backend_app.models.admin import AdminRole
from backend_app.repositories.admin import AdminRepository
from tests.support.workspace import PREFIX, WorkspaceHarness


def housing_path(workspace: WorkspaceHarness, suffix: str = "") -> str:
    return f"{PREFIX}/communities/{workspace.community_id}{suffix}"


def create_node(
    workspace: WorkspaceHarness,
    name: str = "1号楼",
    node_type: str = "building",
    parent_id: str | None = None,
) -> dict[str, Any]:
    result = workspace.client.post(
        housing_path(workspace, "/space-nodes"),
        json={"name": name, "node_type": node_type, "parent_id": parent_id},
        headers=workspace.headers(),
    )
    assert result.status_code == 201, result.text
    return dict(result.json())


def create_house(
    workspace: WorkspaceHarness, node_id: str, room_no: str = "101", **extra: Any
) -> dict[str, Any]:
    result = workspace.client.post(
        housing_path(workspace, "/houses"),
        json={"space_node_id": node_id, "room_no": room_no, **extra},
        headers=workspace.headers(),
    )
    assert result.status_code == 201, result.text
    return dict(result.json())


def set_permissions(workspace: WorkspaceHarness, permissions: set[str]) -> None:
    with workspace.platform.factory() as db:
        role = db.scalar(
            select(AdminRole).where(
                AdminRole.scope == "property_admin",
                AdminRole.property_company_id == workspace.company_id,
                AdminRole.code == "housing_editor",
            )
        )
        if role is None:
            role = AdminRole(
                scope="property_admin",
                property_company_id=workspace.company_id,
                code="housing_editor",
                name="资料维护",
                enabled=True,
                is_system=False,
            )
            db.add(role)
            db.flush()
        repo = AdminRepository(db, "property_admin", workspace.company_id)
        repo.replace_permissions(role.id, permissions)
        repo.replace_roles(workspace.account_id, {role.id})
        db.commit()
