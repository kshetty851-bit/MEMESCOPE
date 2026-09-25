"""Solana news headlines for the sidebar's broadcast (2026-09-25).

Karthik asked for a live Solana news strip between HQ and Settings, read out
by the panda. Two public RSS feeds, both reachable from production and free:
Cointelegraph's Solana tag (every story is about Solana) and a Google News
search for "solana crypto" (the most up to date). Merged, de-duplicated by
title, newest first, cached for a few minutes so the page can poll freely.

Headlines only, with a link to the original. Nothing here is advice and
nothing reads the platform's own data: it is someone else's news, labelled
with whose.

The feeds are third-party XML, so each download is capped in size, and the
parser is the standard library's expat, which does not fetch external
entities and bounds entity expansion (Python 3.12).
"""

from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

FEEDS: tuple[tuple[str, str], ...] = (
    ("Cointelegraph", "https://cointelegraph.com/rss/tag/solana"),
    ("Google News",
     "https://news.google.com/rss/search?q=solana+crypto&hl=en-US&gl=US&ceid=US:en"),
)
#: A feed larger than this is not an RSS feed we expected; it is refused.
MAX_BYTES = 2_000_000
#: How long a fetch is reused. The page polls every few minutes; the feeds
#: themselves update on that order.
CACHE_SECONDS = 180
KEEP = 15

_cache: tuple[float, list[dict]] | None = None
_lock = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class Headline:
    title: str
    source: str
    url: str
    published_at: str | None


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse(xml: bytes, feed: str) -> list[Headline]:
    """RSS 2.0 items -> headlines. A Google News title ends "- Publisher",
    which becomes the source."""
    try:
        # Capped in size by `_fetch`; expat fetches no external entities and
        # bounds entity expansion. See the module note.
        root = ET.fromstring(xml)  # noqa: S314
    except ET.ParseError:
        return []
    out: list[Headline] = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        url = _clean(item.findtext("link"))
        if not title or not url.startswith("https://"):
            continue
        source = feed
        publisher = _clean(item.findtext("source"))
        if feed == "Google News":
            head, sep, tail = title.rpartition(" - ")
            if sep and head:
                title, source = head, publisher or tail
        published = None
        raw = item.findtext("pubDate")
        if raw:
            try:
                published = parsedate_to_datetime(raw).astimezone(UTC).isoformat()
            except (TypeError, ValueError):
                published = None
        out.append(Headline(title=title, source=source, url=url, published_at=published))
    return out


def merge(groups: list[list[Headline]], keep: int = KEEP) -> list[Headline]:
    """Newest first, one per title (case- and punctuation-blind)."""
    seen: set[str] = set()
    items: list[Headline] = []
    for h in sorted((h for g in groups for h in g),
                    key=lambda h: h.published_at or "", reverse=True):
        key = re.sub(r"[^a-z0-9]+", "", h.title.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append(h)
    return items[:keep]


async def _fetch(client: httpx.AsyncClient, feed: str, url: str) -> list[Headline]:
    try:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                return []
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    logger.warning("solana_news_feed_too_large", feed=feed)
                    return []
    except httpx.HTTPError as exc:
        logger.warning("solana_news_feed_unreachable", feed=feed, error=str(exc)[:120])
        return []
    return parse(body, feed)


async def headlines(*, now: float | None = None) -> list[dict]:
    """The merged headlines, from cache when fresh. An outage keeps the last
    good list rather than blanking the broadcast."""
    global _cache
    now = time.monotonic() if now is None else now
    async with _lock:
        if _cache and now - _cache[0] < CACHE_SECONDS:
            return _cache[1]
        async with httpx.AsyncClient(
            timeout=8.0, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (MEMESCOPE news)"},
        ) as client:
            groups = await asyncio.gather(*(_fetch(client, f, u) for f, u in FEEDS))
        items = [asdict(h) for h in merge(list(groups))]
        if items or _cache is None:
            _cache = (now, items)
        return _cache[1]


def reset_cache() -> None:
    global _cache
    _cache = None


__all__ = ["FEEDS", "Headline", "headlines", "merge", "parse", "reset_cache"]
