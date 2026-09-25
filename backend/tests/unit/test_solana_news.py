"""The sidebar's Solana news: parsing, merging and the fetch's refusals."""

from __future__ import annotations

import pytest

from app.news import solana

pytestmark = pytest.mark.unit

COINTELEGRAPH = b"""<?xml version="1.0"?><rss><channel>
<item><title>Solana hits a new high</title><link>https://cointelegraph.com/a</link>
<pubDate>Thu, 25 Sep 2026 08:00:00 +0000</pubDate></item>
<item><title>No link here</title></item>
<item><title>Plain http is refused</title><link>http://example.com/x</link></item>
</channel></rss>"""

GOOGLE = b"""<?xml version="1.0"?><rss><channel>
<item><title>Solana hits a new high! - Decrypt</title><link>https://news.google.com/b</link>
<source url="https://decrypt.co">Decrypt</source>
<pubDate>Thu, 25 Sep 2026 09:00:00 GMT</pubDate></item>
<item><title>ETF flows turn to SOL - Bloomberg</title><link>https://news.google.com/c</link>
<pubDate>Thu, 25 Sep 2026 07:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_an_item_needs_a_title_and_a_secure_link():
    items = solana.parse(COINTELEGRAPH, "Cointelegraph")
    assert [(h.title, h.source) for h in items] == [
        ("Solana hits a new high", "Cointelegraph")]
    assert items[0].published_at == "2026-09-25T08:00:00+00:00"


def test_a_google_title_gives_up_its_publisher():
    items = solana.parse(GOOGLE, "Google News")
    assert [(h.title, h.source) for h in items] == [
        ("Solana hits a new high!", "Decrypt"), ("ETF flows turn to SOL", "Bloomberg")]


def test_merged_newest_first_and_the_same_story_once():
    merged = solana.merge([solana.parse(COINTELEGRAPH, "Cointelegraph"),
                           solana.parse(GOOGLE, "Google News")])
    # "Solana hits a new high" and "...high!" are one story; the newer copy stays.
    assert [(h.title, h.source) for h in merged] == [
        ("Solana hits a new high!", "Decrypt"), ("ETF flows turn to SOL", "Bloomberg")]


def test_broken_xml_is_no_headlines_not_an_error():
    assert solana.parse(b"<rss><channel><item>", "Cointelegraph") == []


async def test_an_outage_keeps_the_last_good_list(monkeypatch):
    solana.reset_cache()
    calls = {"n": 0}

    async def fetch(client, feed, url):
        calls["n"] += 1
        return solana.parse(COINTELEGRAPH, feed) if calls["n"] <= 2 else []

    monkeypatch.setattr(solana, "_fetch", fetch)
    first = await solana.headlines(now=0)
    assert first and first[0]["title"] == "Solana hits a new high"
    cached = await solana.headlines(now=10)                     # inside the cache window
    assert cached == first and calls["n"] == 2
    after = await solana.headlines(now=solana.CACHE_SECONDS + 1)  # both feeds now empty
    assert after == first
    solana.reset_cache()
