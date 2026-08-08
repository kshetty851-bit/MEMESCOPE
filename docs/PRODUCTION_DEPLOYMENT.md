# MEMESCOPE Production Deployment Runbook

This runbook prepares the existing MEMESCOPE stack for one Ubuntu VPS running Docker Compose, Caddy, PostgreSQL, Redis, FastAPI, Next.js, scanner, enrichment, scheduler, and worker containers.

It does not purchase a server, change DNS, or expose the app publicly. Do those only after a local production rehearsal passes.

## 1. Production architecture

```mermaid
flowchart TD
    internet["External users"] --> caddy["Caddy :80/:443"]
    caddy --> frontend["Next.js frontend :3000"]
    caddy --> backend["FastAPI backend :8000"]
    backend --> postgres["PostgreSQL volume: postgres-data"]
    backend --> redis["Redis volume: redis-data"]
    scanner["Scanner"] --> redis
    scanner --> postgres
    enrichment["Market enrichment"] --> redis
    enrichment --> postgres
    scheduler["Celery beat scheduler"] --> redis
    worker["Celery worker"] --> redis
    worker --> postgres
    backup["Backup container"] --> postgres
    backup --> backups["backup-data volume"]
```

Public ports: `80`, `443`, and `443/udp` for HTTP/3. PostgreSQL, Redis, backend, frontend, workers, scanner, and enrichment stay on the internal Docker network.

## 2. Existing production assets

| Asset | Status | Notes |
| --- | --- | --- |
| `docker-compose.prod.yml` | Ready | Production overlay with Caddy, production image targets, no public database/cache ports, restart policies, resource limits, and backup service. |
| `docker-compose.yml` | Ready | Base service graph and shared backend environment anchor used by API, workers, scanner, and enrichment. |
| `docker/caddy/Caddyfile` | Ready | Automatic TLS through Caddy, frontend catch-all, API and WebSocket reverse proxy, long read timeout for live stream. |
| `backend/Dockerfile` | Ready | Development and production targets. Backend healthcheck uses `/live`. |
| `frontend/Dockerfile` | Ready | Production Next.js image target. |
| `scripts/deploy.sh` | Ready | Fetches release, validates Compose config, backs up, builds, migrates, starts, smoke-tests, and rolls back code on verification failure. |
| `scripts/rollback.sh` | Ready with caution | Rolls code back to a previous commit. It does not downgrade database migrations. |
| `scripts/backup.sh` | Ready | `pg_dump -Fc` backups with 7 daily, 4 weekly, 6 monthly retention. |
| `scripts/restore.sh` | Partial | Interactive destructive restore for an intended target database. Use the restore drill below for safe testing. |
| `.env.production.example` | Ready | Template only. Copy to `.env.production`; never commit real secrets. |
| `docker/nginx/nginx.conf` | Stale | Superseded by Caddy. Retained but unused. |

## 3. Minimum VPS recommendation

Measured locally from the working tree only: repository footprint is about 1.3 GB, with the frontend dependency/build area responsible for most of it. Runtime database size and container memory were not measured in this environment.

Provisional starting point for private alpha:

- Ubuntu 24.04 LTS
- 4 vCPU
- 8 GB RAM
- 80 GB SSD
- 2 GB swap
- Daily off-host backup copy if available from the VPS provider

For a very small private alpha, 2 vCPU / 4 GB RAM may run, but it leaves little headroom for Next.js builds, Postgres, Redis, scanner bursts, and enrichment at the same time.

## 4. Create the VPS

Use a reputable VPS provider and create an Ubuntu 24.04 LTS server. Keep password SSH disabled where practical and use SSH keys.

Open only:

- `22/tcp` for SSH, ideally restricted to your IP
- `80/tcp` for Caddy ACME HTTP challenge
- `443/tcp` for HTTPS
- `443/udp` optional for HTTP/3

Do not open PostgreSQL, Redis, backend, frontend, scanner, enrichment, scheduler, or worker ports.

## 5. Connect through SSH

```bash
ssh root@YOUR_SERVER_IP
```

Create an application user:

```bash
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
su - deploy
```

## 6. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git ufw
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker deploy
```

Log out and back in so the Docker group membership applies.

## 7. Configure the firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

If your provider firewall is separate, mirror the same rule set there.

## 8. Clone MEMESCOPE

```bash
mkdir -p ~/apps
cd ~/apps
git clone YOUR_REPOSITORY_URL MEMESCOPE
cd MEMESCOPE
```

Checkout the release branch, tag, or commit you intend to deploy:

```bash
git fetch --all --tags --prune
git checkout YOUR_RELEASE_REF
```

## 9. Configure `.env.production`

```bash
cp .env.production.example .env.production
chmod 600 .env.production
nano .env.production
```

Required values:

- `ENVIRONMENT=production`
- `DEBUG=false`
- `DOMAIN`
- `ACME_EMAIL`
- `SECRET_KEY`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `ALLOWED_HOSTS`
- `CORS_ORIGINS`
- `NEXT_PUBLIC_API_URL`
- `BASE_URL`
- `FRONTEND_URL`
- `ALPHA_ACCESS_CODE`
- `ALPHA_ACCESS_REQUIRED=true`
- `ALPHA_ACCESS_COOKIE_SECURE=true`
- `SOLANA_RPC_PROVIDER`
- `SOLANA_RPC_URL`
- `SOLANA_WS_URL`
- `HELIUS_API_KEY` when the scanner uses Helius

Generate secrets:

```bash
openssl rand -hex 32
openssl rand -base64 48
```

Use different values for `SECRET_KEY`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`.

The temporary alpha code remains `619554` until you change it, but it now belongs only in backend/server configuration. Do not create a `NEXT_PUBLIC_*` alpha code.

## 10. Point DNS

In your DNS provider, create:

```text
A     YOUR_DOMAIN     YOUR_SERVER_IP
AAAA  YOUR_DOMAIN     YOUR_IPV6_ADDRESS   optional
```

Wait for DNS to resolve:

```bash
dig +short YOUR_DOMAIN
```

Do not start Caddy for the final domain until DNS points at the VPS, otherwise certificate issuance can fail.

## 11. Validate production configuration

```bash
set -a
. ./.env.production
set +a
docker compose -f docker-compose.yml -f docker-compose.prod.yml config -q
```

Inspect the rendered config for accidental public ports:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config | grep -n "published:"
```

Only Caddy should publish public ports in the production overlay.

## 12. Build and start the stack

Use the deployment script for normal releases:

```bash
./scripts/deploy.sh --ref YOUR_RELEASE_REF
```

Manual equivalent:

```bash
set -a
. ./.env.production
set +a
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --no-deps backend alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --remove-orphans
```

## 13. Verify HTTPS

```bash
curl -I https://YOUR_DOMAIN/
curl -fsS https://YOUR_DOMAIN/live
curl -fsS https://YOUR_DOMAIN/ready
```

Expected:

- HTTPS certificate is valid.
- `/live` returns 200.
- `/ready` returns 200 with database and Redis status ok.

## 14. Verify Alpha Access

Unlock without printing the code:

```bash
set -a
. ./.env.production
set +a
COOKIE_JAR="$(mktemp)"
ALPHA_PAYLOAD="$(mktemp)"
chmod 600 "$ALPHA_PAYLOAD"
printf '{"code":"%s"}' "$ALPHA_ACCESS_CODE" >"$ALPHA_PAYLOAD"
curl -fsS -c "$COOKIE_JAR" \
  -H 'Content-Type: application/json' \
  -X POST \
  --data-binary "@${ALPHA_PAYLOAD}" \
  "https://${DOMAIN}/api/v1/alpha/unlock"
curl -fsS -b "$COOKIE_JAR" "https://${DOMAIN}/api/v1/alpha/session"
rm -f "$COOKIE_JAR" "$ALPHA_PAYLOAD"
```

Expected: `"authenticated": true`.

## 15. Verify WebSocket

The live browser stream is:

```text
wss://YOUR_DOMAIN/api/v1/tokens/stream
```

Because alpha access is cookie-based, verify WebSocket behavior in a browser after unlocking the alpha screen. In production, unauthenticated WebSocket connections should close with policy violation.

## 16. Verify scanner, enrichment, Radar, scheduler, worker, and Paper Wallet

Check container health and logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 scanner
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 enrichment
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 scheduler
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 worker
```

Check the pipeline health endpoint:

```bash
curl -fsS "https://YOUR_DOMAIN/api/v1/health/pipeline"
```

Use `scripts/health-check.sh` for the deploy smoke test:

```bash
set -a
. ./.env.production
set +a
./scripts/health-check.sh
```

The scanner, enrichment, Radar, and Paper Wallet are considered healthy only if `/api/v1/health/pipeline` reports fresh enough stage timestamps under the configured thresholds.

## 17. Verify reboot recovery

```bash
sudo reboot
```

Reconnect after the server returns:

```bash
cd ~/apps/MEMESCOPE
set -a
. ./.env.production
set +a
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
./scripts/health-check.sh
```

Expected restart behavior:

- PostgreSQL: `unless-stopped`
- Redis: `unless-stopped`
- Backend: `unless-stopped`
- Frontend: `unless-stopped`
- Scheduler: `unless-stopped`
- Worker: `unless-stopped`
- Caddy: `unless-stopped`
- Backup: `unless-stopped`
- Scanner: `on-failure`, so a disabled scanner stays stopped but crashes restart
- Enrichment: `on-failure`, so a disabled enrichment worker stays stopped but crashes restart

## 18. Backups

The production backup service runs `scripts/backup-loop.sh`, which repeatedly calls `scripts/backup.sh`.

Retention:

- 7 daily backups
- 4 weekly backups
- 6 monthly backups

Backup location:

```text
backup-data:/backups
```

List backups:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backup find /backups -maxdepth 2 -type f | sort
```

Trigger a one-off backup:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --entrypoint /bin/sh backup /scripts/backup.sh
```

Backups are not proven safe until a restore drill passes.

## 19. Safe restore drill

This drill restores into a separate temporary database container and does not overwrite production.

Create a backup first:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --entrypoint /bin/sh backup /scripts/backup.sh
```

Choose the newest backup:

```bash
LATEST_BACKUP="$(docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backup sh -c 'ls -1t /backups/daily/*.dump | head -1')"
echo "$LATEST_BACKUP"
```

Start an isolated restore database:

```bash
docker run -d --name memescope-restore-drill \
  --network memescope_default \
  -e POSTGRES_USER=memescope \
  -e POSTGRES_PASSWORD=restore-drill-only \
  -e POSTGRES_DB=memescope_restore \
  postgres:16-alpine
```

Wait for readiness:

```bash
until docker exec memescope-restore-drill pg_isready -U memescope -d memescope_restore; do sleep 2; done
```

Restore the dump:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backup \
  sh -c "cat '$LATEST_BACKUP'" | \
docker exec -i memescope-restore-drill pg_restore \
  --dbname=postgresql://memescope:restore-drill-only@localhost:5432/memescope_restore \
  --clean --if-exists --no-owner --no-privileges --verbose
```

Verify tables and row counts:

```bash
docker exec memescope-restore-drill psql \
  postgresql://memescope:restore-drill-only@localhost:5432/memescope_restore \
  -c "\dt" \
  -c "select count(*) as discovered_tokens from discovered_tokens;" \
  -c "select count(*) as token_market_snapshots from token_market_snapshots;" \
  -c "select count(*) as paper_trade_audit from paper_trade_audit;"
```

Destroy the drill container:

```bash
docker rm -f memescope-restore-drill
```

If any restore step fails, treat backups as unverified and do not publicly launch.

## 20. Logs and rotation

Application containers write logs to stdout/stderr. Production backend logs use JSON when `LOG_FORMAT=json`.

View logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 scanner
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 enrichment
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 scheduler
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 caddy
```

Recommended host-level Docker log rotation:

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
JSON
sudo systemctl restart docker
```

Do not log `.env.production`, access codes, database passwords, Redis passwords, refresh tokens, alpha cookies, or API keys.

## 21. Rollback

Normal rollback:

```bash
./scripts/rollback.sh --to PREVIOUS_COMMIT_SHA
```

Rollback is unsafe when:

- the new release applied a destructive migration;
- the older code cannot read the newer schema;
- data was transformed forward-only;
- a restore has not been tested.

The repository rollback script intentionally does not run Alembic downgrades. Use the database backup if the schema or data must be restored.

## 22. Pre-launch security checklist

Before public deployment, verify:

- `DEBUG=false`
- `ENVIRONMENT=production`
- no secrets committed to git
- `SECRET_KEY` is unique and at least 32 characters
- no default PostgreSQL password
- no default Redis password
- `ALLOWED_HOSTS` is explicit
- `CORS_ORIGINS` is explicit
- `REFRESH_COOKIE_SECURE=true`
- `ALPHA_ACCESS_REQUIRED=true`
- `ALPHA_ACCESS_COOKIE_SECURE=true`
- no `NEXT_PUBLIC_ALPHA_ACCESS_CODE`
- Redis has no public port
- PostgreSQL has no public port
- backend and frontend internal ports are not public
- API docs exposure is intentional; by default production disables docs
- WebSocket stream is protected by alpha cookie in production
- rate limiting remains enabled
- dependency vulnerabilities are reviewed in release notes

Current dependency audit status from the local frontend container on 2026-08-08:

- `npm audit --audit-level=moderate` reports 8 findings: 1 moderate, 7 high.
- Reported packages: `brace-expansion`, `esbuild`, `js-yaml`, `nanoid`, `postcss`, `sharp`, plus transitive `vite` and `next` exposure.
- The `postcss` and `sharp` findings are currently tied to `next`; npm proposes `npm audit fix --force`, which would install Next 16.3.0 and is a breaking framework upgrade.
- Do not publicly deploy until these findings are either safely upgraded or explicitly accepted with reachability analysis in the release checklist.

## 23. Expected monthly infrastructure

Provisional private-alpha estimate:

- VPS: one 4 vCPU / 8 GB RAM / 80 GB SSD instance
- Storage: database volume, Redis AOF volume, Caddy cert volume, backup volume
- Bandwidth: dependent on external users and live stream sessions
- Optional: external object storage or provider snapshots for off-host backups
- Optional: hosted monitoring/error reporting if `SENTRY_DSN` is configured

Do not assume this single-node setup supports unlimited public traffic. It is the simplest 24/7 alpha deployment target.
