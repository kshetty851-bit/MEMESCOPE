"""Who gets watched: older than seven days, a real pool, not a dollar or a stock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.labs.momentum import config
from app.labs.momentum.lab import MomentumLab
from app.labs.momentum.models import MomPair
from app.labs.momentum.sources import Feeds, Listed, PairRow

NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
D = Decimal


def listed(mint: str, *, age_days: float, liq: float = 100_000,
           tags: frozenset[str] = frozenset({"verified"})) -> Listed:
    return Listed(mint=mint, symbol=mint[:6], born_at=NOW - timedelta(days=age_days),
                  liquidity=D(liq), tags=tags, list_name="tag/verified")


def pool(address: str, mint: str, quote: str = config.WSOL_MINT) -> PairRow:
    return PairRow(address, mint, quote, mint[:6], "raydium", D(1), D("0.01"),
                   D(200_000), None, None, D(50_000), None, None, None, None, None,
                   None, None)


class FakeFeeds:
    failures = 0

    def __init__(self) -> None:
        self.calls = {"dex": 0, "jup": 0}
        self.asked: list[str] = []

    async def listed(self) -> list[Listed]:
        return [listed("OLD", age_days=30),
                listed("YOUNG", age_days=2),
                listed("STABLE", age_days=900, tags=frozenset({"verified", "stable"})),
                listed("THIN", age_days=90, liq=10_000),
                listed("NOPOOL", age_days=60)]

    async def token_pairs(self, mint: str) -> list[PairRow]:
        self.asked.append(mint)
        if mint == "NOPOOL":  # priced only through another token
            return [pool("P-NOPOOL", mint, quote="SomeOtherToken")]
        return [pool(f"P-{mint}", mint)]


async def test_only_established_tokens_with_a_real_pool_are_watched(session) -> None:
    feeds = FakeFeeds()
    lab = MomentumLab(session, feeds=feeds, now=NOW)
    plan = await lab.plan_universe()
    assert set(plan.eligible) == {"OLD", "NOPOOL"}, "age, tags and liquidity decided first"
    assert sorted(feeds.asked) == ["NOPOOL", "OLD"], "only eligible tokens are looked up"
    first = await lab.apply_universe(plan)
    await session.commit()
    assert (first["admitted"], first["unresolved"]) == (1, 1)
    rows = (await session.scalars(select(MomPair))).all()
    assert [(r.mint, r.pair_address, r.status) for r in rows] == [("OLD", "P-OLD", "active")]

    # Next refresh: the watched token is only re-stamped, never looked up again.
    feeds.asked.clear()
    again = await MomentumLab(session, feeds=feeds, now=NOW + timedelta(minutes=30)
                              ).refresh_universe()
    await session.commit()
    assert again["refreshed"] == 1 and feeds.asked == ["NOPOOL"]


async def test_the_verified_list_is_read_whole() -> None:
    """Jupiter's category lists stop at 100 whatever `limit` says; the tag
    list is the whole verified set in one call, and it must be asked for."""
    seen: list[str] = []
    row = {"id": "M1", "symbol": "M1", "liquidity": 60_000, "tags": ["verified"],
           "firstPool": {"createdAt": "2026-08-01T00:00:00.85+00:00"}}

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[row])

    async with (httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client,
                Feeds(client=client, dex_per_minute=6000) as feeds):
        feeds._pace["jup"] = feeds._pace["dex"]  # no pacing in a test
        out = await feeds.listed()
    assert any(url.endswith("/tag?query=verified") for url in seen)
    assert len(seen) == len(config.JUPITER_LISTS) * len(config.JUPITER_WINDOWS) + 1
    tagged = [item for item in out if item.list_name == "tag/verified"]
    assert tagged and tagged[0].born_at == datetime(2026, 8, 1, 0, 0, 0, 850000, tzinfo=UTC)
