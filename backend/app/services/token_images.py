"""Mint-owned token image resolution.

The UI renders whatever `discovered_tokens.image_url` says, so this module is
deliberately conservative: the only image it accepts is the `image` field from
the token metadata JSON referenced by that exact token row. No symbol matching,
no pair artwork, no social cards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_METADATA_BYTES = 512_000
MAX_IMAGE_URL_LENGTH = 2048


@dataclass(frozen=True, slots=True)
class TokenImageResolution:
    image_url: str
    source: str = "metadata_json.image"


def normalize_metadata_url(uri: str | None) -> str | None:
    """Return a fetchable metadata JSON URL, or `None` when unsupported."""
    if uri is None:
        return None
    value = uri.strip()
    if not value:
        return None

    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"} and parsed.netloc:
        return value
    if scheme == "ipfs" and parsed.netloc:
        path = f"{parsed.netloc}{parsed.path}".lstrip("/")
        return f"https://ipfs.io/ipfs/{path}"
    if scheme == "ar" and parsed.netloc:
        path = f"{parsed.netloc}{parsed.path}".lstrip("/")
        return f"https://arweave.net/{path}"
    return None


def normalize_image_url(value: str | None) -> str | None:
    """Return a browser-safe image URL, rejecting metadata/document URLs."""
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_IMAGE_URL_LENGTH:
        return None

    parsed = urlparse(candidate)
    scheme = parsed.scheme.lower()
    if scheme == "ipfs" and parsed.netloc:
        path = f"{parsed.netloc}{parsed.path}".lstrip("/")
        candidate = f"https://ipfs.io/ipfs/{path}"
        parsed = urlparse(candidate)
        scheme = parsed.scheme.lower()
    elif scheme == "ar" and parsed.netloc:
        path = f"{parsed.netloc}{parsed.path}".lstrip("/")
        candidate = f"https://arweave.net/{path}"
        parsed = urlparse(candidate)
        scheme = parsed.scheme.lower()

    if scheme not in {"http", "https"} or not parsed.netloc:
        return None

    lowered_path = parsed.path.lower()
    if lowered_path.endswith((".json", ".html", ".htm")):
        return None
    return candidate


def image_from_metadata_json(payload: dict[str, Any]) -> TokenImageResolution | None:
    """Extract only the token artwork field from metadata JSON."""
    image = payload.get("image")
    if not isinstance(image, str):
        return None
    image_url = normalize_image_url(image)
    if image_url is None:
        return None
    return TokenImageResolution(image_url=image_url)


class TokenImageResolver:
    """Fetch token metadata JSON and resolve its exact token image."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> TokenImageResolver:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
            self._owns_client = True
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("TokenImageResolver must be used as an async context manager.")
        return self._client

    async def resolve(self, metadata_uri: str | None) -> TokenImageResolution | None:
        url = normalize_metadata_url(metadata_uri)
        if url is None:
            return None

        try:
            response = await self._http.get(url, headers={"accept": "application/json"})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("token_image_metadata_fetch_failed", metadata_uri=url, error=str(exc))
            return None

        content = response.content
        if len(content) > MAX_METADATA_BYTES:
            logger.debug(
                "token_image_metadata_too_large", metadata_uri=url, bytes=len(content)
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.debug("token_image_metadata_invalid_json", metadata_uri=url)
            return None
        if not isinstance(payload, dict):
            return None
        return image_from_metadata_json(payload)
