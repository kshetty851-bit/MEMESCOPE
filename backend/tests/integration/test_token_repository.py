"""Repository tests — idempotency, filtering, sorting, pagination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import MetadataStatus
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration


def _values(mint: str, **overrides: object) -> dict:
    base: dict = {
        "mint_address": mint,
        "signature": f"sig-{mint}",
        "slot": 435484419,
        "creator_address": "5r1Q8ehbFi4SaF8XLjcNMCdJCEov95wttcmjgk3ncXTr",
        "decimals": 6,
        "block_time": datetime(2026, 7, 27, 5, 0, tzinfo=UTC),
        "source_program": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "metadata_status": MetadataStatus.PENDING,
    }
    base.update(overrides)
    return base


async def test_insert_returns_the_row(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    token = await repo.insert_if_absent(_values("MintAAA"))
    assert token is not None
    assert token.mint_address == "MintAAA"
    assert token.metadata_status is MetadataStatus.PENDING


async def test_duplicate_insert_returns_none_and_does_not_raise(
    db_session: AsyncSession,
) -> None:
    """Idempotency: replaying the same discovery must be a silent no-op."""
    repo = TokenRepository(db_session)
    first = await repo.insert_if_absent(_values("MintDup"))
    second = await repo.insert_if_absent(_values("MintDup", signature="different-sig"))

    assert first is not None
    assert second is None, "a known mint must not be inserted twice"
    assert await repo.count() == 1


async def test_duplicate_does_not_overwrite_the_original(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    await repo.insert_if_absent(_values("MintKeep", name="Original"))
    await repo.insert_if_absent(_values("MintKeep", name="Replacement"))

    token = await repo.get_by_mint("MintKeep")
    assert token is not None
    assert token.name == "Original"


async def test_get_by_mint_returns_none_when_absent(db_session: AsyncSession) -> None:
    assert await TokenRepository(db_session).get_by_mint("NoSuchMint") is None


async def test_update_metadata_resolves_and_counts_attempts(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    token = await repo.insert_if_absent(_values("MintMeta"))
    assert token is not None

    updated = await repo.update_metadata(
        token,
        name="Indian Batman",
        symbol="JEETMAN",
        metadata_uri="https://ipfs.io/ipfs/abc",
        image_url="https://cdn.example/token.png",
        decimals=9,
        status=MetadataStatus.RESOLVED,
    )
    assert updated.name == "Indian Batman"
    assert updated.decimals == 9
    assert updated.image_url == "https://cdn.example/token.png"
    assert updated.metadata_status is MetadataStatus.RESOLVED
    assert updated.metadata_attempts == 1


async def test_list_pending_metadata_only_returns_pending(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    await repo.insert_if_absent(_values("MintPending"))
    resolved = await repo.insert_if_absent(
        _values("MintResolved", metadata_status=MetadataStatus.RESOLVED)
    )
    assert resolved is not None

    pending = await repo.list_pending_metadata()
    assert [token.mint_address for token in pending] == ["MintPending"]


async def test_list_missing_images_requires_metadata_uri_and_no_image(
    db_session: AsyncSession,
) -> None:
    repo = TokenRepository(db_session)
    await repo.insert_if_absent(
        _values("NeedsImage", metadata_uri="https://metadata.test/needs.json")
    )
    await repo.insert_if_absent(_values("NoMetadata"))
    await repo.insert_if_absent(
        _values(
            "AlreadyHasImage",
            metadata_uri="https://metadata.test/has.json",
            image_url="https://cdn.test/has.png",
        )
    )

    missing = await repo.list_missing_images(limit=10)

    assert [token.mint_address for token in missing] == ["NeedsImage"]


async def test_update_image_url_only_changes_the_image(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    token = await repo.insert_if_absent(
        _values(
            "ImageOnly",
            name="Original Name",
            symbol="ORIG",
            metadata_uri="https://metadata.test/image.json",
        )
    )
    assert token is not None

    updated = await repo.update_image_url(token, image_url="https://cdn.test/image.png")

    assert updated.image_url == "https://cdn.test/image.png"
    assert updated.name == "Original Name"
    assert updated.symbol == "ORIG"
    assert updated.metadata_uri == "https://metadata.test/image.json"


async def test_latest_is_newest_first(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    now = datetime.now(UTC)
    for index in range(3):
        await repo.insert_if_absent(
            _values(f"Mint{index}", discovered_at=now - timedelta(minutes=index))
        )

    latest = await repo.latest(limit=3)
    assert [token.mint_address for token in latest] == ["Mint0", "Mint1", "Mint2"]


async def test_search_paginates_and_reports_total(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    now = datetime.now(UTC)
    for index in range(5):
        await repo.insert_if_absent(
            _values(f"Page{index}", discovered_at=now - timedelta(minutes=index))
        )

    page_one, total = await repo.search(offset=0, limit=2)
    page_two, _ = await repo.search(offset=2, limit=2)

    assert total == 5
    assert len(page_one) == 2
    assert {t.mint_address for t in page_one}.isdisjoint({t.mint_address for t in page_two})


async def test_search_filters_by_on_chain_creation_time(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    old = datetime(2026, 7, 20, tzinfo=UTC)
    new = datetime(2026, 7, 26, tzinfo=UTC)
    await repo.insert_if_absent(_values("MintOld", block_time=old))
    await repo.insert_if_absent(_values("MintNew", block_time=new))

    rows, total = await repo.search(created_after=datetime(2026, 7, 25, tzinfo=UTC))
    assert total == 1
    assert rows[0].mint_address == "MintNew"

    rows, total = await repo.search(created_before=datetime(2026, 7, 25, tzinfo=UTC))
    assert total == 1
    assert rows[0].mint_address == "MintOld"


async def test_search_filters_by_creator(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    await repo.insert_if_absent(_values("MintA", creator_address="WalletA"))
    await repo.insert_if_absent(_values("MintB", creator_address="WalletB"))

    rows, total = await repo.search(creator_address="WalletA")
    assert total == 1
    assert rows[0].mint_address == "MintA"


async def test_search_sorts_ascending_and_descending(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    for index, slot in enumerate((300, 100, 200)):
        await repo.insert_if_absent(_values(f"Slot{index}", slot=slot))

    asc, _ = await repo.search(sort_by="slot", order="asc")
    desc, _ = await repo.search(sort_by="slot", order="desc")

    assert [t.slot for t in asc] == [100, 200, 300]
    assert [t.slot for t in desc] == [300, 200, 100]
