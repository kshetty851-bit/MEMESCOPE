"""The email provider seam, and the due-time rule.

No test here may touch a network. `RecordingProvider` is the default everywhere,
and `TestNoRealSendInTests` asserts the configured provider degrades to it when
credentials are absent — which is also what an unconfigured deploy does, so the
scheduled path is the one under test rather than a special case.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.reports.email import (
    Email,
    RecordingProvider,
    SmtpEmailProvider,
    provider_from_settings,
)
from app.reports.service import is_due

DUBAI = "Asia/Dubai"


def email() -> Email:
    return Email(
        subject="MEMESCOPE — Test",
        html_body="<p>hi</p>",
        text_body="hi",
        recipients=("someone@example.com",),
        sender="reports@example.com",
    )


class TestEmailMessage:
    def test_carries_both_bodies(self) -> None:
        message = email().as_message()
        assert message.is_multipart()
        types = {part.get_content_type() for part in message.walk()}
        assert "text/plain" in types
        assert "text/html" in types

    def test_text_part_comes_first(self) -> None:
        """Clients preferring text must not fall through to an empty part."""
        parts = [p for p in email().as_message().walk() if not p.is_multipart()]
        assert parts[0].get_content_type() == "text/plain"

    def test_headers_are_set(self) -> None:
        message = email().as_message()
        assert message["Subject"] == "MEMESCOPE — Test"
        assert "reports@example.com" in message["From"]
        assert message["To"] == "someone@example.com"


class TestRecordingProvider:
    def test_records_instead_of_sending(self) -> None:
        provider = RecordingProvider()
        result = provider.send(email())
        assert result.sent
        assert len(provider.sent) == 1
        assert provider.sent[0].subject == "MEMESCOPE — Test"

    def test_can_simulate_failure(self) -> None:
        provider = RecordingProvider(fail_with="smtp exploded")
        result = provider.send(email())
        assert result.sent is False
        assert result.error == "smtp exploded"
        assert provider.sent == []


class TestNoRealSendInTests:
    def test_unconfigured_settings_yield_a_recording_provider(self, monkeypatch) -> None:
        from app.core import config

        monkeypatch.setattr(config.settings, "SMTP_HOST", "", raising=False)
        monkeypatch.setattr(config.settings, "SMTP_USERNAME", "", raising=False)
        assert isinstance(provider_from_settings(), RecordingProvider)

    def test_configured_settings_yield_smtp(self, monkeypatch) -> None:
        from app.core import config

        monkeypatch.setattr(config.settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(config.settings, "SMTP_USERNAME", "user@example.com")
        provider = provider_from_settings()
        assert isinstance(provider, SmtpEmailProvider)
        assert provider.host == "smtp.example.com"


class TestSmtpFailureIsContained:
    def test_a_dead_host_returns_a_result_rather_than_raising(self) -> None:
        """A report must never take down a worker that also runs the wallet."""
        provider = SmtpEmailProvider(
            host="127.0.0.1",
            port=1,  # nothing listens here
            username="u",
            password="p",
            timeout=0.2,
        )
        result = provider.send(email())
        assert result.sent is False
        assert result.error


class TestIsDue:
    def test_before_the_hour_is_not_due(self) -> None:
        # 04:00 UTC is 08:00 in Dubai.
        assert not is_due(
            datetime(2026, 8, 12, 4, 0, tzinfo=UTC), tz_name=DUBAI, hour=9, minute=0
        )

    def test_at_the_hour_is_due(self) -> None:
        # 05:00 UTC is 09:00 in Dubai.
        assert is_due(
            datetime(2026, 8, 12, 5, 0, tzinfo=UTC), tz_name=DUBAI, hour=9, minute=0
        )

    def test_after_the_hour_is_still_due(self) -> None:
        """A worker down at 09:00 must still send at 09:15."""
        assert is_due(
            datetime(2026, 8, 12, 5, 15, tzinfo=UTC), tz_name=DUBAI, hour=9, minute=0
        )

    def test_minutes_are_respected(self) -> None:
        at_0925 = datetime(2026, 8, 12, 5, 25, tzinfo=UTC)
        assert is_due(at_0925, tz_name=DUBAI, hour=9, minute=0)
        assert not is_due(at_0925, tz_name=DUBAI, hour=9, minute=30)

    def test_utc_would_disagree(self) -> None:
        """The whole reason the timezone is explicit.

        05:00 UTC is 09:00 in Dubai and 05:00 in UTC — due in one, not the other.
        """
        moment = datetime(2026, 8, 12, 5, 0, tzinfo=UTC)
        assert is_due(moment, tz_name=DUBAI, hour=9, minute=0)
        assert not is_due(moment, tz_name="UTC", hour=9, minute=0)
