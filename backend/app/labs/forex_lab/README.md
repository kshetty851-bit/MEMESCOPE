# Forex Lab

A hedged grid on EUR/USD, backtested against a $1,000 paper wallet at 10x
leverage over 2020-01-01 → 2026-06-30. **Backtest only.** Nothing in this
package opens a position anywhere but in memory, nothing is wired to Celery
beat, and there is no API route and no frontend.

```bash
python -m app.labs.forex_lab ingest      # download + aggregate, resumable
python -m app.labs.forex_lab status      # what is loaded
python -m app.labs.forex_lab integrity   # the gate on the data
python -m app.labs.forex_lab export      # candles -> the binary replay file
python -m app.labs.forex_lab backtest    # one config
python -m app.labs.forex_lab sweep       # all 27
python -m app.labs.forex_lab report      # REPORT.md
```

`FOREX_LAB_ENABLED` defaults to false. With it off nothing here runs,
schedules work, or opens a socket — but note that the CLI above is the lab's
own entry point and does not consult the flag: the flag exists to keep the lab
out of a deployed platform, not to stop an operator running a backtest.

## The strategy

Centred at `C`, with `N` levels each side `S` pips apart:

```
        C + 4S   sell limit  (tp C+3S)   buy stop  (tp C+5S)   <- re-centre
        C + 3S   sell limit  (tp C+2S)   buy stop  (tp C+4S)
        C + 2S   sell limit  (tp C+1S)   buy stop  (tp C+3S)
        C + 1S   sell limit  (tp C)      buy stop  (tp C+2S)
        C
        C - 1S   buy limit   (tp C)      sell stop (tp C-2S)
        C - 2S   buy limit   (tp C-1S)   sell stop (tp C-3S)
        C - 3S   buy limit   (tp C-2S)   sell stop (tp C-4S)
        C - 4S   buy limit   (tp C-3S)   sell stop (tp C-5S)   <- re-centre
```

Both orders at a level trigger at the same price, so falling through `C-kS`
opens a long *and* a short and they are never netted — that is what makes it
hedged. Limit fills take profit one step toward the centre, stop fills one step
away; a take-profit re-places the order that opened the position. Crossing
`C ± N·S` closes everything at market, cancels everything, and rebuilds the
grid around the price it crossed at.

There is no per-order stop loss. The margin cap (90% of equity) and the
stop-out (equity below 50% of used margin) are the only things between the
grid and the account.

## Layout

| file | what it is |
|---|---|
| `config.py` | the flag, the instrument, the swap table, the sweep grid |
| `models.py` | `fx_candles`, `fx_ingest_hours` |
| `ticks.py` | Dukascopy's `.bi5` format, and minute aggregation. Pure |
| `ingest.py` | the downloader. The only module that opens a socket |
| `store.py` | reads, and the integrity check |
| `engine.py` | the grid. No DB, no network, no clock |
| `backtest.py` | replay, metrics, the sweep, the baselines |
| `report.py` | REPORT.md, and the gate |

`engine.py` importing nothing from the data layer is the load-bearing part: a
strategy that could read a row could also read the future, and a test asserts
it cannot. `tests/test_isolation.py` parses every module's source and fails if
any of this stops being true.

## Reading the output

`PLAN.md` is what was decided before any code was written, including the gate.
`DECISIONS.md` is every choice the spec left open, and — at the bottom — every
correction to my own arithmetic, with the working shown. `RUNLOG.md` is one
entry per iteration. `REPORT.md` is the result.

The four places the simulation deliberately costs the strategy money are listed
at the top of `engine.py`. The short version: both intra-candle orderings are
simulated and the worse one is kept; the outermost level fills before the
re-centre closes it at the same price; entries are processed before
take-profits so they compete for margin; and equity marks at the side of the
spread a close would pay.

## What this lab is not

It is not a forward test and it does not trade. A grid's headline number is
famously a function of the window it was run over, and six and a half years of
one pair is one sample of one regime. The gate in `REPORT.md` was written down
before the sweep ran and is not adjusted afterwards, which is the only thing
keeping the result from being a search for a window that flatters it.
