"""FOREX LAB — a hedged grid on EUR/USD, backtest only.

A $1,000 paper wallet at 10x leverage, replayed over Dukascopy tick data
aggregated to 1-minute bid/ask candles. No live trading, no paper feed, no
frontend, no scheduler: nothing in this package opens a position anywhere but
in memory, and nothing in it is wired to a Celery beat.

Isolated the way the crypto_trend and graduation labs are:

* its own tables (`fx_*`), its own feature flag (`FOREX_LAB_ENABLED`,
  default off), its own config module;
* it reads one keyless public source (Dukascopy's tick datafeed) and writes
  nothing but `fx_*`;
* it imports no paper, karthik, real-wallet, graduation, rafiq, breakout or
  crypto_trend module, and no shared model beyond `app.db.base.Base`. A test
  parses this package's source and fails if that ever stops being true.

`engine.py` is the one module that matters most, and it imports nothing from
this package's DB layer at all — it is plain Python over a candle iterator, so
the strategy can be unit-tested to the cent without a database in the room.
"""
