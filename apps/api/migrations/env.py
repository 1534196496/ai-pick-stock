"""Alembic 迁移运行环境。"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import Settings
from app.modules.auth import models as auth_models
from app.modules.instruments import models as instrument_models
from app.modules.market_data import models as market_models
from app.modules.portfolios import models as portfolio_models
from app.modules.watchlists import models as watchlist_models

config = context.config
settings = Settings()
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.get_secret_value().replace("%", "%%"),
)
target_metadata = auth_models.User.metadata
assert portfolio_models.Position.metadata is target_metadata
assert portfolio_models.PositionTransaction.metadata is target_metadata
assert portfolio_models.PositionDailySnapshot.metadata is target_metadata
assert instrument_models.Instrument.metadata is target_metadata
assert market_models.LatestQuote.metadata is target_metadata
assert market_models.IntradayQuote.metadata is target_metadata
assert market_models.FundDailyNav.metadata is target_metadata
assert market_models.StockDailyBar.metadata is target_metadata
assert market_models.MarketDataSchedule.metadata is target_metadata
assert watchlist_models.WatchlistGroup.metadata is target_metadata
assert watchlist_models.WatchlistItem.metadata is target_metadata


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
