from backend_app.domain.admin.permissions import normalize_permissions, permission_catalog
from devtools.seed.runtime import Actor, Executor


def populate(executor: Executor, actor: Actor, parameters: dict[str, int]) -> None:
    roles: list[str] = []
    prefix = "seed_" + executor.state.run_id
    permissions = [item.code for item in permission_catalog("platform_admin") if item.assignable]
    for index in range(parameters["roles"]):
        key = f"admin/role/{index}"
        code = f"{prefix}_r{index}"
        assigned = normalize_permissions(
            "platform_admin",
            permissions[index % len(permissions) :: parameters["roles"]] or permissions[:1],
        )
        values = {"code": code, "name": f"填充角色 {index + 1}", "permissions": assigned}
        role = executor.step(
            key,
            actor,
            "role.create",
            "role",
            values,
            unique={"property_company_id": None, "code": code},
            expected={
                "code": code,
                "name": values["name"],
                "enabled": True,
                "is_system": False,
                "$permissions": assigned,
            },
        )
        roles.append(role)
    for index in range(parameters["accounts"]):
        key = f"admin/account/{index}"
        login = f"{prefix}_a{index}"
        account = executor.create_account(
            key,
            actor,
            login,
            f"平台演示账号 {index + 1}",
            "admin",
            roles=[roles[index % len(roles)]],
        )
        if index % 3 != 1:
            executor.change_password(key + "/password", account, "platform_admin", login)
        if index % 3 == 2:
            executor.step(
                key + "/disable",
                actor,
                "account.update",
                "account",
                {"enabled": False},
                identifier=account,
                expected={"enabled": False},
            )
    if len(roles) > 1:
        executor.step(
            "admin/role/disable",
            actor,
            "role.update",
            "role",
            {"enabled": False},
            identifier=roles[-1],
            expected={"enabled": False},
        )
