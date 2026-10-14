import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from backend_app.schemas.admin import AdminPermission, AdminScope

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


def verify_password(encoded: str, password: str) -> bool:
    try:
        return _hasher.verify(encoded, password)
    except VerificationError, InvalidHashError:
        return False


def permission_catalog(scope: AdminScope) -> list[AdminPermission]:
    # Property enablement requires its organization/data-scope implementation first.
    if scope != "platform_admin":
        return []
    definitions = [
        ("admin.account.read", "查看管理员", "管理员", True),
        ("admin.account.create", "创建管理员", "管理员", False),
        ("admin.account.update", "编辑及启停管理员", "管理员", False),
        ("admin.account.reset_password", "重置管理员密码", "管理员", False),
        ("admin.account.assign_roles", "分配管理员角色", "管理员", False),
        ("admin.role.read", "查看角色与权限目录", "角色", True),
        ("admin.role.create", "创建角色", "角色", False),
        ("admin.role.update", "编辑及启停角色", "角色", False),
        ("admin.role.assign_permissions", "配置角色权限", "角色", False),
        ("admin.audit.read", "查看审计日志", "审计", True),
    ]
    return [AdminPermission(code=c, name=n, group=g, assignable=a) for c, n, g, a in definitions]
