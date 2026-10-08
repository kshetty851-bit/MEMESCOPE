"""BTC/USDT Range Lab — paper only.

A range-trading strategy over BTC/USDT 15-minute candles: detect the current
range, call LONG near support, SHORT near resistance, WAIT otherwise, and run a
$1,000 paper account on those calls. There is no wallet, no order router and no
exchange key anywhere in this package; the only network call is a public
candle read.

The live paper book is a deterministic replay of the default config over stored
closed candles from a fixed start, through the same engine the Strategy Lab
backtests with. Closed candles are immutable and the config is versioned, so the
book cannot rewrite its own history — and the live record and a backtest can
never disagree about what the strategy would have done.

Nothing outside this package imports it except the router line and the beat
entry. Do not re-export the engine here (see CLAUDE.md, import cycles).
"""
