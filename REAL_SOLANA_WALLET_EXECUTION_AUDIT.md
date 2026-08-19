# Real Solana wallet and live-execution audit

Audit date: 2026-08-15  
Scope: read-only repository, Git history, and read-only local runtime/database
inspection. No wallet was created, no signer was loaded, no chain balance was
read, and no transaction or real SOL was used.

## Executive conclusion

MEMESCOPE has a serious **pre-mainnet foundation**, including a wallet generator,
public-address balance reader, safety gate, dry-run flow, persistent lifecycle
ledger, signer helper, transaction-evidence verifier, and mock-only reconciliation
coverage. It is **not a working real-money trading system**.

The active runtime is safely inert:

| Runtime fact | Observed value |
| --- | --- |
| Execution mode | `disabled` |
| Execution enabled | `false` |
| Autotrade enabled | `false` |
| Dry-run feature | `false` |
| Public wallet address configured | no |
| Secret-file path configured | no |
| Code-level live release approved | `false` |
| Submission permitted | `false` |
| Live intents / real positions / execution events | 0 / 0 / 0 |

The active database does contain 121 safety evaluations and 20 dry-run intent
records (19 `BLOCKED`, 1 `WOULD_BUY`). Those are research/simulation evidence;
they are not wallet trades. All real-wallet migrations are applied through
`0028_radar_forward_quality (head)`.

## Completion table

Percentages measure the intended production capability, not the amount of code.
`COMPLETE` means the named narrow component is implemented; it does not make the
overall real-money system production-ready.

| Component | Status | % Complete | Evidence | Remaining work |
| --- | --- | ---: | --- | --- |
| **A. Wallet/keypair creation** | COMPLETE | 90% | `generate_wallet.py` makes non-overwritable Solana JSON keypairs with `0600` mode and prints only the public key. | No actual configured wallet exists in this runtime; operator process and backup ceremony still required. |
| Wallet address generation/display | PARTIAL | 60% | Admin-only `/real-wallet/status` and `/real-wallet` render the public key and copy/Solscan link. | Configure a dedicated address through deployment; no user-owned wallet model or address management exists. |
| Secure private-key storage | PARTIAL | 45% | `FileExecutionSigner` accepts a file, rejects broad permissions, and pins its derived key to config. | No secret manager, Docker secret, production mount, isolated signing service, rotation procedure, or access separation. |
| Encryption at rest | NOT STARTED | 0% | Key material is a raw Solana JSON file, protected only by filesystem permissions. | Choose and implement host/KMS/HSM or secret-manager encryption and recovery controls. |
| Secret loading | PARTIAL | 45% | File-path loader exists; raw key bytes are not returned by API/models. | Production Compose resets service volumes and supplies no signer-secret mount or Docker secret. |
| Wallet recovery/import | PARTIAL | 20% | Security document requires offline backup and recovery outside MEMESCOPE. | No audited import/recovery workflow, rotation runbook, or recovery verification. |
| RPC integration | PARTIAL | 55% | Public `getBalance`, mint inspection, and transaction reconciliation adapters exist. | No production wallet-read/reconciliation service is wired to a live executor or independently exercised against devnet/mainnet. |
| Network selection | NOT STARTED | 10% | Global RPC defaults point at mainnet-beta. | Explicit cluster selection, devnet configuration/profile, chain-ID assertions, and environment separation. |
| Mainnet/devnet safeguards | PARTIAL | 65% | Test sandbox refuses external `/execute`; a code constant blocks live submission regardless of environment. | No devnet execution path; global defaults being mainnet means safe operator rehearsal is incomplete. |
| **B. Receive/fund SOL** | PARTIAL | 30% | A generated Solana address can receive an external manual transfer; security doc describes manual funding. | No configured wallet today, funding UI, QR code, transfer workflow, or funding confirmation. |
| Wallet address in UI | PARTIAL | 60% | Admin real-wallet page shows/copies configured public address. | Runtime address is empty; route is not surfaced in normal navigation. |
| QR code | NOT STARTED | 0% | No QR component or API found. | Add a read-only address QR after funding workflow/security review. |
| SOL balance and refresh | PARTIAL | 55% | Public-RPC `getBalance` helper and 30-second UI refresh exist. | No configured address, no runtime validation, no devnet/mainnet verification, and no fee-reserve presentation based on actual balance. |
| SPL token balances / ATA visibility | NOT STARTED | 0% | No `getTokenAccountsByOwner`, ATA inventory, or token-balance endpoint/UI exists. | Build read-only SPL/Token-2022 balance and associated-token-account inventory. |
| Blockchain transaction history | NOT STARTED | 0% | No `getSignaturesForAddress` or chain-history view exists. | Build paginated, reconciled history; distinguish submitted, confirmed, failed, and unknown records. |
| **C. Jupiter quote** | PARTIAL | 65% | Paper quote client, safety-gate buy/sell quotes, and V2 `/order` dry-run client exist. | Validate actual V2 production order contract and freshness under a dedicated executor; paper quote support is not execution. |
| Jupiter swap transaction construction | PARTIAL | 35% | V2 `/order` evidence is captured in dry run; test lifecycle accepts a prepared mock transaction. | No production order-to-unsigned-transaction path is wired; dry-run deliberately omits transaction payloads. |
| Transaction signing | PARTIAL | 45% | `FileExecutionSigner.sign_jupiter_transaction` validates single signer and taker/payer before signing. | It is deliberately unwired from production; needs isolated signer ownership, intent/evidence integration, and devnet proof. |
| Transaction submission | BLOCKED | 5% | `JupiterLiveExecutionTransport` exists, but `LIVE_TRANSPORT_RELEASE_APPROVED = False`; no production lifecycle installs/calls it. | Implement and review a production executor; retain multi-gate release approval and host allowlist. |
| Confirmation and settlement | PARTIAL | 50% | RPC reconciler derives wallet-owned token deltas; ledger only settles verified exact deltas. | Wire a durable production reconciliation worker, confirmation policy, retries/polling, alerts, and live verification. |
| Buy token / sell token | BLOCKED | 10% | Test-only lifecycle has mock BUY/SELL; dry run records only `WOULD_BUY`. | No manual or automatic real buy/sell endpoint, worker, or transaction path. |
| Slippage and price impact | PARTIAL | 55% | Safety gate checks directional quote impact, price deviation, round-trip loss; paper quotes use 50 bps. | Bind approved slippage/min-output to real V2 order and signed transaction; add operator-visible quote preview. |
| Priority fees | PARTIAL | 25% | Configured SOL priority-fee reserve exists for accounting. | No evidence it is added to a live order/transaction; no dynamic fee policy or confirmation accounting. |
| Failed transaction handling | PARTIAL | 50% | Mock lifecycle marks uncertain submissions non-retryable; reconciliation and kill-switch counters exist. | Wire live transport/reconciliation, notification/incident response, and controlled operator resolution. |
| Retry/idempotency | PARTIAL | 60% | Unique intent keys, state transitions, and no-resubmit-on-unknown behavior are tested. | Apply to a real executor and production queue/restart scenarios. |
| Transaction signature persistence | PARTIAL | 55% | Schema persists signatures and unique constraints; mock lifecycle covers them. | No live signatures or production submission path. |
| **D. Live positions and cost basis** | PARTIAL | 50% | Separate real position/intents/events tables retain exact raw amounts, cost basis, signatures, and safety links. | No real records; only mock lifecycle populates the model. |
| Current value / unrealized P&L | NOT STARTED | 0% | No live mark-to-market service or UI fields found. | Add fresh-price valuation, confidence/freshness, and stale/unavailable handling. |
| Realized P&L / execution fees | PARTIAL | 50% | Confirmed lifecycle calculates gross; net uses timestamped SOL/USD and fails honest-null when unavailable. | Validate against real transactions; add reporting and tax/accounting policy. |
| Real transaction history | PARTIAL | 30% | Internal intent/event/position tables exist and appear on admin page. | No chain-history feed, no live records, and no user-facing transaction detail. |
| Blockchain reconciliation | PARTIAL | 50% | Reconciler checks RPC transaction metadata and wallet-owned input/output deltas. | No scheduled production reconciliation path or real-chain validation. |
| **E. Manual real trading UI/API** | NOT STARTED | 0% | `/real-wallet` is explicitly read-only; no POST buy/sell routes or buttons. | Build privileged intent/quote/confirmation/status UX only after executor security review. |
| Amount selection / quote preview / confirmation UX | NOT STARTED | 0% | No real-wallet form components found. | Add bounded amount input, server quote, explicit review, expiry, and status/error states. |
| **F. Automated real trading** | BLOCKED | 15% | Dry-run reuses ranked Radar eligibility, strategy entry rule, safety gate, policy, and V2 orders. | No production bridge from an approved signal to real intent, signing, submit, confirm, or live position. |
| **G. Real exit automation** | NOT STARTED | 10% | Sell intent binding to a confirmed quantity and fee reserve primitives exist. | Implement real price/position monitoring, explicit TP/stop/trailing policy, exit-only mode, sell executor, and failed-exit handling. |
| Paper exit automation (separate) | COMPLETE | 95% | Paper wallet has target, hard stop, trailing stop, expiry, and manual paper sell logic. | This remains simulation and does not execute against real funds. |
| **H. Security controls** | PARTIAL | 55% | Key-file permission/pinning, admin read-only status route, no secret API fields, `.env` ignored, host allowlist, limits, safety gate, state machine, and test sandbox exist. | Production secret isolation, key rotation/recovery, live rate/approval controls, operator kill-switch management, observability/alerting, and independent review. |
| **I. Frontend real-wallet visibility** | PARTIAL | 40% | `/real-wallet` shows public address, SOL balance, readiness, dry-run data, limits, and mock-ledger positions. | No nav link, QR, SPL balances, chain history, manual trade UI, transaction states, or real P&L/current value. `/wallet` is paper-only. |
| **J. Test coverage** | PARTIAL | 65% | Unit/integration coverage exists for generation, signer, balance, safety, dry run, order evidence, transport policy, mock lifecycle, reconciliation, and admin route. | All execution/signing/submission coverage is mocked/test-sandbox only; no devnet or mainnet verification found. |

## Overall completion

| Measure | Completion |
| --- | ---: |
| **OVERALL REAL WALLET COMPLETION** | **30%** |
| **OVERALL LIVE EXECUTION COMPLETION** | **20%** |
| **OVERALL AUTOMATED TRADING COMPLETION** | **15%** |

These conservative figures reflect that no real wallet is currently configured,
no signing key is mounted, and production submission is intentionally impossible.

## What works today

- An operator can generate a dedicated Solana-compatible keypair locally without
  touching a network. This was not done during this audit.
- The code can securely enough for development load a properly permissioned key
  file and verify it matches a configured public key; no such file is configured
  in the active runtime.
- The admin-only read-only endpoint can display a configured public address and
  read its SOL balance through public RPC. The active environment has no address.
- The independent safety gate can evaluate provenance, token configuration,
  market freshness/liquidity, and buy/sell quote risk, then persist an audit row.
- The autonomous **dry-run** can evaluate the published entry signal and record
  blocked/`WOULD_BUY` evidence without signing or submitting.
- Mock-only tests demonstrate an idempotent intent lifecycle, uncertain-submit
  handling, chain-delta reconciliation, position ledger accounting, and kill
  switch behavior.

## What does not work today

- There is no configured real wallet, secret mount, funding confirmation, QR,
  SPL-token inventory, ATA inventory, or blockchain transaction history.
- There is no manual buy/sell API or UI, quote-preview confirmation UX, or real
  transaction-status screen.
- No process turns a live Radar opportunity into a real execution intent.
- No production component requests an executable Jupiter transaction, verifies
  its semantic evidence, signs it, calls Jupiter `/execute`, confirms it, or
  opens/closes a position from an actual chain result.
- No real exit automation, real mark-to-market/unrealized P&L, or real failed
  exit recovery exists.
- No devnet execution environment or devnet verification path exists.

## Exact automated-trading stop point

The implemented dry-run chain is:

```text
Radar ranking -> paper eligibility + published entry rule -> real-wallet safety gate
-> conservative dry-run policy -> Jupiter V2 /order evidence -> persisted WOULD_BUY/BLOCKED
```

It stops **before an executable transaction is retained or requested for a
real intent**. The dry-run uses an ephemeral taker public key and intentionally
has no signer or `/execute` capability. The separate lifecycle/transport code
is test-only or fail-closed; `LIVE_TRANSPORT_RELEASE_APPROVED` is `False` and
there is no production service wiring it into Radar, a worker, or an API route.

## Paper versus real exits

| Capability | Paper wallet | Real wallet |
| --- | --- | --- |
| Take profit / hard stop / trailing stop / expiry | Implemented simulation | Not implemented for real funds |
| Manual sell | Implemented paper-only API and UI | No API/UI |
| Automatic sell | Paper review cycle | No real executor or monitor |
| Jupiter route | Quote evidence only | Dry-run V2 order evidence only |
| Settlement | Simulated accounting | Mock lifecycle/reconciliation primitives only |

## Security findings and funding blockers

### Positive controls already present

- `.env` files and conventional key/certificate extensions are ignored; no
  tracked keypair or `.env` file was found.
- The status endpoint requires the `ADMIN` role and returns no key material.
- The signer verifies file permissions and public-key pinning.
- The current configuration is fail-closed and requires both configuration flags
  and a separate code review switch before submission can ever be considered.
- The V2 host allowlist and test sandbox prevent a test from targeting Jupiter.
- The order-evidence verifier, exact sell position binding, unique signatures,
  idempotency keys, and unknown-submission reconciliation model are sound
  defensive primitives.

### Funding blockers

Do **not** deposit real SOL until all of these are resolved:

1. Create an approved production secret-management design. There is no Docker
   `secrets:` configuration or read-only key-file mount. In the production
   overlay, backend/worker volumes are reset, so the documented future secret
   path cannot currently be delivered to a container.
2. Isolate signing to a minimal execution service/process. The present signer
   helper can be imported by the backend, and the read-only status endpoint can
   load it merely to report readiness; a future secret should not be available
   to general web/API processes.
3. Add a deliberate devnet profile and rehearsal flow. Current global Solana
   defaults target mainnet-beta; no devnet execution configuration or tests were
   found.
4. Establish key generation, offline backup, recovery, rotation, access review,
   incident response, and compromise-response procedures beyond documentation.
5. Build read-only SPL/Token-2022/ATA balances and reconciled transaction history
   so a funded wallet can be independently observed before it is permitted to act.
6. Complete a security review of log/trace redaction and deployment access for
   any future signer-bearing service.

## Before the first real trade

In addition to the funding blockers:

1. Implement one production executor that consumes a persisted, approved intent
   and performs: fresh quote/order -> semantic order-evidence verification ->
   signer call -> guarded `/execute` -> signature persistence -> confirmation ->
   independent RPC reconciliation. It must not retry an uncertain submission.
2. Bind real balance, fee reserve, position/exposure/notional/daily-loss limits,
   cooldown, and active kill switches to that executor—not merely to dry-run
   state or UI settings.
3. Add privileged manual-trade intent and quote-review UX, including amount
   validation, expiry, two-step confirmation, status/error history, and no
   browser access to key material.
4. Exercise the entire flow on devnet, then perform a separately approved,
   tiny, manually reviewed mainnet canary with monitoring and an exit plan.
5. Implement operational alerts, durable reconciliation scheduling, on-call
   runbooks, and an operator-managed kill switch/exit-only procedure.

## Before automated trading

In addition to first-trade readiness:

1. Implement and validate real exit automation before enabling unattended
   entries: fresh pricing, TP/hard-stop/trailing policy, sell intent binding,
   fee reserve, exit-only mode, and failed-exit escalation.
2. Prove long-running reconciliation, restart recovery, quote staleness,
   provider outage, partial-fill/unknown-result, and kill-switch behavior in
   devnet/staging and a restricted canary.
3. Separate the approved real strategy version from paper research explicitly;
   the existing dry-run uses paper eligibility and strategy primitives, but that
   is not authorization to automate real funds.
4. Require an explicit reviewed code change for the existing release constant,
   followed by production approval, deployment verification, and bounded capital
   limits. Environment changes alone must never be enough.

## Recommended implementation roadmap

### Phase 1 — secure deployment and observation (1–2 engineer-weeks)

Build the production signer isolation/secret mount or secret-manager integration,
operator key lifecycle, devnet configuration, and read-only SOL/SPL/ATA/history
views. Add deployment and redaction tests. Keep execution disabled.

### Phase 2 — devnet manual executor (2–3 engineer-weeks)

Implement the durable production intent worker and wire the existing evidence,
signer, transport, confirmation, reconciliation, fee reserve, and policy gates.
Add a manual privileged quote/confirm/status surface. Prove no duplicate submit
and no secret exposure on devnet.

### Phase 3 — controlled mainnet manual canary (1–2 engineer-weeks plus review)

Add alerts, reconciliation scheduling, incident runbooks, operator kill switch,
exit-only procedure, and a small-capital approval workflow. Run a manually
reviewed canary only after independent security review.

### Phase 4 — live position monitoring and exits (2–3 engineer-weeks)

Implement live marks/unrealized P&L, transaction history, TP/stop/trailing exit
decisioning, sell execution, failure escalation, and long-duration restart/outage
tests. Do not enable automated entries before this phase is proven.

### Phase 5 — bounded automation (2–4 engineer-weeks plus soak time)

Connect an explicitly approved strategy to the real intent service, retain all
current caps, add review/alerting/metrics, and conduct a staged low-capital soak.
Only then consider changing the code-level release gate through review.

Estimated remaining implementation scope: **8–14 engineer-weeks**, excluding
security review, devnet/mainnet soak periods, and operational approval time.

## Routes and files inspected

- Real wallet API: `GET /api/v1/real-wallet/status` (admin-only, read-only).
- Real wallet UI: `/real-wallet` in
  `frontend/src/app/(dashboard)/real-wallet/page.tsx`.
- `/wallet` in `frontend/src/app/(dashboard)/wallet/page.tsx` is the **paper
  wallet only**.
- Real-wallet implementation: `backend/app/real_wallet/` and
  `backend/app/real_wallet_safety/`.
- Persistence migrations: `0018`, `0020`–`0025` (plus the paper-only Jupiter
  metadata migration `0015`).
- Security documentation: `docs/EXECUTION_WALLET_SECURITY.md`.
- Tests: execution wallet, safety, dry run, live readiness/transport, order
  evidence, SOL fee pricing, and mock real-wallet lifecycle suites.

No code, configuration, wallet, private key, transaction, or production setting
was modified by this audit.
