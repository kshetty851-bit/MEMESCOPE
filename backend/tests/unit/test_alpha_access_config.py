"""Production hardening for the temporary alpha access gate."""

from __future__ import annotations

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ENVIRONMENT": "production",
        "DEBUG": False,
        "SECRET_KEY": "x" * 48,
        "DEVELOPMENT_BYPASS_AUTH": False,
        "ALLOWED_HOSTS": ["memescope.ai"],
        "REFRESH_COOKIE_SECURE": True,
        "ALPHA_ACCESS_REQUIRED": True,
        "ALPHA_ACCESS_COOKIE_SECURE": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_production_requires_alpha_access_gate() -> None:
    with pytest.raises(ValueError, match="ALPHA_ACCESS_REQUIRED"):
        _settings(ALPHA_ACCESS_REQUIRED=False)


def test_production_requires_secure_alpha_cookie() -> None:
    with pytest.raises(ValueError, match="ALPHA_ACCESS_COOKIE_SECURE"):
        _settings(ALPHA_ACCESS_COOKIE_SECURE=False)


def test_production_requires_alpha_access_code() -> None:
    with pytest.raises(ValueError, match="ALPHA_ACCESS_CODE"):
        _settings(ALPHA_ACCESS_CODE="")
