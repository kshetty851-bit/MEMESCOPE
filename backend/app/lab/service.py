"""V6 Strategy Lab orchestration: one scanner, one observation, twenty judges.

Research simulation. This module reads production observations and writes ONLY
`lab_*` tables — it imports no paper, karthik or real-wallet model, and a
source-parsing test enforces that.

**One authoritative scanner.** The admission stream is `radar_tokens`, and the
market history is the common `token_market_snapshots` series every other
subsystem already reads. For each (token, checkpoint) the observation is built
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
from app.models.radar import RadarToken
from app.models.research_data import ResearchQuote, WalletFlowSnapshot

logger = get_logger(__name__)

SNAPSHOT_HOURS = 24


def _frac_change(now: Decimal | None, then: Decimal | None) -> Decimal | None:
    if now is None or then is None or then <= 0:
        return None
    return now / then - 1


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
        f["liq"] = last.liquidity_usd if last.liquidity_usd and last.liquidity_usd > 0 else None
        f["mcap"] = last.market_cap if last.market_cap and last.market_cap > 0 else None
        f["vol1h"] = last.volume_1h
        if f["liq"] is not None and f["mcap"]:
            f["liq_mcap"] = f["liq"] / f["mcap"]
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
        by_checkpoint: dict[int, list[LabStrategy]] = {}
        for row in strategies:
            if row.checkpoint_minutes is None:
                continue
            by_checkpoint.setdefault(row.checkpoint_minutes, []).append(row)

        decided = opened = 0
        for minutes, rows in sorted(by_checkpoint.items()):
            cutoff = now - timedelta(minutes=minutes)
            ids = [r.id for r in rows]
            due = list((await self._session.execute(
                select(RadarToken.token_id, RadarToken.mint_address,
                       RadarToken.first_detected_at)
                .where(
                    RadarToken.first_detected_at <= cutoff,
                    # Only tokens whose checkpoint falls at or after the freeze
                    # are V6 forward evidence; everything earlier is history
                    # this program has already inspected (mission §15).
                    RadarToken.first_detected_at >= tournament.valid_from
                    - timedelta(minutes=minutes),
                    ~select(LabDecision.id).where(
                        LabDecision.mint_address == RadarToken.mint_address,
                        LabDecision.strategy_row_id.in_(ids),
                    ).exists(),
                )
                .order_by(RadarToken.first_detected_at)
                .limit(limit)
            )).all())

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
        multiplier = sizing.growth_multiplier(await self.equity(row), base=row.starting_equity)
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
        """This registry's strategy rows, and only these.

        Two tournaments now share these tables — V7 and the Compound Lab — so a
        query for "every strategy" is a query for someone else's as well.
        `settle` and `record_equity` both did exactly that, and the failure it
        would have caused is not subtle: `settle` looks its strategy up with
        `self._spec.BY_ID[pos.strategy_id]`, so the first Compound position
        would have raised KeyError inside V7's tick and STOPPED the running
        tournament.
        """
        return list((await self._session.execute(
            select(LabStrategy).where(
                LabStrategy.spec_hash == self._spec.SPEC_HASH
            )
        )).scalars())

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
            s = self._spec.BY_ID[pos.strategy_id]
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
            return Decimal(0), Decimal(0), True, None

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
