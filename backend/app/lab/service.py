"""V6 Strategy Lab orchestration: one scanner, one observation, twenty judges.

Research simulation. This module reads production observations and writes ONLY
`lab_*` tables — it imports no paper, karthik or real-wallet model, and a
source-parsing test enforces that.

**One authoritative observation.** The admission stream is `radar_tokens` for
every registry that does not say otherwise; a registry may set
`CANDIDATE_SOURCE = "graduations"` to be admitted from `pumpfun_graduations`
instead (see `_due_candidates`). The market history is the common
`token_market_snapshots` series every other subsystem already reads, whichever
stream admitted the coin — so the observation and both PIT guarantees below are
identical for either source. For each (token, checkpoint) the observation is built
ONCE and handed to every strategy that acts at that checkpoint — twenty
strategies, never twenty scanners and never twenty provider calls.

Two PIT guarantees, structural rather than promised:
  * every value fed to a rule comes from a row whose `captured_at <=
    checkpoint_at`, filtered in SQL, so a later observation cannot reach a
    decision even when the beat runs late;
  * a decision row is written once per (strategy, mint) and never updated, so
    an outcome can never rewrite the judgement that preceded it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.lab import execution, sellability, spec
from app.lab.rules import MarkState, evaluate_entry, evaluate_exit
from app import sizing
from app.lab.spec import STARTING_EQUITY, Strategy
from app.models.lab import (
    LabDecision,
    LabEquityPoint,
    LabPosition,
    LabStrategy,
    LabTournament,
)
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.graduation import PumpfunGraduation
from app.models.radar import RadarToken
from app.models.social import PumpfunSocialSnapshot
from app.models.early_buyer import TokenEarlyBuyer
from app.models.kol import KolWalletRank
from app.models.token import DiscoveredToken
from app.universe import rules as universe_rules
from app.models.research_data import ResearchQuote, WalletFlowSnapshot

logger = get_logger(__name__)

SNAPSHOT_HOURS = 24


def _frac_change(now: Decimal | None, then: Decimal | None) -> Decimal | None:
    if now is None or then is None or then <= 0:
        return None
    return now / then - 1


def live_print(rows, now: datetime):
    """The most recent TRADING print inside the confirmation window, or None.

    Pure and module-level so the death rule can be tested without a database:
    it is the only irreversible exit the engine has, and it wrote off $337 of
    live positions in a week before it was corroborated.

    `rows` are newest-first, as `_mark` selects them.
    """
    for r in rows:
        if now - r.captured_at > DEATH_CONFIRMATION_WINDOW:
            return None          # ordered, so nothing later can be in window
        if r.trading_status != TradingStatus.INACTIVE and r.price_usd \
                and r.price_usd > 0:
            return r
    return None


#: How long a token must read INACTIVE, with no live print at all, before the
#: engine will call it dead. Death is the only irreversible exit, so it is the
#: only one that requires more than a single observation.
DEATH_CONFIRMATION_WINDOW = timedelta(minutes=2)


class LabService:
    """The tournament engine, over whichever frozen registry it is handed.

    `registry` defaults to the V7 spec, so every existing caller is unchanged.
    It exists because a SECOND tournament (the Compound Lab) needs the same
    execution model, marking, settling and accounting over a different set of
    rules — and the alternative was a parallel copy of this file, which would
    drift from it the first time either was fixed.

    A registry supplies `SPEC_VERSION`, `SPEC_HASH`, `STRATEGIES`, `BY_ID` and
    `FAILURE_EQUITY_FLOOR`. Nothing here may reach `app.lab.spec` directly, or
    the second tournament silently scores itself against the first one's rules.
    """

    def __init__(self, session: AsyncSession, registry: Any = spec) -> None:
        self._session = session
        self._spec = registry

    # --- activation ---------------------------------------------------------

    async def activate(self, *, valid_from: datetime) -> LabTournament:
        """Create the tournament and its twenty portfolios, once.

        Re-running returns what exists: `valid_from` can never move, so the
        contamination boundary and the 24-hour timer are immutable across
        restarts (mission §15).
        """
        existing = (
            await self._session.execute(
                select(LabTournament).where(LabTournament.spec_version == self._spec.SPEC_VERSION)
            )
        ).scalars().first()
        if existing is not None:
            return existing

        tournament = LabTournament(
            spec_version=self._spec.SPEC_VERSION, spec_hash=self._spec.SPEC_HASH,
            valid_from=valid_from,
            snapshot_at=valid_from + timedelta(hours=SNAPSHOT_HOURS),
            status="active",
            protocol_note=("V6_FORWARD_TOURNAMENT_PROTOCOL.md — frozen before scoring. "
                           "Paper/research only; real money disabled."),
        )
        self._session.add(tournament)
        await self._session.flush()

        for s in self._spec.STRATEGIES:
            self._session.add(LabStrategy(
                tournament_id=tournament.id, strategy_id=s.id, name=s.name,
                version=self._spec.SPEC_VERSION, spec_hash=self._spec.SPEC_HASH,
                checkpoint_minutes=s.checkpoint_minutes, size_usd=s.size_usd,
                max_concurrent=s.max_concurrent, max_exposure_usd=s.max_exposure_usd,
                rules=_rules_json(s), starting_equity=STARTING_EQUITY,
                cash=STARTING_EQUITY, peak_equity=STARTING_EQUITY, status="active",
            ))
        await self._session.flush()
        logger.info("lab_activated", strategies=len(self._spec.STRATEGIES),
                    valid_from=valid_from.isoformat(), spec_hash=self._spec.SPEC_HASH)
        return tournament

    # --- observation --------------------------------------------------------

    async def observe(
        self, *, token_id: uuid.UUID, mint: str, detected_at: datetime,
        checkpoint_at: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Every feature any V6 rule may read, strictly at or before the checkpoint.

        Built once per (token, checkpoint) and shared by all strategies acting
        there. Returns (features, context) — context carries provenance and the
        route state for the ledger.
        """
        rows = list((await self._session.execute(
            select(
                TokenMarketSnapshot.id, TokenMarketSnapshot.captured_at,
                TokenMarketSnapshot.price_usd, TokenMarketSnapshot.liquidity_usd,
                TokenMarketSnapshot.market_cap, TokenMarketSnapshot.volume_1h,
                TokenMarketSnapshot.volume_5m, TokenMarketSnapshot.buy_count_24h,
                TokenMarketSnapshot.sell_count_24h, TokenMarketSnapshot.trading_status,
                TokenMarketSnapshot.pool_address,
            )
            .where(
                TokenMarketSnapshot.token_id == token_id,
                TokenMarketSnapshot.captured_at >= detected_at - timedelta(minutes=5),
                TokenMarketSnapshot.captured_at <= checkpoint_at,
                TokenMarketSnapshot.suspect.is_not(True),
            )
            .order_by(TokenMarketSnapshot.captured_at)
        )).all())
        if not rows:
            return {}, {"reason": "no_observations", "route_state": "ROUTE_UNKNOWN"}

        last = rows[-1]
        priced = [r for r in rows if r.price_usd and r.price_usd > 0]
        # A glitch print never becomes a feature: the same 10-minute x3 band the
        # execution model applies to fills also applies to what the rules read.
        median = execution.rolling_median(
            [(r.captured_at, r.price_usd) for r in priced], checkpoint_at
        )
        if priced and execution.off_band(priced[-1].price_usd, median):
            priced = [r for r in priced if not execution.off_band(r.price_usd, median)]

        def at_or_before(minutes_back: int):
            cut = checkpoint_at - timedelta(minutes=minutes_back)
            return next((r for r in reversed(rows) if r.captured_at <= cut), None)

        prev15 = at_or_before(15)
        prev5 = at_or_before(5)
        prev10 = at_or_before(10)

        f: dict[str, Any] = {}
        # PROVENANCE as a feature, so a registry can require it in its entry
        # rules rather than the engine deciding for everyone. 1 when the token
        # was discovered on pump.fun's bonding curve or on PumpSwap, which is
        # pump.fun's own AMM for pools that never touch the curve — both are
        # pump.fun. `jupiter_verified` and anything else is 0.
        #
        # Additive: SPEC_HASH is taken over the STRATEGIES, not over the feature
        # builder, so adding a key here cannot drift a running tournament.
        f["is_pumpfun"] = Decimal(1) if await self._is_pumpfun(token_id) else Decimal(0)
        # SOCIAL: attention rather than price. Every other feature here is
        # derived from the market; these two come from how many people are
        # commenting on the coin, which is orthogonal to all of them.
        seen, velocity = await self._social(mint)
        f["social_seen"] = Decimal(1) if seen else Decimal(0)
        if velocity is not None:
            f["social_reply_velocity"] = velocity
        # KOL: was a followed wallet among this coin's first buyers?
        #
        # Reads the FROZEN ranking (`kol_wallet_ranks`), never a live one — a
        # ranking recomputed at decision time would include the very trades
        # being judged. Zero when no ranking exists, so a registry that asks
        # for this simply never fires until one has been taken, which is the
        # correct behaviour rather than a silent pass.
        f["kol_early"] = Decimal(await self._kol_early_count(mint))
        f["liq"] = last.liquidity_usd if last.liquidity_usd and last.liquidity_usd > 0 else None
        f["mcap"] = last.market_cap if last.market_cap and last.market_cap > 0 else None
        f["vol1h"] = last.volume_1h
        if f["liq"] is not None and f["mcap"]:
            f["liq_mcap"] = f["liq"] / f["mcap"]
        # TURNOVER: five-minute volume against the liquidity backing it.
        #
        # Measured 2026-09-09 over 4,130 tokens: read in the five minutes
        # BEFORE the outcome window, tokens that later doubled sat at 0.63 and
        # tokens that did not at 0.11. Volume alone does not separate them —
        # the movers traded ~2.8x as much on HALF the liquidity, so it is the
        # ratio that carries the signal, not either term.
        #
        # It behaves as a THRESHOLD, not a ranking: below ~0.02 roughly 15%
        # went on to double, above it roughly 40%, and flat and non-monotonic
        # across every decile above. Do not read a bigger number as a better
        # token; the honest use is a floor.
        if f["liq"] is not None and last.volume_5m is not None:
            f["turnover_5m"] = Decimal(last.volume_5m) / f["liq"]
        if prev15 is not None:
            f["liqchg_15m"] = _frac_change(f["liq"], prev15.liquidity_usd)
            if priced and prev15.price_usd:
                f["ret_15m"] = _frac_change(priced[-1].price_usd, prev15.price_usd)
            db = _delta(last.buy_count_24h, prev15.buy_count_24h)
            ds = _delta(last.sell_count_24h, prev15.sell_count_24h)
            if db is not None and ds is not None and (db + ds) > 0:
                f["sell_share_15m"] = Decimal(ds) / Decimal(db + ds)
                f["tx_15m"] = db + ds
        if prev5 is not None and prev10 is not None and last.volume_5m and prev5.volume_5m:
            f["vol_accel"] = _frac_change(last.volume_5m, prev5.volume_5m)
        if priced:
            peak = max(r.price_usd for r in priced)
            if peak > 0:
                f["dd_from_peak_det"] = priced[-1].price_usd / peak - 1
            f["price"] = priced[-1].price_usd

        # --- wallet flow: the table is keyed by POOL, so resolve mint -> pool
        pool = next((r.pool_address for r in reversed(rows) if r.pool_address), None)
        keys = [k for k in (pool, mint) if k]
        flow = None
        if keys:
            flow = (await self._session.execute(
                select(WalletFlowSnapshot)
                .where(WalletFlowSnapshot.key.in_(keys),
                       WalletFlowSnapshot.captured_at <= checkpoint_at)
                .order_by(WalletFlowSnapshot.captured_at.desc())
                .limit(1)
            )).scalars().first()
        if flow is not None:
            f["w1h_unique_wallets"] = flow.w1h_unique_wallets
            f["w1h_unique_buyers"] = flow.w1h_unique_buyers
            f["w1h_unique_sellers"] = flow.w1h_unique_sellers
            f["w1h_top10_tx_share"] = flow.w1h_top10_tx_share
            f["flow_quality"] = flow.w1h_quality

        # --- route: a real two-sided Jupiter quote, or UNKNOWN. Never assumed.
        quotes = list((await self._session.execute(
            select(ResearchQuote)
            .where(ResearchQuote.mint_address == mint,
                   ResearchQuote.requested_at <= checkpoint_at + timedelta(minutes=5))
            .order_by(ResearchQuote.requested_at.desc())
            .limit(6)
        )).scalars())
        buy = next((q for q in quotes if q.side == "buy"), None)
        sell = next((q for q in quotes if q.side == "sell"), None)
        if buy is not None:
            f["buy_route_ok"] = bool(buy.ok)
            if buy.ok and buy.price_impact_pct is not None:
                f["buy_impact_pct"] = buy.price_impact_pct
        if sell is not None:
            f["sell_route_ok"] = bool(sell.ok)
        route_state = (
            "ROUTE_UNKNOWN" if buy is None
            else "BUY_FAILED" if not buy.ok
            else "BUY_OK_SELL_OK" if (sell and sell.ok)
            else "BUY_OK_SELL_FAILED" if (sell and not sell.ok)
            else "ROUTE_UNKNOWN"
        )

        ctx = {
            "route_state": route_state,
            "observations": len(rows),
            "pool_address": pool,
            "flow_key": (pool if (flow and pool and flow.key == pool) else
                         (mint if flow else None)),
            "flow_source": (flow.key_kind if flow else None),
            "trading_status": str(last.trading_status),
            "median_10m": str(median) if median is not None else None,
            "snapshot_first_id": str(rows[0].id),
            "snapshot_last_id": str(last.id),
            "snapshot_last_at": last.captured_at.isoformat(),
        }
        return f, ctx

    # --- decisions ----------------------------------------------------------

    def _source_for(self, strategy_id: str) -> str:
        """Which admission stream this ARM reads.

        A registry may hold arms on different populations — the point of the
        pump.swap arm is to sit beside the graduation arms on one board — so the
        source is resolved per strategy, falling back to the registry's own
        `CANDIDATE_SOURCE` and then to radar.

        Deliberately a registry-level MAPPING rather than a field on `Strategy`:
        that dataclass is shared by eight registries and `asdict` puts every
        field into the canonical JSON, so a new field with a null default would
        change the hash of all of them and halt every live tournament at once.
        """
        by_id = getattr(self._spec, "SOURCE_BY_STRATEGY", {}) or {}
        return by_id.get(strategy_id) or getattr(
            self._spec, "CANDIDATE_SOURCE", "radar"
        )

    async def _due_candidates(
        self, tournament: LabTournament, *, minutes: int, ids: list,
        cutoff: datetime, limit: int, source: str | None = None,
        now: datetime | None = None,
    ) -> list:
        """The (token_id, mint, detected_at) triples due at this checkpoint.

        Radar is the default and every registry that predates this reads it, so
        nothing changes for them. A registry may set

            CANDIDATE_SOURCE = "graduations"

        to draw from the pump.fun graduation cohort instead, or "pumpswap" for
        pump.swap markets newly reaching tradeable depth. The graduation source
        exists because
        a hypothesis taken FROM the graduation study was being tested on radar's
        population: only 3.6% of the tokens the Compound Lab judged had ever
        graduated, so the lab was answering a question about a different set of
        coins than the one its number came from.

        Both branches apply the same two bounds. `<= cutoff` is the checkpoint
        having arrived. `>= valid_from - minutes` keeps this forward evidence:
        a coin whose checkpoint fell before the tournament was frozen is history
        this program has already inspected (mission §15), and admitting it would
        let a known outcome in through the back door.
        """
        source = source or getattr(self._spec, "CANDIDATE_SOURCE", "radar")
        floor = tournament.valid_from - timedelta(minutes=minutes)

        # A token is judged ONCE per arm, for ever — that is what makes a
        # decision row a permanent record rather than a running opinion. A
        # rolling CONTROL cannot work under that rule: it samples a fixed
        # universe and would exhaust it in one burst.
        #
        # So a cooldown is keyed BY SOURCE, not by registry. A graduation is a
        # one-time event and re-drawing it six hours later would buy a stale
        # launch; a random established token has no event at all and is meant
        # to be re-drawn. Registry-wide, this switch would have quietly given
        # the graduation arms the control's behaviour.
        cooldown = (getattr(self._spec, "REJUDGE_BY_SOURCE", {}) or {}).get(source)

        def not_judged(mint_col):
            clauses = [LabDecision.mint_address == mint_col,
                       LabDecision.strategy_row_id.in_(ids)]
            if cooldown is not None:
                clauses.append(
                    LabDecision.decided_at >= (now or cutoff) - cooldown)
            return ~select(LabDecision.id).where(*clauses).exists()

        if source == "graduations":
            # Joined to DiscoveredToken because the engine keys everything on
            # token_id; a graduation we have never discovered has no market
            # series to observe and so cannot be judged at all.
            q = (
                select(DiscoveredToken.id, PumpfunGraduation.mint_address,
                       PumpfunGraduation.first_seen_complete_at)
                .join(DiscoveredToken,
                      DiscoveredToken.mint_address == PumpfunGraduation.mint_address)
                .where(
                    PumpfunGraduation.first_seen_complete_at <= cutoff,
                    PumpfunGraduation.first_seen_complete_at >= floor,
                    not_judged(PumpfunGraduation.mint_address),
                )
                .order_by(PumpfunGraduation.first_seen_complete_at)
                .limit(limit)
            )
        elif source == "pumpswap":
            # NEWLY LIQUID pump.swap markets that are not fresh graduations.
            #
            # A different question from the graduation arms: those ask what a
            # coin does in the minutes after its curve completes, this asks what
            # one does when it first becomes a market deep enough to trade. The
            # populations overlap by construction — a graduation lands on
            # pump.swap — so recent graduates are excluded rather than counted
            # twice, and what is left is the ~19/hour that reach depth without
            # having just graduated (457 of 731 crossings in a measured day).
            #
            # "Newly" is load-bearing. Without the `prior` clause every token
            # already above the floor would be admitted at activation, and the
            # arm would open fifty arbitrary established positions in its first
            # minute and then go quiet — a one-off snapshot of the universe
            # wearing a strategy's clothes. The clause asks for the FIRST time
            # this token was ever seen at depth.
            floor_usd = getattr(self._spec, "LIQUIDITY_FLOOR", Decimal("100000"))
            prior = aliased(TokenMarketSnapshot)
            q = (
                select(TokenMarketSnapshot.token_id, DiscoveredToken.mint_address,
                       TokenMarketSnapshot.captured_at)
                .distinct(TokenMarketSnapshot.token_id)
                .join(DiscoveredToken,
                      DiscoveredToken.id == TokenMarketSnapshot.token_id)
                .where(
                    TokenMarketSnapshot.suspect.is_not(True),
                    TokenMarketSnapshot.dex_name == "pumpswap",
                    TokenMarketSnapshot.liquidity_usd >= floor_usd,
                    TokenMarketSnapshot.captured_at <= cutoff,
                    TokenMarketSnapshot.captured_at >= floor,
                    ~select(prior.id).where(
                        prior.token_id == TokenMarketSnapshot.token_id,
                        prior.suspect.is_not(True),
                        prior.liquidity_usd >= floor_usd,
                        prior.captured_at < floor,
                    ).exists(),
                    ~select(PumpfunGraduation.id).where(
                        PumpfunGraduation.mint_address == DiscoveredToken.mint_address,
                        PumpfunGraduation.first_seen_complete_at
                        >= TokenMarketSnapshot.captured_at - timedelta(hours=2),
                    ).exists(),
                    not_judged(DiscoveredToken.mint_address),
                )
                .order_by(TokenMarketSnapshot.token_id,
                          TokenMarketSnapshot.captured_at)
                .limit(limit)
            )
        elif source == "deepamm":
            # A ROLLING BASELINE over the deep AMMs, not a strategy.
            #
            # Raydium, Orca, Meteora and MetaDAO carry $1.3m-$3.6m of median
            # depth but almost no EVENTS: of 157 tokens at $100k depth in a
            # measured day, FOUR had newly arrived. An event-driven arm there
            # would take four trades a day, and admitting the other 153 at once
            # would buy a whole universe inside one hour — 157 draws of a single
            # market condition, which reads like a sample and is not one.
            #
            # So this samples: a few tokens per tick, re-drawable after
            # `REJUDGE_AFTER`, spreading draws across conditions indefinitely.
            # It answers "what does a random established token do in five
            # minutes", which is the question the graduation arms must beat.
            # `ORDER BY random()` is the point rather than an oversight.
            floor_usd = getattr(self._spec, "LIQUIDITY_FLOOR", Decimal("100000"))
            per_tick = min(limit, getattr(self._spec, "SAMPLE_PER_TICK", 1))
            venues = list(getattr(
                self._spec, "DEEP_VENUES",
                ("raydium", "orca", "meteora", "metadao"),
            ))
            # A baseline of "established tokens" must be established tokens the
            # other arms could plausibly have traded — NOT the index. Sampling
            # the raw venue list drew USDC and JTO on the first attempt, and a
            # stablecoin held five minutes returns zero with no variance, which
            # would flatter the baseline into meaninglessness.
            #
            # Both bounds are the universe wallet's own, imported rather than
            # restated so there is one definition of "on a peg" and one of
            # "effectively an index" on this platform.
            peg_clauses = [
                func.abs(TokenMarketSnapshot.price_usd - lvl) / lvl
                > universe_rules.PEG_TOLERANCE
                for lvl in universe_rules.PEG_LEVELS
            ]
            newest = (
                select(TokenMarketSnapshot.token_id,
                       DiscoveredToken.mint_address,
                       TokenMarketSnapshot.captured_at)
                .distinct(TokenMarketSnapshot.token_id)
                .join(DiscoveredToken,
                      DiscoveredToken.id == TokenMarketSnapshot.token_id)
                .where(
                    TokenMarketSnapshot.suspect.is_not(True),
                    TokenMarketSnapshot.dex_name.in_(venues),
                    TokenMarketSnapshot.liquidity_usd >= floor_usd,
                    TokenMarketSnapshot.liquidity_usd
                    <= universe_rules.MAX_LIQUIDITY_USD,
                    TokenMarketSnapshot.price_usd.is_not(None),
                    TokenMarketSnapshot.price_usd > 0,
                    *peg_clauses,
                    TokenMarketSnapshot.captured_at <= cutoff,
                    TokenMarketSnapshot.captured_at >= floor,
                    not_judged(DiscoveredToken.mint_address),
                )
                .order_by(TokenMarketSnapshot.token_id,
                          TokenMarketSnapshot.captured_at.desc())
                .subquery()
            )
            q = select(newest).order_by(func.random()).limit(per_tick)
        elif source == "radar":
            q = (
                select(RadarToken.token_id, RadarToken.mint_address,
                       RadarToken.first_detected_at)
                .where(
                    RadarToken.first_detected_at <= cutoff,
                    RadarToken.first_detected_at >= floor,
                    not_judged(RadarToken.mint_address),
                )
                .order_by(RadarToken.first_detected_at)
                .limit(limit)
            )
        else:
            # Loud, because a typo here would silently trade nothing at all and
            # look identical to a quiet market.
            raise ValueError(f"unknown CANDIDATE_SOURCE {source!r}")

        return list((await self._session.execute(q)).all())

    async def evaluate_due(self, *, now: datetime, limit: int = 120) -> dict[str, Any]:
        """Judge every (token, checkpoint) that is due and unjudged.

        Grouped by checkpoint so the shared observation is built once and read
        by every strategy acting there.
        """
        tournament = (await self._session.execute(
            select(LabTournament).where(LabTournament.spec_version == self._spec.SPEC_VERSION)
        )).scalars().first()
        if tournament is None:
            return {"skipped": "not_activated"}
        if tournament.spec_hash != self._spec.SPEC_HASH:
            logger.error("lab_spec_hash_drift", stored=tournament.spec_hash,
                         current=self._spec.SPEC_HASH)
            return {"halted": "spec_hash_drift"}

        strategies = list((await self._session.execute(
            select(LabStrategy).where(LabStrategy.tournament_id == tournament.id)
        )).scalars())
        # Grouped by (checkpoint, SOURCE): the observation is built once and
        # shared by every strategy acting there, and two arms reading different
        # admission streams are not looking at the same tokens, so they cannot
        # share one.
        by_group: dict[tuple[int, str], list[LabStrategy]] = {}
        for row in strategies:
            if row.checkpoint_minutes is None:
                continue
            key = (row.checkpoint_minutes, self._source_for(row.strategy_id))
            by_group.setdefault(key, []).append(row)

        decided = opened = 0
        for (minutes, source), rows in sorted(by_group.items()):
            cutoff = now - timedelta(minutes=minutes)
            ids = [r.id for r in rows]
            due = await self._due_candidates(
                tournament, minutes=minutes, ids=ids, cutoff=cutoff,
                limit=limit, source=source, now=now,
            )

            for token_id, mint, detected_at in due:
                checkpoint_at = detected_at + timedelta(minutes=minutes)
                if checkpoint_at < tournament.valid_from:
                    continue
                features, ctx = await self.observe(
                    token_id=token_id, mint=mint,
                    detected_at=detected_at, checkpoint_at=checkpoint_at,
                )
                for row in rows:
                    s = self._spec.BY_ID[row.strategy_id]
                    verdict = evaluate_entry(s, features)
                    decision = LabDecision(
                        strategy_row_id=row.id, strategy_id=row.strategy_id,
                        mint_address=mint, token_id=token_id,
                        checkpoint_at=checkpoint_at, checkpoint_minutes=minutes,
                        decided_at=now, eligible=verdict.eligible,
                        skip_reason=verdict.skip_reason,
                        features=_jsonable(features), snapshot_ids=ctx,
                        route_state=ctx.get("route_state"),
                        quoted_impact_pct=features.get("buy_impact_pct"),
                        requested_size_usd=row.size_usd,
                    )
                    self._session.add(decision)
                    await self._session.flush()
                    decided += 1
                    if verdict.eligible and await self._open(
                        row, s, decision, features, ctx, checkpoint_at
                    ):
                        opened += 1
        return {"decided": decided, "opened": opened}

    async def _open(
        self, row: LabStrategy, s: Strategy, decision: LabDecision,
        features: dict[str, Any], ctx: dict[str, Any], at: datetime,
    ) -> bool:
        """Open a virtual position if capital, concurrency and exposure allow.

        Sequential capital: the cash must actually be there. That is what makes
        redeployment real rather than free, and it is the mechanism behind the
        opportunity-cost inversion V4/V5/V6 all measured.
        """
        if row.status != "active":
            decision.skip_reason = "candidate_failed"
            return False
        live, deployed = await self._open_book(row)
        if live >= row.max_concurrent:
            decision.skip_reason = "max_concurrent"
            return False

        # --- GROWTH LADDER -------------------------------------------------
        # The stake rises with the portfolio: base size until $200, twice that
        # from $200, four times from $400 (see `app.sizing`). Derived here from
        # live equity rather than written back onto the row, so the frozen spec
        # figure stays readable next to what was actually staked.
        #
        # The exposure ceiling is scaled by the same factor deliberately. It is
        # denominated in dollars, so leaving it fixed while the stake doubles
        # would quietly halve how many positions the strategy can hold at once
        # — a change to its diversification that nobody asked for, arriving as
        # a side effect of a sizing rule.
        # A registry may opt OUT of the ladder entirely with SIZING_SCALES =
        # False, and the Five-Minute Lab does. Default True, so every registry
        # that has not heard of this keeps the behaviour it has today.
        #
        # It exists because the wallet ratchet is ALREADY a compounding effect:
        # each cycle's base is the last cycle's target. Letting the stake also
        # double at 2x equity runs two of them at once and makes a result
        # unattributable to either — the same argument the Compound spec makes
        # for refusing a per-position take-profit beside a wallet target.
        # Three modes, and a registry says which. "linear" stakes a fixed
        # FRACTION of the wallet — $10 at $100, $20 at $200, $30 at $300,
        # capped — where the default ladder jumps 1x/2x/4x at powers of two
        # and would stake $20 on that same $300 wallet.
        mode = getattr(self._spec, "SIZING_MODE", None)
        if mode == "linear":
            multiplier = sizing.linear_multiplier(
                await self.equity(row), base=row.starting_equity,
                cap_multiple=Decimal(getattr(self._spec, "SIZING_CAP_MULTIPLE", 10)),
            )
        elif getattr(self._spec, "SIZING_SCALES", True):
            multiplier = sizing.growth_multiplier(
                await self.equity(row), base=row.starting_equity
            )
        else:
            multiplier = Decimal(1)
        size_usd = row.size_usd * multiplier
        max_exposure_usd = row.max_exposure_usd * multiplier
        # The decision row was written with the spec's base size before this
        # ran. Correct it to what the ladder actually asked for, so the record
        # of the request and the position that follows it cannot disagree.
        decision.requested_size_usd = size_usd

        if deployed + size_usd > max_exposure_usd:
            decision.skip_reason = "max_exposure"
            return False
        if row.cash < size_usd:
            decision.skip_reason = "insufficient_cash"
            return False
        price, liq = features.get("price"), features.get("liq")
        if price is None or liq is None:
            decision.skip_reason = "unpriceable"
            return False
        qty = execution.buy_quantity(size_usd, price, liq)
        if qty is None or qty <= 0:
            decision.skip_reason = "unpriceable"
            return False

        row.cash -= size_usd
        # Flushed immediately, not at the end of the tick: the concurrency and
        # exposure counts for the NEXT strategy must see this row, and any
        # settlement in the same tick must be able to find it.
        self._session.add(LabPosition(
            strategy_row_id=row.id, strategy_id=row.strategy_id, decision_id=decision.id,
            mint_address=decision.mint_address, token_id=decision.token_id,
            opened_at=at, entry_price=price, entry_liquidity_usd=liq,
            size_usd=size_usd, quantity=qty, quantity_remaining=qty,
            banked_proceeds_usd=Decimal(0),
            entry_impact_pct=features.get("buy_impact_pct"),
            entry_source=("quote" if features.get("buy_impact_pct") is not None else "model"),
            status="open", peak_exec_multiple=Decimal(1),
            route_state=ctx.get("route_state"),
        ))
        await self._session.flush()
        return True

    async def _open_book(self, row: LabStrategy) -> tuple[int, Decimal]:
        got = (await self._session.execute(
            select(func.count(), func.coalesce(func.sum(LabPosition.size_usd), 0))
            .where(LabPosition.strategy_row_id == row.id, LabPosition.status == "open")
        )).one()
        return int(got[0] or 0), Decimal(got[1] or 0)

    async def _my_strategy_rows(self) -> list[LabStrategy]:
        """This registry's strategy rows — every VERSION of them, not just the live one.

        Two tournaments share these tables, so a query for "every strategy" is a
        query for someone else's as well. `settle` looks its strategy up in
        `self._spec.BY_ID`, so the first Compound position inside V7's tick would
        raise KeyError and STOP the running tournament. That is the failure this
        scope exists to prevent and it still does.

        **But scoping on `spec_hash` was too tight, and the way it failed was
        silent.** A version bump changes the hash, so the moment a registry ships
        a new spec its PREVIOUS tournament stops matching — and with it stops
        being settled, marked, or re-quoted (`sellability.refresh` filters on
        `LIVE_SPEC_VERSIONS`, which moves too). An open position in a superseded
        book can then never be marked, never exited, and cannot even reach its
        time exit, because that fires in `settle`. INC-056 by another road: a
        position the platform will not re-price is a position it cannot sell.
        It very nearly stranded a live 4.8x.

        Scoping on `strategy_id` instead follows the registry across its own
        versions. Ids are globally unique and prefix-namespaced — V7-, CMP-,
        MOM-, DPT-, CPY-, SOC- — and `test_strategy_ids_are_globally_unique`
        holds that true, which is what keeps a foreign row out.

        A SUPERSEDED book is only settled while its frozen exits still match the
        ones this spec would apply. `settle` reads `s.exits` from the live
        registry, so winding down an old book under new rules would quietly
        break the guarantee the whole platform rests on — that a tournament's
        result followed the rules frozen at its start. When they differ the row
        is skipped and said out loud: that book needs a person, not a default.
        """
        rows = list((await self._session.execute(
            select(LabStrategy).where(
                LabStrategy.strategy_id.in_(list(self._spec.BY_ID))
            )
        )).scalars())

        mine: list[LabStrategy] = []
        for row in rows:
            if row.spec_hash == self._spec.SPEC_HASH:
                mine.append(row)
                continue
            frozen = (row.rules or {}).get("exits")
            live = _rules_json(self._spec.BY_ID[row.strategy_id]).get("exits")
            if frozen == live:
                mine.append(row)
            else:
                logger.warning(
                    "lab_superseded_exits_moved", strategy=row.strategy_id,
                    row_spec_hash=row.spec_hash, live_spec_hash=self._spec.SPEC_HASH,
                    detail="superseded book left unsettled: its frozen exits differ "
                           "from the live registry's, and settling it under the new "
                           "rules would misreport it",
                )
        return mine

    # --- settlement ---------------------------------------------------------

    async def settle(self, *, now: datetime) -> dict[str, int]:
        """Mark every open position and fire whichever frozen exit applies."""
        mine = await self._my_strategy_rows()
        rows = {r.id: r for r in mine}
        if not rows:
            return {"closed": 0, "partials": 0, "stale": 0, "open": 0}
        opens = list((await self._session.execute(
            select(LabPosition).where(
                LabPosition.status == "open",
                LabPosition.strategy_row_id.in_(list(rows)),
            )
        )).scalars())
        closed = partials = stale = 0

        for pos in opens:
            row = rows.get(pos.strategy_row_id)
            if row is None:
                continue
            s = self._spec.BY_ID.get(pos.strategy_id)
            if s is None:
                # Unreachable while ids stay unique — and a raw subscript here
                # is what stops a whole tournament ticking, so it fails soft.
                logger.warning("lab_settle_unknown_strategy",
                               strategy=pos.strategy_id, position=str(pos.id))
                continue
            mark = await self._mark(pos, now)
            pos.last_evaluated_at = now
            if mark is None:
                stale += 1
                continue
            price, liq, is_dead, sell_ok = mark

            gross = execution.sell_proceeds(pos.quantity, price, liq) if not is_dead \
                else Decimal(0)
            exec_mult = (gross / pos.size_usd) if pos.size_usd else Decimal(0)
            held_open = execution.sell_proceeds(pos.quantity_remaining, price, liq) \
                if not is_dead else Decimal(0)

            if exec_mult > pos.peak_exec_multiple:
                pos.peak_exec_multiple = exec_mult
            pos.last_exec_multiple = exec_mult
            pos.last_open_value_usd = pos.banked_proceeds_usd + held_open
            pos.reached_125 = pos.reached_125 or exec_mult >= Decimal("1.25")
            pos.reached_150 = pos.reached_150 or exec_mult >= Decimal("1.5")
            pos.reached_200 = pos.reached_200 or exec_mult >= Decimal("2.0")
            if s.exits.break_even_arm is not None and exec_mult >= s.exits.break_even_arm:
                pos.break_even_armed = True
            if abs(exec_mult - 1) > Decimal("0.05"):
                pos.flat_since = None
            elif pos.flat_since is None:
                pos.flat_since = now

            held_hours = (now - pos.opened_at).total_seconds() / 3600
            flat_hours = ((now - pos.flat_since).total_seconds() / 3600) \
                if pos.flat_since else 0.0
            verdict = evaluate_exit(s.exits, MarkState(
                exec_multiple=exec_mult, peak_exec_multiple=pos.peak_exec_multiple,
                held_hours=held_hours, liquidity_usd=liq,
                entry_liquidity_usd=pos.entry_liquidity_usd, is_dead=is_dead,
                sell_route_ok=sell_ok, break_even_armed=pos.break_even_armed,
                partial_done=pos.partial_done, flat_hours=flat_hours,
            ))
            if verdict.action is None:
                continue

            if verdict.action == "PARTIAL":
                sell_qty = pos.quantity_remaining * (s.exits.partial_fraction or Decimal("0.5"))
                fill = execution.capped_fill_price(price, pos.entry_price,
                                                   verdict.trigger_multiple)
                got = execution.sell_proceeds(sell_qty, fill, liq)
                pos.banked_proceeds_usd += got
                pos.quantity_remaining -= sell_qty
                pos.partial_done = True
                pos.partial_at = now
                row.cash += got
                partials += 1
                continue

            if is_dead:
                proceeds = pos.banked_proceeds_usd  # the remaining stake is worth $0
                pos.exit_price = Decimal(0)
            else:
                fill = execution.capped_fill_price(price, pos.entry_price,
                                                   verdict.trigger_multiple)
                proceeds = pos.banked_proceeds_usd + execution.sell_proceeds(
                    pos.quantity_remaining, fill, liq
                )
                pos.exit_price = fill
            pos.status = "closed"
            pos.closed_at = now
            pos.exit_reason = verdict.reason
            pos.exit_proceeds_usd = proceeds
            pos.last_open_value_usd = Decimal(0)
            if verdict.reason == "sell_route_lost":
                pos.route_state = "BUY_OK_SELL_FAILED"
            row.cash += proceeds - pos.banked_proceeds_usd
            closed += 1
            await self._apply_breaker(row, now)

        await self._session.flush()
        return {"closed": closed, "partials": partials, "stale": stale,
                "open": len(opens) - closed}

    #: The one exit a person can cause. Named so it can never be mistaken for a
    #: rule the tournament followed.
    MANUAL_EXIT_REASON = "manual_close"

    async def close_manually(
        self, *, position_id: uuid.UUID, now: datetime, actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Close one open position by hand, at the price the market will bear.

        **This is the only way a position leaves the book without a frozen rule
        firing, and it is why the exit is tagged rather than blended in.** The
        tournament's whole claim is that every result followed the registry; a
        hand-closed position did not, so it is labelled at the point of exit and
        counted separately wherever the record is read. Silently recording it as
        an ordinary exit would make the leaderboard a number nobody can cite.

        The FILL is deliberately not a favour. It goes through `_mark` and the
        shared execution model — the same stale guard, the same glitch band, the
        same impact against real depth — so selling by hand cannot invent a
        price the strategies themselves could never have got. An unmarkable
        position is refused rather than closed at its last healthy print, which
        is the same answer `settle` gives.
        """
        pos = (await self._session.execute(
            select(LabPosition).where(LabPosition.id == position_id)
        )).scalars().first()
        if pos is None:
            return {"closed": False, "reason": "not_found"}
        if pos.status != "open":
            # Not an error worth raising: two clicks on the same row, or a
            # settle that won the race, both land here and both are fine.
            return {"closed": False, "reason": "already_closed",
                    "exit_reason": pos.exit_reason}

        row = (await self._session.execute(
            select(LabStrategy).where(LabStrategy.id == pos.strategy_row_id)
        )).scalars().first()
        if row is None:
            return {"closed": False, "reason": "strategy_missing"}

        mark = await self._mark(pos, now)
        if mark is None:
            return {"closed": False, "reason": "unmarkable"}
        price, liq, is_dead, _sell_ok = mark

        if is_dead:
            proceeds = pos.banked_proceeds_usd
            pos.exit_price = Decimal(0)
        else:
            # No `capped_fill_price` here: that cap exists to stop a LEVEL exit
            # claiming it filled at its trigger. A manual sell has no trigger —
            # it takes the marked price and the impact that comes with it.
            proceeds = pos.banked_proceeds_usd + execution.sell_proceeds(
                pos.quantity_remaining, price, liq
            )
            pos.exit_price = price

        pos.status = "closed"
        pos.closed_at = now
        # `reason` lets the Compound Lab's wallet target reuse this exact fill
        # path while recording WHY the position left the book. A cycle close is
        # not a hand sell and must not be counted as one.
        pos.exit_reason = reason or self.MANUAL_EXIT_REASON
        pos.exit_proceeds_usd = proceeds
        pos.last_open_value_usd = Decimal(0)
        row.cash += proceeds - pos.banked_proceeds_usd
        await self._session.flush()

        logger.warning("lab_position_closed_by_hand", position=str(pos.id),
                       strategy=pos.strategy_id, mint=pos.mint_address,
                       actor=actor, proceeds=str(proceeds))
        return {"closed": True, "strategy_id": pos.strategy_id,
                "mint": pos.mint_address, "proceeds_usd": proceeds,
                "pnl_usd": proceeds - pos.size_usd,
                "exit_reason": pos.exit_reason}

    async def trim_manually(
        self, *, position_id: uuid.UUID, now: datetime, fraction: Decimal,
        actor: str,
    ) -> dict[str, Any]:
        """Sell part of an open position by hand, banking the proceeds.

        The scale-out counterpart to `close_manually`, and it exists because a
        copy lab has to mirror a leader who sells in tranches. Closing the whole
        book on his first trim exits while he is still holding, which biases the
        record against exactly the position that runs.

        Same fill discipline as `close_manually`: `_mark`, the stale guard, the
        glitch band, impact against real depth. No `capped_fill_price`, because
        there is no trigger to cap against.

        **`partial_done` and `partial_at` are deliberately NOT set.** Those
        belong to the frozen `partial_at` exit rule; a hand trim did not follow
        the registry, and marking it as though it had would let a leaderboard
        claim a rule fired that never did. The caller's own ledger is where a
        trim is recorded.
        """
        if fraction <= 0 or fraction >= 1:
            return {"trimmed": False, "reason": "fraction_out_of_range"}

        pos = (await self._session.execute(
            select(LabPosition).where(LabPosition.id == position_id)
        )).scalars().first()
        if pos is None:
            return {"trimmed": False, "reason": "not_found"}
        if pos.status != "open":
            return {"trimmed": False, "reason": "already_closed"}

        row = (await self._session.execute(
            select(LabStrategy).where(LabStrategy.id == pos.strategy_row_id)
        )).scalars().first()
        if row is None:
            return {"trimmed": False, "reason": "strategy_missing"}

        mark = await self._mark(pos, now)
        if mark is None:
            return {"trimmed": False, "reason": "unmarkable"}
        price, liq, is_dead, _sell_ok = mark
        if is_dead:
            # Nothing to bank and nothing to sell into. `settle` will close it
            # at zero on its own terms; a trim must not pretend otherwise.
            return {"trimmed": False, "reason": "dead"}

        sell_qty = pos.quantity_remaining * fraction
        if sell_qty <= 0:
            return {"trimmed": False, "reason": "nothing_left"}
        got = execution.sell_proceeds(sell_qty, price, liq)
        pos.banked_proceeds_usd += got
        pos.quantity_remaining -= sell_qty
        row.cash += got
        await self._session.flush()

        logger.info("lab_position_trimmed", position=str(pos.id),
                    strategy=pos.strategy_id, mint=pos.mint_address,
                    actor=actor, fraction=str(fraction), proceeds=str(got))
        return {"trimmed": True, "proceeds_usd": got,
                "quantity_remaining": pos.quantity_remaining}

    #: pump.fun's bonding curve, and PumpSwap — its own AMM for direct pool
    #: launches. `SCANNER_WATCH_PROGRAMS` is the same pair the scanner listens
    #: to, so this cannot drift from what discovery actually admitted.
    @staticmethod
    def _pumpfun_programs() -> set[str]:
        from app.core.config import settings

        return set(settings.SCANNER_WATCH_PROGRAMS)

    async def _is_pumpfun(self, token_id) -> bool:
        """Was this token discovered on pump.fun?

        Read from `discovered_tokens.source_program`, which records the program
        that emitted the launch — the fact at discovery, not a guess from the
        pool it trades in now.
        """
        src = await self._session.scalar(
            select(DiscoveredToken.source_program)
            .where(DiscoveredToken.id == token_id)
        )
        return bool(src) and src in self._pumpfun_programs()

    async def _kol_early_count(self, mint: str) -> int:
        """How many FOLLOWED wallets were among this coin's first buyers.

        Scoped to this registry's own `spec_version`, so two KOL tournaments
        with different frozen rankings cannot read each other's wallets — the
        same scoping bug that once let one lab settle another's book.
        """
        version = getattr(self._spec, "SPEC_VERSION", None)
        if not version:
            return 0
        return int(await self._session.scalar(
            select(func.count())
            .select_from(TokenEarlyBuyer)
            .join(KolWalletRank,
                  KolWalletRank.wallet_address == TokenEarlyBuyer.wallet_address)
            .where(TokenEarlyBuyer.mint_address == mint,
                   KolWalletRank.spec_version == version)
        ) or 0)

    async def _social(self, mint: str) -> tuple[bool, Decimal | None]:
        """(seen in the social feed, replies per hour) for this mint.

        Velocity needs TWO readings and returns None until there are two, so a
        rule that requires it simply does not fire rather than firing on a
        guess. That is deliberate: `reply_count` is cumulative, so a single
        reading measures a coin's AGE as much as its interest, and acting on
        one would rediscover survivorship.

        The two most recent readings, not the first and last: a coin's comment
        rate now is the question, and averaging over its whole life would blur
        a burst into the weeks around it.
        """
        rows = list((await self._session.execute(
            select(PumpfunSocialSnapshot.reply_count,
                   PumpfunSocialSnapshot.observed_at)
            .where(PumpfunSocialSnapshot.mint_address == mint,
                   PumpfunSocialSnapshot.reply_count.is_not(None))
            .order_by(PumpfunSocialSnapshot.observed_at.desc())
            .limit(2)
        )).all())
        if not rows:
            return False, None
        if len(rows) < 2:
            return True, None
        (new_count, new_at), (old_count, old_at) = rows
        hours = Decimal(str((new_at - old_at).total_seconds() / 3600))
        if hours <= 0:
            return True, None
        return True, (Decimal(new_count) - Decimal(old_count)) / hours

    async def _mark(
        self, pos: LabPosition, now: datetime
    ) -> tuple[Decimal, Decimal, bool, bool | None] | None:
        """Latest tradeable print, or None when nothing may be acted on.

        Applies the stale guard and the glitch band: a print older than 15
        minutes, or more than 3x off the 10-minute median, is not a market you
        can trade against, and holding is the honest response to not knowing.
        """
        rows = list((await self._session.execute(
            select(TokenMarketSnapshot.captured_at, TokenMarketSnapshot.price_usd,
                   TokenMarketSnapshot.liquidity_usd, TokenMarketSnapshot.trading_status)
            .where(TokenMarketSnapshot.token_id == pos.token_id,
                   TokenMarketSnapshot.suspect.is_not(True))
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .limit(40)
        )).all())
        if not rows:
            return None
        latest = rows[0]
        if latest.trading_status == TradingStatus.INACTIVE:
            # ONE inactive reading is not a death, and treating it as one cost
            # real money. Measured over seven days and 806 `dead_zero` exits,
            # 56 of them — 6.9% — were written off at $0.00 while the token was
            # trading again within ten minutes at more than half the entry
            # price: $337 of stake booked as total losses on positions actually
            # worth $860. One was closed at zero seventeen seconds before the
            # same token printed 7.4% ABOVE its entry.
            #
            # The provider drops to `inactive` for a poll or two — a pool
            # re-index, a missed round — and the old code took the first such
            # reading as final and irreversible. Death is the one exit that
            # cannot be revised, so it is the one that must be corroborated.
            #
            # A live print inside the window is used to mark AGAINST, not merely
            # to veto the death: skipping the tick would leave the position
            # unmarked on the very cycle a good price existed.
            #
            # Bounded by TIME rather than by a count of readings, deliberately.
            # "Two consecutive inactives" never confirms for a token that stops
            # being polled at all, and that is precisely how this lab once froze
            # its worst positions at their last healthy price and held them for
            # ever. A genuinely dead pool has no live print and closes here,
            # about two minutes later than before.
            live = live_print(rows, now)
            if live is None:
                return Decimal(0), Decimal(0), True, None
            latest = live

        # A fresh SELL QUOTE outranks a fresh snapshot, and is consulted before
        # the staleness guard rather than after it.
        #
        # This guard was skipping 162 of 224 open positions every tick — 72% of
        # the book — and the skip is self-selecting in the worst possible way: a
        # dying token stops being enriched, so its snapshot goes stale, so it is
        # never marked and never evaluated for an exit again. The Lab froze its
        # worst positions at their last healthy price and held them for ever,
        # which is precisely what Karthik found by hand.
        #
        # Staleness is a statement about the SNAPSHOT, not about the market. If
        # someone asked Jupiter within the last few minutes, the answer is
        # current evidence whatever the snapshot's age.
        realisable = await sellability.realisable_price(
            self._session, pos.mint_address, now=now
        )
        stale = execution.is_stale(latest.captured_at, now)
        if realisable is not None:
            worth = realisable * pos.quantity_remaining
            if worth <= pos.size_usd * sellability.DEAD_FRACTION:
                return realisable, Decimal(0), True, None
            if stale:
                # No usable snapshot, but a real quote: price from the quote and
                # carry the last observed liquidity, which only the opt-in
                # liquidity exits read and which the quote already reflects.
                return (realisable, Decimal(str(latest.liquidity_usd or 0)),
                        False, True)
        if stale:
            return None
        if not latest.price_usd or latest.price_usd <= 0 or not latest.liquidity_usd \
                or latest.liquidity_usd <= 0:
            return None
        median = execution.rolling_median(
            [(r.captured_at, r.price_usd) for r in rows if r.price_usd and r.price_usd > 0],
            latest.captured_at,
        )
        if execution.off_band(latest.price_usd, median):
            return None
        sell_ok = await self._session.scalar(
            select(ResearchQuote.ok)
            .where(ResearchQuote.mint_address == pos.mint_address,
                   ResearchQuote.side == "sell")
            .order_by(ResearchQuote.requested_at.desc()).limit(1)
        )
        # Snapshot is usable. The quote can still LOWER the mark — it is taken at
        # the largest holder's size, so a smaller position would really fill
        # better, and crediting one with more than the model allows would be
        # inventing value rather than removing it.
        if realisable is not None and realisable < latest.price_usd:
            return realisable, latest.liquidity_usd, False, sell_ok
        return latest.price_usd, latest.liquidity_usd, False, sell_ok

    async def _apply_breaker(self, row: LabStrategy, now: datetime) -> None:
        equity = await self.equity(row)
        if equity > row.peak_equity:
            row.peak_equity = equity
        if row.status == "active" and equity < self._spec.FAILURE_EQUITY_FLOOR:
            row.status = "failed"
            row.failed_reason = "drawdown_below_800"
            row.failed_at = now
            logger.warning("lab_strategy_failed", strategy=row.strategy_id,
                           equity=str(equity))

    async def equity(self, row: LabStrategy) -> Decimal:
        """Cash plus EXECUTABLE open value — never cash plus deployed cost."""
        open_value = Decimal(await self._session.scalar(
            select(func.coalesce(func.sum(
                func.coalesce(LabPosition.last_open_value_usd, LabPosition.size_usd)
            ), 0)).where(LabPosition.strategy_row_id == row.id,
                         LabPosition.status == "open")
        ) or 0)
        return row.cash + open_value

    async def record_equity(self, *, now: datetime) -> int:
        rows = await self._my_strategy_rows()
        for row in rows:
            got = (await self._session.execute(
                select(func.count(),
                       func.coalesce(func.sum(LabPosition.size_usd), 0),
                       func.coalesce(func.sum(func.coalesce(
                           LabPosition.last_open_value_usd, LabPosition.size_usd)), 0))
                .where(LabPosition.strategy_row_id == row.id,
                       LabPosition.status == "open")
            )).one()
            n, cost, value = int(got[0] or 0), Decimal(got[1] or 0), Decimal(got[2] or 0)
            self._session.add(LabEquityPoint(
                strategy_row_id=row.id, strategy_id=row.strategy_id, captured_at=now,
                cash=row.cash, deployed_cost=cost, open_value=value,
                equity=row.cash + value, open_positions=n,
            ))
        await self._session.flush()
        return len(rows)


def _delta(now: int | None, then: int | None) -> int | None:
    """Counter difference, clamped at zero — the 24h counters tick backwards on
    a small fraction of rows and a negative trade count is not information."""
    if now is None or then is None:
        return None
    return max(0, int(now) - int(then))


def _jsonable(features: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in features.items()}


def _rules_json(s: Strategy) -> dict[str, Any]:
    return spec.rules_json(s)
