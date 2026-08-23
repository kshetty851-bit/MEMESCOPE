# PW-LIFECYCLE-1 — Multi-Generation Position Management + Shared Capital

**Status:** COMPLETE. No migration. Nothing deployed. SEC-2 still inactive.
**Archived-book management ships OFF** — turning it on settles 9 positions, so it is
your decision, not a deploy side effect.

---

## 1. What was already correct

Two of the three target properties needed no change, which is why this phase required
no migration:

- **"Position permanently remembers which generation opened it"** — already true.
  `paper_positions.wallet_id` → `paper_wallets.generation` is immutable; a wallet row
  is never re-generationed.
- **"Exit logic belongs to the position"** — already true. `_rules_for` reads the
  target, stop, trailing distance and expiry off the position's own row, explicitly
  *not* from the configured strategy. An archived generation's book therefore closes
  on the policy it was opened under, and SEC-2 rules can never reach backwards.

The gap was entirely behavioural: `review()` scoped **both** exits and entries to the
live wallet, and cash was computed per wallet.

## 2. What changed

**Two different scopes, deliberately asymmetric:**

```
exits    → every wallet that still holds something (archived included)
entries  → the live wallet only
```

- `wallets_with_open_positions()` — the exit engine's scope. Live book first, then
  oldest generation, so a long archive tail is walked in a stable order. A wallet with
  no open positions is not swept.
- `lineage_wallets()` — the capital pool, oldest generation first.
- `_cash_for()` now pools across the lineage, using the **earliest** member's starting
  balance, counted once.

## 3. Capital: a lineage, not a retroactive merge

Naive pooling of all six historical wallets against one $1,000 base yields **−$1,934**.
That is not a balance — it is six independent experiments added together. Generation 2
alone has compounded its own $1,000 through $17,530 of cumulative entries and $17,586
returned. Every archived wallet's own `archive_reason` also states it is *"retained
unchanged"* and *"never mixed into the live wallet's figures"*.

So capital is inherited **forward along a lineage**, declared in code:

```python
CAPITAL_LINEAGES = (frozenset({"trailing_stop_25_v1", "trailing_stop_25_secured_v2"}),)
```

- **Today** the live wallet's lineage has exactly one member, so pooled cash is
  **$13.76 — byte-identical to the per-wallet value**. The change is inert until a
  cutover happens. Verified live.
- **After cutover** the pool is {gen 7, gen 2}: gen 7 inherits, mints nothing, and
  gen 2's 14 open positions keep holding $1,400 down so gen 7 cannot over-allocate.
- Generations 1, 3, 4, 5, 6 ran different strategies, form their own lineages, and are
  untouched.

Declared in code rather than parsed from `archive_reason` prose: lineage is a fact
about the product, and parsing text to decide where money lives is wrong once and then
wrong forever.

## 4. Frozen position audit — 105 positions, read-only

Each position was replayed over the observations the platform already stored. Nothing
was closed, no P&L written, no exit invented, and no position priced at today's market.

| Classification | Count |
|---|---|
| **Legitimately open** — observations exist, no rule breached | **96** |
| **Historically recoverable** — a barrier or expiry was breached at a known past time and price | **9** |
| **Unresolved** — no usable observation | **0** |

| Generation | Open | Recoverable | Unresolved |
|---|---|---|---|
| 1 (equal_weight_v1) | 0 | **6** | 0 |
| 5 (all_scanned) | 95 | 3 | 0 |
| 6 (track_record) | 1 | 0 | 0 |

**Breached by rule:** target 4 · stop 3 · expiry 2

Generation 1's entire book is recoverable — it carried a 48-hour expiry and was
abandoned the day after it opened. Earliest breach: a stop on 2026-08-05 06:23.

**Recommendation:** enable `PAPER_WALLET_MANAGE_ARCHIVED_GENERATIONS` so the exit
engine settles those 9 at their observed historical prices and keeps managing the
other 96. This is a correction, not a rewrite — but it changes 9 recorded outcomes, so
it needs your word.

## 5. Safe cutover sequence

The blocker from SEC-2 is gone once step 1 is approved.

1. **Enable `PAPER_WALLET_MANAGE_ARCHIVED_GENERATIONS=true`.** Confirm the 9
   recoverable positions settle at historical prices and 96 keep running. *Requires
   your approval — it changes 9 outcomes.*
2. **Deploy and let one review pass run.** Verify archived books are being evaluated
   (`last_evaluated_at` advancing on generations 1/5/6).
3. **Cut over:** make `TRAILING_STOP_25_SECURED_V2` operational, retire
   `TRAILING_STOP_25_V1`, point `PAPER_WALLET_STRATEGY_ID` at the new id, and archive
   generation 2 into generation 7.
4. **Verify:** gen 2's 14 positions still being exited; gen 7's cash is the inherited
   pool minus gen 2's committed $1,400, **not** a fresh $1,000; only gen 7 accepts
   entries.

Step 1 must happen **before** step 3, or generation 2's book is abandoned exactly as
generations 1, 5 and 6 were.

## 6. Not done, deliberately

- No migration. Alembic head unchanged at `0039_token_security`; the main/backup_main
  divergence was not touched.
- No historical trade modified, no Track Record rewritten, no P&L recomputed.
- Holding-period strategy untouched. SEC-2 inactive. Real Wallet untouched.
- Live wallet behaviour unchanged: review output identical, cash identical, 14 open
  positions intact.
