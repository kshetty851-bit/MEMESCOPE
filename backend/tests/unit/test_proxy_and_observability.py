"""Trusted-proxy handling and error-reporting initialisation.

Both were deployment defects rather than bugs anything local would surface:
behind a reverse proxy the rate limiter silently keyed every user into one
bucket, and `SENTRY_DSN` was configuration that nothing read.
"""

from __future__ import annotations

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import Settings
from app.main import create_app


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ENVIRONMENT": "local",
        "SECRET_KEY": "x" * 48,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestTrustedProxies:
    def test_defaults_to_trusting_nothing(self) -> None:
        # A default that trusts a forwarded header would let any client pick
        # its own rate-limit bucket simply by setting one.
        assert _settings().TRUSTED_PROXY_IPS == []

    def test_accepts_a_comma_separated_list(self) -> None:
        settings = _settings(TRUSTED_PROXY_IPS="10.0.0.1, 10.0.0.2")

        assert settings.TRUSTED_PROXY_IPS == ["10.0.0.1", "10.0.0.2"]

    def test_proxy_middleware_absent_when_no_proxies_declared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.main.settings", _settings())

        app = create_app()

        assert not any(m.cls is ProxyHeadersMiddleware for m in app.user_middleware)

    def test_proxy_middleware_present_when_proxies_declared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.main.settings", _settings(TRUSTED_PROXY_IPS="10.0.0.1"))

        app = create_app()

        assert any(m.cls is ProxyHeadersMiddleware for m in app.user_middleware)

    def test_proxy_middleware_is_outermost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # `request.client` must be corrected before the rate limiter keys on it
        # and before the request context logs it. Starlette applies
        # `user_middleware` outermost-first, so this has to be index 0.
        monkeypatch.setattr("app.main.settings", _settings(TRUSTED_PROXY_IPS="10.0.0.1"))

        app = create_app()

        assert app.user_middleware[0].cls is ProxyHeadersMiddleware


class TestSentryInit:
    def test_no_dsn_means_no_initialisation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.core.observability.settings", _settings())

        from app.core.observability import init_sentry

        assert init_sentry() is False

    def test_dsn_initialises_with_release_and_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def fake_init(**kwargs: object) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(
            "app.core.observability.settings",
            _settings(
                SENTRY_DSN="https://key@example.ingest.sentry.io/1",
                BUILD_SHA="abc1234",
                SENTRY_TRACES_SAMPLE_RATE=0.25,
            ),
        )
        import sentry_sdk

        monkeypatch.setattr(sentry_sdk, "init", fake_init)

        from app.core.observability import init_sentry

        assert init_sentry() is True
        assert captured["environment"] == "local"
        assert captured["release"] == "abc1234"
        assert captured["traces_sample_rate"] == 0.25
        # Request bodies and headers carry tokens and wallet addresses.
        assert captured["send_default_pii"] is False

    def test_sample_rate_is_bounded(self) -> None:
        with pytest.raises(ValueError):
            _settings(SENTRY_TRACES_SAMPLE_RATE=1.5)


class TestTrustedProxyMatching:
    """The default must actually cover the addresses Compose hands out.

    A CIDR that looks right but does not match is the worst outcome here: the
    control appears configured, nothing errors, and every user silently shares
    one rate-limit bucket. This asserts the default against a real address from
    the project's own bridge network (172.19.0.0/16 at the time of writing).
    """

    def test_default_production_cidr_covers_compose_addresses(self) -> None:
        from uvicorn.middleware.proxy_headers import _TrustedHosts

        trusted = _TrustedHosts(["172.16.0.0/12"])

        # Docker allocates compose bridge networks from 172.16.0.0/12.
        assert "172.19.0.4" in trusted
        assert "172.17.0.1" in trusted
        assert "172.31.255.254" in trusted

    def test_default_production_cidr_excludes_the_public_internet(self) -> None:
        from uvicorn.middleware.proxy_headers import _TrustedHosts

        trusted = _TrustedHosts(["172.16.0.0/12"])

        # If these were trusted, any client could set X-Forwarded-For and pick
        # its own bucket — worse than having no limiter at all.
        assert "203.0.113.10" not in trusted
        assert "8.8.8.8" not in trusted
        # Docker Desktop's published-port path presents this on macOS, which is
        # why a local `-p` test does not exercise the production topology.
        assert "192.168.65.1" not in trusted


class TestEmptyOptionalSettings:
    """An unconfigured optional must not stop the process from starting.

    `SENTRY_DSN: ${SENTRY_DSN:-}` in a compose file supplies an empty string
    rather than omitting the variable, and an empty string is not a valid URL.
    Every deployment without a Sentry project therefore crashed on boot — the
    default path was the broken one. Found by the Phase 6C production rehearsal.
    """

    def test_empty_sentry_dsn_means_disabled_not_invalid(self) -> None:
        settings = _settings(SENTRY_DSN="")

        assert settings.SENTRY_DSN is None

    def test_whitespace_sentry_dsn_is_also_treated_as_unset(self) -> None:
        assert _settings(SENTRY_DSN="   ").SENTRY_DSN is None

    def test_a_real_dsn_still_validates(self) -> None:
        settings = _settings(SENTRY_DSN="https://key@example.ingest.sentry.io/1")

        assert settings.SENTRY_DSN is not None

    def test_a_malformed_dsn_is_still_rejected(self) -> None:
        # Empty is "unset"; nonsense is still a configuration error worth
        # failing on, or a typo would silently disable error reporting.
        with pytest.raises(ValueError):
            _settings(SENTRY_DSN="not-a-url")
