# Real wallet Phase 1 readiness

Date: 2026-08-15  
Scope: secure custody boundary and read-only wallet observation. No production
wallet was created, no key was configured, no wallet was funded, and no
transaction was signed or submitted.

## Verdict

**Phase 1 is ready for secure, read-only devnet observation. It is not ready
for a mainnet transaction or funding.**

The application remains fail-closed: `REAL_WALLET_EXECUTION_MODE=disabled`,
`REAL_WALLET_EXECUTION_ENABLED=false`,
`REAL_WALLET_AUTOTRADE_ENABLED=false`, and the reviewed transport release
constant remains `False`. A further Phase-1 mainnet guard refuses `/execute`
whenever the declared wallet network is `mainnet`.

## Architecture reused

- The dedicated admin-only `GET /api/v1/real-wallet/status` surface remains
  read-only.
- Existing transport policy, safety gate, exposure limits, kill-switch ledger,
  idempotency model, order-evidence verification, and Jupiter V2 `/order`
  client are retained. No scanner, Radar, forward-quality instrumentation,
  paper strategy, or paper accounting was changed.
- Existing `FileExecutionSigner` remains an explicit offline primitive only;
  it is not called by the API, worker, scheduler, or frontend.

## Security and custody model

- The status API no longer loads a signer to calculate a readiness badge. It
  returns only `signer_status=not_available_to_api`.
- Application settings now reject `REAL_WALLET_EXECUTION_SECRET_FILE`. This
  prevents a secret mount from being accidentally shared with the API, worker,
  scanner, or scheduler before an isolated signer service exists.
- There is no key field in API responses, database models, logs, or frontend
  payloads. The existing key-file permission and public-key pinning checks stay
  available to an explicit local operator command.
- A future signing service must be separately reviewed, mount a read-only
  deployment secret only into that service, and expose a narrow authenticated
  signing protocol. It is deliberately not part of this phase.

## Wallet initialization and recovery

`python -m app.real_wallet.wallet_init --create --output <secure-keypair-path>
--backup-manifest <secure-proof-path>` creates a non-overwritable, `0600`
Solana JSON keypair without network access. `--import-from <existing-keypair>`
supports the same one-time, validated owner-only copy.

The required backup manifest contains only the public address and a SHA-256
fingerprint; it never contains recovery material. Operators must verify a
separate encrypted offline backup before any future funding. Automated tests
use temporary test keypairs only.

## Network safeguards

- `REAL_WALLET_NETWORK` is explicit (`devnet` by default) and uses a dedicated
  `REAL_WALLET_RPC_URL`; it cannot inherit the scanner's mainnet RPC.
- The status API calls `getGenesisHash` before reading a configured wallet's
  SOL or SPL balances. On a mismatch or unavailable RPC it returns an
  unverified status and no balance.
- The verified devnet identity is
  `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`.
- Mainnet execution is blocked centrally even if all older release flags are
  hypothetically enabled.

## Read-only balance support

- SOL: `getBalance` at confirmed commitment.
- SPL and Token-2022: separate `getTokenAccountsByOwner` calls return token
  account, mint, raw quantity, formatted quantity, decimals, and program id.
- Name, symbol, and image are included only when the mint already has local
  discovered-token metadata. Chain balances are never derived from paper
  wallet accounting.

## API and frontend

The real-wallet admin page now shows the active network, RPC verification,
wallet address/copy/explorer link, SOL balance, SPL balances, execution and
autotrade state, custody boundary, and existing safety/readiness controls. It
has a prominent **LIVE EXECUTION DISABLED** banner.

The funding surface provides a `solana:<address>` receive URI and copy action.
It intentionally does not use a third-party QR renderer, which would disclose
the address to another service. There is no funding action, Buy button,
signing control, or submission control.

## Jupiter readiness

The existing V2 client remains `/order`-only. Its tested evidence retains
request id, route plan, price impact, and latency while omitting transaction
payloads. Order-evidence tests cover taker/mint/amount binding, slippage,
minimum output, quote freshness, price impact, and route evidence. There is no
`/execute` method on this client.

## Verification completed

- Focused backend wallet suite: **76 passed**.
- Backend changed-file Ruff: passed.
- Frontend Prettier, TypeScript, and ESLint: passed.
- Docker Compose syntax: passed.
- Read-only devnet `getGenesisHash`: verified the stated devnet identity. No
  wallet address was queried; no SOL or transaction was used.

## Main risks and next phase

The project still has no configured production wallet, isolated signer
service, secret manager/KMS integration, funding workflow, transaction history,
manual intent executor, confirmation worker, or mainnet canary approval. Do
not fund or enable mainnet execution. Phase 2 should begin only after a
separate security review authorizes an isolated signer and a devnet manual
executor.

## Updated completion estimate

| Capability | Before Phase 1 | After Phase 1 |
| --- | ---: | ---: |
| Real-wallet foundation | 30% | 45% |
| Live execution | 20% | 20% |
| Automated trading | 15% | 15% |

The increased foundation score reflects custody hardening, explicit network
verification, read-only SPL visibility, and the operational initialization
workflow. It does not imply readiness to hold or trade real funds.
