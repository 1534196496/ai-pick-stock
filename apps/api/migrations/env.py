"""Alembic 迁移运行环境。"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import Settings
from app.modules.auth import models as auth_models

config = context.config
settings = Settings()
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.get_secret_value().replace("%", "%%"),
)
target_metadata = auth_models.User.metadata


def run_migrations_offline() -> None:
    """在不创建数据库连接时生成 SQL 迁移内容。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """连接目标 PostgreSQL 并在事务内执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
