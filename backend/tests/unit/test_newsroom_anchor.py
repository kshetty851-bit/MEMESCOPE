"""The newsroom TV: what the anchor says, and when a new bulletin is paid for."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.newsroom import anchor

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)          # 19:00 Dubai


def story(i: str, title: str, sources: int = 1, kind: str = "report", hours: float = 1) -> dict:
    return {"id": i, "title": title, "publishers": ["The Block"] * sources, "source": "The Block",
            "sources": sources, "kind": kind, "last_at": (NOW - timedelta(hours=hours)).isoformat()}


BUNDLE = {
    "lead": story("L", "Swiss Bitcoin ETF Approved - The Block", 5),
    "stories": [story("a", "Opinion piece", 9, kind="commentary"), story("b", "Old news", 9, hours=30),
                story("c", "Solana upgrade ships", 3), story("d", "Small item")],
    "ours": {"graduations_24h": 1030, "rug_rate_24h": 67.0,
             "survivors": [{"name": "MiiPals", "symbol": "Mii", "change_1h_pct": 787.9}]},
    "market": {"coins": [{"symbol": "BTC", "price": 82354, "ch24h": 0.44}]},
    "fear_greed": {"value": 55, "label": "Greed"},
}


def test_the_script_reads_only_the_page():
    segs = anchor.script(BUNDLE, NOW)
    text = " ".join(s["text"] for s in segs)
    assert "Good evening" in text and "7:00 PM in Dubai" in text
    assert "1,030 coins graduated" in text and "67 percent" in text and "MiiPals, up 788 percent" in text
    assert "Our top story: Swiss Bitcoin ETF Approved, reported by 5 outlets." in text   # publisher tail cut
    assert "Opinion piece" not in text and "Old news" not in text
    assert text.index("Solana upgrade") < text.index("Small item")                       # wider first
    assert "Bitcoin at 82,354 dollars, up 0.4 percent" in text and "reads 55, greed" in text
    assert "AI presenter" in text and "nothing here is financial advice" in text


class Redis:
    def __init__(self):
        self.d: dict = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.d:
            return False
        self.d[k] = v
        return True

    async def delete(self, k):
        self.d.pop(k, None)

    async def incr(self, k):
        self.d[k] = int(self.d.get(k, 0)) + 1

    async def expire(self, k, s):
        pass


def test_one_bulletin_an_hour_and_none_without_a_key(monkeypatch):
    calls = []

    async def speak(key, text):
        calls.append(text)
        return b"mp3-" + str(len(calls)).encode()

    monkeypatch.setattr(anchor, "_speak", speak)
    r = Redis()
    run = lambda at, key="k": asyncio.run(anchor.bulletin(r, BUNDLE, key, at))  # noqa: E731
    assert run(NOW, key="") is None and calls == []
    first = run(NOW)
    assert run(NOW + timedelta(minutes=59)) == first and len(calls) == 1          # still fresh
    second = run(NOW + timedelta(minutes=61))
    assert second["id"] != first["id"] and len(calls) == 2
    assert asyncio.run(anchor.audio(r, second["id"])) == b"mp3-2"
    r.d[anchor.DAY_KEY + f"{NOW:%Y%m%d}"] = anchor.DAILY_CAP                        # cap reached
    assert run(NOW + timedelta(hours=3)) == second and len(calls) == 2
