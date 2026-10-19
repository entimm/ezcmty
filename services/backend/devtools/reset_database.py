import argparse
import sys

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from backend_app.core.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清空开发数据库的 public，供重新执行迁移")
    parser.parse_args(argv)
    settings = get_settings()
    if "env" not in settings.model_fields_set or settings.env not in {"local", "test"}:
        print("db-reset 只允许显式配置 APP_ENV=local/test", file=sys.stderr)
        return 1

    engine = create_engine(
        settings.database_url.get_secret_value(),
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c timezone=UTC"},
    )
    try:
        with engine.connect() as connection:
            database, host, port = connection.exec_driver_sql(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()"
            ).one()
            connection.rollback()
            if database in {"postgres", "template0", "template1"}:
                print("禁止清空 PostgreSQL 维护数据库", file=sys.stderr)
                return 1
            print(f"目标数据库：{database}（{host or '本地 socket'}:{port or 5432}）")
            confirmation = input("将删除 public 中的全部数据、结构及依赖对象。请输入数据库名确认：")
            if confirmation != database:
                print("数据库名不匹配，已取消清空", file=sys.stderr)
                return 1
            with connection.begin():
                connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
                connection.exec_driver_sql("CREATE SCHEMA public AUTHORIZATION pg_database_owner")
                connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO PUBLIC")
    except EOFError:
        print("未收到确认，已取消清空", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断清空", file=sys.stderr)
        return 130
    except SQLAlchemyError as exc:
        print(f"清空失败（{type(exc).__name__}），请检查连接、权限及数据库状态", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print("数据库 public 已清空，请执行 make migrate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
