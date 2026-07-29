#!/bin/sh
# Restore a PostgreSQL backup.
#
#   ./scripts/restore.sh /backups/daily/memescope-20260728T030000Z.dump
#
# Deliberately interactive and deliberately not wired into any automation.
# A restore overwrites live data; the one thing worse than having no backup is
# a script that can silently replace a good database with an old one.

set -eu

DUMP="${1:-}"
PGDATABASE="${PGDATABASE:-memescope}"

if [ -z "$DUMP" ]; then
	echo "usage: restore.sh <path-to-dump>" >&2
	echo "" >&2
	echo "available backups:" >&2
	ls -1t /backups/daily /backups/weekly /backups/monthly 2>/dev/null >&2 || true
	exit 2
fi

[ -f "$DUMP" ] || {
	echo "no such dump: $DUMP" >&2
	exit 1
}

echo "About to restore ${DUMP} into database '${PGDATABASE}'."
echo "THIS REPLACES THE CURRENT CONTENTS OF THAT DATABASE."
printf "Type the database name to confirm: "
read -r confirm
[ "$confirm" = "$PGDATABASE" ] || {
	echo "aborted." >&2
	exit 1
}

# Stop the writers first. Restoring underneath a running enrichment worker
# produces a database that is neither the backup nor the current state.
echo "[restore] stop the application before continuing:"
echo "    docker compose -f docker-compose.yml -f docker-compose.prod.yml stop backend worker scheduler scanner enrichment"
printf "Press enter once those are stopped: "
read -r _

# `--clean --if-exists` drops objects before recreating them, so a restore onto
# a populated database succeeds instead of colliding. `--single-transaction`
# means a failure part-way leaves the original intact rather than a half-restore.
pg_restore \
	--dbname="$PGDATABASE" \
	--clean --if-exists \
	--single-transaction \
	--no-owner --no-privileges \
	--verbose \
	"$DUMP"

echo "[restore] done. Restart the application:"
echo "    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
echo "[restore] then verify: ./scripts/health-check.sh"
