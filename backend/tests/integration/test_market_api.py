"""REST API tests for the market enrichment endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TradingStatus
from app.repositories.market import EnrichmentStateRepository, MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX

MINT_A = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
MINT_B = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
MINT_UNKNOWN = "So11111111111111111111111111111111111111112"

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
async def seeded(db_session: AsyncSession) -> None:
    tokens = TokenRepository(db_session)
    snapshots = MarketSnapshotRepository(db_session)
    states = EnrichmentStateRepository(db_session)

    token_a = await tokens.insert_if_absent(
        {
            "mint_address": MINT_A,
            "signature": "sigA",
            "slot": 100,
            "name": "Indian Batman",
            "symbol": "JEETMAN",
            "discovered_at": NOW,
        }
    )
    token_b = await tokens.insert_if_absent(
        {
            "mint_address": MINT_B,
            "signature": "sigB",
            "slot": 90,
            "name": "Bonk",
            "symbol": "BONK",
            "discovered_at": NOW - timedelta(hours=2),
        }
    )
    assert token_a is not None
    assert token_b is not None

    def _row(token: Any, minute: int, **overrides: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "token_id": token.id,
            "mint_address": token.mint_address,
            "captured_at": NOW + timedelta(minutes=minute),
            "price_usd": Decimal("0.000003155"),
            "liquidity_usd": Decimal("1000"),
            "market_cap": Decimal("50000"),
            "fully_diluted_valuation": Decimal("60000"),
            "volume_24h": Decimal("2500"),
            "volume_1h": Decimal("300"),
            "volume_5m": Decimal("25"),
            "buy_count_24h": 10,
            "sell_count_24h": 5,
            "dex_name": "pumpfun",
            "trading_pair": "JEETMAN/SOL",
            "pool_address": "poolA",
            "trading_status": TradingStatus.TRADING,
            "provider": "dexscreener",
        }
        values.update(overrides)
        return values

    for minute in range(3):
        await snapshots.add_snapshot(
            _row(token_a, minute, volume_24h=Decimal(1000 * (minute + 1)))
        )
    await snapshots.add_snapshot(
        _row(token_b, 0, volume_24h=Decimal("50"), liquidity_usd=Decimal("10"))
    )

    await states.ensure_state(
        token_id=token_a.id, mint_address=MINT_A, next_refresh_at=NOW + timedelta(seconds=30)
    )


# --- GET /tokens/{mint}/market ----------------------------------------------


async def test_current_market_returns_latest_snapshot(
    client: AsyncClient, seeded: None
) -> None:
    response = await client.get(f"{API}/tokens/{MINT_A}/market")
    assert response.status_code == 200

    body = response.json()
    assert body["mint_address"] == MINT_A
    assert body["snapshot_count"] == 3
    # Newest snapshot wins.
    assert Decimal(body["market"]["volume_24h"]) == Decimal("3000")
    assert body["market"]["dex_name"] == "pumpfun"
    assert body["market"]["trading_status"] == "trading"
    assert body["enrichment_status"] == "active"
    assert body["next_refresh_at"] is not None


async def test_market_is_null_when_not_yet_enriched(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A token with no pool indexed yet is a 200 with null market, not a 404."""
    await TokenRepository(db_session).insert_if_absent(
        {"mint_address": MINT_UNKNOWN, "signature": "sigU", "slot": 1}
    )

    response = await client.get(f"{API}/tokens/{MINT_UNKNOWN}/market")
    assert response.status_code == 200

    body = response.json()
    assert body["market"] is None
    assert body["snapshot_count"] == 0


async def test_market_for_unknown_token_is_404(client: AsyncClient) -> None:
    response = await client.get(f"{API}/tokens/{MINT_B}/market")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_market_rejects_malformed_mint(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/tokens/not-a-mint!/market")).status_code == 422


# --- GET /tokens/{mint}/history ---------------------------------------------


async def test_history_is_newest_first(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"{API}/tokens/{MINT_A}/history")
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 3
    captured = [item["captured_at"] for item in body["items"]]
    assert captured == sorted(captured, reverse=True)


async def test_history_paginates(client: AsyncClient, seeded: None) -> None:
    body = (
        await client.get(f"{API}/tokens/{MINT_A}/history", params={"page": 1, "page_size": 2})
    ).json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2

    page_two = (
        await client.get(f"{API}/tokens/{MINT_A}/history", params={"page": 2, "page_size": 2})
    ).json()
    assert len(page_two["items"]) == 1


async def test_history_filters_by_time_window(client: AsyncClient, seeded: None) -> None:
    body = (
        await client.get(
            f"{API}/tokens/{MINT_A}/history",
            params={"since": (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")},
        )
    ).json()
    assert body["total"] == 2


async def test_history_rejects_inverted_window(client: AsyncClient, seeded: None) -> None:
    response = await client.get(
        f"{API}/tokens/{MINT_A}/history",
        params={"since": "2026-07-27T12:00:00Z", "until": "2026-07-20T12:00:00Z"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_history_for_unknown_token_is_404(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/tokens/{MINT_B}/history")).status_code == 404


async def test_history_rejects_oversized_page(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"{API}/tokens/{MINT_A}/history", params={"page_size": 5000})
    assert response.status_code == 422


# --- GET /market/trending ----------------------------------------------------


async def test_trending_returns_one_entry_per_token(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"{API}/market/trending")
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 2, "one row per token, not one per snapshot"
    mints = [entry["token"]["mint_address"] for entry in body["items"]]
    assert sorted(mints) == sorted([MINT_A, MINT_B])


async def test_trending_ranks_by_volume_by_default(client: AsyncClient, seeded: None) -> None:
    body = (await client.get(f"{API}/market/trending")).json()
    assert body["sort_by"] == "volume_24h"
    assert body["items"][0]["token"]["mint_address"] == MINT_A
    assert Decimal(body["items"][0]["market"]["volume_24h"]) == Decimal("3000")


async def test_trending_supports_alternate_sorts(client: AsyncClient, seeded: None) -> None:
    body = (
        await client.get(f"{API}/market/trending", params={"sort_by": "liquidity_usd"})
    ).json()
    assert body["items"][0]["token"]["mint_address"] == MINT_A


async def test_trending_filters_by_min_liquidity(client: AsyncClient, seeded: None) -> None:
    body = (await client.get(f"{API}/market/trending", params={"min_liquidity": 500})).json()
    assert body["total"] == 1
    assert body["items"][0]["token"]["mint_address"] == MINT_A


async def test_trending_paginates(client: AsyncClient, seeded: None) -> None:
    body = (await client.get(f"{API}/market/trending", params={"page_size": 1})).json()
    assert body["total"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 1


async def test_trending_includes_token_and_market(client: AsyncClient, seeded: None) -> None:
    entry = (await client.get(f"{API}/market/trending")).json()["items"][0]
    assert entry["token"]["symbol"] == "JEETMAN"
    assert entry["market"]["provider"] == "dexscreener"


async def test_trending_rejects_unknown_sort(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"{API}/market/trending", params={"sort_by": "wat"})
    assert response.status_code == 422


async def test_market_endpoints_are_public(client: AsyncClient, seeded: None) -> None:
    assert (await client.get(f"{API}/market/trending")).status_code == 200
    assert (await client.get(f"{API}/tokens/{MINT_A}/market")).status_code == 200


async def test_day2_token_routes_still_work(client: AsyncClient, seeded: None) -> None:
    """Regression guard: adding /tokens/{mint}/market must not shadow /tokens/latest."""
    assert (await client.get(f"{API}/tokens/latest")).status_code == 200
    assert (await client.get(f"{API}/tokens")).status_code == 200
    assert (await client.get(f"{API}/tokens/{MINT_A}")).status_code == 200
