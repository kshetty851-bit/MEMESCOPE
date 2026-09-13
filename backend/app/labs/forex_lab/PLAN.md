# forex_lab — run plan

A hedged-grid backtest on EUR/USD. $1,000 paper wallet, 10x leverage, no live
trading, no paper feed, no frontend. Isolated the way `crypto_trend` and
`graduation` are: `fx_*` tables, one env flag (`FOREX_LAB_ENABLED`,
default off), its own config module, nothing existing edited.

## Environment facts established before writing a line

| Question | Answer | How it was established |
|---|---|---|
| Dukascopy reachable? | Yes | `datafeed.dukascopy.com` returns HTTP 200 LZMA for `EURUSD/2023/00/03/14h_ticks.bi5` |
| Throughput | ~2.5 files/s at concurrency 128, ~83% first-pass success | probe over 512 real hour-files |
| Pre-aggregated monthly candles? | **No** — genuine 404 (162-byte body, distinct from the 3464-byte transient 404) | 8 retries on `BID_candles_min_1.bi5` |
| Postgres | `memescope-test-pg` on localhost:5432 | `docker ps` |
| Python | fresh 3.12 venv at `~/.venvs/fxgrid` (the repo's `.venv` symlink is broken) | — |

Ticks are therefore the only path. ~40,500 hour-files for 2020-01-01 →
2026-06-30, ≈5–6 h wall clock. The loader starts in the background at the top
of iteration 1 and the engine is built while it runs, because the engine has
no dependency on the data.

## Phases

**Phase 1 — data.** `fx_candles` (1-minute bid/ask OHLC) + `fx_ingest_hours`
(one row per downloaded hour-file → idempotent + resumable). Loader decodes
Dukascopy's `.bi5`: LZMA-compressed records of `>3I2f` = (ms-since-hour,
ask-points, bid-points, ask-volume, bid-volume), points scaled by 1e-5 for
EUR/USD. CLI: `python -m app.labs.forex_lab ingest`.

**Phase 2 — engine.** Pure Python, no DB, no network. Event-driven on candles.
Then a replay backtester over the stored candles, then the sweep.

## Decisions taken without asking (detail + arithmetic in DECISIONS.md)

1. **Grid levels are mid prices; the spread parameter is paid half on each
   fill.** A round trip pays one full 0.8-pip spread — what a broker actually
   charges. Charging the full spread on both legs would double-count it.
2. **Worst-ordering within a candle** is resolved by simulating both
   `open→low→high→close` and `open→high→low→close` on a copied state and
   keeping whichever ends with lower equity. A fast path skips both when the
   candle's range touches no level and no re-center boundary.
3. **Level N sits exactly on the re-center boundary.** Its orders fill, *then*
   the re-center closes them — strictly worse for the strategy (two spreads
   paid for nothing), so that is the conservative ordering.
4. **Margin is held at the open price** for the life of the position, and
   summed over every position in hedging mode (no netting) — the spec gives a
   per-micro-lot formula, so it is summed, not offset.
5. **Swap rates are derived from published ECB deposit-facility and Fed
   funds rates** per year with a broker markup, because OANDA's historical
   swap tables are not retrievable here. The derivation is shown in full in
   DECISIONS.md. Triple swap on the Wednesday rollover is ON — without it the
   weekend carry is simply never charged, which would understate cost.
6. **The swap table lives in `config.py`, not the database**, because the spec
   requires the engine to have no DB dependency.

## Gate (pre-stated, not to be adjusted)

PF ≥ 1.3 · positive in ≥ 4 of 6 years including 2022 · max DD < 25% · no
single month > 30% of total profit.

## Loop

build/fix → full test suite → integrity check → if green, sweep → report.
Max 12 iterations, appended to RUNLOG.md. A failing test gets the code fixed,
never the expectation — unless the expectation's own arithmetic is shown wrong
in DECISIONS.md first.
