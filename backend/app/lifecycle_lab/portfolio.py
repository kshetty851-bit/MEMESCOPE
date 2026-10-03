"""Meme Lifecycle Lab — the paper portfolio ledger.

$1,000 starting capital, $10 per position, at most 5 open and $50 deployed
(``PortfolioConfig``). Paper only: there is no execution path anywhere in this
package, and ``domain.REAL_TRADING`` is ``False``.

Rules the ledger enforces, each with a recorded reason when it refuses:

* ``no_price`` — nothing to fill at. Never filled at an invented price.
* ``already_holding_mint`` — one open position per mint, whatever meme or arm
  asked for it, so one token cannot occupy several slots.
* ``max_open`` / ``max_deployed`` — capacity.
* ``insufficient_cash`` — the position *plus its entry costs* must be covered.

A refused entry is a ``Rejection`` row, never a silent drop: a strategy that
fires fifty times and fills five has a very different capacity profile from one
that fired five times.

Accounting (fees are cash, not a footnote):

* entry: ``cash -= size_usd + entry_fees_usd``; ``quantity = size_usd / price``
* exit:  ``cash += quantity * exit_price - exit_fees_usd``
* ``pnl = quantity * exit_price - exit_fees - size_usd - entry_fees``
* ``deployed`` = Σ ``size_usd`` of open positions (cost basis, ex-fees)
* ``equity`` = cash + Σ quantity * mark. ``None`` when any open position has
  no mark — a holding nobody priced is unmeasured, not worthless
  (``app/paper/metrics.py``, same philosophy).
* ``drawdown`` is measured from the running peak of *known* equity, as a
  fraction (0.12 = 12% below the peak).

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.lifecycle_lab.config import PortfolioConfig
from app.lifecycle_lab.domain import (
    AgeBucket,
    Arm,
    DivergenceCase,
    ExitReason,
    LifecycleState,
)
from app.lifecycle_lab.exits import ExitSignal, side_cost

_ZERO = Decimal(0)

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

REJECT_NO_PRICE = "no_price"
REJECT_ALREADY_HOLDING_MINT = "already_holding_mint"
REJECT_MAX_OPEN = "max_open"
REJECT_MAX_DEPLOYED = "max_deployed"
REJECT_INSUFFICIENT_CASH = "insufficient_cash"


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def trade_key(arm: Arm, mint_address: str, entry_at: datetime) -> str:
    """Deterministic identity: the same decision in the same replay is the
    same trade, so a re-run is comparable row for row."""
    raw = f"{arm.value}|{mint_address}|{entry_at.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PaperTrade:
    trade_key: str
    arm: Arm
    meme_id: str
    mint_address: str
    entry_at: datetime
    entry_price: Decimal
    size_usd: Decimal
    quantity: Decimal
    entry_fees_usd: Decimal
    entry_market_cap: Decimal | None
    entry_liquidity_usd: Decimal | None
    token_age_seconds: int | None
    age_bucket: AgeBucket
    lifecycle_state: LifecycleState
    divergence_case: DivergenceCase
    #: Stable reason code from the strategy; prose is rendered elsewhere.
    entry_reason: str
    entry_features: dict[str, Any]
    #: ``{"at": iso, "kind": code, "detail": JSON-safe}``, chronological. A
    #: tuple so a frozen trade cannot be edited in place; serialised as a list.
    evidence_timeline: tuple[dict[str, Any], ...]
    #: ``constant_product`` or ``flat`` (unknown depth at entry or exit).
    cost_model: str
    exit_at: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: ExitReason | None = None
    exit_fees_usd: Decimal | None = None
    pnl_usd: Decimal | None = None
    return_pct: Decimal | None = None
    status: str = STATUS_OPEN
    contains_backfill: bool = False
    hindsight: bool = False

    @property
    def cost_basis(self) -> Decimal:
        return self.size_usd + self.entry_fees_usd

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_key": self.trade_key,
            "arm": self.arm.value,
            "meme_id": self.meme_id,
            "mint_address": self.mint_address,
            "entry_at": self.entry_at.isoformat(),
            "entry_price": str(self.entry_price),
            "size_usd": str(self.size_usd),
            "quantity": str(self.quantity),
            "entry_fees_usd": str(self.entry_fees_usd),
            "entry_market_cap": _s(self.entry_market_cap),
            "entry_liquidity_usd": _s(self.entry_liquidity_usd),
            "token_age_seconds": self.token_age_seconds,
            "age_bucket": self.age_bucket.value,
            "lifecycle_state": self.lifecycle_state.value,
            "divergence_case": self.divergence_case.value,
            "entry_reason": self.entry_reason,
            "entry_features": self.entry_features,
            "evidence_timeline": list(self.evidence_timeline),
            "cost_model": self.cost_model,
            "exit_at": None if self.exit_at is None else self.exit_at.isoformat(),
            "exit_price": _s(self.exit_price),
            "exit_reason": None if self.exit_reason is None else self.exit_reason.value,
            "exit_fees_usd": _s(self.exit_fees_usd),
            "pnl_usd": _s(self.pnl_usd),
            "return_pct": _s(self.return_pct),
            "status": self.status,
            "contains_backfill": self.contains_backfill,
            "hindsight": self.hindsight,
        }


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    at: datetime
    #: ``None`` when any open position is unpriced.
    equity: Decimal | None
    cash: Decimal
    deployed: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    open_positions: int
    #: Running high of known equity (starts at starting capital).
    peak_equity: Decimal
    #: Fraction below ``peak_equity``; ``None`` when equity is unknown.
    drawdown: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "equity": _s(self.equity),
            "cash": str(self.cash),
            "deployed": str(self.deployed),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": _s(self.unrealized_pnl),
            "open_positions": self.open_positions,
            "peak_equity": str(self.peak_equity),
            "drawdown": _s(self.drawdown),
        }


@dataclass(frozen=True, slots=True)
class EntryRequest:
    """Everything known at the decision instant that the trade records."""

    at: datetime
    arm: Arm
    meme_id: str
    mint_address: str
    #: Latest market price visible at ``at``. ``None`` → ``no_price``.
    price: Decimal | None
    liquidity_usd: Decimal | None
    market_cap: Decimal | None
    token_age_seconds: int | None
    age_bucket: AgeBucket
    lifecycle_state: LifecycleState
    divergence_case: DivergenceCase
    entry_reason: str
    entry_features: dict[str, Any] = field(default_factory=dict)
    evidence_timeline: tuple[dict[str, Any], ...] = ()
    contains_backfill: bool = False
    hindsight: bool = False


@dataclass(frozen=True, slots=True)
class Rejection:
    at: datetime
    arm: Arm
    meme_id: str
    mint_address: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "arm": self.arm.value,
            "meme_id": self.meme_id,
            "mint_address": self.mint_address,
            "reason": self.reason,
            "detail": self.detail,
        }


class Portfolio:
    """A deterministic paper ledger. Mutable, but only through its methods."""

    def __init__(self, cfg: PortfolioConfig) -> None:
        self.cfg = cfg
        self.cash: Decimal = cfg.starting_capital
        self.realized_pnl: Decimal = _ZERO
        self.peak_equity: Decimal = cfg.starting_capital
        self._open: dict[str, PaperTrade] = {}
        self._open_by_mint: dict[str, str] = {}
        self.closed: list[PaperTrade] = []
        self.rejections: list[Rejection] = []

    # -- views ---------------------------------------------------------------

    @property
    def open_trades(self) -> tuple[PaperTrade, ...]:
        """Open positions in entry order (then key) — deterministic."""
        return tuple(sorted(self._open.values(), key=lambda t: (t.entry_at, t.trade_key)))

    @property
    def deployed(self) -> Decimal:
        return sum((t.size_usd for t in self._open.values()), _ZERO)

    def holds_mint(self, mint_address: str) -> bool:
        return mint_address in self._open_by_mint

    def get_open(self, key: str) -> PaperTrade | None:
        return self._open.get(key)

    # -- entry ---------------------------------------------------------------

    def _reject(self, req: EntryRequest, reason: str, **detail: Any) -> Rejection:
        rejection = Rejection(
            at=req.at,
            arm=req.arm,
            meme_id=req.meme_id,
            mint_address=req.mint_address,
            reason=reason,
            detail={k: (str(v) if isinstance(v, Decimal) else v) for k, v in detail.items()},
        )
        self.rejections.append(rejection)
        return rejection

    def try_open(self, req: EntryRequest) -> PaperTrade | Rejection:
        """Open a position, or record exactly why not. Checks run in a fixed
        order so the recorded reason is deterministic when several apply."""
        cfg = self.cfg
        if req.price is None or req.price <= 0:
            return self._reject(req, REJECT_NO_PRICE)
        if req.mint_address in self._open_by_mint:
            return self._reject(
                req,
                REJECT_ALREADY_HOLDING_MINT,
                open_trade=self._open_by_mint[req.mint_address],
            )
        if len(self._open) >= cfg.max_open_positions:
            return self._reject(
                req,
                REJECT_MAX_OPEN,
                open_positions=len(self._open),
                limit=cfg.max_open_positions,
            )
        size = cfg.position_size
        if self.deployed + size > cfg.max_deployed:
            return self._reject(
                req, REJECT_MAX_DEPLOYED, deployed=self.deployed, limit=cfg.max_deployed
            )
        cost = side_cost(size, req.liquidity_usd, cfg)
        if self.cash < size + cost.total:
            return self._reject(
                req, REJECT_INSUFFICIENT_CASH, cash=self.cash, required=size + cost.total
            )

        trade = PaperTrade(
            trade_key=trade_key(req.arm, req.mint_address, req.at),
            arm=req.arm,
            meme_id=req.meme_id,
            mint_address=req.mint_address,
            entry_at=req.at,
            entry_price=req.price,
            size_usd=size,
            quantity=size / req.price,
            entry_fees_usd=cost.total,
            entry_market_cap=req.market_cap,
            entry_liquidity_usd=req.liquidity_usd,
            token_age_seconds=req.token_age_seconds,
            age_bucket=req.age_bucket,
            lifecycle_state=req.lifecycle_state,
            divergence_case=req.divergence_case,
            entry_reason=req.entry_reason,
            entry_features=req.entry_features,
            evidence_timeline=req.evidence_timeline,
            cost_model=cost.cost_model,
            contains_backfill=req.contains_backfill,
            hindsight=req.hindsight,
        )
        self.cash -= trade.cost_basis
        self._open[trade.trade_key] = trade
        self._open_by_mint[trade.mint_address] = trade.trade_key
        return trade

    # -- exit ----------------------------------------------------------------

    def close(
        self,
        key: str,
        signal: ExitSignal,
        *,
        extra_evidence: tuple[dict[str, Any], ...] = (),
        contains_backfill: bool = False,
    ) -> PaperTrade:
        trade = self._open.pop(key)
        del self._open_by_mint[trade.mint_address]
        gross = trade.quantity * signal.fill_price
        cost = side_cost(gross, signal.liquidity_usd, self.cfg)
        pnl = gross - cost.total - trade.cost_basis
        cost_model = trade.cost_model
        if cost.cost_model != trade.cost_model:
            # A round trip is only as well-modelled as its worse side.
            cost_model = "flat"
        exit_event = {
            "at": signal.at.isoformat(),
            "kind": f"exit:{signal.reason.value}",
            "detail": {
                "fill_price": str(signal.fill_price),
                "observed_price": str(signal.observed_price),
                "trigger_price": _s(signal.trigger_price),
                "exit_fees_usd": str(cost.total),
                **signal.detail,
            },
        }
        closed = replace(
            trade,
            exit_at=signal.at,
            exit_price=signal.fill_price,
            exit_reason=signal.reason,
            exit_fees_usd=cost.total,
            pnl_usd=pnl,
            return_pct=pnl / trade.cost_basis * 100,
            status=STATUS_CLOSED,
            cost_model=cost_model,
            evidence_timeline=(*trade.evidence_timeline, *extra_evidence, exit_event),
            contains_backfill=trade.contains_backfill or contains_backfill,
        )
        self.cash += gross - cost.total
        self.realized_pnl += pnl
        self.closed.append(closed)
        return closed

    def annotate(self, key: str, events: tuple[dict[str, Any], ...]) -> None:
        """Append evidence to an open trade (e.g. an exit rule that could not
        be checked). The trade stays frozen; the ledger swaps the value."""
        if events:
            trade = self._open[key]
            self._open[key] = replace(
                trade, evidence_timeline=(*trade.evidence_timeline, *events)
            )

    def mark_end_of_data(self) -> tuple[PaperTrade, ...]:
        """Positions still open when the data ran out: labelled, never filled.
        They stay ``status='open'`` and are excluded from closed-trade stats."""
        return tuple(replace(t, exit_reason=ExitReason.END_OF_DATA) for t in self.open_trades)

    # -- valuation -----------------------------------------------------------

    def snapshot(self, at: datetime, marks: dict[str, Decimal | None]) -> PortfolioSnapshot:
        """Value the book at ``at`` against ``marks`` (mint → price or None).

        Updates the running peak when equity is known. Unknown equity neither
        raises nor lowers the peak — it was not measured.
        """
        open_value: Decimal | None = _ZERO
        basis = _ZERO
        for trade in self._open.values():
            basis += trade.cost_basis
            mark = marks.get(trade.mint_address)
            if mark is None or open_value is None:
                open_value = None
                continue
            open_value += trade.quantity * mark
        equity = None if open_value is None else self.cash + open_value
        unrealized = None if open_value is None else open_value - basis
        drawdown: Decimal | None = None
        if equity is not None:
            if equity > self.peak_equity:
                self.peak_equity = equity
            drawdown = (
                (self.peak_equity - equity) / self.peak_equity
                if self.peak_equity > 0
                else None
            )
        return PortfolioSnapshot(
            at=at,
            equity=equity,
            cash=self.cash,
            deployed=self.deployed,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            open_positions=len(self._open),
            peak_equity=self.peak_equity,
            drawdown=drawdown,
        )
