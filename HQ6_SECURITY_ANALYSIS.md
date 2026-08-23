# HQ-6 — Shared Token Security Contract & Impact Analysis

**Status:** COMPLETE. Read-only. No Paper Wallet behaviour was changed.
**Date:** 2026-08-20 · **Evaluator version:** 1.0.0

---

## 0. The premise correction that shaped this phase

The brief asked us to "audit exactly what `verify_liquidity_security()` currently
proves."

**It proves nothing, because it does not exist and never has.** It was invented by
an earlier agent, imported into `backend/app/paper/service.py`, and removed in
commit `3bac791` ("fix(backend): remove hallucinated security import") three hours
before this phase began. The reason codes the brief attributed to it —
`LIQUIDITY_UNLOCKED`, `LIQUIDITY_SECURITY_UNKNOWN` — appear nowhere in the
repository's history.

There has never been LP-ownership, LP-burn, lock, or protocol-custody verification
anywhere in MEMESCOPE. Everything below follows from that fact.

---

## 1. Security coverage matrix

| Check | Paper today | Real Wallet today | Shared evaluator | Evidence quality |
|---|---|---|---|---|
| Mint authority | **NOT CHECKED** | CHECKED (fail-closed) | CHECKED (PASS/FAIL/UNKNOWN) | On-chain, `getAccountInfo` |
| Freeze authority | **NOT CHECKED** | CHECKED | CHECKED | On-chain |
| Token program | **NOT CHECKED** | CHECKED | CHECKED | On-chain |
| Token-2022 extensions | **NOT CHECKED** | CHECKED (allowlist) | CHECKED (allowlist + danger list) | On-chain |
| Transfer fee / permanent delegate / transfer hook / non-transferable / default account state | **NOT CHECKED** | Indirectly (allowlist rejects) | CHECKED (named, explicit) | On-chain |
| Venue | **NOT CHECKED** | CHECKED (string match) | CHECKED (string match) | **Name comparison only** |
| Liquidity amount | CHECKED (`> 0`) | CHECKED (threshold + ratio) | not a security check | Market snapshot |
| **Liquidity security / LP custody** | **NOT CHECKED** | **NOT CHECKED** | **UNKNOWN, always** | **NONE — never implemented** |
| Pool authenticity | NOT CHECKED | NOT CHECKED | NOT CHECKED | none |
| Price impact | NOT CHECKED | CHECKED | out of scope (market quality) | Jupiter quote |
| Round-trip loss | NOT CHECKED | CHECKED | out of scope | Jupiter quote |
| Sellability / honeypot | NOT CHECKED | Indirectly (sell route) | NOT CHECKED | none |
| Quote freshness | NOT CHECKED | CHECKED | out of scope | Jupiter |
| Market freshness | NOT CHECKED | CHECKED | out of scope | Snapshot age |
| Trading status | CHECKED | CHECKED | out of scope | Provider field |
| Provenance (pump.fun program) | NOT CHECKED | CHECKED | not re-implemented | Discovery record |

**Paper Wallet's entry path performs zero token-security checks.** `judge()` in
`app/paper/eligibility.py` evaluates: already-traded, already-held, has-snapshot,
has-price, `trading_status == "trading"`, `liquidity > 0`. Nothing else.

Checks that exist but are **not actually called** in the audited deployment: the
entire `RealWalletSafetyGate`, because `REAL_WALLET_EXECUTION_MODE=disabled`.

---

## 2. Pump.fun / PumpSwap security semantics

The only venue logic in the codebase is:

```python
snapshot.dex_name.lower() in {"pumpfun", "pumpswap"}
```

A string comparison. It is **venue recognition**, not custody verification.

**Pump.fun (bonding curve):** while a token is on its curve there is no LP position
to own, burn or lock — the curve account *is* the market and the program holds the
reserves. Custody is a **protocol property**. But this platform does not read the
curve account, so it cannot demonstrate a given token is still on the curve rather
than graduated. → **UNKNOWN**, not PASS.

**PumpSwap (graduated AMM):** whether LP tokens are burned, locked, or held by a
deployer who can pull them is a fact about a specific pool account **that this
platform has never fetched**. → **PROTOCOL ASSUMPTION ONLY. UNKNOWN**, not PASS.

174 of the live wallet's 182 positions are on PumpSwap, so this is precisely the
wrong place to guess. The UI is forbidden from rendering the word "locked"
(asserted by test).

---

## 3. Current candidate security funnel — measured

Sample: 80 highest-scored active Radar candidates, evaluated live 2026-08-20.

```
432   radar tokens (all time)
432   active on radar
432   active and priced
 80   evaluated (sample)
  ↓
  0   security VERIFIED    (0.0%)
  1   security FAILED      (1.2%)
 79   security UNKNOWN    (98.8%)
```

Per-check, across all 216 evaluations written this phase:

| Check | PASS | FAIL | UNKNOWN |
|---|---|---|---|
| MINT_AUTHORITY | 216 | 0 | 0 |
| FREEZE_AUTHORITY | 216 | 0 | 0 |
| TOKEN_PROGRAM | 216 | 0 | 0 |
| TOKEN_EXTENSIONS | 216 | 0 | 0 |
| VENUE | 207 | 2 | 7 |
| **LIQUIDITY_SECURITY** | **0** | **0** | **216** |

**Failures by reason:** `VENUE_UNSUPPORTED` × 2 (both `orca`).

**What drives UNKNOWN:** `LIQUIDITY_SECURITY` — 100%. Nothing else.

Every pump.fun token evaluated has both authorities already revoked and carries no
Token-2022 extensions. The authority checks are, on current evidence, free.

---

## 4. Existing Paper trade analysis (generation 2, live wallet)

100 most recent positions re-inspected. **Historical limitation applied strictly:**

- authority **ACTIVE today** → was necessarily active at entry (`SetAuthority(None)`
  is irreversible). Sound, one-directional inference.
- authority **REVOKED today** → says nothing about entry. **UNKNOWN.**
- venue / liquidity → current only, never historical.

| Bucket | Count | Closed | Win rate | Net PnL | Profit factor |
|---|---|---|---|---|---|
| **VERIFIED at entry** | **0** | — | — | — | — |
| **FAILED at entry (provable)** | **0** | 0 | — | — | — |
| **UNKNOWN** | **100** | 86 | 31.4% | **+$164.65** | 1.15 |

**No historical position has entry-time security evidence, so none can be called
verified.** No PASS was manufactured. The absence of a VERIFIED bucket is the
finding, not a gap in the analysis.

---

## 5. If VERIFIED were required today

| Outcome | Count | Share |
|---|---|---|
| Would pass | 0 | **0.0%** |
| Blocked — positively unsafe | 1 | 1.2% |
| Blocked — UNKNOWN | 79 | 98.8% |

**Requiring VERIFIED would stop the strategy trading entirely**, and would do so for
a reason that has nothing to do with any token being unsafe: `LIQUIDITY_SECURITY`
is unverifiable for every venue MEMESCOPE trades, because the verification was
never built.

**UNKNOWN here is an observability problem, not a risk signal.**

---

## 6. Recommended future policy — **C (HYBRID by check)**

Do **not** implement yet. Recommendation only.

- **A — Require VERIFIED:** blocks 100% of flow. Not viable until LP verification
  exists.
- **B — Fail only positively unsafe:** blocks 1.2%. Keeps flow, but silently accepts
  a token whose mint authority is live the day one appears.
- **C — Hybrid by check (recommended):** require `PASS` on `MINT_AUTHORITY`,
  `FREEZE_AUTHORITY`, `TOKEN_PROGRAM`, `TOKEN_EXTENSIONS` and `VENUE`; accept
  `UNKNOWN` **only** on `LIQUIDITY_SECURITY`, and only while it is unimplemented.

**Why C, from the measured evidence:** the five checks C requires currently pass at
100%, 100%, 100%, 100% and 97% — so C costs ~1.2% of candidate flow today while
closing a real hole (Paper would otherwise buy the `orca` token, since `judge()`
never looks at venue). It fails closed the moment a live-authority token appears,
which is the case that actually matters. And it makes the liquidity exemption
**explicit and temporary** rather than hiding it inside a blanket "allow UNKNOWN".

**The real next piece of work** is verifying LP custody — read the pool account and
LP mint supply. Until that exists, no policy can honestly reach VERIFIED.

---

## 7. The uncomfortable truth HQ now displays

Paper Wallet still does not consult token security. A Token Case File can therefore
truthfully show, simultaneously:

```
ATLAS     — FAILED (VENUE_UNSUPPORTED) or UNKNOWN
DECISION  — PASSED
REX       — BOUGHT
```

This is not hidden or smoothed. It is asserted by test
(`case-file.test.ts` → "Atlas and Rex may disagree, and HQ must say so").
