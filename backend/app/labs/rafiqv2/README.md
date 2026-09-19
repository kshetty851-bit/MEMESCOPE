# Rafiqv2 Lab

Six books, A2 B2 C2 D2 E2 G2, on one engine. Each book starts from $1,000 and
learns from its own trades. **Paper only**: a position is a row that records
what the rules would have done. The lab has its own tables (`rafiqv2_*`), its
own flag, a 30-second beat and a page at `/rafiqv2-lab`. It sits beside the
Rafiq Lab (`app/labs/rafiq`), which keeps running its own A2–E2 and G1 unchanged.

Nothing here has made money. The rules limit losses; they do not promise a profit.

## Switching it on

1. `alembic upgrade head`. This applies `0099_rafiqv2_lab`, which adds three new tables and changes nothing else.
2. Set `RAFIQV2_LAB_ENABLED=true` in `.env.production`. The compose anchor already passes it through.
3. Restart the `backend`, `worker` and `scheduler` containers.

The beat runs `rafiqv2-lab-tick` every 30 seconds. With the flag off, the task returns before opening a session.

## Where everything lives

| file | what it is |
|---|---|
| `books/strategy_*.json` | The six books, exactly as delivered. They are the rules. |
| `learning.py` | As delivered, plus one fix (see below). |
| `strategy_common.py` | The rug ladder, profit lock, death-rate breaker and ratchet. |
| `config.py` | Loads the JSON. Any setting the engine does not implement is refused. |
| `engine.py` | The one exit rule, pure. |
| `service.py` | The tick. |
| `api.py` | `GET /labs/rafiqv2/status`, `/positions` and `/trades`. No write routes. |

Reused from `app.labs.rafiq` rather than copied:

- the read-only feed, including its dead-pool rule;
- the cost model;
- the entry gate;
- the glitch band;
- the daily breaker;
- G1's `EquityRatchet`.

**Deleting that lab means moving these modules first.**

## One tick, per book

1. **Settle open positions.** Exits are checked in this order:
   stop → profit lock → scale-out (a partial sale) → runner trail → rug ladder → max hold.
   - A pool that reads gone is worth $0 at once, and is booked at $0 (`pool_gone`) once it has read gone for 10 minutes. "Gone" means an `inactive` reading or a delisting after the last tradeable print. The 10 minutes is two of the 5-minute polls a token older than 30 minutes gets. A single `inactive` snapshot is what made 6.9% of the platform Lab's zeros tokens that were still trading.
   - A pool that nothing has priced recently is held. Staleness is not treated as death.
2. **Feed the learner.** `on_exit` runs for every close whose hour after exit has passed.
3. **Value the book** at what its pools would pay. Then move the ratchet and ask the daily breaker.
4. **Enter**, unless a breaker holds entries. For each fresh Radar admission:
   - check the score;
   - check the reading is tradeable and fresh;
   - call `current_parameters()`;
   - size the position;
   - run the gate;
   - buy;
   - call `on_entry`.

A halt only stops new entries. Nothing is ever force-sold.

## Decisions made without asking

- **What `lock_giveback` means.** The published ladder has no give-back number. Each rung may give back `(giveback − 0.15) ×` its trigger gain more than published. At 0.15 the ladder is exactly as delivered. At the 0.40 bound, the +25% rung locks +7.75% instead of +14%. No floor goes below the 1% friction.
- **`rug_strictness` is added to every rung.** Positive values cut more; negative values cut less.
- **Learned values are frozen per position.** The strictness, give-back and size multiplier read before an entry stay on that position for life.
- **Multiples are measured against the price actually paid**, after fee and impact, as everywhere else in the lab. So "breakeven at 120s" means the position has earned back its entry cost. A token whose price has not moved is cut at 60–120 s.
- **The runner trail is 45% off the peak price**, as in G1. It applies after the scale-out; D2 has no scale-out, so it applies from entry. The lock's floor sits above the trail until the peak is near 3×.
- **A token "died"** if its final sale filled at 10% of entry or less, or its pool was gone. That flag is recorded on the death-rate breaker at the close. The learner receives the same flag later.
- **The learner hears a close one hour after the exit.**
  - Its peak is the best tradeable price over the hold and that hour. "Did a cut token recover?" and "did a locked token keep running?" are both questions about prices after the sale.
  - `lock_armed` is passed as "the lock sold it", which is the event the module's docstring describes ("locks are firing").
- **Size is 1% of equity × the multiplier, clamped to $5–$50.**
- **The daily breaker latches** for the rest of the UTC day, as its own docstring says.
- **The beat runs every 30 s**, because the ladder has rungs at 30 s and 60 s. An advisory lock stops two ticks overlapping.

## Defects found in the delivered material

1. **Fixed:** every audit line recorded `n=0`. Both calibrators cleared their evidence before reading its size. `test_an_adjustment_records_the_sample_it_was_made_on` pins the fix.
2. **Handled in the wiring:** the lock calibrator counted any position that had armed the lock and then lost 31% or more as "the lock was too tight". A token that armed at +3% and then rugged through the stop was evidence for loosening the lock.
3. **Open:** `on_exit` takes one `peak_multiple` for two different questions.
   - "Round-tripped winner" needs the peak while the position was held.
   - "Cut but recovered" needs the peak after the exit.

   With the combined peak, a trade sold at a loss that then ran +10% counts as a round trip, which pushes the lock tighter. Fixing this means changing the delivered interface.
4. **Open:** the rug calibrator's z-test compares two different events: cut tokens that recovered, against kept tokens that died. A z of 1.96 or more means one rate beats the other, not that the gates are wrong.
5. **Open:** `learning.py` says top-10 holder concentration and LP lock status are "not recorded anywhere". The Rafiq Lab has recorded both at entry since 2026-09-12, and this lab records both on every position (`entry_top10_holder_pct`, `entry_lp_locked`).
6. B2's config says "0.80 × 1.20 returns the stake whole". It returns 96%.

## Known limits

- **The rug ladder is only as fast as the data.** The platform prices a token under 30 minutes old every 30 s, and every 5 minutes after that. Rafiq positions are not in the priority lane (`services/market/priority.py`).
- **A crash below a third of the 10-minute median is treated as a glitch**, the band this project added after fake prints. So a rug that still reads as tradeable is sold only once the median catches up, a few minutes later. A pool that reads gone is not affected.
- **The hour-after peak is a lower bound**, because it is read from 5-minute snapshots.

## Tests

```bash
cd backend && pytest app/labs/rafiqv2 -q
```

There are 41 tests:

- 25 are the delivered tests, with only their import paths changed;
- 12 cover the engine and config without a database;
- 4 run whole ticks against Postgres (they skip when there is none).
