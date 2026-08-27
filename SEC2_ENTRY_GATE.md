# SEC-2 — Strict Security Entry Gate

**Status:** Gate COMPLETE and validated locally. **Generation cutover NOT executed —
blocked on a decision only you can make.** Nothing deployed.

---

## 1. The gate

**One enforcement point, one policy function.** `app/security/entry_policy.py::decide`
is the sole authority; both the service and the repository call it.

```
candidate → eligibility.judge() → strategy.entry_for() → ★ SECURITY GATE ★ → open_position()
                                                              │
                                              repository re-checks the decision
```

Placed after eligibility and sizing (so no RPC is spent on rows that fail cheaper
tests) and before any capital is committed or any execution quote requested.

**Mandatory checks — all must positively PASS:** mint authority, freeze authority,
token program, token extensions, venue, liquidity security.

`TOKEN_EXTENSIONS` is the only check whose `NOT_APPLICABLE` is accepted (a plain SPL
mint has no extensions — a complete answer). The allowlist is deliberate: any other
check returning NOT_APPLICABLE blocks entry until somebody decides otherwise.

### The two-concept separation (§0)

| Situation | Security verdict | Entry | Token labelled unsafe? |
|---|---|---|---|
| All checks pass, fresh | VERIFIED | ALLOWED | — |
| Mint authority active | FAILED | `REFUSED_UNSAFE` | **yes** |
| `LP_OUTSTANDING` | **UNKNOWN** | `REFUSED_UNKNOWN` | **no** |
| RPC outage / no evaluation | UNKNOWN or none | `REFUSED_UNAVAILABLE` | **no** |
| Stale PASS | (unchanged) | `REFUSED_UNAVAILABLE` | **no** |

`LP_OUTSTANDING` stays UNKNOWN and is **never** promoted to FAILED — SEC-1 could not
resolve LP holders, so FAIL would be a claim the platform cannot support. It blocks
entry anyway, because UNKNOWN ≠ PASS.

### TOCTOU

Evidence is re-read immediately before the buy, then age-checked **twice**: against
`MAX_EVIDENCE_AGE` (15 min, derived from the shared contract's shortest per-check
window) and against each check's own window. A PASS that expires between check and
use cannot authorise a buy. Tested in both directions, including evidence dated in
the future.

### The invariant (§24, §41)

`PaperRepository.open_position` refuses to create a position for a security-gated
wallet without a live ALLOW, and **raises** rather than returning `None` — `None`
means "lost the race" and is swallowed as ordinary, so a missing gate reported that
way would vanish into a refusal counter.

It reads the wallet's own `strategy_id` from the database rather than trusting the
caller, so a caller cannot declare itself ungated.

**Bypass audit:** every `insert(PaperPosition)` in the codebase is inside
`repository.open_position`. Both service call sites route through it. A test asserts
no other module contains a `PaperPosition` insert. **0 production-reachable bypasses.**

---

## 2. Two real bugs found and fixed

### The cache was not version-aware

First validation run returned **63.7% retention**, not the ~90% SEC-1 predicted, with
`EVIDENCE_STALE` as the top blocker (23 of 29 blocks).

Cause: `TokenSecurityService.evaluate_candidates` reused cached rows on **freshness
alone**. Rows written by the pre-SEC-1 evaluator (1.0.0) were minutes old and
therefore "fresh", so the cache served them to the gate, which correctly refused them
on version. In production this would mean that after *any* evaluator bump, a full
freshness window of candidates gets blocked while good evidence sits one RPC away.

Fixed: a stored evaluation is reusable only if its `evaluator_version` matches. After
the fix, retention is **91.2%** and `EVIDENCE_STALE` disappears from the block reasons.

### An autouse fixture leaked a mutated singleton (§26)

`tests/conftest.py::force_operational_for_tests` flipped the archived Track Record
strategy to `operational=True` and **never restored it**. Being autouse, the mutation
leaked into every subsequent test in the session, so "exactly one strategy is
operational" read as *two* from inside pytest and the invariant was untestable.

Fixed to restore afterwards. The SEC-2 invariant test additionally shells out to a
clean interpreter with no conftest loaded, so it measures what the worker, scheduler
and API actually import rather than what a fixture did.

---

## 3. Live validation — 80 candidates, no positions created

| Scenario | Result |
|---|---|
| fully verified | **ALLOW** |
| `LP_OUTSTANDING` | REFUSE · `REFUSED_UNKNOWN` |
| mint authority active | REFUSE · `REFUSED_UNSAFE` |
| unsupported venue | REFUSE · `REFUSED_UNSAFE` |
| RPC outage | REFUSE · `REFUSED_UNAVAILABLE` |
| stale PASS | REFUSE · `REFUSED_UNAVAILABLE` · `EVIDENCE_STALE` |
| older evaluator version | REFUSE · `REFUSED_UNAVAILABLE` |

| Outcome | Count | Share |
|---|---|---|
| VERIFIED / would enter | **73** | **91.2%** |
| FAILED / blocked (unsafe) | 0 | 0.0% |
| UNKNOWN / blocked | 6 | 7.5% |
| Infrastructure / temp blocked | 1 | 1.2% |

**Block reasons:** `LP_OUTSTANDING` 3 · `VENUE_UNKNOWN` 2 ·
`LIQUIDITY_SECURITY_UNVERIFIED` 1 · `POOL_NOT_PROTOCOL_MIGRATED` 1 ·
`MIGRATION_DESTINATION_UNVERIFIED` 1

**By venue:** pumpswap 78 (73 enter / 5 blocked) · no market data 2 (blocked).

**Gate latency:** 0.35 s per candidate. ~3 RPC calls, reused from SEC-1's cache in
the steady state.

SEC-1 predicted ~90% strict retention. **Observed 91.2%.**

---

## 4. ⚠️ THE CUTOVER IS BLOCKED — three architectural conflicts

The gate is built and the new strategy `trailing_stop_25_secured_v2` is declared. It
is **not operational**, and I did not run the cutover, because the repository's
generation architecture makes it destructive in three ways that the brief explicitly
told me to stop on.

**A new generation archives the current wallet. Archived wallets are never advanced** —
`repository.py`: *"nothing advances positions that belong to one"*. This is
observable in the live data:

| Generation | Open positions | Last evaluated |
|---|---|---|
| 1 (archived) | 6 | 2026-08-05 — 15 days ago |
| 5 (archived) | 98 | 2026-08-16 — 4 days ago |
| 6 (archived) | 1 | 2026-08-16 |
| **2 (live)** | **14** | **minutes ago** |

**1. It would abandon 14 open positions holding $1,400.** They would never reach
their trailing stops. That directly contradicts §11 ("continue under their original
exit logic"), §43 ("existing positions continue to be managed") and §44 ("EXIT STILL
OCCURS").

**2. It would mint a fresh $1,000 (§28).** Every generation starts at
`PAPER_WALLET_STARTING_BALANCE`. Gen 2 currently has $1,400 committed to open
positions on a compounded book — a new wallet does not inherit it.

**3. The new wallet would be blind to old positions for capacity (§29).**
`metrics.cash_for` derives cash from a wallet's *own* starting balance and its *own*
positions, so generation 7 would allocate a full $1,000 while $1,400 sits committed
elsewhere.

### Options

| Option | Effect |
|---|---|
| **A. Wait for gen 2 to flatten**, then cut over | No abandonment, no duplication. Positions have no expiry, so this could take a long time. |
| **B. Cut over now, accept abandonment** | 14 positions frozen mid-trade; Track Record gains 14 permanently-open rows that never resolve. |
| **C. Build managed-archive first** | Let archived wallets keep running exits while refusing new entries. A real change to generation architecture — its own phase. |
| **D. Enable the gate on generation 2 in place** | No new generation, no abandonment, no capital change. But it mixes two entry policies inside one Track Record, which §10 forbids. |

**My recommendation: C, then A.** Option C removes the abandonment problem
permanently — and it is worth doing regardless, because gens 1/5/6 already have 105
positions frozen mid-trade whose recorded outcome is simply wrong. Once archived
wallets exit properly, the cutover becomes safe at any moment.

Flipping the gate on afterwards is a two-line change: make
`TRAILING_STOP_25_SECURED_V2` operational and point `PAPER_WALLET_STRATEGY_ID` at it.

---

## 5. Safety

- Paper entry behaviour **unchanged in the running system** — generation 2 is
  ungated, and the live review pass is byte-identical in shape after restarting the
  worker on SEC-2 code.
- No position modified · no Track Record rewritten · no historical security fabricated.
- **No migration.** The evaluation reference is recorded in the existing
  `paper_decision_snapshots.availability` JSONB. Alembic head unchanged at
  `0039_token_security`.
- Real Wallet untouched; all barriers closed; 0 mainnet transactions.
- Exit path isolation asserted by test: no exit function references the gate, and
  `_security_for_entry` has exactly one call site.

## 6. Unresolved gaps

1. **Archived-wallet exits** — the blocker above. 105 positions across gens 1/5/6 are
   already frozen mid-trade.
2. **LP holder resolution** — `LP_OUTSTANDING` stays UNKNOWN; resolving holders would
   let creator-held LP be classified FAIL and would recover ~4% of blocked flow.
3. **Non-pump.fun venues** — Orca/Raydium/Meteora get no custody verdict, so any such
   token is blocked by construction.
