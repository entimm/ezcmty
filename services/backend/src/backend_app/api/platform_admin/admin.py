from collections.abc import Callable

from fastapi import APIRouter
from fastapi.params import Depends as DependsParameter

from backend_app.api.admin_management import create_admin_management_router


def create_platform_management_router(
    permission: Callable[[str], DependsParameter], check_write: Callable[..., None]
) -> APIRouter:
    return create_admin_management_router("platform_admin", permission, check_write)
