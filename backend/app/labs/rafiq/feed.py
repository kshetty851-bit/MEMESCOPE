"""READ-ONLY access to the shared token feed.

This is the ONLY module in the lab that knows a MEMESCOPE table exists, and
every statement it issues is a `SELECT`. There is no insert, no update, no
delete and no flush against a shared table anywhere below — a test parses this
file and fails if one appears.

WHAT IT READS, AND WHAT IT CANNOT
---------------------------------
`radar_tokens`               admissions, and the opportunity score the
                             strategies' `entry_threshold` compares against
`token_market_snapshots`     price, liquidity, market cap, 5-minute volume,
                             cumulative buy/sell counts, trading status
`wallet_flow_snapshots`      unique buyers and sellers, trade counts, top-10
                             concentration — **behind a flag that ships off**,
                             so these are frequently absent
`token_security_evaluations` the safety verdict, or nothing at all

There is no social source in this platform, so Strategy E's social stream is
permanently absent rather than assumed. Every field an `Observation` cannot
fill is `None`, and `None` never becomes a default further up.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.rafiq.adapters.safety import SafetyVerdict
from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarToken
from app.models.research_data import WalletFlowSnapshot
from app.models.token import DiscoveredToken
from app.models.token_security import TokenSecurityEvaluationRow

#: How far back a 15-minute change is measured from.
_CHANGE_WINDOW = timedelta(minutes=15)
#: A security evaluation older than this says nothing about now.
_SAFETY_MAX_AGE = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A Radar admission the lab may consider. Nothing is decided here."""

    token_id: uuid.UUID
    mint_address: str
    symbol: str | None
    detected_at: datetime
    opportunity_score: Decimal


@dataclass(frozen=True, slots=True)
class Observation:
    """One token's market at one instant, as far as the feed can see it.

    Every field is optional except the identity and the clock, because every
    one of them genuinely can be missing and a substituted value would be a
    number nobody measured.
    """

    mint_address: str
    observed_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    market_cap: Decimal | None
    volume_m5: Decimal | None
    liquidity_change_15m: Decimal | None
    #: 10-minute rolling median, for the glitch band. None under three prints.
    median_price_10m: Decimal | None
    #: Unique wallets over the hour. None whenever wallet flow is unavailable.
    buyers: int | None
    sellers: int | None
    #: Trade counts over the hour, from the same wallet-flow row.
    buys: int | None
    sells: int | None
    top10_tx_share: Decimal | None
    safety: SafetyVerdict | None
    safety_observed_at: datetime | None

    @property
    def is_priceable(self) -> bool:
        return self.price_usd is not None and self.price_usd > 0


def _median(values: list[Decimal]) -> Decimal | None:
    if len(values) < 3:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


class RafiqFeed:
    """Read-only view of the shared feed. Holds a session; mutates nothing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def candidates(self, *, since: datetime, limit: int = 200) -> list[Candidate]:
        """Radar admissions first detected after `since`, oldest first.

        `since` is the lab's activation instant. An admission that predates it
        is never entered: the historical record has been inspected many times
        and trading it would be a backtest wearing a forward run's clothes.
        """
        # `symbol` lives on `discovered_tokens`, not on the Radar row, so it
        # is joined rather than assumed — an outer join, because a Radar
        # admission whose discovery row was pruned is still a candidate.
        rows = (await self._session.execute(
            select(RadarToken.token_id, RadarToken.mint_address,
                   DiscoveredToken.symbol, RadarToken.first_detected_at,
                   RadarToken.current_opportunity_score)
            .outerjoin(DiscoveredToken, DiscoveredToken.id == RadarToken.token_id)
            .where(RadarToken.first_detected_at > since)
            .order_by(RadarToken.first_detected_at)
            .limit(limit)
        )).all()
        return [Candidate(r.token_id, r.mint_address, r.symbol,
                          r.first_detected_at, r.current_opportunity_score)
                for r in rows]

    async def observe(self, *, token_id: uuid.UUID, mint: str,
                      at: datetime) -> Observation | None:
        """The freshest market at or before `at`, or None if nothing priced it.

        Every row is filtered `captured_at <= at` in SQL, so a later
        observation cannot reach a decision even when the beat runs late.
        """
        rows = (await self._session.execute(
            select(TokenMarketSnapshot.captured_at, TokenMarketSnapshot.price_usd,
                   TokenMarketSnapshot.liquidity_usd, TokenMarketSnapshot.market_cap,
                   TokenMarketSnapshot.volume_5m, TokenMarketSnapshot.pool_address)
            .where(TokenMarketSnapshot.token_id == token_id,
                   TokenMarketSnapshot.captured_at <= at,
                   TokenMarketSnapshot.captured_at >= at - timedelta(hours=2),
                   TokenMarketSnapshot.suspect.is_not(True))
            .order_by(TokenMarketSnapshot.captured_at)
        )).all()
        if not rows:
            return None

        last = rows[-1]
        cut = at - _CHANGE_WINDOW
        prior = next((r for r in reversed(rows) if r.captured_at <= cut), None)
        change = None
        if prior is not None and prior.liquidity_usd and prior.liquidity_usd > 0 \
                and last.liquidity_usd is not None:
            change = last.liquidity_usd / prior.liquidity_usd - 1

        window = at - timedelta(minutes=10)
        median = _median([r.price_usd for r in rows
                          if r.captured_at >= window and r.price_usd and r.price_usd > 0])

        pool = next((r.pool_address for r in reversed(rows) if r.pool_address), None)
        flow = None
        keys = [k for k in (pool, mint) if k]
        if keys:
            flow = (await self._session.execute(
                select(WalletFlowSnapshot)
                .where(WalletFlowSnapshot.key.in_(keys),
                       WalletFlowSnapshot.captured_at <= at)
                .order_by(WalletFlowSnapshot.captured_at.desc())
                .limit(1)
            )).scalars().first()

        safety, safety_at = None, None
        row = (await self._session.execute(
            select(TokenSecurityEvaluationRow.overall_status,
                   TokenSecurityEvaluationRow.evaluated_at)
            .where(TokenSecurityEvaluationRow.mint_address == mint,
                   TokenSecurityEvaluationRow.evaluated_at <= at,
                   TokenSecurityEvaluationRow.evaluated_at >= at - _SAFETY_MAX_AGE)
            .order_by(TokenSecurityEvaluationRow.evaluated_at.desc())
            .limit(1)
        )).first()
        if row is not None:
            # `VERIFIED` is MEMESCOPE's pass state, and its own contract is
            # explicit that it "means every applicable check was actually
            # performed and passed — it is never reachable by silence". An
            # earlier version of this mapping looked for "PASSED", which the
            # platform never emits, so every verdict fell through to UNKNOWN
            # and Strategy E's mandatory safety stream could never confirm.
            # `test_safety_mapping_covers_the_real_enum` now pins these
            # spellings to the platform's enum, so a rename breaks a test
            # instead of silently switching E off.
            safety = {
                "VERIFIED": SafetyVerdict.PASSED, "FAILED": SafetyVerdict.FAILED,
            }.get(str(row.overall_status), SafetyVerdict.UNKNOWN)
            safety_at = row.evaluated_at

        return Observation(
            mint_address=mint,
            observed_at=last.captured_at,
            price_usd=last.price_usd if last.price_usd and last.price_usd > 0 else None,
            liquidity_usd=(last.liquidity_usd
                           if last.liquidity_usd and last.liquidity_usd > 0 else None),
            market_cap=last.market_cap if last.market_cap and last.market_cap > 0 else None,
            volume_m5=last.volume_5m,
            liquidity_change_15m=change,
            median_price_10m=median,
            buyers=flow.w1h_unique_buyers if flow else None,
            sellers=flow.w1h_unique_sellers if flow else None,
            buys=flow.w1h_buy_count if flow else None,
            sells=flow.w1h_sell_count if flow else None,
            top10_tx_share=flow.w1h_top10_tx_share if flow else None,
            safety=safety,
            safety_observed_at=safety_at,
        )

    async def token_id(self, mint: str) -> uuid.UUID | None:
        """The Radar's token id for a mint, or None if it never admitted one."""
        return (await self._session.execute(
            select(RadarToken.token_id).where(RadarToken.mint_address == mint)
        )).scalar_one_or_none()
