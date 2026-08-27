"""The reset email. One link, one hour, and a line telling the reader what to
do if it was not them — which is the only part an attacker's victim will read.
"""

from __future__ import annotations

from app.core.config import settings
from app.reports.email import Email

SUBJECT = "Reset your MEMESCOPE password"


def build(*, recipient: str, reset_url: str) -> Email:
    text = (
        "Someone asked to reset the password for this MEMESCOPE account.\n\n"
        f"{reset_url}\n\n"
        "The link works once and expires in one hour.\n\n"
        "If this was not you, nothing has changed and you do not need to do "
        "anything — the link cannot be used without this email. Requesting a "
        "new reset immediately invalidates this one.\n"
    )
    html = (
        "<p>Someone asked to reset the password for this MEMESCOPE account.</p>"
        f'<p><a href="{reset_url}">Choose a new password</a></p>'
        "<p>The link works once and expires in one hour.</p>"
        "<p>If this was not you, nothing has changed and you do not need to do "
        "anything &mdash; the link cannot be used without this email. "
        "Requesting a new reset immediately invalidates this one.</p>"
    )
    return Email(
        subject=SUBJECT, html_body=html, text_body=text,
        recipients=(recipient,),
        sender=settings.SMTP_FROM_EMAIL or "no-reply@memescope.site",
        sender_name=settings.SMTP_FROM_NAME or "MEMESCOPE",
    )
