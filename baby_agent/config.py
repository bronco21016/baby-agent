"""Application settings loaded from environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")

    # Huckleberry
    huckleberry_email: str = Field(..., alias="HUCKLEBERRY_EMAIL")
    huckleberry_password: str = Field(..., alias="HUCKLEBERRY_PASSWORD")
    huckleberry_timezone: str = Field("America/New_York", alias="HUCKLEBERRY_TIMEZONE")

    # Session
    session_ttl_seconds: int = Field(1800, alias="SESSION_TTL_SECONDS")

    # Server
    host: str = Field("0.0.0.0", alias="HOST")
    port: int = Field(8000, alias="PORT")

    # Claude
    claude_model: str = Field("claude-opus-4-6", alias="CLAUDE_MODEL")
    claude_effort: Literal["low", "medium", "high", "max"] = Field("high", alias="CLAUDE_EFFORT")


# Single shared instance
settings = Settings()
