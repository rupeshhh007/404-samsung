"""Validated application configuration settings for INTERLOCK.

Implements all settings defined in docs/contracts/CONFIGURATION.md with exact
names, types, defaults, validation ranges, and fail-closed security.
"""

from typing import List, Literal, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    INTERLOCK_HOST: str = Field(default="127.0.0.1", min_length=1)
    INTERLOCK_PORT: int = Field(default=8000, ge=1, le=65535)
    INTERLOCK_FRONTEND_ORIGINS: str = Field(default="http://localhost:5173")
    INTERLOCK_WS_URL: str = Field(default="ws://localhost:8000/api/v1")
    INTERLOCK_MODE: Literal["DEMO", "LIVE", "TEST"] = Field(default="DEMO")
    INTERLOCK_MODEL_PROVIDER: Literal["fallback", "configured"] = Field(default="fallback")
    INTERLOCK_MODEL_API_KEY: Optional[str] = Field(default=None)
    INTERLOCK_TOOL_TIMEOUT_MS: int = Field(default=5000, ge=100, le=60000)
    INTERLOCK_BRANCH_TOP_K: int = Field(default=2, ge=0, le=3)
    INTERLOCK_BRANCH_TTL_MS: int = Field(default=10000, ge=100, le=60000)
    INTERLOCK_SPECULATION_BUDGET: int = Field(default=3, ge=0, le=20)
    INTERLOCK_FAKE_LATENCY_MS: int = Field(default=250, ge=0, le=60000)
    INTERLOCK_FAULT_MODE: Literal["none", "scenario"] = Field(default="scenario")
    INTERLOCK_SESSION_RETENTION_S: int = Field(default=3600, ge=60, le=86400)
    INTERLOCK_EVENT_RETENTION: int = Field(default=10000, ge=100, le=100000)
    INTERLOCK_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    @property
    def frontend_origins_list(self) -> List[str]:
        """Parse CSV frontend origins into a list of trimmed strings."""
        return [origin.strip() for origin in self.INTERLOCK_FRONTEND_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_model_api_key(self) -> "Settings":
        """Validate API key requirements based on provider and mode.

        Required only when configured; missing uses fallback in DEMO, fails LIVE.
        """
        if self.INTERLOCK_MODEL_PROVIDER == "configured":
            if not self.INTERLOCK_MODEL_API_KEY or not self.INTERLOCK_MODEL_API_KEY.strip():
                if self.INTERLOCK_MODE == "LIVE":
                    raise ValueError(
                        "INTERLOCK_MODEL_API_KEY is required in LIVE mode when INTERLOCK_MODEL_PROVIDER='configured'"
                    )
        return self
