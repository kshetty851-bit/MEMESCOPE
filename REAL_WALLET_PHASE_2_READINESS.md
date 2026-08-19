# Real Wallet Phase 2 readiness

## Verdict

**Manual devnet verification is implementation-ready; mainnet and automated
trading remain blocked.** The only remaining step is a deliberately external
one: an owner must supply a funded devnet-only keypair file and its matching
public address. No live transfer was attempted from this workspace because
those credentials and faucet funds are not configured.

## Architecture

Phase 2 is an admin-only, manual workflow:

```text
read-only quote -> durable intent -> simulation -> explicit approval
-> isolated signer -> one devnet submission -> confirmation -> reconciliation
```

It is deliberately separate from Paper Wallet, Radar/Generation 2, strategy
workers, and all autotrading code. The only executable shape is a very small
native-SOL System Program transfer on a verified Solana devnet endpoint.

## Quote provider

The repository's Jupiter integrations were audited. Their public swap/order
paths are not used for Phase 2 because no reviewed devnet execution route is
available. A mainnet Jupiter quote is never represented as devnet.

The implemented `solana_system_program_devnet` quote is read-only and persists
the wallet, mints, base-unit input/output/minimum output, zero slippage and
price impact, estimated fee, provider reference, route metadata, timestamps,
expiry, and raw-provider reference. It exists solely to verify custody and
ledger plumbing with a safe devnet transfer path; it is not a swap engine.

## Durable ledger and lifecycle

Migration `20260816_0036_real_wallet_devnet_manual.py` creates the separate
`real_wallet_devnet_quotes`, `real_wallet_devnet_intents`, and
`real_wallet_devnet_events` tables. Migration
`20260816_0037_real_wallet_devnet_execution.py` adds complete execution,
approval, simulation, signing, submission, confirmation, reconciliation, and
strict global event-order fields.

Legal lifecycle states are `DRAFT`, `QUOTED`, `SIMULATED`,
`AWAITING_APPROVAL`, `APPROVED`, `SIGNED`, `SUBMITTED`, `CONFIRMED`, `FAILED`,
`CANCELLED`, and `EXPIRED`. State changes use compare-and-swap updates and
append immutable, secret-free audit events. Intent creation is idempotent;
signing and submission have durable claims so retries cannot create a second
signature or send.

## Transaction, simulation, and approval controls

The server constructs the unsigned transaction; a browser never supplies wire
bytes. Before simulation and again in the signer/submission boundary, the
inspector requires exactly:

- verified `devnet` genesis hash;
- one configured wallet fee payer and signer;
- one quoted recipient and exact lamport amount;
- one System Program transfer instruction; and
- no unexpected account, signer, writable account, program, instruction, mint,
  destination, authority, or blockhash shape.

Simulation persists its success/failure, RPC logs, compute units, context slot,
blockhash, timestamp, and raw result. A failure moves the intent to `FAILED`
and blocks approval and signing. Approval requires an admin and the exact
`APPROVE_DEVNET_TRANSFER` phrase; both quote and approval expiries are checked
at every later boundary.

## Isolated signer and submission

Only the opt-in `devnet-signer` process can read
`PHASE2_DEVNET_SIGNER_FILE`; it requires a `0600` JSON keypair file mounted
read-only. API/web/worker processes do not have the field or mount. They can
send an approved intent ID over a Unix-domain socket only.

The signer reloads the authoritative intent, independently verifies devnet,
rebuilds and validates the expected transfer specification, checks expiry and
approval, atomically claims a single signing attempt, and returns only the
signature metadata. It never returns or records secret material. An interrupted
`SIGNING` claim becomes terminal `FAILED` with an unknown signing outcome rather
than risking a second signature.

Submission rechecks devnet, simulation, expiry, signed-byte fingerprint, signer
validation, and transaction semantics. It persists `SUBMITTED` before the sole
`sendTransaction` call. A response timeout is recorded as unknown and is never
retried by re-sending the transaction. Confirmation has bounded polling and
records confirmed, failed, dropped, or still-pending evidence. Reconciliation
only runs after confirmed semantics and persists expected versus actual SOL
delta, recipient output, token delta (`null` for SOL), network fee, execution
price, slippage, and quote-versus-actual output.

## Admin interface

The Real Wallet page exposes the manual sequence and displays the wallet,
destination, input/output, quote/minimum output, slippage, price impact,
estimated fees, quote age and expiry, simulation, intent/approval state,
signature, confirmation, audit events, and reconciliation. It prominently
labels `DEVNET ONLY`, `MAINNET BLOCKED`, and `AUTOTRADE DISABLED`.

There is no automatic approval path, no background signer or submitter, no
Paper Wallet trigger, and no Generation 2 integration.

## Files changed

- Backend workflow and repository: `backend/app/real_wallet/devnet_workflow.py`,
  `devnet_repository.py`, `devnet_intent.py`, and `devnet_transaction.py`.
- Isolated signer boundary: `backend/app/real_wallet/devnet_signer.py`,
  `devnet_signer_client.py`, and `signer.py`.
- Admin API and UI: `backend/app/real_wallet/api.py` and
  `frontend/src/app/(dashboard)/real-wallet/page.tsx`.
- Persistence/config/deployment: `backend/app/models/real_wallet_execution.py`,
  both Phase 2 migrations, `backend/app/core/config.py`, `docker-compose.yml`,
  and environment examples.
- Verification and operator documentation:
  `backend/tests/unit/test_real_wallet_devnet_phase2.py`,
  `backend/tests/integration/test_real_wallet_devnet_phase2.py`,
  `docs/EXECUTION_WALLET_SECURITY.md`, and this report.

## Verification

Focused Phase 2, Real Wallet safety, and related API integration tests: **34
passed**. This includes durable quote/intent/idempotency/audit ordering,
lifecycle/expiry, simulation success and failure, explicit approval, allowlist
rejection, unexpected signer/writable/program/mint/destination/amount checks,
isolated signer unknown/unapproved/expired/restart handling, independent devnet
verification, duplicate sign/submit protection, confirmation, reconciliation,
admin authentication, mainnet hard stops, API secret-path isolation, and
Paper/Radar isolation.

Also passed:

- focused Ruff checks for the Phase 2 implementation and tests;
- frontend TypeScript typecheck, lint, and Prettier check for the Real Wallet
  page; and
- Docker Compose validation, including the opt-in `devnet-signer` profile.

The complete backend suite was also run: **3,754 passed, 39 failed, 63
skipped** in 168.21 seconds. None of the failures is in the Phase 2 files or
its dependency path; they are existing Paper Wallet/track-record,
enrichment-priority, and Yellowstone-shadow failures in the already-dirty
worktree. The in-container full-suite run also skips the Compose source-contract
tests because `docker-compose.yml` is intentionally not mounted there; Compose
itself was validated separately from the repository root.

Repository-wide Ruff likewise reports 186 existing violations in unrelated
research exports, legacy migrations, Paper code, and scripts. The focused Ruff
gate for every Phase 2 implementation and test file passes.

## Live devnet verification blocker and exact operator inputs

No funded devnet signer is present in the workspace. To perform the final live
verification, the owner must provide all of the following outside Git:

1. A **new devnet-only** Solana JSON keypair at an owner-readable path, with
   `chmod 600 /secure/offline/memescope-phase2-devnet.json`.
2. Its matching public address as `REAL_WALLET_PUBLIC_KEY`.
3. At least `0.002 SOL` of faucet-only devnet funds. For an operator with the
   Solana CLI: `solana airdrop 0.002 <REAL_WALLET_PUBLIC_KEY> --url devnet`.
4. An authenticated admin session for the manual UI approval.

With those inputs, run from the repository root (substitute the real path and
public address; do not put either secret bytes or the file path in frontend
configuration):

```bash
export REAL_WALLET_NETWORK=devnet
export REAL_WALLET_RPC_URL=https://api.devnet.solana.com
export REAL_WALLET_PUBLIC_KEY='<matching-devnet-public-key>'
export REAL_WALLET_EXECUTION_SECRET_FILE=''
export PHASE2_DEVNET_SIGNER_SOCKET=/run/memescope-devnet-signer/signer.sock
export PHASE2_DEVNET_SIGNER_FILE_HOST=/secure/offline/memescope-phase2-devnet.json
docker compose --profile devnet-signer up -d --force-recreate backend devnet-signer
```

Then use the admin UI to create a quote for a tiny transfer to a separately
controlled devnet recipient, simulate, explicitly approve, sign, submit,
confirm, and reconcile. This is manual by design; no command above enables
autotrading or mainnet.

## Permanent safety assertions

- **Mainnet blocked:** every Phase 2 execution boundary refuses any configured
  network other than devnet before RPC use and verifies the devnet genesis hash.
- **Autotrade disabled:** `REAL_WALLET_AUTOTRADE_ENABLED=false`; there is no
  Phase 2 scheduler, worker, or automatic approval/submission path.
- **Paper Wallet cannot execute real trades:** no Paper Wallet or Generation 2
  module imports, calls, or writes the Phase 2 execution path or ledger.
