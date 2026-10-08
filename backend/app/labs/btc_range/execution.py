"""The paper account: replay closed candles through the strategy, one trade at a time.

`run_backtest` is the only simulator. The live paper book is this function run
over stored candles from a fixed start, so a backtest and the live record
cannot disagree about what the strategy would have done.

The rules that decide whether the result can be believed:

  - **No look-ahead.** A signal is formed from candles up to and including
    candle `i`, and fills at the OPEN of candle `i + 1`. The candle that made
    the decision is never the candle that traded on it.
  - **The entry candle can exit the trade.** Its range is real price action after
    the fill, so a stop inside it counts — including a gap through the stop at
    the open, which fills at the open, not at the stop level.
  - **Same-candle ambiguity resolves against us.** When one candle's range
    contains both the stop and the target, OHLC cannot say which came first.
    Counting the target would flatter the strategy on exactly the candles
    nobody can verify, so the stop wins.
  - **Costs are adverse on every fill.** Slippage always moves the price against
    the position, and fees are charged on notional at entry and again at exit.
  - **Never force a trade.** No qualifying signal means no trade; a quiet
    dataset reports zero trades and `None` for every ratio that needs one.
  - **Gaps are not filled in.** Candles are used as supplied. A missing candle
    is missing data, and inventing one would invent prices.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from app.labs.btc_range.engine import PRICE_STEP, RATIO_STEP, evaluate, quantize
from app.labs.btc_range.types import (
    BacktestResult,
    Call,
    Candle,
    EquityPoint,
    ExitReason,
    Metrics,
    OpenPosition,
    Reason,
    Signal,
    StrategyConfig,
    Trade,
)

USD_STEP = Decimal("0.01")
QTY_STEP = Decimal("0.00001")

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_BPS = Decimal(10_000)


@dataclass(slots=True)
class _Position:
    """A live position. Mutable only because nothing outside this module sees it."""

    side: Call
    signal_at: datetime
    entry_index: int
    entry_at: datetime
    entry_price: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    quantity: Decimal
    notional: Decimal
    entry_fee: Decimal
    risk_amount: Decimal


def _fee(notional: Decimal, cfg: StrategyConfig) -> Decimal:
    return quantize(notional * cfg.fee_bps / _BPS, USD_STEP)


def _fill(price: Decimal, side: Call, *, opening: bool, cfg: StrategyConfig) -> Decimal:
    """A fill, moved against the position by slippage.

    Buying (opening a long, closing a short) pays up; selling receives less.
    """
    slip = cfg.slippage_bps / _BPS
    buying = (side is Call.LONG) == opening
    return quantize(price * (Decimal(1) + slip if buying else Decimal(1) - slip), PRICE_STEP)


def _stop_or_target(pos: _Position, candle: Candle) -> tuple[Decimal, ExitReason] | None:
    """The un-slipped level this candle exits at, or None if it exits nowhere.

    Gaps are checked against the open first: a candle that opens through the
    stop was never at the stop price, so it fills at the open.
    """
    if pos.side is Call.LONG:
        if candle.open <= pos.stop_loss:
            return candle.open, ExitReason.STOP_LOSS
        if candle.open >= pos.take_profit:
            return candle.open, ExitReason.TAKE_PROFIT
        hit_stop = candle.low <= pos.stop_loss
        hit_target = candle.high >= pos.take_profit
    else:
        if candle.open >= pos.stop_loss:
            return candle.open, ExitReason.STOP_LOSS
        if candle.open <= pos.take_profit:
            return candle.open, ExitReason.TAKE_PROFIT
        hit_stop = candle.high >= pos.stop_loss
        hit_target = candle.low <= pos.take_profit

    if hit_stop:  # includes the both-hit case: the stop wins, see module docstring
        return pos.stop_loss, ExitReason.STOP_LOSS
    if hit_target:
        return pos.take_profit, ExitReason.TAKE_PROFIT
    return None


def _unrealised(pos: _Position, mark: Decimal) -> Decimal:
    move = mark - pos.entry_price if pos.side is Call.LONG else pos.entry_price - mark
    return quantize(pos.quantity * move, USD_STEP) - pos.entry_fee


def _close(
    pos: _Position,
    candle: Candle,
    level: Decimal,
    reason: ExitReason,
    cfg: StrategyConfig,
) -> Trade:
    exit_price = _fill(level, pos.side, opening=False, cfg=cfg)
    exit_fee = _fee(quantize(pos.quantity * exit_price, USD_STEP), cfg)
    move = (
        exit_price - pos.entry_price if pos.side is Call.LONG else pos.entry_price - exit_price
    )
    fees = pos.entry_fee + exit_fee
    pnl = quantize(pos.quantity * move, USD_STEP) - fees
    return Trade(
        side=pos.side,
        signal_at=pos.signal_at,
        entry_at=pos.entry_at,
        entry_price=pos.entry_price,
        take_profit=pos.take_profit,
        stop_loss=pos.stop_loss,
        quantity=pos.quantity,
        notional=pos.notional,
        exit_at=candle.open_time,
        exit_price=exit_price,
        exit_reason=reason,
        fees=fees,
        pnl=pnl,
        r_multiple=quantize(pnl / pos.risk_amount, RATIO_STEP)
        if pos.risk_amount > 0
        else None,
    )


def _open(
    signal: Signal,
    next_candle: Candle,
    next_index: int,
    cash: Decimal,
    cfg: StrategyConfig,
) -> _Position | None:
    """Size and fill an entry at the next candle's open, or None if it cannot be sized."""
    if signal.stop_loss is None or signal.take_profit is None:
        return None
    side = signal.call
    equity = cash  # flat: cash is the whole account
    if equity <= 0:
        return None

    fill = _fill(next_candle.open, side, opening=True, cfg=cfg)
    stop_distance = abs(fill - signal.stop_loss)
    if stop_distance <= 0:
        return None

    risk_amount = quantize(equity * cfg.risk_per_trade_pct / _HUNDRED, USD_STEP)
    quantity = (risk_amount / stop_distance).quantize(QTY_STEP, rounding=ROUND_DOWN)
    # The cap, not the risk budget, usually binds at 1x on a tight stop. The
    # position is then smaller than planned and a stop costs less than
    # `risk_per_trade_pct`; it is never larger.
    max_quantity = (equity * cfg.max_leverage / fill).quantize(QTY_STEP, rounding=ROUND_DOWN)
    quantity = min(quantity, max_quantity)
    if quantity <= 0:
        return None

    notional = quantize(quantity * fill, USD_STEP)
    return _Position(
        side=side,
        signal_at=signal.at,
        entry_index=next_index,
        entry_at=next_candle.open_time,
        entry_price=fill,
        take_profit=signal.take_profit,
        stop_loss=signal.stop_loss,
        quantity=quantity,
        notional=notional,
        entry_fee=_fee(notional, cfg),
        risk_amount=risk_amount,
    )


def _max_drawdown_pct(values: Sequence[Decimal], starting_balance: Decimal) -> Decimal:
    """Peak-to-trough, as a percent of the peak. The start is the first peak."""
    peak = starting_balance
    worst = _ZERO
    for value in values:
        if value > peak:
            peak = value
        elif peak > 0:
            drop = (peak - value) / peak
            if drop > worst:
                worst = drop
    return quantize(worst * _HUNDRED, RATIO_STEP)


def compute_metrics(
    trades: Sequence[Trade],
    starting_balance: Decimal,
    equity_values: Sequence[Decimal] | None = None,
) -> Metrics:
    """Summary figures from trades and, optionally, an equity curve.

    `equity_values` is the curve drawdown and ending equity are read from. The
    whole account passes its mark-to-market curve, so an unrealised dip counts.
    A single side has no marked curve of its own, so it passes nothing and gets
    the cumulative realised curve of its trades from the starting balance.

    A figure that needs a trade (win rate, expectancy, drawdown) is `None`
    without one: an account that never traded has no measured drawdown, and
    reporting 0% would read as a clean record rather than an absent one.
    """
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]
    gross_profit = sum(wins, _ZERO)
    gross_loss = sum(losses, _ZERO)
    net_pnl = sum((t.pnl for t in trades), _ZERO)

    if equity_values is None:
        running = starting_balance
        realised: list[Decimal] = []
        for t in trades:
            running += t.pnl
            realised.append(running)
        equity_values = realised
    ending_equity = equity_values[-1] if equity_values else starting_balance

    count = len(trades)
    return Metrics(
        trades=count,
        wins=len(wins),
        losses=len(losses),
        win_rate=quantize(Decimal(len(wins)) / Decimal(count) * _HUNDRED, RATIO_STEP)
        if count
        else None,
        net_pnl=net_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=quantize(gross_profit / abs(gross_loss), RATIO_STEP)
        if gross_loss < 0
        else None,
        expectancy=quantize(net_pnl / Decimal(count), USD_STEP) if count else None,
        max_drawdown_pct=_max_drawdown_pct(equity_values, starting_balance) if count else None,
        return_pct=quantize(
            (ending_equity - starting_balance) / starting_balance * _HUNDRED, RATIO_STEP
        )
        if starting_balance > 0
        else _ZERO,
        ending_equity=ending_equity,
    )


def run_backtest(
    candles: Sequence[Candle],
    cfg: StrategyConfig,
    *,
    close_open_at_end: bool = True,
) -> BacktestResult:
    """Replay `candles` (ascending, closed) through `cfg`.

    `close_open_at_end=True` marks the books for a backtest: a position still
    open at the last candle is closed at its close so its P&L is counted.
    The live book passes False and gets the position back as `open_position`,
    because a trade that has not ended is not a result yet.
    """
    if cfg.lookback < 1:
        raise ValueError("lookback must be at least 1")

    n = len(candles)
    lookback = cfg.lookback
    cash = cfg.starting_balance
    position: _Position | None = None
    trades: list[Trade] = []
    equity_curve: list[EquityPoint] = []
    signal_counts: dict[Call, int] = {Call.LONG: 0, Call.SHORT: 0, Call.WAIT: 0}
    wait_reasons: dict[Reason, int] = {}
    #: First candle index at which a new signal may be taken.
    next_signal_index = lookback

    for i in range(lookback, n):
        candle = candles[i]

        if position is not None:
            exit_at = _stop_or_target(position, candle)
            if exit_at is None and 0 < cfg.max_hold_candles <= i - position.entry_index + 1:
                exit_at = (candle.close, ExitReason.TIME_STOP)
            if exit_at is not None:
                trade = _close(position, candle, exit_at[0], exit_at[1], cfg)
                trades.append(trade)
                cash += trade.pnl
                position = None
                next_signal_index = i + cfg.cooldown_candles

        equity = cash if position is None else cash + _unrealised(position, candle.close)
        equity_curve.append(EquityPoint(at=candle.open_time, equity=equity))

        if position is None and i >= next_signal_index and i < n - 1:
            signal = evaluate(candles[i - lookback : i + 1], cfg)
            signal_counts[signal.call] += 1
            if signal.call is Call.WAIT:
                wait_reasons[signal.reasons[0]] = wait_reasons.get(signal.reasons[0], 0) + 1
            else:
                position = _open(signal, candles[i + 1], i + 1, cash, cfg)

    open_position: OpenPosition | None = None
    if position is not None:
        last = candles[-1]
        if close_open_at_end:
            trade = _close(position, last, last.close, ExitReason.END_OF_DATA, cfg)
            trades.append(trade)
            cash += trade.pnl
            # The marked point above is before the exit fee and slippage. Left
            # alone, ending equity would disagree with the trades that produced
            # it, so the final point is restated to the realised account.
            equity_curve[-1] = EquityPoint(at=last.open_time, equity=cash)
        else:
            open_position = OpenPosition(
                side=position.side,
                signal_at=position.signal_at,
                entry_at=position.entry_at,
                entry_price=position.entry_price,
                take_profit=position.take_profit,
                stop_loss=position.stop_loss,
                quantity=position.quantity,
                notional=position.notional,
                entry_fee=position.entry_fee,
                mark_price=quantize(last.close, PRICE_STEP),
                unrealised_pnl=_unrealised(position, last.close),
            )

    # The last candle is evaluated even though nothing can trade on it, so the
    # page can say what the strategy thinks now regardless of any open position.
    last_signal = evaluate(candles[n - 1 - lookback :], cfg) if n >= lookback + 1 else None

    curve_values = [point.equity for point in equity_curve]
    start_balance = cfg.starting_balance
    return BacktestResult(
        config=cfg,
        start=candles[0].open_time if n else None,
        end=candles[-1].open_time if n else None,
        candles=n,
        signal_counts=signal_counts,
        wait_reasons=wait_reasons,
        trades=tuple(trades),
        open_position=open_position,
        equity_curve=tuple(equity_curve),
        metrics=compute_metrics(trades, start_balance, curve_values),
        long_metrics=compute_metrics(
            [t for t in trades if t.side is Call.LONG], start_balance
        ),
        short_metrics=compute_metrics(
            [t for t in trades if t.side is Call.SHORT], start_balance
        ),
        last_signal=last_signal,
    )
