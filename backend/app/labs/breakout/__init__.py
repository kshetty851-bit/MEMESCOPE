"""Breakout Lab — momentum into daily resistance on ESTABLISHED Solana tokens.

Phase 1 is the data layer only: a universe of pools older than a week with
real liquidity, and daily and hourly candles for each. No setup detection,
no scoring, no trading, no UI.

Isolated the way the Crypto Trend lab is: its own `bo_*` tables, its own
flag, its own config, its own tests, and no import of any paper wallet,
real wallet, radar, or other lab. It reads two keyless public APIs and
writes only its own tables.
"""
