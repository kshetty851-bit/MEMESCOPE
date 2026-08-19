"""Entrypoint for the isolated Yellowstone shadow process."""

from __future__ import annotations

import asyncio
import contextlib
import signal

from app.core.logging import configure_logging
from app.services.discovery.yellowstone import YellowstoneShadowProvider


def main() -> int:
    configure_logging()
    provider = YellowstoneShadowProvider()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, provider.stop)
    loop.run_until_complete(provider.run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
