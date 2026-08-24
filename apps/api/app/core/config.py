"""从环境变量加载并校验应用配置。"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """保存 API 启动必需且经过边界校验的配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AIPICKSTOCK_",
        extra="ignore",
    )

    database_url: SecretStr = Field(min_length=1)
    environment: Literal["development", "test", "production"] = "development"
    session_lifetime_days: int = Field(default=30, ge=1, le=90)

    @field_validator("database_url")
    @classmethod
    def require_psycopg_database_url(cls, value: SecretStr) -> SecretStr:
        """拒绝非 PostgreSQL/psycopg 3 地址，避免环境间驱动行为漂移。"""
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            message = "database_url 必须使用 postgresql+psycopg://"
            raise ValueError(message)
        return value
