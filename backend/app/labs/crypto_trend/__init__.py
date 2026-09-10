"""CRYPTO TREND LAB — market data for trend-following on the top-20 by market cap.

Phase 1: the data layer only. No signals, no trading, no UI.

Isolated the way the Rafiq lab is:

* its own tables (`ct_*`), its own feature flag (`CRYPTO_TREND_LAB_ENABLED`,
  default off), its own config module;
* it reads two keyless public APIs (CoinGecko for the ranking, Binance
  Futures for candles and funding) and writes nothing but `ct_*`;
* it imports no paper, karthik, real-wallet or lab engine, and no shared
  model at all. A test parses this package's source and fails if that ever
  stops being true.

With the flag off nothing here runs, schedules work, or opens a socket.
"""
