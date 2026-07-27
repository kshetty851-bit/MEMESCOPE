"""REST API tests for the token discovery endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.token import MetadataStatus
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX

# Valid base58, so it survives the path pattern check.
MINT_A = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
MINT_B = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


@pytest.fixture
async def seeded(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    now = datetime.now(UTC)
    await repo.insert_if_absent(
        {
            "mint_address": MINT_A,
            "signature": "sigA",
            "slot": 100,
            "creator_address": "WalletA",
            "decimals": 6,
            "name": "Indian Batman",
            "symbol": "JEETMAN",
            "metadata_uri": "https://ipfs.io/ipfs/abc",
            "block_time": now - timedelta(minutes=1),
            "discovered_at": now,
            "metadata_status": MetadataStatus.RESOLVED,
        }
    )
    await repo.insert_if_absent(
        {
            "mint_address": MINT_B,
            "signature": "sigB",
            "slot": 90,
            "creator_address": "WalletB",
            "decimals": 5,
            "name": "Bonk",
            "symbol": "BONK",
            "block_time": now - timedelta(days=3),
            "discovered_at": now - timedelta(hours=2),
            "metadata_status": MetadataStatus.RESOLVED,
        }
    )


async def test_list_returns_page_envelope(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"{API}/tokens")
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["pages"] == 1
    assert len(body["items"]) == 2


async def test_list_is_newest_first_by_default(client: AsyncClient, seeded: None) -> None:
    body = (await client.get(f"{API}/tokens")).json()
    assert body["items"][0]["mint_address"] == MINT_A


async def test_list_pagination(client: AsyncClient, seeded: None) -> None:
    body = (await client.get(f"{API}/tokens", params={"page": 1, "page_size": 1})).json()
    assert body["total"] == 2
    assert body["pages"] == 2
    assert len(body["items"]) == 1

    page_two = (await client.get(f"{API}/tokens", params={"page": 2, "page_size": 1})).json()
    assert page_two["items"][0]["mint_address"] != body["items"][0]["mint_address"]


async def test_list_sorting(client: AsyncClient, seeded: None) -> None:
    body = (
        await client.get(f"{API}/tokens", params={"sort_by": "slot", "order": "asc"})
    ).json()
    assert [item["slot"] for item in body["items"]] == [90, 100]


async def test_list_filters_by_creation_time(client: AsyncClient, seeded: None) -> None:
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    body = (await client.get(f"{API}/tokens", params={"created_after": cutoff})).json()
    assert body["total"] == 1
    assert body["items"][0]["mint_address"] == MINT_A


async def test_list_filters_by_creator(client: AsyncClient, seeded: None) -> None:
    body = (await client.get(f"{API}/tokens", params={"creator_address": "WalletB"})).json()
    assert body["total"] == 1
    assert body["items"][0]["mint_address"] == MINT_B


async def test_list_rejects_inverted_time_range(client: AsyncClient, seeded: None) -> None:
    response = await client.get(
        f"{API}/tokens",
        params={
            "created_after": "2026-07-27T00:00:00Z",
            "created_before": "2026-07-20T00:00:00Z",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_list_rejects_oversized_page(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/tokens", params={"page_size": 500})).status_code == 422


async def test_latest_returns_newest_first(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"{API}/tokens/latest", params={"limit": 5})
    assert response.status_code == 200

    items = response.json()
    assert isinstance(items, list)
    assert items[0]["mint_address"] == MINT_A


async def test_get_by_mint(client: AsyncClient, seeded: None) -> None:
    response = await client.get(f"{API}/tokens/{MINT_A}")
    assert response.status_code == 200

    body = response.json()
    assert body["symbol"] == "JEETMAN"
    assert body["decimals"] == 6
    assert body["metadata_status"] == "resolved"


async def test_get_unknown_mint_is_404_with_envelope(client: AsyncClient) -> None:
    response = await client.get(f"{API}/tokens/{MINT_B}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_get_invalid_mint_is_rejected(client: AsyncClient) -> None:
    """Malformed base58 must not reach the database."""
    assert (await client.get(f"{API}/tokens/not-a-valid-mint!")).status_code == 422


async def test_endpoints_are_public(client: AsyncClient, seeded: None) -> None:
    """Discoveries are public chain data; no bearer token required."""
    assert (await client.get(f"{API}/tokens")).status_code == 200
