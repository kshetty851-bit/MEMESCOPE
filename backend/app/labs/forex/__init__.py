"""Forex Strategy Lab — research and paper only.

Backtests forex strategies (EUR/USD first) over stored historical candles,
with costs, leverage and margin modelled, and validates them out of sample.
There is no broker connection, no order router and no credential anywhere in
this package; the only network call is a public historical-candle download.

Do not re-export the engine here (see CLAUDE.md, import cycles).
"""
