"""The front page's curation (2026-10-20): no round-ups, quote headlines are
commentary, and no publisher crowds the single-source stories."""

from datetime import UTC, datetime

import pytest

from app.newsroom import news

pytestmark = pytest.mark.unit


def story(title: str, source: str, sources: int = 1) -> dict:
    return {"title": title, "source": source, "sources": sources}


def test_round_ups_are_dropped():
    assert news.is_roundup("Here’s what happened in crypto today")
    assert news.is_roundup("Bitcoin daily recap: BTC holds $108k")
    assert news.is_roundup("This week in crypto: ETFs and more")
    assert not news.is_roundup("Switzerland approves its first Bitcoin ETF")


def test_a_quote_headline_is_commentary_but_a_regulator_is_not():
    def kind(title: str) -> str:
        item = news.Item(id="i", source="s", url="https://x.example/2026/10/a", title=title,
                         summary="", published_at=datetime(2026, 10, 20, tzinfo=UTC))
        return news.classify(item).kind
    assert kind("Sam Callahan: Bitcoin Doesn’t Need Rate Cuts to Succeed") == "commentary"
    assert kind("SEC: new custody rule for brokers") == "report"
    assert kind("Michael J. Saylor: Buy More") == "commentary"


def test_no_publisher_fills_more_than_its_share():
    many = [story(f"Story {i}", "Bitcoin.com News") for i in range(40)]
    others = [story(f"Other {i}", "CoinDesk") for i in range(10)]
    shared = [story("Big story", "Bitcoin.com News", sources=4)]
    out = news.curate([*many, *shared, *others], limit=100)
    assert sum(s["source"] == "Bitcoin.com News" and s["sources"] == 1 for s in out) == 15
    assert shared[0] in out                      # carried by several: always kept
    assert len([s for s in out if s["source"] == "CoinDesk"]) == 10
    assert [s["title"] for s in out][:2] == ["Story 0", "Story 1"]   # order kept
