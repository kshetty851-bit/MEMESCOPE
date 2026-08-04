"""Identity, market and age for a page of tokens, resolved in batch.

Sprint 23. Both the Radar and the Opportunity board need the same three facts
about a page of mints — what it is called, what it is trading at, how old it
is — and both need them without a query per row. Before this, the board owned
the only implementation as a private helper; giving the Radar its market strip
would have meant a second copy that drifts from the first.

Joined at read time rather than copied onto the ranking rows, for the same
reason identity is: a snapshot that lands later is reflected without a
backfill, and the ranking row stays the immutable record of a detection.

This module does I/O and is therefore not an engine — but `market_strip` is
pure, so the rendering rule (never estimate, never zero a missing reading) is
testable without a database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.schemas.market_strip import MarketStripOut

#: The window the 24h change is measured over. Named rather than inlined
#: because it is part of the claim: "24h" means "against the newest reading at
#: or before this moment", not "against whatever we happen to hold".
CHANGE_WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class TokenContext:
    """Everything a row needs beyond the ranking row itself.

    Each field is independently optional: a token can have a name and no
    market, or a market and no age, and the row renders whichever facts exist.
    """

    names: dict[str, tuple[str | None, str | None]]
    markets: dict[str, TokenMarketSnapshot]
    prior_prices: dict[str, Decimal]
    ages: dict[str, datetime]

    @classmethod
    def empty(cls) -> TokenContext:
        return cls(names={}, markets={}, prior_prices={}, ages={})

    def name_for(self, mint: str) -> tuple[str | None, str | None]:
        return self.names.get(mint, (None, None))

    def strip_for(self, mint: str) -> MarketStripOut | None:
        return market_strip(self.markets.get(mint), prior_price=self.prior_prices.get(mint))

    def age_seconds(self, mint: str, *, now: datetime) -> int | None:
        """Seconds since the token existed on chain, or since we first saw it.

        `None` rather than 0 when neither is known: "we do not know how old
        this is" and "this was created this instant" are different claims.
        """
        origin = self.ages.get(mint)
        if origin is None:
            return None
        return int(max((now - origin).total_seconds(), 0))


async def resolve_token_context(
    session: AsyncSession, mints: Sequence[str], *, now: datetime
) -> TokenContext:
    """Resolve a whole page in three queries, never one per row."""
    unique = list(dict.fromkeys(mints))
    if not unique:
        return TokenContext.empty()

    tokens = await TokenRepository(session).get_many_by_mints(unique)
    market_repository = MarketSnapshotRepository(session)
    markets = await market_repository.latest_for_mints(unique)
    prior_prices = await market_repository.price_as_of_for_mints(
        unique, as_of=now - CHANGE_WINDOW
    )
    return TokenContext(
        names={mint: (token.name, token.symbol) for mint, token in tokens.items()},
        markets=markets,
        prior_prices=prior_prices,
        # `block_time` is when the mint existed; `discovered_at` is when we
        # first saw it. The first is the truthful age and the second is the
        # honest fallback — never the moment the row was written.
        ages={
            mint: (token.block_time or token.discovered_at) for mint, token in tokens.items()
        },
    )


def market_strip(
    snapshot: TokenMarketSnapshot | None, *, prior_price: Decimal | None
) -> MarketStripOut | None:
    """Render the market strip, or `None` when the token has never been priced.

    The 24-hour change is omitted rather than zeroed when there is no reading
    from far enough back — a token four minutes old has not been flat for a
    day, it simply did not exist.
    """
    if snapshot is None:
        return None

    change: Decimal | None = None
    price = snapshot.price_usd
    if price is not None and price > 0 and prior_price is not None and prior_price > 0:
        change = ((price - prior_price) / prior_price * 100).quantize(Decimal("0.01"))

    return MarketStripOut(
        price_usd=price,
        market_cap=snapshot.market_cap,
        liquidity_usd=snapshot.liquidity_usd,
        volume_24h=snapshot.volume_24h,
        change_24h_pct=change,
        captured_at=snapshot.captured_at,
        dex_name=snapshot.dex_name,
    )
