# 2026-08-05 — a 60-second provider outage silently removed 163 tokens

Found because the paper wallet's open positions read "updated 25 minutes ago" on
the dashboard, and kept getting older.

## What happened

| | |
|---|---|
| Trigger | DexScreener circuit breaker opened, 60-second cooldown |
| Detected | ~90 minutes later, by a user reading the freshness label |
| Impact | 163 of the 200 tokens in the priority enrichment lane stopped refreshing **permanently**; 10 of the paper wallet's 12 holdings went dark for over an hour |
| Data lost | None. No wrong figure was ever published |
| Recovery | Manual until this fix; now automatic |

The freshness label was doing its job. The page said the prices were 25 minutes
old because they were, and that is the only reason this was caught at all.

## The chain

1. `07:02:41` — DexScreener failed 5 times, the breaker opened for 60 seconds.

2. While open, `provider.fetch_many` raises `ProviderUnavailableError` for the
   whole batch. In `MarketEnrichmentService.enrich`, `succeeded = error is None`,
   so **every token in the batch took `consecutive_failures + 1`** — despite no
   request being made on any of their behalf.

3. A rejected call returns at `latency_ms=0`. The worker re-claimed and
   re-rejected at full loop speed, so the 10-failure dead-letter budget was
   spent in seconds rather than over the minutes the threshold implies.

4. `claim_due` filters on `status == ACTIVE`, so a dead-lettered token is never
   claimed again. `requeue_dead_letters` existed on the repository, documented
   as an operator action — and **had no caller anywhere in the codebase**.

5. The provider recovered within the minute. The 163 tokens did not.

## Three defects, and why each is a defect

**1. A provider outage was charged to the token.** A circuit-breaker rejection
is evidence about the provider, not about a mint. The token was never asked.

**2. Dead-lettering was terminal.** One bad minute removed a token from the
platform with no path back that did not involve a human noticing.

**3. The threshold was a count, not a duration.** Ten failures is 2.5 minutes on
the 15-second priority lane and 20 minutes on the normal one. The tokens the
product most wants fresh were therefore the easiest to park — exactly backwards,
and the reason the damage landed almost entirely on the lane that matters.

## The fix

- `ProviderUnavailableError` and `CircuitOpenError` now carry
  `retry_after_seconds`, so the caller can defer by the breaker's own cooldown
  instead of parsing it out of a message string.
- `MarketEnrichmentService._defer` handles provider-unavailable as a **batch
  deferral**: one UPDATE moving `next_refresh_at`, touching no failure count, no
  attempt count, and no status. Reported as `deferred`, counted apart from
  `failed` at both the service and worker level, so an outage can never again be
  read as tokens going bad.
- `RefreshScheduler.should_dead_letter` requires elapsed failing time as an
  independent second condition (`ENRICHMENT_DEAD_LETTER_MIN_MINUTES`, 30). A
  short outage cannot park anything, in any lane.
- `app.workers.enrichment_tasks.requeue_dead_letters` runs every 5 minutes,
  readmitting tokens that have served `ENRICHMENT_DEAD_LETTER_RETRY_MINUTES`
  (60), bounded per pass and oldest-first. Dead-lettering is now a **quarantine
  rather than a grave**, so any future mistake heals itself whatever its cause.

## Verification

- 14 new tests, including the incident's exact shape: a token one failure short
  of the threshold, hammered by 100 circuit rejections, must stay `ACTIVE`.
- Live: the recovery pass readmitted **154 tokens**; every paper-wallet holding
  returned to `active` and to a 0-minute price age within one minute.
- 3,472 backend and 374 frontend tests pass; `make check` clean.

## What this cost the paper wallet

Nothing that corrupts the record, and one thing worth stating.

Exits resolve against the stored observation series, so the trailing stop still
closed at the first reading that breached it, dated to that reading. The trades
are correct. What the outage delayed was *when* those decisions were recorded —
a stop that should have fired at 07:30 fired when the data resumed, at the right
price but later than it should have been visible.

After recovery the wallet settled 4 trades, all on the trailing stop, and wrote
4 audit rows — the first live exercise of the permanent record, which Sprint 30
could only prove by test.

## The one that got away, and is worth watching

`Falcon9` closed at **-11.64% gross but -24.29% net**: $12.09 of price impact on
a $100 position, because the pool it exited into was far thinner than the one it
entered. That is the progressive cost model working as designed, and it is the
clearest live evidence yet for Sprint 27's point that a flat per-trade cost
estimate would misreport this market.
