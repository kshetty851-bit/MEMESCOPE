"""Error reporting.

`sentry-sdk` has been a declared dependency and `SENTRY_DSN` a declared setting
since Day 1, but nothing ever called `init()` - so the DSN was configuration
that did nothing, and an operator setting it would reasonably believe errors
were being reported when they were not. Silent observability is worse than
none, because it removes the prompt to go looking.

Initialisation is deliberately conditional: with no DSN the SDK is never
started, which keeps development and CI free of both network calls and the need
for a secret.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def init_sentry() -> bool:
    """Start error reporting if a DSN is configured. Returns whether it did."""
    if settings.SENTRY_DSN is None:
        return False

    # Imported lazily so a deployment that does not use Sentry pays neither the
    # import cost nor a hard dependency on the SDK being importable.
    import sentry_sdk

    sentry_sdk.init(
        dsn=str(settings.SENTRY_DSN),
        environment=settings.ENVIRONMENT,
        release=settings.BUILD_SHA,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # Off by default in the SDK, set explicitly because it is the setting
        # most likely to leak user data and least likely to be reviewed later.
        # Request bodies and headers can carry tokens and wallet addresses.
        send_default_pii=False,
    )

    logger.info(
        "sentry_initialised",
        environment=settings.ENVIRONMENT,
        release=settings.BUILD_SHA,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )
    return True
