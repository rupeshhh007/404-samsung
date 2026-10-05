"""T-CFG-01: bounded settings and fail-closed configured provider."""

import pytest
from pydantic import ValidationError

from interlock.config import Settings


def test_t_cfg_01_defaults_and_bounds(monkeypatch):
    for key in ("INTERLOCK_MODE", "INTERLOCK_MODEL_PROVIDER", "INTERLOCK_MODEL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    assert settings.INTERLOCK_MODE == "DEMO"
    assert settings.INTERLOCK_MODEL_PROVIDER == "fallback"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, INTERLOCK_PORT=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, INTERLOCK_BRANCH_TOP_K=4)


def test_t_cfg_01_live_configured_model_requires_key(monkeypatch):
    monkeypatch.delenv("INTERLOCK_MODEL_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, INTERLOCK_MODE="LIVE",
                 INTERLOCK_MODEL_PROVIDER="configured")
    assert Settings(_env_file=None, INTERLOCK_MODE="DEMO",
                    INTERLOCK_MODEL_PROVIDER="configured").INTERLOCK_MODE == "DEMO"
