#!/usr/bin/env bash
# One-command deployment: pull, build, migrate, restart, verify, roll back on failure.
#
#   ./scripts/deploy.sh                 # deploy origin/main
#   ./scripts/deploy.sh --ref v0.2.0    # deploy a tag
#   ./scripts/deploy.sh --no-rollback   # keep a broken release for inspection
#
# THE ROLLBACK CONTRACT
#
# Before anything changes, the current commit is recorded and the database is
# backed up. If verification fails afterwards, both are restored automatically.
# The point is that a failed deploy costs the time of one rollback rather than
# an incident: the operator is not left deciding what to do while the site is
# down.
#
# What rollback does NOT do is reverse a migration. Migrations are forward-only
# here, so the backup is the recovery path for a schema change that goes wrong —
# which is why the backup is taken *before* `alembic upgrade`, not after.

set -euo pipefail

cd "$(dirname "$0")/.."

REF="origin/main"
ROLLBACK=1
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

while [ $# -gt 0 ]; do
	case "$1" in
	--ref)
		REF="$2"
		shift 2
		;;
	--no-rollback)
		ROLLBACK=0
		shift
		;;
	*)
		echo "unknown argument: $1" >&2
		exit 2
		;;
	esac
done

log() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
die() {
	printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2
	exit 1
}

[ -f .env.production ] || die ".env.production is missing. Copy .env.production.example and fill it in."

# Everything below reads the production environment. Exported rather than passed
# so `docker compose` interpolation sees it.
set -a
# shellcheck disable=SC1091
. ./.env.production
set +a

PREVIOUS_SHA="$(git rev-parse HEAD)"
log "Current release: ${PREVIOUS_SHA:0:12}"

# --- 1. Pull -----------------------------------------------------------------
log "Fetching ${REF}"
git fetch --all --tags --prune
git checkout --detach "$REF"
NEW_SHA="$(git rev-parse HEAD)"
export BUILD_SHA="${NEW_SHA:0:12}"
log "Deploying: ${BUILD_SHA}"

# --- 2. Back up --------------------------------------------------------------
# Before the build, so a build that takes ten minutes does not widen the window
# between the backup and the migration it exists to protect.
log "Backing up the database"
"${COMPOSE[@]}" run --rm --entrypoint /bin/sh backup /scripts/backup.sh \
	|| die "Backup failed — refusing to deploy without a restore point."

# --- 3. Build ----------------------------------------------------------------
log "Building images"
"${COMPOSE[@]}" build --pull

# --- 4. Migrate --------------------------------------------------------------
# Run as a one-off before the new code starts, so the schema is never behind the
# application that expects it.
log "Applying migrations"
"${COMPOSE[@]}" run --rm --no-deps backend alembic upgrade head \
	|| die "Migration failed. Database unchanged beyond any partial migration; restore from the backup above."

# --- 5. Restart --------------------------------------------------------------
log "Starting services"
"${COMPOSE[@]}" up -d --remove-orphans

# --- 6. Verify ---------------------------------------------------------------
log "Waiting for the stack to settle"
deadline=$((SECONDS + 120))
until curl -sf -o /dev/null -m 5 "${BASE_URL:-http://localhost:8001}/ready"; do
	if [ "$SECONDS" -ge "$deadline" ]; then
		echo "readiness did not come up within 120s" >&2
		break
	fi
	sleep 3
done

log "Verifying"
if ./scripts/health-check.sh; then
	log "Deployed ${BUILD_SHA} successfully"
	"${COMPOSE[@]}" ps
	exit 0
fi

# --- 7. Roll back ------------------------------------------------------------
if [ "$ROLLBACK" -eq 0 ]; then
	die "Verification failed. --no-rollback set, leaving ${BUILD_SHA} running for inspection."
fi

printf '\n\033[31m✗ Verification failed — rolling back to %s\033[0m\n' "${PREVIOUS_SHA:0:12}" >&2
exec ./scripts/rollback.sh --to "$PREVIOUS_SHA"
