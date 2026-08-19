# MEMESCOPE Execution Wallet Security

## Purpose and boundary

The MEMESCOPE execution wallet is a dedicated, low-balance Solana hot wallet for a future autonomous-execution release. It is not a browser wallet and is never connected to an operator's personal wallet. Scanner, Radar, strategy, and the frontend cannot call its signer directly.

Creating or funding this wallet does not enable trading. The current supported modes are `disabled` and `dry_run`; default mode is `disabled`. Phase 2 adds one intentionally separate exception: an admin-operated, **devnet-only** native-SOL transfer verification flow. It cannot route a Jupiter swap, cannot create a position, cannot call a strategy, and cannot run automatically. There is still no funding operation, withdrawal operation, or autotrade control.

## Generate locally

Use the backend runtime on a secure operator machine. Choose a directory that is not inside this repository and is excluded from cloud sync:

```bash
cd backend
python -m app.real_wallet.generate_wallet --output /secure/offline/memescope-execution.json
```

The command generates a Solana-compatible JSON keypair file with owner-only (`0600`) permissions. It prints the **public address** and the secret-file location; it deliberately does not print raw secret bytes. It makes no RPC call and cannot send SOL or submit a transaction.

Immediately make an offline backup of the secret file (for example, encrypted removable media stored separately). Verify the backup by comparing its public address using an offline tool. MEMESCOPE cannot recover a lost secret.

Never place the keypair file or its bytes in Git, PostgreSQL, Redis, Celery task arguments, logs, an API response, frontend source, a `NEXT_PUBLIC_*` variable, a Docker image, screenshots, chat, or automatic cloud storage.

## Configure the public address and secret boundary

Set only the public address in runtime configuration:

```dotenv
REAL_WALLET_PUBLIC_KEY=<public-address>
REAL_WALLET_EXECUTION_MODE=disabled
REAL_WALLET_EXECUTION_ENABLED=false
REAL_WALLET_AUTOTRADE_ENABLED=false
```

No application container may mount or load a signing key.
`REAL_WALLET_EXECUTION_SECRET_FILE` is rejected at startup so a path cannot
accidentally give the API, workers, scanner, or scheduler access to custody
material. `FileExecutionSigner` checks that the derived public address exactly
matches `REAL_WALLET_PUBLIC_KEY`; a mismatch fails closed with
`execution_wallet_public_key_mismatch`.

The current wallet dashboard reads balance through public Solana RPC and works without a secret file. It displays only the public address and read-only balance.

## Phase 2 manual devnet signer

The only process allowed to read a signer file is the opt-in
`devnet-signer` Compose profile. It receives an owner-only (`0600`) read-only
mount at `/run/secrets/phase2-devnet-signer.json`. The API, worker, scheduler,
scanner, and frontend receive at most `PHASE2_DEVNET_SIGNER_SOCKET`; they never
receive the file path or transaction bytes for signing.

The API can send only an approved intent ID through a Unix-domain socket. The
signer then reloads the authoritative PostgreSQL record, re-verifies the
devnet genesis hash, checks quote and approval expiry, reconstructs the allowed
native-SOL transfer specification, and independently inspects the transaction.
It allows exactly one legacy System Program transfer with the configured wallet
as the sole signer/fee payer, the quoted destination, the quoted lamport amount,
and no additional accounts, writable accounts, programs, or instructions.

The signer persistently claims `SIGNING` before it reads the secret. It signs
once, stores the signed transaction and validation evidence in the protected
execution ledger, and returns only the intent ID and transaction signature. If
the process dies after the claim, the next signer invocation marks the outcome
unknown and terminally fails the intent rather than attempting a second
signature. No private material is placed in an API response, database field,
event, task payload, or log.

This flow always refuses `REAL_WALLET_NETWORK` values other than `devnet`, and
also refuses an RPC endpoint whose genesis hash is not Solana devnet. It has no
mainnet route. The only quote provider currently available is the explicit
`solana_system_program_devnet` transfer path. Jupiter's public swap flow is not
used because no reviewed devnet swap route was found; a mainnet Jupiter quote is
never relabelled as devnet.

## Funding and recovery

Funding is manual: copy the public address from the admin-only Real Wallet page, open a personal wallet independently, and manually transfer a limited amount of SOL. MEMESCOPE never pulls funds from a personal wallet. For a first future live test, keep the balance approximately **0.05–0.10 SOL**, not savings or meaningful capital.

The current hard limits remain deliberately small: maximum trade `$5`, one position, `$10` total exposure, `$20` daily notional, `$10` daily realized loss, and a retained SOL fee reserve. A future execution policy must retain enough SOL for transaction and exit fees.

There is no automatic withdrawal capability. Future recovery/withdrawal must be an explicit, separately authorized operator workflow using the offline backup—not strategy code. Do not create a `withdraw_all_to_external_address` capability in autonomous trading code.

## Kill switches and future authorization

Even once live support exists, a wallet presence is not authorization. A new entry must require all of: a strategy signal, a fresh RealWalletSafetyGate pass, autonomous-policy pass, verified signer, limits pass, `REAL_WALLET_EXECUTION_MODE=live`, `REAL_WALLET_EXECUTION_ENABLED=true`, and `REAL_WALLET_AUTOTRADE_ENABLED=true`. Unknown, stale, missing, or failed evidence means no entry.

Keep the three controls disabled to stop new execution. A future exit-only mode must be distinct from disabling entries, so it can liquidate already-held positions safely.

## Compromise model

This is a hot wallet: compromise is possible. Its protection is isolation from the personal wallet, a low balance, public-key pinning, strict backend-only secret handling, and independent safety/policy controls. If the server may be compromised, disable execution/autotrade, move any funds using the offline backup from a clean machine, rotate the wallet, and never reuse the potentially exposed keypair.
