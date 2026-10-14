import argparse
from getpass import getpass

from backend_app.core.errors import AppError
from backend_app.db.session import get_session_factory
from backend_app.schemas.admin import AccountCreate
from backend_app.services.admin import AdminService


def main() -> None:
    parser = argparse.ArgumentParser(description="后台受控初始化")
    parser.add_argument("command", choices=["init-platform-admin"])
    parser.add_argument("--login-name", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    password = getpass("初始密码（12–128 字符）: ")
    if password != getpass("确认初始密码: "):
        parser.error("两次密码不一致")
    try:
        AccountCreate(login_name=args.login_name, display_name=args.display_name, password=password)
    except ValueError:
        parser.error("登录名、显示名称或密码不符合规则")
    with get_session_factory()() as db:
        try:
            AdminService(db, "platform_admin").initialize_super_admin(
                args.login_name, args.display_name, password
            )
        except AppError as exc:
            db.rollback()
            parser.error(exc.public_detail or str(exc))
    print("平台超级管理员已创建，首次登录必须修改密码。")


if __name__ == "__main__":
    main()
