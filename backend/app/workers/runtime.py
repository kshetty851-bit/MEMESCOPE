"""Running async work from a synchronous Celery task.

`asyncio.run()` closes the event loop as soon as the coroutine returns, but the
SQLAlchemy async engine keeps pooled connections alive beyond that. When those
are finalised later they try to close on a loop that no longer exists, and the
worker logs a `RuntimeError: Event loop is closed` traceback for a task that
actually succeeded.

Disposing the engine inside the loop, before it closes, is what makes the
teardown orderly. Every Celery task that touches the database goes through
`run_async` rather than calling `asyncio.run` directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from app.db.session import dispose_engine

T = TypeVar("T")


async def _with_disposal(coro: Coroutine[Any, Any, T]) -> T:
    try:
        return await coro
    finally:
        # Runs while the loop is still open, which is the entire point.
        await dispose_engine()


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion and release the connection pool cleanly."""
    return asyncio.run(_with_disposal(coro))
