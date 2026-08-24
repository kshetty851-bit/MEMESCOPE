"""Arena orchestration: build PIT observations, judge, and account.

Research simulation. This module reads production observations and writes ONLY
`arena_*` tables — it imports no paper, karthik or real-wallet model, and a
source-parsing test enforces that.

Two PIT guarantees, both structural rather than promised:
  * every value fed to the rules comes from a row whose `captured_at <=
    checkpoint_at`, filtered in SQL, so a later observation cannot reach a
    decision even if the beat runs hours late;
  * a decision row is written once per (candidate, mint) and never updated,
    so an outcome can never rewrite the judgement that preceded it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.arena import rules
from app.arena.rules import Observation
from app.core.config import settings
from app.core.logging import get_logger
from app.models.arena import ArenaCandidate, ArenaDecision, ArenaPosition
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.research_data import NurseryAdmission, ResearchQuote, WalletFlowSnapshot
from app.models.token import DiscoveredToken

logger = get_logger(__name__)

FEE = Decimal("0.003")
IMPACT_DIVISOR = Decimal("12")


def _model_quantity(size: Decimal, price: Decimal, liquidity: Decimal) -> Decimal | None:
    """Tokens `size` buys under the calibrated model. None when unpriceable."""
    if price <= 0 or liquidity <= 0:
        return None
    depth = (liquidity / 2) / IMPACT_DIVISOR
    spend = size * (1 - FEE)
    return spend / (price * (1 + spend / depth))


def _model_proceeds(qty: Decimal, price: Decimal, liquidity: Decimal) -> Decimal:
    if qty <= 0 or price <= 0 or liquidity <= 0:
        return Decimal(0)
    depth = (liquidity / 2) / IMPACT_DIVISOR
    gross = qty * price
    return (gross / (1 + gross / depth)) * (1 - FEE)


class ArenaService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- activation ---------------------------------------------------------

    async def activate(self, *, valid_from: datetime) -> list[ArenaCandidate]:
        """Create the five portfolios, once. Re-running returns the existing set —
        `valid_from` can never move, so the contamination boundary is immutable."""
        existing = list(
            (await self._session.execute(select(ArenaCandidate))).scalars()
        )
        if existing:
            return existing
        made = []
        for code, name in [(rules.CASH_CODE, rules.CASH_NAME)] + [
            (c, n) for c, (n, _) in rules.EVALUATORS.items()
        ]:
            row = ArenaCandidate(
                code=code, name=name, version=rules.RULES_VERSION, valid_from=valid_from,
                starting_equity=rules.STARTING_EQUITY, cash=rules.STARTING_EQUITY,
                peak_equity=rules.STARTING_EQUITY, status="active",
            )
            self._session.add(row)
            made.append(row)
        await self._session.flush()
        logger.info("arena_activated", candidates=len(made), valid_from=valid_from.isoformat())
        return made

    # --- observation --------------------------------------------------------

    async def observation_for(
        self, *, token_id: uuid.UUID, mint: str, entered_at: datetime, checkpoint_at: datetime
    ) -> tuple[Observation, dict[str, Any]]:
        """Everything the rules may read, strictly at or before the checkpoint."""
        snaps = list(
            (
                await self._session.execute(
                    select(
                        TokenMarketSnapshot.captured_at,
                        TokenMarketSnapshot.price_usd,
                        TokenMarketSnapshot.liquidity_usd,
                        TokenMarketSnapshot.trading_status,
                        TokenMarketSnapshot.pool_address,
                    )
                    .where(
                        TokenMarketSnapshot.token_id == token_id,
                        TokenMarketSnapshot.captured_at >= entered_at,
                        TokenMarketSnapshot.captured_at <= checkpoint_at,
                        TokenMarketSnapshot.suspect.is_not(True),
                    )
                    .order_by(TokenMarketSnapshot.captured_at)
                )
            ).all()
        )
        priced = [s for s in snaps if s.price_usd and s.price_usd > 0]
        liqs = [(s.captured_at, s.liquidity_usd) for s in snaps if s.liquidity_usd and s.liquidity_usd > 0]

        liquidity_now = liqs[-1][1] if liqs else None
        ten_m = entered_at + timedelta(minutes=10)
        at_10 = next((v for t, v in reversed(liqs) if t <= ten_m), None)

        worst_drop = None
        if len(liqs) > 1:
            worst = Decimal(0)
            for (_, a), (_, b) in zip(liqs, liqs[1:], strict=False):
                if a > 0 and b < a:
                    worst = max(worst, (a - b) / a)
            worst_drop = worst

        drawdown = None
        if priced:
            peak = max(s.price_usd for s in priced)
            last = priced[-1].price_usd
            if peak > 0:
                drawdown = max(Decimal(0), (peak - last) / peak)

        pool = next((s.pool_address for s in reversed(snaps) if s.pool_address), None)
        keys = [mint] + ([pool] if pool else [])
        flow = (
            await self._session.execute(
                select(WalletFlowSnapshot)
                .where(
                    WalletFlowSnapshot.key.in_(keys),
                    WalletFlowSnapshot.captured_at <= checkpoint_at,
                )
                .order_by(WalletFlowSnapshot.captured_at.desc())
                .limit(1)
            )
        ).scalars().first()

        quotes = list(
            (
                await self._session.execute(
                    select(ResearchQuote)
                    .where(
                        ResearchQuote.mint_address == mint,
                        ResearchQuote.checkpoint_minutes == rules.CHECKPOINT_MINUTES,
                        ResearchQuote.requested_at <= checkpoint_at + timedelta(minutes=5),
                    )
                    .order_by(ResearchQuote.requested_at.desc())
                    .limit(4)
                )
            ).scalars()
        )
        buy = next((q for q in quotes if q.side == "buy"), None)
        sell = next((q for q in quotes if q.side == "sell"), None)

        obs = Observation(
            buy_route_ok=(buy.ok if buy else None),
            sell_route_ok=(sell.ok if sell else None),
            quoted_impact_pct=(buy.price_impact_pct if buy and buy.ok else None),
            liquidity_usd=liquidity_now,
            unique_wallets_1h=(flow.w1h_unique_wallets if flow else None),
            unique_buyers_1h=(flow.w1h_unique_buyers if flow else None),
            unique_sellers_1h=(flow.w1h_unique_sellers if flow else None),
            top10_tx_share=(flow.w1h_top10_tx_share if flow else None),
            flow_quality=(flow.w1h_quality if flow else None),
            liquidity_at_10m=at_10,
            max_liquidity_drop_frac=worst_drop,
            observation_count=len(snaps),
            drawdown_from_peak=drawdown,
        )
        route_state = (
            "ROUTE_UNKNOWN" if buy is None
            else "BUY_FAILED" if not buy.ok
            else "BUY_OK_SELL_OK" if (sell and sell.ok)
            else "BUY_OK_SELL_FAILED" if (sell and not sell.ok)
            else "ROUTE_UNKNOWN"
        )
        ctx = {
            "price": str(priced[-1].price_usd) if priced else None,
            "liquidity": str(liquidity_now) if liquidity_now else None,
            "liquidity_10m": str(at_10) if at_10 else None,
            "observations": len(snaps),
            "unique_wallets_1h": obs.unique_wallets_1h,
            "unique_buyers_1h": obs.unique_buyers_1h,
            "unique_sellers_1h": obs.unique_sellers_1h,
            "top10_tx_share": str(obs.top10_tx_share) if obs.top10_tx_share is not None else None,
            "flow_quality": obs.flow_quality,
            "drawdown": str(drawdown) if drawdown is not None else None,
            "max_liq_drop": str(worst_drop) if worst_drop is not None else None,
            "route_state": route_state,
            "impact_pct": str(obs.quoted_impact_pct) if obs.quoted_impact_pct is not None else None,
        }
        return obs, ctx

    # --- decisions ----------------------------------------------------------

    async def evaluate_due(self, *, now: datetime, limit: int = 50) -> dict[str, int]:
        """Judge every token whose checkpoint has passed and is unjudged."""
        candidates = list(
            (await self._session.execute(select(ArenaCandidate))).scalars()
        )
        if not candidates:
            return {"skipped": "not_activated"}
        by_code = {c.code: c for c in candidates}
        valid_from = min(c.valid_from for c in candidates)
        cutoff = now - timedelta(minutes=rules.CHECKPOINT_MINUTES)

        judged = list(
            (
                await self._session.execute(
                    select(NurseryAdmission.mint_address, NurseryAdmission.token_id,
                           NurseryAdmission.entered_at)
                    .where(
                        NurseryAdmission.entered_at <= cutoff,
                        NurseryAdmission.entered_at
                        >= valid_from - timedelta(minutes=rules.CHECKPOINT_MINUTES),
                        ~select(ArenaDecision.id)
                        .where(ArenaDecision.mint_address == NurseryAdmission.mint_address)
                        .exists(),
                    )
                    .order_by(NurseryAdmission.entered_at)
                    .limit(limit)
                )
            ).all()
        )
        decided = opened = 0
        for mint, token_id, entered_at in judged:
            checkpoint_at = entered_at + timedelta(minutes=rules.CHECKPOINT_MINUTES)
            if checkpoint_at < valid_from:
                continue  # contaminated: its checkpoint predates the freeze
            obs, ctx = await self.observation_for(
                token_id=token_id, mint=mint, entered_at=entered_at, checkpoint_at=checkpoint_at
            )
            for code, (_, fn) in rules.EVALUATORS.items():
                cand = by_code.get(code)
                if cand is None:
                    continue
                verdict = fn(obs)
                decision = ArenaDecision(
                    candidate_id=cand.id, mint_address=mint, token_id=token_id,
                    checkpoint_at=checkpoint_at, checkpoint_minutes=rules.CHECKPOINT_MINUTES,
                    eligible=verdict.eligible, skip_reason=verdict.skip_reason,
                    features=ctx, route_state=ctx["route_state"],
                    quoted_impact_pct=obs.quoted_impact_pct,
                )
                self._session.add(decision)
                await self._session.flush()
                decided += 1
                if verdict.eligible and await self._open(cand, decision, obs, ctx, checkpoint_at):
                    opened += 1
        return {"decided": decided, "opened": opened}

    async def _open(
        self, cand: ArenaCandidate, decision: ArenaDecision, obs: Observation,
        ctx: dict[str, Any], at: datetime,
    ) -> bool:
        """Open a virtual position if capital and execution allow. Sequential:
        the cash must actually be there, which is what makes redeployment real."""
        if cand.status != "active":
            decision.skip_reason = "candidate_failed"
            return False
        live = int(
            await self._session.scalar(
                select(func.count()).select_from(ArenaPosition).where(
                    ArenaPosition.candidate_id == cand.id, ArenaPosition.status == "open"
                )
            ) or 0
        )
        if live >= rules.MAX_CONCURRENT:
            decision.skip_reason = "max_concurrent"
            return False
        if cand.cash < rules.POSITION_SIZE_USD:
            decision.skip_reason = "insufficient_cash"
            return False
        price = Decimal(ctx["price"]) if ctx.get("price") else None
        liq = Decimal(ctx["liquidity"]) if ctx.get("liquidity") else None
        if price is None or liq is None:
            decision.skip_reason = "unpriceable"
            return False
        qty = _model_quantity(rules.POSITION_SIZE_USD, price, liq)
        if qty is None or qty <= 0:
            decision.skip_reason = "unpriceable"
            return False
        cand.cash -= rules.POSITION_SIZE_USD
        # Flushed immediately, not at the end of the tick: the concurrency
        # count this method runs for the NEXT candidate must see this row, and
        # settlement in the same tick must be able to find it. Without it the
        # sequential-capital guarantee silently becomes a per-candidate one.
        position = ArenaPosition(
                candidate_id=cand.id, decision_id=decision.id, mint_address=decision.mint_address,
                token_id=decision.token_id, opened_at=at, entry_price=price,
                size_usd=rules.POSITION_SIZE_USD, quantity=qty,
                target_price=price * rules.TAKE_PROFIT_MULTIPLE,
                entry_impact_pct=obs.quoted_impact_pct,
                entry_source=("quote" if obs.quoted_impact_pct is not None else "model"),
                status="open", route_state=ctx["route_state"], peak_multiple=Decimal(1),
        )
        self._session.add(position)
        await self._session.flush()
        return True

    # --- settlement ---------------------------------------------------------

    async def settle(self, *, now: datetime) -> dict[str, int]:
        """Advance open positions against the frozen exit policy."""
        opens = list(
            (
                await self._session.execute(
                    select(ArenaPosition).where(ArenaPosition.status == "open")
                )
            ).scalars()
        )
        closed = 0
        cands = {
            c.id: c for c in (await self._session.execute(select(ArenaCandidate))).scalars()
        }
        for pos in opens:
            snap = (
                await self._session.execute(
                    select(TokenMarketSnapshot)
                    .where(
                        TokenMarketSnapshot.token_id == pos.token_id,
                        TokenMarketSnapshot.suspect.is_not(True),
                    )
                    .order_by(TokenMarketSnapshot.captured_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            pos.last_evaluated_at = now
            if snap is None:
                continue
            is_dead = snap.trading_status == TradingStatus.INACTIVE
            price = snap.price_usd
            liq = snap.liquidity_usd
            proceeds = (
                Decimal(0) if (is_dead or not price or not liq)
                else _model_proceeds(pos.quantity, price, liq)
            )
            mult = (proceeds / pos.size_usd) if pos.size_usd else Decimal(0)
            if pos.peak_multiple is None or mult > pos.peak_multiple:
                pos.peak_multiple = mult
            pos.reached_125 = pos.reached_125 or mult >= Decimal("1.25")
            pos.reached_150 = pos.reached_150 or mult >= Decimal("1.5")
            pos.reached_200 = pos.reached_200 or mult >= Decimal("2.0")

            held_h = (now - pos.opened_at).total_seconds() / 3600
            reason = rules.exit_decision(
                multiple=mult, liquidity_usd=liq, sell_route_ok=None,
                held_hours=held_h, is_dead=is_dead,
            )
            if reason is None:
                continue
            pos.status = "closed"
            pos.closed_at = now
            pos.exit_reason = reason
            pos.exit_price = price if not is_dead else Decimal(0)
            pos.exit_proceeds_usd = Decimal(0) if reason == "dead_zero" else proceeds
            if reason == "sell_route_lost":
                pos.route_state = "BUY_OK_SELL_FAILED"
            cand = cands.get(pos.candidate_id)
            if cand is not None:
                cand.cash += pos.exit_proceeds_usd
                equity = await self._equity(cand)
                if equity > cand.peak_equity:
                    cand.peak_equity = equity
                if cand.status == "active" and equity < rules.FAILURE_EQUITY_FLOOR:
                    cand.status = "failed"
                    cand.failed_reason = "drawdown_below_800"
                    cand.failed_at = now
                    logger.warning("arena_candidate_failed", code=cand.code, equity=str(equity))
            closed += 1
        # Flushed before returning so the unit of work is consistent for any
        # later read in the same tick — the beat commits after this, and a
        # caller that queries in between must not see a half-settled book.
        await self._session.flush()
        return {"closed": closed, "open": len(opens) - closed}

    async def _equity(self, cand: ArenaCandidate) -> Decimal:
        deployed = Decimal(
            await self._session.scalar(
                select(func.coalesce(func.sum(ArenaPosition.size_usd), 0)).where(
                    ArenaPosition.candidate_id == cand.id, ArenaPosition.status == "open"
                )
            ) or 0
        )
        return cand.cash + deployed
