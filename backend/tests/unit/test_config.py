"""Unit tests for settings parsing and production guardrails."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    """Build settings from explicit values only.

    Every field the assertions depend on is passed as an init kwarg. Without
    that, ambient environment variables (which the container and CI both set)
    would leak in and make these tests pass or fail by accident.
    """
    base: dict[str, object] = {
        "ENVIRONMENT": "local",
        "DEBUG": False,
        # Pinned off: the local container exports this, and leaving it ambient
        # would make the production-hardening tests trip on the bypass guard
        # instead of the rule each one is actually named for.
        "DEVELOPMENT_BYPASS_AUTH": False,
        "SECRET_KEY": "x" * 48,
        "ALLOWED_HOSTS": "*",
        "REFRESH_COOKIE_SECURE": True,
        "ALPHA_ACCESS_REQUIRED": False,
        "ALPHA_ACCESS_COOKIE_SECURE": False,
        "CORS_ORIGINS": "http://localhost:3000",
        "POSTGRES_HOST": "db",
        "POSTGRES_USER": "memescope",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "memescope",
    }
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]


def test_database_uri_uses_async_driver() -> None:
    assert _settings().DATABASE_URI.startswith("postgresql+asyncpg://")


def test_sync_uri_is_derived_for_alembic() -> None:
    assert _settings().SYNC_DATABASE_URI.startswith("postgresql+psycopg://")


def test_csv_env_vars_parse_into_lists() -> None:
    settings = _settings(CORS_ORIGINS="http://a.test, http://b.test")
    assert settings.CORS_ORIGINS == ["http://a.test", "http://b.test"]


def test_production_rejects_debug() -> None:
    with pytest.raises(ValidationError, match="DEBUG must be disabled"):
        _settings(ENVIRONMENT="production", DEBUG=True, ALLOWED_HOSTS="api.memescope.ai")


def test_production_rejects_wildcard_hosts() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS must be explicit"):
        _settings(ENVIRONMENT="production", ALLOWED_HOSTS="*")


def test_production_config_passes_when_hardened() -> None:
    settings = _settings(
        ENVIRONMENT="production",
        ALLOWED_HOSTS="api.memescope.ai",
        REFRESH_COOKIE_SECURE=True,
        ALPHA_ACCESS_REQUIRED=True,
        ALPHA_ACCESS_COOKIE_SECURE=True,
    )
    assert settings.is_production


def test_pumpfun_radar_rejects_an_inverted_age_window() -> None:
    with pytest.raises(ValidationError, match="PUMPFUN_RADAR_MIN_AGE_DAYS"):
        _settings(PUMPFUN_RADAR_MIN_AGE_DAYS=9, PUMPFUN_RADAR_MAX_AGE_DAYS=8)
