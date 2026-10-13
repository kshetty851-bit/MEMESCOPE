# Safety boundary

The scoring package is advisory. The explicitly launched service is paper-only.

- It has no wallet, signing, RPC submission, exchange or wallet-write client. Deployment helpers provision only its dedicated read-only market role, isolated container and paper volume.
- It never reads credentials from configuration examples.
- Score output contains `execution_authorized=false` and `production_write_authorized=false`.
- The integration outbox requires an explicit `--acknowledge-no-execution` flag and is written atomically with owner-only permissions.
- Use a technically read-only database role for extraction. Never reuse a trading-service credential.
- A downstream system must not interpret `ACCEPT` as an order instruction. It is a research decision for paper/shadow evaluation.

The service uses a SELECT-only database role, explicit read-only transactions, its own SQLite ledger, a single-process lock and atomic fill/assessment writes. Status requests validate the existing alpha cookie server-side. No mutation API exists. It retains the latest 10,000 non-fill assessments and all fill-linked assessments to bound storage. The scoring fallback remains explicitly rules-only; missing safety data cannot authorize an entry.
