from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend_app.core.config import get_settings
from backend_app.db.base import Base
from backend_app.models import (  # noqa: F401
    admin,
    billing,
    house_claims,
    housing,
    imports,
    miniapp,
    payments,
    property,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option(
    "sqlalchemy.url", get_settings().database_url.get_secret_value().replace("%", "%%")
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c timezone=UTC"},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
