# Safety boundary

This package is advisory and offline by construction.

- It has no wallet, signing, RPC submission, exchange, deployment, migration, or production-write client.
- It never reads credentials from configuration examples.
- Score output contains `execution_authorized=false` and `production_write_authorized=false`.
- The integration outbox requires an explicit `--acknowledge-no-execution` flag and is written atomically with owner-only permissions.
- Use a technically read-only database role for extraction. Never reuse a trading-service credential.
- A downstream system must not interpret `ACCEPT` as an order instruction. It is a research decision for paper/shadow evaluation.
