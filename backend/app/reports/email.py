"""Sending mail, and refusing to when nothing is configured.

MEMESCOPE had no outbound email before the daily report. This is the whole of
it: one protocol, one SMTP implementation, and one that records instead of
sending so tests and unconfigured deploys can exercise the same path.

## Why a protocol rather than a module of functions

The report task must be testable without a network, and a test that sends real
mail is a test nobody can run twice. `EmailProvider` is the seam: the scheduler
takes one, production passes `SmtpEmailProvider`, tests pass `RecordingProvider`
and assert on what would have gone out.

## What is deliberately absent

No retry loop, no queue, no template engine. Celery already owns retries and
this package already renders its own HTML; adding a second mechanism for either
would mean two places to look when a report does not arrive.

Credentials come from the environment and are never logged. `SecretStr` keeps
the password out of a repr that might reach a log line.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)


class EmailError(RuntimeError):
    """A send failed. Carries no credentials."""


@dataclass(frozen=True, slots=True)
class Email:
    """One message, rendered and ready.

    Both bodies are required rather than optional. A multipart/alternative mail
    with an empty text part renders as blank in clients that prefer text, and
    "the email arrived empty" is a worse failure than a plain-looking one.
    """

    subject: str
    html_body: str
    text_body: str
    recipients: tuple[str, ...]
    sender: str
    sender_name: str = "MEMESCOPE"

    def as_message(self) -> EmailMessage:
        """The MIME message, text first so clients pick their preferred part."""
        message = EmailMessage()
        message["Subject"] = self.subject
        message["From"] = f"{self.sender_name} <{self.sender}>"
        message["To"] = ", ".join(self.recipients)
        message.set_content(self.text_body)
        message.add_alternative(self.html_body, subtype="html")
        return message


@dataclass(frozen=True, slots=True)
class SendResult:
    """What happened, in a form the delivery log can store."""

    sent: bool
    provider_message_id: str | None = None
    error: str | None = None


class EmailProvider(Protocol):
    """Anything that can deliver an `Email`."""

    def send(self, email: Email) -> SendResult: ...


@dataclass(frozen=True, slots=True)
class SmtpEmailProvider:
    """Delivery over SMTP.

    Synchronous on purpose. It runs inside a Celery worker, which is already a
    thread the application is not waiting on, and an async SMTP client would add
    a dependency for a call that happens once a day.
    """

    host: str
    port: int
    username: str
    password: str
    use_tls: bool = True
    timeout: float = 20.0

    def send(self, email: Email) -> SendResult:
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                if self.use_tls:
                    server.starttls(context=ssl.create_default_context())
                if self.username:
                    server.login(self.username, self.password)
                # `send_message` returns a dict of *refused* recipients; empty
                # means every address was accepted by the server.
                refused = server.send_message(email.as_message())
        except (smtplib.SMTPException, OSError) as exc:
            # The exception type is logged, never the message, because SMTP
            # errors routinely echo the envelope back.
            logger.warning("daily_report_smtp_failed", error_type=type(exc).__name__)
            return SendResult(sent=False, error=f"{type(exc).__name__}: {exc}")

        if refused:
            return SendResult(sent=False, error=f"recipients refused: {sorted(refused)}")

        # SMTP has no message id to return; the server assigns one and does not
        # report it through this API. `None` is the honest answer.
        return SendResult(sent=True, provider_message_id=None)


@dataclass(slots=True)
class RecordingProvider:
    """Records instead of sending.

    The default in tests and the fallback when no SMTP host is configured, so
    the scheduler exercises exactly one code path whether or not a deploy can
    actually send.
    """

    sent: list[Email] = field(default_factory=list)
    fail_with: str | None = None

    def send(self, email: Email) -> SendResult:
        if self.fail_with is not None:
            return SendResult(sent=False, error=self.fail_with)
        self.sent.append(email)
        return SendResult(sent=True, provider_message_id=f"recorded-{len(self.sent)}")


def provider_from_settings() -> EmailProvider:
    """The configured provider, or a recording one when nothing is configured.

    Never raises. A deploy without SMTP credentials should skip its report and
    say so, not crash a worker that is also running the paper wallet.
    """
    from app.core.config import settings

    if not settings.email_configured:
        return RecordingProvider()

    return SmtpEmailProvider(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD.get_secret_value(),
        use_tls=settings.SMTP_USE_TLS,
        timeout=settings.SMTP_TIMEOUT_SECONDS,
    )
