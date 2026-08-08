"""Redis channels are namespaced by environment.

The test suite creates and drops its own Postgres database but published onto
the same Redis channel as whatever stack was running. A `pytest` run therefore
announced tokens that existed only in `memescope_test`; the development
enrichment worker consumed them, failed the foreign key, and tore down its
subscription. A green test run left the development pipeline crash-looping.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, settings

pytestmark = pytest.mark.unit


def _settings(environment: str) -> Settings:
    """A valid Settings for any environment.

    The production hardening validators are satisfied explicitly rather than
    inherited from the ambient container environment, which runs with DEBUG and
    the auth bypass on and would fail to construct at all.
    """
    return Settings(
        ENVIRONMENT=environment,  # type: ignore[arg-type]
        SECRET_KEY="test-secret-key-not-for-production-use-only-0000",
        ALLOWED_HOSTS=["example.com"],
        CORS_ORIGINS=["https://example.com"],
        REFRESH_COOKIE_SECURE=environment == "production",
        DEBUG=False,
        DEVELOPMENT_BYPASS_AUTH=False,
    )


class TestIsolation:
    @pytest.mark.parametrize(
        ("left", "right"),
        [("local", "test"), ("local", "production"), ("test", "production")],
    )
    def test_environments_never_share_a_discovery_channel(self, left: str, right: str) -> None:
        assert _settings(left).token_channel != _settings(right).token_channel

    @pytest.mark.parametrize(
        ("left", "right"),
        [("local", "test"), ("local", "production"), ("test", "production")],
    )
    def test_environments_never_share_a_score_channel(self, left: str, right: str) -> None:
        assert _settings(left).score_channel != _settings(right).score_channel

    @pytest.mark.parametrize(
        ("left", "right"),
        [("local", "test"), ("local", "production"), ("test", "production")],
    )
    def test_environments_never_share_a_live_channel(self, left: str, right: str) -> None:
        assert _settings(left).live_channel != _settings(right).live_channel

    def test_environments_never_share_the_scanner_state_key(self) -> None:
        """Otherwise a test run would report the development scanner as down."""
        assert _settings("test").scanner_state_key != _settings("local").scanner_state_key

    def test_the_test_environment_cannot_reach_a_development_worker(self) -> None:
        """The precise failure, asserted directly."""
        test_publishes_to = _settings("test").token_channel
        development_listens_on = _settings("local").token_channel

        assert test_publishes_to != development_listens_on


class TestNaming:
    def test_the_channel_carries_its_environment(self) -> None:
        assert _settings("production").token_channel.startswith("production:")

    def test_the_base_name_is_preserved(self) -> None:
        """Namespacing prefixes; it does not rewrite the channel."""
        config = _settings("local")
        assert config.token_channel.endswith(config.TOKEN_EVENT_CHANNEL)
        assert config.score_channel.endswith(config.SCORE_EVENT_CHANNEL)
        assert config.live_channel.endswith(config.LIVE_EVENT_CHANNEL)

    def test_a_custom_base_name_is_still_namespaced(self) -> None:
        """An operator overriding the channel must not lose isolation."""
        config = Settings(
            ENVIRONMENT="local",  # type: ignore[arg-type]
            SECRET_KEY="test-secret-key-not-for-production-use-only-0000",
            TOKEN_EVENT_CHANNEL="custom:channel",
        )
        assert config.token_channel == "local:custom:channel"

    def test_the_running_suite_is_on_the_test_namespace(self) -> None:
        """Guards against a future change that reads the raw setting again."""
        assert settings.ENVIRONMENT == "test"
        assert settings.token_channel.startswith("test:")
