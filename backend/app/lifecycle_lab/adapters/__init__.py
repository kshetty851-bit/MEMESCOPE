"""Source adapters. One module per source, one common protocol (``base``)."""

from __future__ import annotations

from typing import Any

import httpx

from app.lifecycle_lab.adapters.base import (
    AdapterError,
    AdapterResult,
    SourceAdapter,
    Subject,
)
from app.lifecycle_lab.adapters.dexscreener import DexScreenerAdapter
from app.lifecycle_lab.adapters.gdelt import GdeltAdapter
from app.lifecycle_lab.adapters.geckoterminal import GeckoTerminalAdapter
from app.lifecycle_lab.adapters.pumpfun_replies import PumpfunRepliesAdapter
from app.lifecycle_lab.adapters.reddit import RedditAdapter
from app.lifecycle_lab.adapters.wikipedia import WikipediaAdapter
from app.lifecycle_lab.adapters.x import XAdapter

__all__ = [
    "AdapterError",
    "AdapterResult",
    "DexScreenerAdapter",
    "GdeltAdapter",
    "GeckoTerminalAdapter",
    "PumpfunRepliesAdapter",
    "RedditAdapter",
    "SourceAdapter",
    "Subject",
    "WikipediaAdapter",
    "XAdapter",
    "build_adapters",
]


def build_adapters(settings: Any, client: httpx.AsyncClient) -> list[SourceAdapter]:
    """Every adapter, enabled or not - a disabled one still yields a DISABLED run."""
    return [
        PumpfunRepliesAdapter(settings),
        WikipediaAdapter(settings, client),
        GdeltAdapter(settings, client),
        DexScreenerAdapter(settings, client),
        GeckoTerminalAdapter(settings, client),
        RedditAdapter(settings, client),
        XAdapter(settings),
    ]
