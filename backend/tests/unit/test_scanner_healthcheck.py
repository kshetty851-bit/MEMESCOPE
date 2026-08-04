"""The scanner container healthcheck.

Docker restarts the scanner when this exits non-zero. What it decides is
therefore load-bearing in both directions: too lenient and the four-day outage
repeats, too strict and a quiet market becomes a restart loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.config import settings
from app.health import probe
from app.health.schemas import ScannerHealth

pytestmark = pytest.mark.unit


def _health(status: str, minutes: float | None = 1.0) -> ScannerHealth:
    last = None if minutes is None else datetime.now(UTC) - timedelta(minutes=minutes)
    return ScannerHealth(
        status=status,  # type: ignore[arg-type]
        last_discovery=last,
        minutes_since_last_token=minutes,
    )


@pytest.fixture
def stub_scanner_health(monkeypatch: pytest.MonkeyPatch):
    """Replace the database and Redis round trips with a chosen verdict."""

    def _install(health: ScannerHealth) -> None:
        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

        class _Service:
            def __init__(self, *args: Any, **kwargs: Any) -> None: ...

            async def scanner(self, now: datetime) -> ScannerHealth:
                return health

        monkeypatch.setattr(probe, "SessionFactory", lambda: _Session())
        monkeypatch.setattr(probe, "PipelineHealthService", _Service)

        async def _noop(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(probe, "init_redis", _noop)
        monkeypatch.setattr(probe, "close_redis", _noop)
        monkeypatch.setattr(probe, "dispose_engine", _noop)
        monkeypatch.setattr(settings, "FEATURE_SCANNER_ENABLED", True)

    return _install


class TestVerdict:
    async def test_healthy_passes(self, stub_scanner_health: Any) -> None:
        stub_scanner_health(_health("healthy"))
        assert await probe.check() is True

    async def test_down_fails(self, stub_scanner_health: Any) -> None:
        """Discovery has stopped: restart is the right response."""
        stub_scanner_health(_health("down", minutes=5760.0))
        assert await probe.check() is False

    async def test_degraded_passes(self, stub_scanner_health: Any) -> None:
        """A quiet market is not a broken scanner.

        Restarting here would turn a slow hour into a crash loop, and a restart
        cannot conjure token launches that are not happening.
        """
        stub_scanner_health(_health("degraded", minutes=20.0))
        assert await probe.check() is True

    async def test_a_disabled_scanner_always_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It touches nothing — no database, no Redis.

        A disabled scanner that failed its own healthcheck would block every
        service declaring `depends_on: service_healthy`.
        """
        monkeypatch.setattr(settings, "FEATURE_SCANNER_ENABLED", False)
        assert await probe.check() is True


class TestExitCodes:
    def test_healthy_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _ok() -> bool:
            return True

        monkeypatch.setattr(probe, "check", _ok)
        assert probe.main() == 0

    def test_unhealthy_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _bad() -> bool:
            return False

        monkeypatch.setattr(probe, "check", _bad)
        assert probe.main() == 1

    def test_an_unreachable_dependency_fails_rather_than_crashing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A traceback out of a healthcheck is an unreadable failure.

        The probe cannot vouch for the scanner if it cannot reach the database,
        so it fails — but it says why first.
        """

        async def _explode() -> bool:
            raise ConnectionError("could not connect to postgres")

        monkeypatch.setattr(probe, "check", _explode)
        assert probe.main() == 1
        # `main` configures structlog, which renders to stdout rather than
        # through the stdlib handler caplog observes.
        assert "scanner_probe_failed" in capsys.readouterr().out
