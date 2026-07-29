#!/usr/bin/env bash
# Return the deployment to a previous commit.
#
#   ./scripts/rollback.sh                    # previous commit
#   ./scripts/rollback.sh --to <sha>         # a specific one
#
# Called automatically by deploy.sh when verification fails, and safe to run by
# hand.
#
# SCHEMA IS NOT ROLLED BACK. Migrations are forward-only, so this restores the
# *code* only. That is the right default: most failed deploys are application
# faults, and additive migrations are compatible with the previous release. When
# a migration is genuinely the problem, restore a backup with scripts/restore.sh
# — this script tells you so rather than pretending it handled it.

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
TARGET=""

while [ $# -gt 0 ]; do
	case "$1" in
	--to)
		TARGET="$2"
		shift 2
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

[ -f .env.production ] || die ".env.production is missing."
set -a
# shellcheck disable=SC1091
. ./.env.production
set +a

if [ -z "$TARGET" ]; then
	TARGET="$(git rev-parse 'HEAD@{1}' 2>/dev/null)" || die "No previous commit recorded. Pass --to <sha>."
fi

git rev-parse --verify "$TARGET" >/dev/null 2>&1 || die "Unknown commit: $TARGET"

log "Rolling back to ${TARGET:0:12}"
git checkout --detach "$TARGET"
export BUILD_SHA="${TARGET:0:12}"

log "Rebuilding"
"${COMPOSE[@]}" build

log "Starting services"
"${COMPOSE[@]}" up -d --remove-orphans

log "Waiting for readiness"
deadline=$((SECONDS + 120))
until curl -sf -o /dev/null -m 5 "${BASE_URL:-http://localhost:8001}/ready"; do
	[ "$SECONDS" -ge "$deadline" ] && break
	sleep 3
done

log "Verifying"
if ./scripts/health-check.sh; then
	log "Rolled back to ${BUILD_SHA}"
	exit 0
fi

# A failed rollback is the worst state this system can be in, so it says exactly
# what to do next rather than exiting on a bare non-zero.
cat >&2 <<'EOF'

✗ ROLLBACK FAILED — the previous release is not healthy either.

This usually means the database schema has moved ahead of the code. Next steps:

  1. Inspect:  docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail 100
  2. Restore:  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
                 run --rm backup /scripts/restore.sh /backups/daily/<newest>.dump
  3. Verify:   ./scripts/health-check.sh

EOF
exit 1
