"""Token image resolution must remain mint-owned and conservative."""

from __future__ import annotations

import httpx
import pytest

from app.services.token_images import (
    TokenImageResolver,
    image_from_metadata_json,
    normalize_image_url,
    normalize_metadata_url,
)


def test_metadata_uri_schemes_become_fetchable_urls() -> None:
    assert normalize_metadata_url("ipfs://QmMeta") == "https://ipfs.io/ipfs/QmMeta"
    assert normalize_metadata_url("ar://ArMeta") == "https://arweave.net/ArMeta"
    assert normalize_metadata_url("https://example.test/meta.json") == (
        "https://example.test/meta.json"
    )
    assert normalize_metadata_url("ftp://example.test/meta.json") is None


def test_metadata_json_selects_only_token_image_field() -> None:
    resolution = image_from_metadata_json(
        {
            "image": "ipfs://QmTokenImage",
            "banner": "https://example.test/banner.png",
            "external_url": "https://example.test",
        }
    )

    assert resolution is not None
    assert resolution.image_url == "https://ipfs.io/ipfs/QmTokenImage"


def test_metadata_json_rejects_document_urls_as_images() -> None:
    assert normalize_image_url("https://example.test/token.json") is None
    assert image_from_metadata_json({"image": "https://example.test/index.html"}) is None
    assert image_from_metadata_json({"og:image": "https://example.test/social.png"}) is None


@pytest.mark.asyncio
async def test_two_same_symbol_mints_resolve_from_their_own_metadata_uri() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://metadata.test/mint-a.json":
            return httpx.Response(
                200, json={"symbol": "DUP", "image": "https://cdn.test/a.png"}
            )
        if str(request.url) == "https://metadata.test/mint-b.json":
            return httpx.Response(
                200, json={"symbol": "DUP", "image": "https://cdn.test/b.png"}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with TokenImageResolver(client) as resolver:
        a = await resolver.resolve("https://metadata.test/mint-a.json")
        b = await resolver.resolve("https://metadata.test/mint-b.json")

    assert a is not None
    assert b is not None
    assert a.image_url == "https://cdn.test/a.png"
    assert b.image_url == "https://cdn.test/b.png"


@pytest.mark.asyncio
async def test_resolver_refuses_invalid_metadata_payloads() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"image": "not-a-url"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with TokenImageResolver(client) as resolver:
        assert await resolver.resolve("https://metadata.test/mint.json") is None
