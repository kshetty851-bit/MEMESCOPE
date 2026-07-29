"""The development authentication bypass.

An auth bypass is worth more test weight than the feature it enables. What
matters is not that it works, but that it cannot possibly be active anywhere it
should not be - so these assert the guards, not the convenience.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ENVIRONMENT": "local",
        "SECRET_KEY": "x" * 48,
        "DEVELOPMENT_BYPASS_AUTH": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


# --- The guard ----------------------------------------------------------------


def test_production_refuses_to_boot_with_the_bypass_set() -> None:
    """Refusing beats ignoring: a process that started "fine" with an auth
    bypass requested would leave whoever set it believing something false."""
    with pytest.raises(ValueError, match="DEVELOPMENT_BYPASS_AUTH"):
        _settings(
            ENVIRONMENT="production",
            DEVELOPMENT_BYPASS_AUTH=True,
            DEBUG=False,
            ALLOWED_HOSTS=["memescope.ai"],
            REFRESH_COOKIE_SECURE=True,
        )


def test_production_boots_normally_without_it() -> None:
    config = _settings(
        ENVIRONMENT="production",
        DEBUG=False,
        ALLOWED_HOSTS=["memescope.ai"],
        REFRESH_COOKIE_SECURE=True,
    )
    assert config.auth_bypass_active is False


@pytest.mark.parametrize("environment", ["staging", "test"])
def test_the_bypass_is_inert_outside_local(environment: str) -> None:
    """Setting the flag anywhere but local is a no-op rather than an error.

    `test` is excluded on purpose: otherwise a developer with the flag exported
    would run the whole suite with authentication disabled, and every auth test
    would pass for the wrong reason.
    """
    config = _settings(ENVIRONMENT=environment, DEVELOPMENT_BYPASS_AUTH=True)
    assert config.DEVELOPMENT_BYPASS_AUTH is True
    assert config.auth_bypass_active is False


def test_the_bypass_activates_in_local() -> None:
    assert _settings(DEVELOPMENT_BYPASS_AUTH=True).auth_bypass_active is True


def test_it_is_off_by_default() -> None:
    """A convenience that has to be asked for, never one that has to be removed."""
    assert _settings().DEVELOPMENT_BYPASS_AUTH is False
    assert _settings().auth_bypass_active is False


# --- The principal ------------------------------------------------------------


def test_the_developer_principal_is_serialisable() -> None:
    """It is returned from `/users/me`, so it has to satisfy the read schema.

    Both fields here have failed in practice: a `.local` address is rejected as
    a reserved name, and the timestamps are server defaults that stay null on an
    object that is never flushed.
    """
    from app.api.deps import _developer_principal
    from app.schemas.user import UserRead

    principal = _developer_principal()
    rendered = UserRead.model_validate(principal)

    assert rendered.email == "developer@memescope.dev"
    assert rendered.created_at is not None


def test_the_developer_principal_is_never_persisted() -> None:
    """A real row would outlive the flag, leaving a privileged account behind."""
    from sqlalchemy import inspect

    from app.api.deps import _developer_principal

    assert inspect(_developer_principal()).transient is True
