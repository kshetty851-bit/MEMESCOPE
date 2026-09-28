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

# Since 2026-09-28 backups leave out the price snapshots' ROWS (backup.sh), so
# the four foreign keys that point INTO token_market_snapshots cannot be
# re-added while old decision rows still name snapshots that are not there —
# and inside --single-transaction that one failure would roll the whole
# restore back. So: restore everything but those four keys, clear the links
# that now point at nothing (decisions keep everything else), then add the
# keys back from the dump itself.
list="$(mktemp)"
keys="$(mktemp)"
pg_restore --list "$DUMP" >"$list.all"
grep -E 'FK CONSTRAINT .*market_snapshot_id' "$list.all" >"$keys" || true
grep -v -E 'FK CONSTRAINT .*market_snapshot_id' "$list.all" >"$list"

# `--clean --if-exists` drops objects before recreating them, so a restore onto
# a populated database succeeds instead of colliding. `--single-transaction`
# means a failure part-way leaves the original intact rather than a half-restore.
pg_restore \
	--dbname="$PGDATABASE" \
	--clean --if-exists \
	--single-transaction \
	--no-owner --no-privileges \
	--use-list="$list" \
	--verbose \
	"$DUMP"

if [ -s "$keys" ]; then
	echo "[restore] re-linking decisions to the price snapshots that survived"
	for t in paper_decision_outcomes paper_decision_snapshots radar_decision_outcomes radar_decision_snapshots; do
		psql --dbname="$PGDATABASE" -v ON_ERROR_STOP=1 -q -c "
			UPDATE $t SET market_snapshot_id = NULL
			WHERE market_snapshot_id IS NOT NULL
			  AND NOT EXISTS (SELECT 1 FROM token_market_snapshots s
			                  WHERE s.id = $t.market_snapshot_id)" 2>/dev/null || true
	done
	pg_restore --dbname="$PGDATABASE" --no-owner --no-privileges \
		--single-transaction --use-list="$keys" "$DUMP"
fi
rm -f "$list" "$list.all" "$keys"

echo "[restore] done. Restart the application:"
echo "    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
echo "[restore] then verify: ./scripts/health-check.sh"
