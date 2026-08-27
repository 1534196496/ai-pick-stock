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
    public_web_url: str = "http://127.0.0.1:18080"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    market_data_live_enabled: bool = False
    stock_refresh_seconds: int = Field(default=60, ge=30, le=3600)
    fund_estimate_enabled: bool = False
    ai_provider: Literal["openai", "anthropic"] | None = None
    ai_base_url: str | None = None
    ai_api_key: SecretStr | None = None
    ai_model: str | None = None
    ai_timeout_seconds: int = Field(default=60, ge=10, le=180)
    ai_agent_enabled: bool = True
    ai_agent_codex_bin: str | None = None
    ai_agent_skill_root: str = "/app/agent_skills"
    ai_agent_prompt_spec_path: str = "/app/docs/ai-investment-analysis-prompt-spec.md"
    ai_agent_workspace: str = "/tmp/ai-pick-stock-agent"
    ai_agent_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    ai_agent_turn_timeout_seconds: int = Field(default=300, ge=30, le=900)
    ai_agent_max_concurrency: int = Field(default=3, ge=1, le=10)

    @property
    def smtp_configured(self) -> bool:
        """判断生产密码重置投递所需配置是否完整。"""
        return self.smtp_host is not None and self.smtp_from_email is not None

    @property
    def ai_configured(self) -> bool:
        """判断全站 AI 分析所需提供商、Key 与模型是否齐全。"""
        key = self.ai_api_key.get_secret_value() if self.ai_api_key is not None else ""
        return bool(self.ai_provider and key.strip() and (self.ai_model or "").strip())

    @property
    def resolved_ai_base_url(self) -> str | None:
        """返回显式兼容地址或对应官方协议的默认地址。"""
        if self.ai_provider is None:
            return None
        if self.ai_base_url and self.ai_base_url.strip():
            return self.ai_base_url.strip().rstrip("/")
        if self.ai_provider == "openai":
            return "https://api.openai.com/v1"
        return "https://api.anthropic.com"

    @property
    def codex_agent_configured(self) -> bool:
        """判断 OpenAI Responses 协议是否足以启动 Codex Agent。"""
        return self.ai_agent_enabled and self.ai_provider == "openai" and self.ai_configured

    @field_validator("database_url")
    @classmethod
    def require_psycopg_database_url(cls, value: SecretStr) -> SecretStr:
        """拒绝非 PostgreSQL/psycopg 3 地址，避免环境间驱动行为漂移。"""
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            message = "database_url 必须使用 postgresql+psycopg://"
            raise ValueError(message)
        return value
