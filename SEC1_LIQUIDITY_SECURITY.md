# SEC-1 — On-Chain Liquidity Security Verification

**Status:** COMPLETE. Read-only. No Paper behaviour changed. No enforcement enabled.
**Date:** 2026-08-20 · **Evaluator version:** 1.0.0 → **1.1.0**

---

## 1. Protocol facts, established from live chain state

Nothing below is from memory. Each was decoded from mainnet during this phase.

### PumpSwap pool account — 301 bytes, discriminator `f19a6d0411b16dbc`

| offset | size | field |
|---|---|---|
| 0 | 8 | discriminator |
| 8 | 1 | pool_bump |
| 9 | 2 | index (u16) |
| 11 | 32 | **creator** |
| 43 | 32 | base_mint |
| 75 | 32 | quote_mint |
| 107 | 32 | lp_mint |
| 139 | 32 | pool_base_token_account |
| 171 | 32 | pool_quote_token_account |
| 203 | 8 | lp_supply *(pool's own notional record)* |
| 211 | 32 | coin_creator |

Confirmed against ground truth: decoded `base_mint` equalled the token under
investigation and `quote_mint` equalled wrapped SOL, on 5/5 independent pools.

Program IDs, read from account owners rather than recalled:
- pump.fun `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`
- PumpSwap `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`

### The derivation that makes this cryptographic

```
pool_authority = PDA(["pool-authority", mint], PUMPFUN)     # matched 5/5
pool           = PDA(["pool", u16(0), pool_authority,
                      mint, WSOL], PUMPSWAP)                # matched 3/3
```

Every observed `creator` is **off-curve** — no private key can exist for it.
Because the pool address is *computed* from the migration authority, a matching
account is itself proof of pump.fun migration provenance. It also means the
platform never searches for a pool, so there is no "which of its pools did we
check" ambiguity (§12) and no `getProgramAccounts` scan.

### Why `LP supply == 0` is not a security check

Tested rather than assumed. A random sample of **60 live pools found all 60
with LP supply zero** — but only 11 were pump.fun migrations. The other 49 were
**drained** pools holding dust (0.000000004 base / 0.00497 quote). Their LP
supply is zero because every LP token was *redeemed* — the liquidity was pulled.

**A naive "LP supply is zero → PASS" rule would have called all 49 secure.**

Zero LP supply is necessary, never sufficient. It only means something beside
proof that the pool is a protocol migration. A wider scan of 200 pools found 5
with non-zero LP supply, so the check discriminates rather than being vacuous.

---

## 2. What a PASS proves — and what it does not

**PASS answers exactly one question:** can the token's creator unilaterally
remove the liquidity backing the market this platform prices?

`PUMPSWAP_MIGRATED_LP_BURNED` requires **all** of:
1. account at the *derived* canonical pool address exists
2. owner is the PumpSwap program; discriminator and 301-byte size match
3. `base_mint` is this token and `quote_mint` is WSOL
4. `creator` equals the derived pump.fun migration authority
5. both vaults readable, mints correct, **authority is the pool PDA**
6. **LP mint supply is 0** — no redeemable claim on the reserves exists
7. the venue/pool the platform prices *is* the pool that was verified

`BONDING_CURVE_CUSTODY` requires the curve account to exist, be owned by
pump.fun, decode, and report `complete == false`.

**A PASS does NOT mean:** the token is safe, cannot rug, cannot collapse in
price, is sellable, or has a safe contract. Mint authority, freeze authority and
Token-2022 extensions are separate checks in the same evaluation. Sellability is
deliberately not folded in (§14).

**Stated limit on the curve verdict:** it proves no *creator* withdrawal path
exists through account authority. It does not prove the pump.fun program itself
contains no privileged instruction — that is a program-audit question, not an
account-state one, and this module does not claim to have answered it.

**The word "locked" is never displayed.** What gets proven is protocol custody
or a burned migration LP; neither is a locker. Asserted by test.

---

## 3. A real bug this phase caught in its own logic

Mint `GbM8TcLhMnRAda4ccagVvxRXiiDa7sQvPFKUivqNpump` is **genuinely still on its
pump.fun bonding curve** — 24.5% progress, 6.6 SOL of real reserves — and the
curve custody verdict for it is entirely correct.

It also has an **Orca** pool holding **$194,646**, and Orca is the venue
MEMESCOPE prices and would trade.

The first implementation returned PASS. That PASS was true about the wrong
market: the curve's 6.6 SOL is secure, the $194k that actually backs the price
was never examined. A `_traded_market_guard` now refuses any PASS whose verified
mechanism is not the market the platform reads, emitting
`TRADED_POOL_UNVERIFIED`. This is also §12's multiple-pool rule: rather than
picking a pool, the evaluator refuses when the traded one is not the derived one.

---

## 4. Live results — 80 current candidates

| | HQ-6 baseline | **SEC-1** |
|---|---|---|
| VERIFIED | 0 (0.0%) | **72 (90.0%)** |
| FAILED | 1 (1.2%) | 0 (0.0%) |
| UNKNOWN | 79 (98.8%) | **8 (10.0%)** |

`LIQUIDITY_SECURITY` specifically: **74 PASS (92.5%)**, 6 UNKNOWN — against
216/216 UNKNOWN at HQ-6.

**Mechanisms:** `PUMPSWAP_MIGRATED_LP_BURNED` 74 · `NONE` 6

**UNKNOWN reasons — all implementation-complete, none an implementation gap:**

| Reason | Count | Meaning |
|---|---|---|
| `LP_OUTSTANDING` | 4 | Redeemable LP genuinely exists; holders not resolved |
| `MIGRATION_DESTINATION_UNVERIFIED` | 1 | Graduated, liquidity not at the derived pool |
| `POOL_NOT_PROTOCOL_MIGRATED` | 1 | No pump.fun migration pool |
| `LIQUIDITY_SECURITY_UNVERIFIED` | 1 | RPC failure |

**By venue:** pumpswap 78 (72 verified / 6 unknown) · no market data 2 (unknown).

**Failures:** none in this sample. The one `VENUE_UNSUPPORTED` failure from the
HQ-6 baseline (an Orca token) is no longer in the top-80.

---

## 5. Policy retention — measured, neither enabled

| Policy | Retains |
|---|---|
| **STRICT** — liquidity must PASS | **72 / 80 = 90.0%** |
| **HYBRID C** — liquidity UNKNOWN allowed | 78 / 80 = 97.5% |

At HQ-6 STRICT retained **0%** and was unusable. It now retains 90%, and the
gap to Hybrid C is **7.5 percentage points**.

---

## 6. Open paper positions — CURRENT security, not entry-time

14 open positions audited read-only. **Nothing was modified.**

| | Count |
|---|---|
| VERIFIED | 11 (78.6%) |
| FAILED | **0** |
| UNKNOWN | 3 (1 `LP_OUTSTANDING`, 2 no market data) |

**No dangerous condition was found**, so there is nothing to escalate. These are
current states and are **not** entry-time evidence; they must never be read as
retroactive justification for any past entry.

---

## 7. Performance

- **~3 RPC calls per token**: one `getMultipleAccounts` for [curve, pool], one
  for [lp_mint, base_vault, quote_vault], plus the existing mint `getAccountInfo`.
- **0.85 s/token** on the public `api.mainnet-beta.solana.com` endpoint,
  dominated by its rate limiting; the client's existing backoff absorbed it.
- No `getProgramAccounts`. No unbounded fan-out. Sequential, capped by
  `TOKEN_SECURITY_MAX_PER_PASS` (25).
- Cache: `LIQUIDITY_SECURITY` keeps HQ-6's 15-minute freshness window — it is
  dynamic state and is deliberately the shortest window in the contract.

---

## 8. Recommended SEC-2 policy — **STRICT**, with one carve-out

The HQ-6 recommendation (Hybrid C) was made when strict retention was 0%. That
constraint is gone.

**Recommend requiring `LIQUIDITY_SECURITY == PASS`** for new Paper entries,
because the 10% it excludes is not noise:
- 4 of 8 exclusions are `LP_OUTSTANDING` — a genuinely withdrawable LP position,
  the exact risk this phase was built to detect;
- 2 are tokens with no market data, which `judge()` already refuses;
- 1 is a graduated token whose liquidity is somewhere unverified;
- 1 is a transient RPC failure, which retries.

The carve-out: an RPC outage must not halt trading. `LIQUIDITY_SECURITY_UNVERIFIED`
(infrastructure) should be distinguished from the evidence-based UNKNOWNs before
enforcement, or a provider incident becomes a trading incident.

**Not implemented. Not enabled.**

---

## 9. Unresolved gaps

1. **LP holder resolution.** `LP_OUTSTANDING` is UNKNOWN, not FAIL, because
   holders are not resolved. `getTokenLargestAccounts` on the LP mint would let
   creator-held LP be positively classified as FAIL.
2. **Non-pump.fun venues are unverifiable.** Orca, Raydium and Meteora pools get
   no custody verdict at all. Every such token is UNKNOWN by construction.
3. **Program-level trust.** Neither pump.fun nor PumpSwap has been audited here
   for privileged instructions. Custody is proven at the account level only.
