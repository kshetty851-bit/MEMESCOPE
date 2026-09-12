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
`token_security_evaluations` the safety verdict, and the LIQUIDITY_SECURITY
                             check's LP-custody reading, or nothing at all
`holder_snapshots`           top-10 holder concentration — **behind
                             FEATURE_RESEARCH_COLLECTORS_ENABLED, which
                             ships off**, so this is frequently absent

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
from app.models.research_data import HolderSnapshot, WalletFlowSnapshot
from app.models.token import DiscoveredToken
from app.models.token_security import TokenSecurityEvaluationRow

#: How far back a 15-minute change is measured from.
_CHANGE_WINDOW = timedelta(minutes=15)
#: The evaluator's own name for the on-chain LP-custody check. Pinned by
#: `test_lp_check_name_matches_the_platform` so a rename in the shared
#: contract breaks a test instead of silently returning `no_lp_check`.
_LP_CHECK = "LIQUIDITY_SECURITY"
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


@dataclass(frozen=True, slots=True)
class Mark:
    """One print, for a forward window. Not the engine's `Mark` — that one
    carries a decision's worth of derived state, this is three columns."""

    captured_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class EntryFeatures:
    """Holder concentration and LP custody as of one entry decision.

    Both facts are read from stores this platform already fills, at the
    decision instant, filtered `<= at` in SQL — so a collection that lands a
    second after the decision can never be read back into it. Neither field is
    fetched synchronously and neither can fail a trade: a silent store yields
    `None` and names itself in `error`, and the caller enters anyway.

    `error` exists because a bare `None` cannot be interpreted. "no row in the
    store" and "a row that measured this as null" are different facts about
    the platform, and an analysis that cannot tell them apart will read a
    collector being switched off as a population of tokens with no holders.
    """

    top10_holder_pct: Decimal | None
    #: When that snapshot was taken. The age at the decision is
    #: `opened_at - this`, which is the only form in which age is trustworthy:
    #: stored as an age it would silently be an age-at-write-time.
    top10_captured_at: datetime | None
    #: The LIQUIDITY_SECURITY check's status — PASS / FAIL / UNKNOWN /
    #: NOT_APPLICABLE, verbatim from the platform's evaluator.
    lp_status: str | None
    #: Why, when it is not PASS. `LP_OUTSTANDING` (a redeemable claim on the
    #: reserves exists) and `POOL_CUSTODY_OUT_OF_SCOPE` (this evaluator has
    #: nothing to say) are both UNKNOWN and mean opposite things, so the
    #: status alone cannot answer the question this instrument was added for.
    lp_reason_codes: list[str] | None
    lp_checked_at: datetime | None
    #: Comma-joined store names that had nothing to say. `None` when both
    #: answered.
    error: str | None


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

    async def candidates(self, *, since: datetime, not_before: datetime | None = None,
                         limit: int = 200) -> list[Candidate]:
        """Radar admissions the lab may still act on, NEWEST first.

        `since` is the lab's activation instant. An admission that predates it
        is never entered: the historical record has been inspected many times
        and trading it would be a backtest wearing a forward run's clothes.

        `not_before` is the freshness cutoff, and it is applied HERE rather than
        only in the caller. Both halves of that matter, and the first version
        got both wrong:

        * it ordered OLDEST first, so once more than `limit` admissions had
          accumulated the window froze over the oldest ones and never moved. The
          lab went blind after 200 admissions — every candidate it could see was
          by then hours old and rejected on age, while fresh ones it could have
          traded were never fetched. It stopped entering and looked idle rather
          than broken;
        * filtering for freshness only in the caller cannot fix that, because
          the rows are already lost to `LIMIT` by the time the caller sees them.

        Newest-first plus a SQL-side cutoff means the limit can only ever clip
        admissions that are already too old to trade.
        """
        # `symbol` lives on `discovered_tokens`, not on the Radar row, so it
        # is joined rather than assumed — an outer join, because a Radar
        # admission whose discovery row was pruned is still a candidate.
        rows = (await self._session.execute(
            select(RadarToken.token_id, RadarToken.mint_address,
                   DiscoveredToken.symbol, RadarToken.first_detected_at,
                   RadarToken.current_opportunity_score)
            .outerjoin(DiscoveredToken, DiscoveredToken.id == RadarToken.token_id)
            .where(RadarToken.first_detected_at > since,
                   *([RadarToken.first_detected_at >= not_before]
                     if not_before is not None else []))
            .order_by(RadarToken.first_detected_at.desc())
            .limit(limit)
        )).all()
        # Handed back oldest-first so entries are taken in the order they were
        # admitted; only the FETCH is newest-first.
        return [Candidate(r.token_id, r.mint_address, r.symbol,
                          r.first_detected_at, r.current_opportunity_score)
                for r in reversed(rows)]

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

    async def entry_features(self, *, mint: str, at: datetime) -> EntryFeatures:
        """The two entry features, point-in-time, or a named absence.

        No max-age filter, deliberately. A cut-off here would discard the
        reading and leave a null that looks like a token nobody measured; the
        timestamp is returned instead, so staleness is a column the analysis
        can threshold rather than a decision this module already made.
        """
        missing: list[str] = []

        holder = (await self._session.execute(
            select(HolderSnapshot.top10_pct, HolderSnapshot.captured_at)
            .where(HolderSnapshot.mint_address == mint,
                   HolderSnapshot.captured_at <= at,
                   HolderSnapshot.top10_pct.is_not(None))
            .order_by(HolderSnapshot.captured_at.desc())
            .limit(1)
        )).first()
        if holder is None:
            missing.append("no_holder_snapshot")

        status = codes = checked = None
        row = (await self._session.execute(
            select(TokenSecurityEvaluationRow.checks,
                   TokenSecurityEvaluationRow.evaluated_at)
            .where(TokenSecurityEvaluationRow.mint_address == mint,
                   TokenSecurityEvaluationRow.evaluated_at <= at)
            .order_by(TokenSecurityEvaluationRow.evaluated_at.desc())
            .limit(1)
        )).first()
        if row is None:
            missing.append("no_security_evaluation")
        else:
            checked = row.evaluated_at
            check = next((c for c in (row.checks or [])
                          if c.get("name") == _LP_CHECK), None)
            if check is None:
                # An evaluation that ran without this check is not the same as
                # no evaluation: the timestamp is kept so the gap is visible.
                missing.append("no_lp_check")
            else:
                status = str(check.get("status"))[:16]
                codes = [str(c) for c in (check.get("reason_codes") or [])]

        return EntryFeatures(
            top10_holder_pct=holder.top10_pct if holder is not None else None,
            top10_captured_at=holder.captured_at if holder is not None else None,
            lp_status=status, lp_reason_codes=codes, lp_checked_at=checked,
            error=",".join(missing) or None)

    async def forward_window(self, *, mint: str, after: datetime,
                             until: datetime) -> list[Mark]:
        """Every clean print in `(after, until]`, oldest first.

        Strictly open at the start, so a decision's own observation is never
        part of its forward return. `suspect` rows are excluded here exactly
        as they are for a live mark — a glitch print would otherwise become a
        token's recorded maximum.
        """
        rows = (await self._session.execute(
            select(TokenMarketSnapshot.captured_at, TokenMarketSnapshot.price_usd,
                   TokenMarketSnapshot.liquidity_usd)
            .where(TokenMarketSnapshot.mint_address == mint,
                   TokenMarketSnapshot.captured_at > after,
                   TokenMarketSnapshot.captured_at <= until,
                   TokenMarketSnapshot.suspect.is_not(True))
            .order_by(TokenMarketSnapshot.captured_at)
        )).all()
        return [Mark(captured_at=r.captured_at, price_usd=r.price_usd,
                     liquidity_usd=r.liquidity_usd) for r in rows]

    async def latest_marks(self, mints: set[str]) -> dict[str, tuple[Decimal, Decimal | None]]:
        """The freshest usable (price, liquidity) for each mint, or absent.

        `suspect` prints are excluded for the same reason the runner excludes
        them: a glitch is not a price, and an "if held" figure built on one
        would invent a recovery that never happened. A mint nothing has priced
        is simply missing from the mapping — the caller reports null, never
        zero, because "we cannot see it" and "it went to zero" are different
        claims and this project has already published one as the other.
        """
        if not mints:
            return {}
        rows = (await self._session.execute(
            select(TokenMarketSnapshot.mint_address, TokenMarketSnapshot.price_usd,
                   TokenMarketSnapshot.liquidity_usd)
            .where(TokenMarketSnapshot.mint_address.in_(mints),
                   TokenMarketSnapshot.price_usd.is_not(None),
                   TokenMarketSnapshot.price_usd > 0,
                   TokenMarketSnapshot.suspect.is_not(True))
            .order_by(TokenMarketSnapshot.mint_address,
                      TokenMarketSnapshot.captured_at.desc())
        )).all()
        out: dict[str, tuple[Decimal, Decimal | None]] = {}
        for mint, price, liquidity in rows:
            out.setdefault(mint, (price, liquidity))
        return out
