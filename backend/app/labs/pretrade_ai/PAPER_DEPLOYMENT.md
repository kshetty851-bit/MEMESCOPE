# Paper service deployment

The same `/pretrade-ai` page polls `/api/v1/labs/pretrade-ai/status`. A dedicated container scans every 30 seconds independently of the page. It validates every status request through the existing internal `/api/v1/alpha/session`; invalid cookies fail closed. No write endpoint exists.

Build the lab directory with `Dockerfile.paper`. Set `PRETRADE_READ_DSN` to a dedicated PostgreSQL login with SELECT only on grad_migrations, grad_tokens and grad_postgrad_samples, and default_transaction_read_only=on. Set `PRETRADE_STATE=/data/paper.sqlite3`; mount a persistent named volume writable by uid 10001. Do not supply exchange, signer, wallet or existing application secrets. Connect to the backend's private Docker network; do not publish its port to the host.

Caddy routes only `/api/v1/labs/pretrade-ai/*` to `pretrade-ai:8011`. The normal backend route is unchanged. Validate configuration before graceful reload. No wallet/worker container restarts are needed. The service is deliberately not added to application startup or existing strategy scheduling.

Rollback: stop the `memescope-pretrade-ai` container and restore the preceding Caddy file, then validate/reload. Preserve the paper volume. Other services remain running. Source review and frontend release are separate from the host-side service rollout.

Current limitation: four of 21 features can be mapped honestly from these tables. The supplied code requires all eight hard-gate fields and 65% completeness, so live discovery currently produces INSUFFICIENT_DATA assessments and no buys. Additional timestamped authority, swap, route, holder and identity evidence must be collected before eligibility can be achieved; public five-minute counts must not be relabeled as lifetime swaps. The trade engine is verified using explicit test fixtures, not presented as demonstrated real-market profitability.
